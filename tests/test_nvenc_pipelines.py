"""test_nvenc_pipelines.py — Inyeccion del encoder en los pipelines + API/UI (FASE 12 D/F).

Sin FFmpeg real: se validan los CONSTRUCTORES de comando (que inyectan los args del encoder
sin tocar audio/mapa/filtros) y los endpoints via TestClient con deteccion mockeada.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import core_overlays as co
import depurador
import reframe
import video_encoder as ve

_OK = ve.NvencStatus(True, "ok", ve.MSG_OK)
_NO = ve.NvencStatus(False, "no_encoder", ve.MSG_NO_ENCODER)

_NVENC_Q = ve.build_video_args(ve.select_encoder("nvenc", "quality", status=_OK))
_NVENC_F = ve.build_video_args(ve.select_encoder("nvenc", "fast", status=_OK))
_CPU_F = ve.build_video_args(ve.select_encoder("cpu", "fast"))


@pytest.fixture(autouse=True)
def _reset():
    ve._reset_cache_for_tests()
    ve.set_default_mode("auto")
    yield
    ve._reset_cache_for_tests()
    ve.set_default_mode("auto")


# ── D. Constructores de comando por pipeline ────────────────────────────────────
def test_depurador_edl_cmd_inyecta_encoder_y_conserva_audio(tmp_path):
    from pathlib import Path

    edl = [(0.0, 1.0), (2.0, 3.0)]
    cmd = depurador._edl_cmd(Path("in.mp4"), edl, _NVENC_Q, tmp_path / "o.mp4")
    assert "h264_nvenc" in cmd
    # Audio y mapeo intactos:
    assert cmd[cmd.index("-c:a") + 1] == "aac"
    assert "-b:a" in cmd and cmd[cmd.index("-b:a") + 1] == "128k"
    assert "[outv]" in cmd and "[outa]" in cmd


def test_reframe_cpu_fast_byte_identico():
    # CPU fast (sin -pix_fmt en los args) debe reproducir el comando historico exacto.
    from pathlib import Path

    cmd = reframe._cmd_ffmpeg_pipe(Path("in.mp4"), Path("o.mp4"), 30.0, True, _CPU_F)
    v = cmd[cmd.index("-map") :]  # a partir del primer -map
    assert "-c:v" in cmd and cmd[cmd.index("-c:v") + 1] == "libx264"
    assert cmd[cmd.index("-c:v") : cmd.index("-c:v") + 6] == [
        "-c:v",
        "libx264",
        "-crf",
        "18",
        "-preset",
        "fast",
    ]
    # -pix_fmt yuv420p (output) agregado por reframe, faststart y audio copy presentes:
    assert (
        cmd[cmd.index("-pix_fmt", cmd.index("-c:v")) + 1] == "yuv420p"
    )  # el pix_fmt DESPUES del -c:v
    assert cmd.count("-pix_fmt") == 2  # bgr24 (input) + yuv420p (output)
    assert "+faststart" in cmd and cmd[cmd.index("-c:a") + 1] == "copy"
    assert v  # sanity


def test_reframe_nvenc_no_duplica_pix_fmt():
    from pathlib import Path

    cmd = reframe._cmd_ffmpeg_pipe(Path("in.mp4"), Path("o.mp4"), 30.0, True, _NVENC_F)
    assert "h264_nvenc" in cmd
    # input bgr24 + un solo yuv420p del encoder NVENC (no se agrega otro):
    assert cmd.count("-pix_fmt") == 2
    assert cmd.count("yuv420p") == 1


# La inyeccion del encoder en la ruta stack (regresion Codex P2) y su publicacion atomica
# se cubren en test_nvenc_reframe_atomic.py (tests 2 y 13, con el flujo real de temp+verify).


def test_reframe_sin_audio_no_mapea_audio():
    from pathlib import Path

    cmd = reframe._cmd_ffmpeg_pipe(Path("in.mp4"), Path("o.mp4"), 30.0, False, _CPU_F)
    assert "1:a" not in cmd and "-c:a" not in cmd


def test_overlays_construir_comando_inyecta_nvenc(tmp_path):
    from pathlib import Path

    png = tmp_path / "e.png"
    png.write_bytes(b"x")
    cmd = co.construir_comando(
        Path("in.mp4"),
        "sub.ass",
        Path("o.mp4"),
        [(png, 0.0, 1.0)],
        100,
        200,
        0.1,
        1080,
        1920,
        video_args=_NVENC_Q,
    )
    assert "h264_nvenc" in cmd
    assert cmd[cmd.index("-c:a") + 1] == "copy"  # audio intacto


def test_overlays_default_es_cpu_historico(tmp_path):
    from pathlib import Path

    cmd = co.construir_comando(
        Path("in.mp4"),
        "sub.ass",
        Path("o.mp4"),
        [],
        100,
        200,
        0.1,
        1080,
        1920,
    )
    assert cmd[cmd.index("-c:v") : cmd.index("-c:v") + 6] == [
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
    ]


# ── F. API / UI ─────────────────────────────────────────────────────────────────
@pytest.fixture
def api():
    import app as studio_app

    return TestClient(studio_app.app)


def test_get_video_encoder(api, monkeypatch):
    monkeypatch.setattr(ve, "detect_nvenc", lambda **k: _OK)
    ve.set_default_mode("auto")
    d = api.get("/api/system/video-encoder").json()
    assert d["requested"] == "auto" and d["selected"] == "nvenc"
    assert d["encoder"] == "h264_nvenc" and d["nvenc"]["available"] is True


def test_put_video_encoder_valido(api):
    r = api.put("/api/system/video-encoder", json={"mode": "cpu"})
    assert r.status_code == 200 and r.json()["requested"] == "cpu"
    assert ve.get_default_mode() == ve.EncoderMode.CPU


def test_put_video_encoder_invalido_400(api):
    r = api.put("/api/system/video-encoder", json={"mode": "gpu"})
    assert r.status_code == 400
    assert ve.get_default_mode() == ve.EncoderMode.AUTO  # no se cambio


def test_capabilities_incluye_nvenc_sin_degradar(api, monkeypatch):
    monkeypatch.setattr(ve, "detect_nvenc", lambda **k: _NO)
    d = api.get("/api/system/capabilities").json()
    assert "nvenc" in d["capabilities"]
    assert d["capabilities"]["nvenc"]["available"] is False
    assert d["status"] in ("ready", "degraded")  # el status NO depende de nvenc


# ── F. Guard 503 antes del job para modo nvenc explicito ────────────────────────
@pytest.fixture
def render_api(tmp_path, monkeypatch):
    import app as studio_app

    creados = []
    monkeypatch.setattr(studio_app, "INPUT_DIR", tmp_path)
    monkeypatch.setattr(studio_app, "TRANSCRIPTS", tmp_path)
    monkeypatch.setattr(studio_app.jobs, "new_job", lambda msg: creados.append(msg) or "j1")

    class _T:
        def __init__(self, *a, **k):
            pass

        def start(self):
            pass

    monkeypatch.setattr(studio_app.threading, "Thread", _T)
    (tmp_path / "vid.mp4").write_bytes(b"data")
    (tmp_path / "vid_groups.json").write_text(json.dumps([]), encoding="utf-8")
    return TestClient(studio_app.app), creados


def test_guard_nvenc_explicito_503_sin_job(render_api, monkeypatch):
    client, creados = render_api
    ve.set_default_mode("nvenc")
    monkeypatch.setattr(ve, "detect_nvenc", lambda **k: _NO)
    r = client.post("/api/videos/vid/render?style=hormozi")
    assert r.status_code == 503
    assert creados == []  # no se creo job/thread
    assert ":\\" not in r.json()["detail"]  # mensaje saneado


def test_guard_auto_no_bloquea(render_api, monkeypatch):
    client, creados = render_api
    ve.set_default_mode("auto")
    monkeypatch.setattr(ve, "detect_nvenc", lambda **k: _NO)
    r = client.post("/api/videos/vid/render?style=hormozi")
    # auto sin NVENC no bloquea: el job se crea (cae a CPU en ejecucion)
    assert r.status_code == 200 and creados


def test_encoder_status_nvenc_forzado_reporta_nvenc(monkeypatch):
    # Codex P2 round 2: en modo nvenc explicito, selected refleja NVENC (no CPU) aunque no este
    # disponible; el job se rechaza con 503, no cae a CPU. nvenc.available lo delata.
    monkeypatch.setattr(ve, "detect_nvenc", lambda **k: _NO)
    d = ve.encoder_status("nvenc")
    assert d["selected"] == "nvenc" and d["encoder"] == "h264_nvenc"
    assert d["nvenc"]["available"] is False
    # auto sin NVENC si cae a CPU:
    assert ve.encoder_status("auto")["selected"] == "cpu"


def test_auto_guard_nvenc_503_no_500(render_api, monkeypatch):
    # Codex P2 round 2: el 503 del guard NO debe volverse 500 dentro del try del endpoint Auto.
    client, creados = render_api
    ve.set_default_mode("nvenc")
    monkeypatch.setattr(ve, "detect_nvenc", lambda **k: _NO)
    r = client.post("/api/videos/vid/auto?mode=classic")
    assert r.status_code == 503  # accionable, no 500 generico
    assert creados == []
