"""test_nvenc_submagic.py — Guard condicional y snapshot del pre-reframe local de Submagic.

Submagic es remoto, PERO con reframe=true sobre un video horizontal hace un encode LOCAL
(reframe a 9:16) antes del upload. El guard de encoder solo aplica en ese caso. Sin red real.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import core
import jobs
import submagic
import video_encoder as ve

_OK = ve.NvencStatus(True, "ok", ve.MSG_OK)
_NO = ve.NvencStatus(False, "no_encoder", ve.MSG_NO_ENCODER)
_HORIZ = {"width": 1920, "height": 1080, "duration": 3.0, "has_audio": True}
_VERT = {"width": 1080, "height": 1920, "duration": 3.0, "has_audio": True}


@pytest.fixture(autouse=True)
def _reset():
    ve._reset_cache_for_tests()
    ve.set_default_mode("auto")
    yield
    ve._reset_cache_for_tests()
    ve.set_default_mode("auto")


@pytest.fixture
def sm_api(tmp_path, monkeypatch):
    import app as studio_app

    creados = []
    uploads = []
    monkeypatch.setattr(studio_app, "INPUT_DIR", tmp_path)
    monkeypatch.setattr(studio_app.jobs, "new_job", lambda msg: creados.append(msg) or "j1")

    class _T:
        def __init__(self, *a, **k):
            pass

        def start(self):
            pass

    monkeypatch.setattr(studio_app.threading, "Thread", _T)
    monkeypatch.setattr(submagic, "tiene_key", lambda: True)
    monkeypatch.setattr(submagic, "enviar_video", lambda *a, **k: uploads.append(1) or ("pid", 0.0))
    (tmp_path / "vid.mp4").write_bytes(b"data")
    return TestClient(studio_app.app), creados, uploads, monkeypatch


def _set_dims(monkeypatch, dims):
    monkeypatch.setattr(core, "get_video_info", lambda p: dims)


# ── 1: horizontal + reframe + nvenc no disponible -> 503, cero jobs ─────────────
def test_1_horizontal_reframe_nvenc_no_disp_503(sm_api, monkeypatch):
    client, creados, uploads, _ = sm_api
    _set_dims(monkeypatch, _HORIZ)
    ve.set_default_mode("nvenc")
    monkeypatch.setattr(ve, "detect_nvenc", lambda **k: _NO)
    r = client.post("/api/videos/vid/submagic?reframe=true")
    assert r.status_code == 503
    assert creados == [] and uploads == []  # ni job ni upload remoto


# ── 2: horizontal + reframe + auto sin NVENC -> job permitido (CPU) ─────────────
def test_2_horizontal_reframe_auto_sin_nvenc_permite(sm_api, monkeypatch):
    client, creados, _uploads, _ = sm_api
    _set_dims(monkeypatch, _HORIZ)
    ve.set_default_mode("auto")
    monkeypatch.setattr(ve, "detect_nvenc", lambda **k: _NO)
    r = client.post("/api/videos/vid/submagic?reframe=true")
    assert r.status_code == 200 and creados  # auto cae a CPU en el reframe local


# ── 3: horizontal + reframe + nvenc disponible -> job permitido (NVENC) ─────────
def test_3_horizontal_reframe_nvenc_disp_permite(sm_api, monkeypatch):
    client, creados, _uploads, _ = sm_api
    _set_dims(monkeypatch, _HORIZ)
    ve.set_default_mode("nvenc")
    monkeypatch.setattr(ve, "detect_nvenc", lambda **k: _OK)
    r = client.post("/api/videos/vid/submagic?reframe=true")
    assert r.status_code == 200 and creados


# ── 4: vertical + reframe + nvenc no disponible -> permitido (no encode local) ──
def test_4_vertical_reframe_nvenc_no_disp_permite(sm_api, monkeypatch):
    client, creados, _uploads, _ = sm_api
    _set_dims(monkeypatch, _VERT)
    ve.set_default_mode("nvenc")
    monkeypatch.setattr(ve, "detect_nvenc", lambda **k: _NO)
    r = client.post("/api/videos/vid/submagic?reframe=true")
    # ya es vertical: no habra reframe local -> el guard NO aplica aunque falte NVENC
    assert r.status_code == 200 and creados


# ── 5: reframe=false + nvenc no disponible -> permitido ─────────────────────────
def test_5_sin_reframe_nvenc_no_disp_permite(sm_api, monkeypatch):
    client, creados, _uploads, _ = sm_api
    _set_dims(monkeypatch, _HORIZ)
    ve.set_default_mode("nvenc")
    monkeypatch.setattr(ve, "detect_nvenc", lambda **k: _NO)
    r = client.post("/api/videos/vid/submagic?reframe=false")
    assert r.status_code == 200 and creados  # sin reframe local, ruta remota valida


# ── 6: el worker conserva el snapshot aunque cambie el default antes del reframe ─
def test_6_worker_conserva_snapshot(monkeypatch):
    ve.set_default_mode("cpu")
    seen = {}

    class _Stop(Exception):
        pass

    def fake_reframe(jid, mp4, reframe_9x16):
        seen["mode"] = ve.active_mode()  # el reframe local lee el modo aqui
        ve.set_default_mode("nvenc")  # cambiar el default DESPUES no debe afectar al job
        raise _Stop()

    monkeypatch.setattr(jobs, "_reframe_para_submagic", fake_reframe)
    monkeypatch.setattr(jobs, "update_job", lambda *a, **k: None)
    monkeypatch.setattr(submagic, "tiene_key", lambda: True)
    jobs.run_submagic_render("j", Path("x.mp4"), "n", True, None)
    assert seen["mode"] == ve.EncoderMode.CPU  # snapshot inmutable


# ── 7: guard rechaza -> no se inicia upload remoto ──────────────────────────────
def test_7_guard_rechaza_no_hay_upload(sm_api, monkeypatch):
    client, creados, uploads, _ = sm_api
    _set_dims(monkeypatch, _HORIZ)
    ve.set_default_mode("nvenc")
    monkeypatch.setattr(ve, "detect_nvenc", lambda **k: _NO)
    monkeypatch.setattr(submagic, "enviar_video", lambda *a, **k: uploads.append("BOOM"))
    client.post("/api/videos/vid/submagic?reframe=true")
    assert uploads == []  # el thread nunca arranco -> sin upload


# ── Probe del endpoint: fallos traducidos a error accionable (no 500) ───────────
def test_probe_ffprobe_ausente_503(sm_api, monkeypatch):
    import media_deps

    client, creados, uploads, _ = sm_api

    def _raise(_p):
        raise media_deps.FFprobeUnavailable(media_deps._FFPROBE_MSG)

    monkeypatch.setattr(core, "get_video_info", _raise)
    r = client.post("/api/videos/vid/submagic?reframe=true")
    assert r.status_code == 503 and creados == [] and uploads == []


def test_probe_video_incorpobable_400(sm_api, monkeypatch):
    import media_deps

    client, creados, uploads, _ = sm_api

    def _raise(_p):
        raise media_deps.MediaProbeError("No se pudo analizar el video.")

    monkeypatch.setattr(core, "get_video_info", _raise)
    r = client.post("/api/videos/vid/submagic?reframe=true")
    assert r.status_code == 400 and creados == [] and uploads == []
    assert ":\\" not in r.json()["detail"]  # saneado


# ── 8: inventario documenta Submagic remoto con pre-reframe local ───────────────
def test_8_inventario_documenta_submagic():
    inv = (
        (
            Path(__file__).resolve().parents[1]
            / "revision"
            / "pre-hyperframes"
            / "NVENC_INVENTARIO.md"
        )
        .read_text(encoding="utf-8")
        .lower()
    )
    assert "submagic" in inv and "reframe" in inv and "local" in inv


# ── Predicado puro compartido (endpoint == worker) ──────────────────────────────
def test_predicado_local_horizontal_vs_vertical():
    assert jobs._submagic_reframe_local(True, 1920, 1080) is True  # horizontal -> encode local
    assert jobs._submagic_reframe_local(True, 1080, 1920) is False  # vertical -> no
    assert jobs._submagic_reframe_local(False, 1920, 1080) is False  # toggle off -> no
