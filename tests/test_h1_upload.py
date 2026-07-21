"""H1 · P0-2 — Upload seguro: basename + extension + tope de bytes + temporal validado.

verificar_video (ffprobe) y el post-proceso (info/thumb) se mockean; sin FFmpeg real. Todo
en tmp_path. Un test verde exige que un upload invalido nunca se publique al destino final.
"""

from __future__ import annotations

import asyncio
import io

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app as studio_app
import media_integrity


@pytest.fixture
def api(tmp_path, monkeypatch):
    inp = tmp_path / "input"
    trans = tmp_path / "transcripts"
    thumbs = tmp_path / "thumbs"
    for d in (inp, trans, thumbs):
        d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(studio_app, "INPUT_DIR", inp)
    monkeypatch.setattr(studio_app, "TRANSCRIPTS", trans)
    monkeypatch.setattr(studio_app, "THUMBS_DIR", thumbs)
    # Sin FFmpeg: ffprobe del temporal y post-proceso mockeados a exito por defecto.
    monkeypatch.setattr(media_integrity, "verificar_video", lambda _p: None)
    monkeypatch.setattr(studio_app.core, "get_video_info", lambda _p: {"duration": 1.0})
    monkeypatch.setattr(studio_app.core, "extract_thumb", lambda *a, **k: None)
    monkeypatch.delenv("CENTRITO_MAX_VIDEO_BYTES", raising=False)
    return TestClient(studio_app.app, raise_server_exceptions=True), inp


def _post(client, filename, data=b"videobytes"):
    return client.post(
        "/api/videos/upload", files={"file": (filename, io.BytesIO(data), "video/mp4")}
    )


def _sin_temporales(inp):
    tmp_dir = inp / ".uploads"
    return not tmp_dir.exists() or not any(tmp_dir.iterdir())


# ── Nombre / extension ───────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "filename",
    ["..\\..\\x.mp4", "../../x.mp4", "/x.mp4", "C:\\x.mp4", "\\\\srv\\s\\x.mp4"],
)
def test_filename_traversal_no_escapa(api, filename):
    """El guard rechaza (400) O el parser multipart neutraliza a basename (contenido en input).

    En ambos casos el invariante P0-2 se cumple: nada se escribe FUERA de input/.
    """
    client, inp = api
    resp = _post(client, filename)
    assert resp.status_code in (200, 400, 422)
    # Nunca un archivo escapa al directorio padre del sandbox.
    assert not list(inp.parent.glob("*.mp4"))
    assert not (inp.parent / "x.mp4").exists()
    if resp.status_code == 200:  # aceptado -> contenido en input con basename seguro
        assert any(p.suffix == ".mp4" and p.is_file() for p in inp.iterdir())
    assert _sin_temporales(inp)


def test_filename_vacio_rechazado(api):
    client, _ = api
    # Filename vacio: FastAPI lo valida como archivo ausente (422) o el guard lo corta (400).
    assert _post(client, "").status_code in (400, 422)


@pytest.mark.parametrize("filename", ["clip.txt", "clip.mp4.txt", "clip", "clip.mov.exe"])
def test_extension_invalida_400(api, filename):
    client, inp = api
    assert _post(client, filename).status_code == 400
    assert _sin_temporales(inp)


@pytest.mark.parametrize("filename", ["VIDEO.MP4", "clip.MOV", "buena.mp4"])
def test_extension_valida_case_insensitive_200(api, filename):
    client, inp = api
    r = _post(client, filename)
    assert r.status_code == 200
    assert (inp / filename).exists()
    assert _sin_temporales(inp)


# ── Limite de bytes ──────────────────────────────────────────────────────────
def test_oversize_content_length_413(api, monkeypatch):
    client, inp = api
    monkeypatch.setenv("CENTRITO_MAX_VIDEO_BYTES", "5")
    r = _post(client, "grande.mp4", data=b"0123456789")  # 10 bytes > 5
    assert r.status_code == 413
    assert not (inp / "grande.mp4").exists()
    assert _sin_temporales(inp)


def test_limite_invalido_cae_a_default(monkeypatch):
    monkeypatch.setenv("CENTRITO_MAX_VIDEO_BYTES", "no-numero")
    assert studio_app._max_video_bytes() == studio_app._DEFAULT_MAX_VIDEO_BYTES
    monkeypatch.setenv("CENTRITO_MAX_VIDEO_BYTES", "-5")
    assert studio_app._max_video_bytes() == studio_app._DEFAULT_MAX_VIDEO_BYTES


def test_chunk_limit_aborta_sin_content_length(tmp_path):
    """Aunque Content-Length falte o mienta, el tope por chunks aborta con 413."""

    class _FakeUpload:
        def __init__(self, chunks):
            self._chunks = list(chunks)

        async def read(self, _n):
            return self._chunks.pop(0) if self._chunks else b""

    tmp = tmp_path / "t.mp4"
    fake = _FakeUpload([b"a" * 4, b"b" * 4])  # 8 bytes, limite 5
    with pytest.raises(HTTPException) as exc:
        asyncio.run(studio_app._stream_a_temporal(fake, tmp, 5))
    assert exc.value.status_code == 413


# ── Contenido invalido / errores ─────────────────────────────────────────────
def test_archivo_no_multimedia_422(api, monkeypatch):
    client, inp = api

    def _rechaza(_p):
        raise media_integrity.MediaIntegrityError("sin stream de video")

    monkeypatch.setattr(media_integrity, "verificar_video", _rechaza)
    r = _post(client, "fake.mp4")
    assert r.status_code == 422
    assert not (inp / "fake.mp4").exists()
    assert _sin_temporales(inp)


def test_excepcion_durante_publicacion_500_saneado(api, monkeypatch):
    client, inp = api

    def _boom(*_a, **_k):
        raise OSError("DISCO-LLENO-DETALLE-INTERNO")

    monkeypatch.setattr(studio_app.os, "replace", _boom)
    r = _post(client, "video.mp4")
    assert r.status_code == 500
    assert "DISCO-LLENO" not in r.text
    assert _sin_temporales(inp)


# ── Reemplazo atomico / preservacion ─────────────────────────────────────────
def test_reemplazo_exitoso(api):
    client, inp = api
    (inp / "video.mp4").write_bytes(b"VIEJO")
    r = _post(client, "video.mp4", data=b"NUEVO-VALIDO")
    assert r.status_code == 200
    assert (inp / "video.mp4").read_bytes() == b"NUEVO-VALIDO"
    assert _sin_temporales(inp)


def test_reemplazo_fallido_preserva_original(api, monkeypatch):
    client, inp = api
    (inp / "video.mp4").write_bytes(b"ORIGINAL")

    def _rechaza(_p):
        raise media_integrity.MediaIntegrityError("invalido")

    monkeypatch.setattr(media_integrity, "verificar_video", _rechaza)
    r = _post(client, "video.mp4", data=b"CARGA-MALA")
    assert r.status_code == 422
    assert (inp / "video.mp4").read_bytes() == b"ORIGINAL"  # el final anterior intacto
    assert _sin_temporales(inp)
