"""test_h3_depurar.py — Depuracion en modo degradado + metadata parcial (H3, correctivo).

Cubre: capacidad `depurar`, guard backend (no crea job sin FFmpeg/ffprobe), errores tipados del
depurador (sin stderr/rutas), y metadata parcial de core.get_video_info sin ffmpeg.
Todo inyectado: sin red, sin GPU, sin subprocess real cuando la herramienta "falta".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import core
import depurador
import jobs
import media_deps


class _FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# ── depurador._probe_duration ──────────────────────────────────────────────────
def test_probe_duration_ffprobe_ausente_tipado(monkeypatch):
    monkeypatch.setattr(media_deps, "ffprobe_disponible", lambda which=None: False)

    def _no_run(*a, **k):
        raise AssertionError("no debe correr subprocess si ffprobe falta")

    monkeypatch.setattr(depurador.subprocess, "run", _no_run)
    with pytest.raises(media_deps.FFprobeUnavailable):
        depurador._probe_duration(Path("x.mp4"))


def test_probe_duration_returncode_nonzero_es_probe_error(monkeypatch):
    monkeypatch.setattr(media_deps, "ffprobe_disponible", lambda which=None: True)
    monkeypatch.setattr(
        depurador.subprocess, "run", lambda *a, **k: _FakeProc(1, "", "secreto\nC:\\ruta")
    )
    with pytest.raises(media_deps.MediaProbeError) as exc:
        depurador._probe_duration(Path("x.mp4"))
    assert "C:\\" not in str(exc.value) and "secreto" not in str(exc.value)


def test_probe_duration_json_invalido_es_probe_error(monkeypatch):
    monkeypatch.setattr(media_deps, "ffprobe_disponible", lambda which=None: True)
    monkeypatch.setattr(depurador.subprocess, "run", lambda *a, **k: _FakeProc(0, "{roto"))
    with pytest.raises(media_deps.MediaProbeError):
        depurador._probe_duration(Path("x.mp4"))


# ── depurador._run_edl / _volume_at ────────────────────────────────────────────
def test_run_edl_ffmpeg_ausente_tipado(monkeypatch):
    monkeypatch.setattr(media_deps, "ffmpeg_disponible", lambda which=None: False)

    def _no_run(*a, **k):
        raise AssertionError("no debe correr subprocess si ffmpeg falta")

    monkeypatch.setattr(depurador.subprocess, "run", _no_run)
    with pytest.raises(media_deps.FFmpegUnavailable):
        depurador._run_edl(Path("x.mp4"), [(0.0, 1.0)], Path("o.mp4"))


def test_run_edl_ffmpeg_presente_falla_error_saneado(monkeypatch, tmp_path):
    # Tras la fase NVENC, _run_edl delega la codificacion en video_encoder (modo cpu -> libx264).
    # El fallo de FFmpeg se sanea alli: la excepcion publica NO lleva stderr ni rutas.
    import video_encoder

    monkeypatch.setattr(media_deps, "ffmpeg_disponible", lambda which=None: True)
    monkeypatch.setattr(depurador.media_deps, "require_ffmpeg", lambda: None)
    monkeypatch.setattr(video_encoder, "active_mode", lambda: video_encoder.EncoderMode.CPU)
    monkeypatch.setattr(
        video_encoder.subprocess,
        "run",
        lambda *a, **k: _FakeProc(1, "", "C:\\priv\\stderr secreto"),
    )
    with pytest.raises(RuntimeError) as exc:
        depurador._run_edl(Path("x.mp4"), [(0.0, 1.0)], tmp_path / "o.mp4")
    assert "C:\\" not in str(exc.value) and "secreto" not in str(exc.value)
    assert str(exc.value) == "La codificacion de video no pudo completarse."


def test_volume_at_ffmpeg_ausente_tipado(monkeypatch):
    monkeypatch.setattr(media_deps, "ffmpeg_disponible", lambda which=None: False)
    monkeypatch.setattr(
        depurador.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError())
    )
    with pytest.raises(media_deps.FFmpegUnavailable):
        depurador._volume_at(Path("x.mp4"), 0.0)


# ── jobs._error_publico_depurar ────────────────────────────────────────────────
def test_error_publico_depurar_mapea_tipos():
    f = jobs._error_publico_depurar
    assert f(media_deps.FFmpegUnavailable(media_deps._FFMPEG_MSG)) == media_deps._FFMPEG_MSG
    assert f(media_deps.MediaProbeError("x")) == "No se pudo analizar el video para depurarlo."
    assert f(RuntimeError("stderr con C:\\ruta")) == "La depuracion no pudo completarse."


def test_error_publico_depurar_no_filtra_rutas():
    msg = jobs._error_publico_depurar(RuntimeError("FFmpeg\nC:\\Users\\PC\\secreto"))
    assert "C:\\" not in msg and "secreto" not in msg


# ── Endpoint start_depurar: guard antes de crear el job ────────────────────────
@pytest.fixture
def dep_api(tmp_path, monkeypatch):
    import app as studio_app

    creados = []
    monkeypatch.setattr(studio_app, "INPUT_DIR", tmp_path)
    monkeypatch.setattr(studio_app, "TRANSCRIPTS", tmp_path)
    monkeypatch.setattr(studio_app.jobs, "new_job", lambda msg: creados.append(msg) or "job-dep")

    class _FakeThread:
        def __init__(self, *a, **k):
            pass

        def start(self):
            pass

    monkeypatch.setattr(studio_app.threading, "Thread", _FakeThread)
    (tmp_path / "vid.mp4").write_bytes(b"data")
    (tmp_path / "vid_words.json").write_text(json.dumps({"words": []}), encoding="utf-8")
    return TestClient(studio_app.app), creados


def test_start_depurar_sin_ffmpeg_503_sin_job(dep_api, monkeypatch):
    client, creados = dep_api
    monkeypatch.setattr(media_deps, "ffmpeg_disponible", lambda which=None: False)
    monkeypatch.setattr(media_deps, "ffprobe_disponible", lambda which=None: True)
    resp = client.post("/api/videos/vid/depurar?mode=seguro")
    assert resp.status_code == 503 and "FFmpeg" in resp.json()["detail"]
    assert creados == []  # new_job NO llamado


def test_start_depurar_sin_ffprobe_503_sin_job(dep_api, monkeypatch):
    client, creados = dep_api
    monkeypatch.setattr(media_deps, "ffmpeg_disponible", lambda which=None: True)
    monkeypatch.setattr(media_deps, "ffprobe_disponible", lambda which=None: False)
    resp = client.post("/api/videos/vid/depurar?mode=seguro")
    assert resp.status_code == 503 and creados == []
    assert ":\\" not in resp.json()["detail"]  # sin ruta absoluta


def test_start_depurar_con_dependencias_crea_un_job(dep_api, monkeypatch):
    client, creados = dep_api
    monkeypatch.setattr(media_deps, "ffmpeg_disponible", lambda which=None: True)
    monkeypatch.setattr(media_deps, "ffprobe_disponible", lambda which=None: True)
    resp = client.post("/api/videos/vid/depurar?mode=seguro")
    assert resp.status_code == 200 and resp.json() == {"job_id": "job-dep"}
    assert len(creados) == 1  # exactamente un job


# ── core.get_video_info: metadata parcial sin ffmpeg ───────────────────────────
_FFPROBE_AUDIO = json.dumps(
    {
        "streams": [
            {"codec_type": "video", "width": 1080, "height": 1920, "r_frame_rate": "30/1"},
            {"codec_type": "audio"},
        ],
        "format": {"duration": "12.0"},
    }
)
_FFPROBE_MUDO = json.dumps(
    {
        "streams": [{"codec_type": "video", "width": 1080, "height": 1920, "r_frame_rate": "30/1"}],
        "format": {"duration": "12.0"},
    }
)


def test_get_video_info_sin_ffmpeg_metadata_parcial(monkeypatch):
    monkeypatch.setattr(media_deps, "ffprobe_disponible", lambda which=None: True)
    monkeypatch.setattr(media_deps, "ffmpeg_disponible", lambda which=None: False)
    monkeypatch.setattr(core.subprocess, "run", lambda *a, **k: _FakeProc(0, _FFPROBE_AUDIO))
    info = core.get_video_info(Path("v.mp4"))
    assert info["width"] == 1080 and info["height"] == 1920 and info["duration"] == 12.0
    assert info["has_audio"] is True
    assert info["mean_volume"] is None and info["volume_unavailable"] is True


def test_get_video_info_volumen_medido(monkeypatch):
    monkeypatch.setattr(media_deps, "ffprobe_disponible", lambda which=None: True)
    monkeypatch.setattr(core.subprocess, "run", lambda *a, **k: _FakeProc(0, _FFPROBE_AUDIO))
    monkeypatch.setattr(core, "_probe_volume", lambda p: -20.0)
    info = core.get_video_info(Path("v.mp4"))
    assert info["mean_volume"] == -20.0 and info["volume_unavailable"] is False


def test_get_video_info_sin_audio_silencio_conocido(monkeypatch):
    monkeypatch.setattr(media_deps, "ffprobe_disponible", lambda which=None: True)
    monkeypatch.setattr(core.subprocess, "run", lambda *a, **k: _FakeProc(0, _FFPROBE_MUDO))
    info = core.get_video_info(Path("v.mp4"))
    assert info["has_audio"] is False
    assert info["mean_volume"] == -99.0 and info["volume_unavailable"] is False


def test_get_video_info_ffprobe_ausente_sigue_tipado(monkeypatch):
    monkeypatch.setattr(media_deps, "ffprobe_disponible", lambda which=None: False)
    with pytest.raises(media_deps.FFprobeUnavailable):
        core.get_video_info(Path("v.mp4"))


def test_get_video_info_video_invalido_sigue_probe_error(monkeypatch):
    monkeypatch.setattr(media_deps, "ffprobe_disponible", lambda which=None: True)
    monkeypatch.setattr(core.subprocess, "run", lambda *a, **k: _FakeProc(1, ""))
    with pytest.raises(media_deps.MediaProbeError):
        core.get_video_info(Path("v.mp4"))


# ── list_videos propaga volume_unavailable y NO lo cachea ──────────────────────
def test_listado_volumen_pendiente_no_es_silencio(monkeypatch, tmp_path):
    import app as studio_app

    monkeypatch.setattr(studio_app, "INPUT_DIR", tmp_path)
    monkeypatch.setattr(studio_app, "TRANSCRIPTS", tmp_path)
    (tmp_path / "clip.mp4").write_bytes(b"data")

    def _partial(_p):
        return {
            "width": 1080,
            "height": 1920,
            "duration": 5.0,
            "fps": 30.0,
            "has_audio": True,
            "mean_volume": None,
            "volume_unavailable": True,
        }

    monkeypatch.setattr(core, "get_video_info", _partial)
    monkeypatch.setattr(core, "extract_thumb", lambda *a, **k: None)
    client = TestClient(studio_app.app)
    card = next(v for v in client.get("/api/videos").json() if v["name"] == "clip")
    assert card["metadata_unavailable"] is False
    assert card["volume_unavailable"] is True
    assert card["mean_volume"] is None
    # No se cachea metadata con volumen pendiente (se re-mide cuando ffmpeg vuelva).
    assert not (tmp_path / "clip_info.json").exists()
