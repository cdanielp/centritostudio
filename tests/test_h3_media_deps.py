"""test_h3_media_deps.py — Endurecimiento multimedia (H3, FASE 11.B).

ffprobe/ffmpeg ausentes ya NO producen JSONDecodeError ni FileNotFoundError crudo: se lanza una
excepcion tipada con mensaje accionable y SIN rutas privadas. Un returncode!=0 con la herramienta
presente se distingue de "herramienta ausente". La UI sigue cargando.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import core
import media_deps
import media_integrity


class _FakeProc:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


# ── ffprobe ausente ────────────────────────────────────────────────────────────
def test_get_video_info_ffprobe_ausente_error_tipado(monkeypatch):
    monkeypatch.setattr(media_deps, "ffprobe_disponible", lambda which=None: False)
    with pytest.raises(media_deps.FFprobeUnavailable) as exc:
        core.get_video_info(Path("x.mp4"))
    msg = str(exc.value)
    assert "FFprobe" in msg and ":\\" not in msg and "/Users/" not in msg


def test_get_video_info_ffprobe_ausente_no_jsondecodeerror(monkeypatch):
    monkeypatch.setattr(media_deps, "ffprobe_disponible", lambda which=None: False)
    try:
        core.get_video_info(Path("x.mp4"))
    except media_deps.FFprobeUnavailable:
        pass
    except ValueError as exc:  # JSONDecodeError es subclase de ValueError
        pytest.fail(f"se filtro un JSONDecodeError: {exc}")


# ── ffprobe presente, archivo invalido -> MediaProbeError (NO 'instala FFmpeg') ────
def test_get_video_info_returncode_nonzero_es_probe_error(monkeypatch):
    monkeypatch.setattr(media_deps, "ffprobe_disponible", lambda which=None: True)
    monkeypatch.setattr(core.subprocess, "run", lambda *a, **k: _FakeProc(returncode=1, stdout=""))
    with pytest.raises(media_deps.MediaProbeError):
        core.get_video_info(Path("roto.mp4"))


def test_get_video_info_stdout_vacio_es_probe_error(monkeypatch):
    monkeypatch.setattr(media_deps, "ffprobe_disponible", lambda which=None: True)
    monkeypatch.setattr(
        core.subprocess, "run", lambda *a, **k: _FakeProc(returncode=0, stdout="   ")
    )
    with pytest.raises(media_deps.MediaProbeError):
        core.get_video_info(Path("vacio.mp4"))


def test_get_video_info_json_valido_devuelve_dict(monkeypatch):
    monkeypatch.setattr(media_deps, "ffprobe_disponible", lambda which=None: True)
    payload = (
        '{"streams":[{"codec_type":"video","width":1080,"height":1920,"r_frame_rate":"30/1"}],'
    )
    payload += '"format":{"duration":"4.0"}}'
    monkeypatch.setattr(core.subprocess, "run", lambda *a, **k: _FakeProc(0, payload))
    info = core.get_video_info(Path("ok.mp4"))
    assert info["width"] == 1080 and info["height"] == 1920 and info["has_audio"] is False


# ── ffmpeg ausente en _probe_volume ────────────────────────────────────────────
def test_probe_volume_ffmpeg_ausente_error_tipado(monkeypatch):
    monkeypatch.setattr(media_deps, "ffmpeg_disponible", lambda which=None: False)
    with pytest.raises(media_deps.FFmpegUnavailable) as exc:
        core._probe_volume(Path("x.mp4"))
    assert "FFmpeg" in str(exc.value)


def test_probe_volume_oserror_se_convierte_en_tipado(monkeypatch):
    monkeypatch.setattr(media_deps, "ffmpeg_disponible", lambda which=None: True)

    def _boom(*a, **k):
        raise OSError("WinError 2")

    monkeypatch.setattr(core.subprocess, "run", _boom)
    with pytest.raises(media_deps.FFmpegUnavailable):
        core._probe_volume(Path("x.mp4"))


# ── media_integrity: ffprobe ausente preserva el contrato fail-closed del resume ──
def test_video_reanudable_ffprobe_ausente_es_false_no_lanza(monkeypatch, tmp_path):
    v = tmp_path / "v.mp4"
    v.write_bytes(b"data")
    monkeypatch.setattr(media_deps, "ffprobe_disponible", lambda which=None: False)
    # video_reanudable NO debe propagar: convierte el fallo en False (se re-renderiza).
    assert media_integrity.video_reanudable(v) is False


def test_ffprobe_ausente_no_lanza_subprocess(monkeypatch, tmp_path):
    v = tmp_path / "v.mp4"
    v.write_bytes(b"data")
    monkeypatch.setattr(media_deps, "ffprobe_disponible", lambda which=None: False)

    def _no_debe_correr(*a, **k):
        raise AssertionError("no debe ejecutar subprocess si which dice que falta")

    monkeypatch.setattr(media_integrity.subprocess, "run", _no_debe_correr)
    with pytest.raises(media_integrity.MediaIntegrityError):
        media_integrity._ffprobe(v)


# ── jobs: el mensaje al usuario es accionable y sin rutas ──────────────────────
def test_error_publico_auto_traduce_dependencia(monkeypatch):
    import jobs

    msg = jobs._error_publico_auto(media_deps.FFmpegUnavailable(media_deps._FFMPEG_MSG))
    assert "FFmpeg" in msg and ":\\" not in msg


# ── UI sigue cargando sin binarios ─────────────────────────────────────────────
def test_ui_carga_aunque_falten_binarios():
    import app as studio_app

    with TestClient(studio_app.app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/system/health").status_code == 200
        assert client.get("/api/videos").status_code == 200


def test_listado_biblioteca_tolera_ffprobe_ausente(monkeypatch, tmp_path):
    """Sin ffprobe (y sin _info.json cacheado) el listado NO debe dar 500: degrada la metadata."""
    import app as studio_app
    import core

    monkeypatch.setattr(studio_app, "INPUT_DIR", tmp_path)
    (tmp_path / "clip.mp4").write_bytes(b"data")  # sin _info.json ni thumb

    def _boom(_p):
        raise media_deps.FFprobeUnavailable(media_deps._FFPROBE_MSG)

    monkeypatch.setattr(core, "get_video_info", _boom)
    monkeypatch.setattr(core, "extract_thumb", lambda *a, **k: (_ for _ in ()).throw(OSError()))

    client = TestClient(studio_app.app)
    resp = client.get("/api/videos")
    assert resp.status_code == 200
    card = next(v for v in resp.json() if v["name"] == "clip")
    # Metadata ausente != silencio: mean_volume null + flag, para que la UI ofrezca Transcribir.
    assert card["metadata_unavailable"] is True
    assert card["mean_volume"] is None and card["has_audio"] is None


def test_upload_sin_ffprobe_rechaza_antes_de_streamear(monkeypatch):
    """503 accionable ANTES de copiar el cuerpo (no gasta disco para luego borrarlo)."""
    import app as studio_app

    monkeypatch.setattr(media_deps, "ffprobe_disponible", lambda which=None: False)

    async def _no_stream(*a, **k):
        raise AssertionError("no debe streamear el cuerpo si ffprobe falta")

    monkeypatch.setattr(studio_app, "_stream_a_temporal", _no_stream)
    client = TestClient(studio_app.app)
    resp = client.post("/api/videos/upload", files={"file": ("clip.mp4", b"x" * 1000, "video/mp4")})
    assert resp.status_code == 503 and "FFprobe" in resp.json()["detail"]
