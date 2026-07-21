"""H1 · P1-OUT-1/2 — Publicacion atomica + verificacion de integridad de MP4.

ffprobe se mockea (sin FFmpeg real); el temporal y el final son archivos sinteticos en
tmp_path. Un test verde exige que el output NO valido nunca se publique.
"""

from __future__ import annotations

import json
import types

import pytest

import core
import jobs_registry
import jobs_render
import media_integrity as mi

VIDEO_OK = {"streams": [{"codec_type": "video", "duration": "3.0"}], "format": {"duration": "3.0"}}
SIN_VIDEO = {"streams": [{"codec_type": "audio"}], "format": {"duration": "3.0"}}
DUR_CERO = {"streams": [{"codec_type": "video"}], "format": {"duration": "0"}}
DUR_NAN = {"streams": [{"codec_type": "video", "duration": "nan"}], "format": {"duration": "inf"}}
SIN_DUR = {"streams": [{"codec_type": "video"}], "format": {}}


def _fake_ffprobe(returncode=0, payload=None):
    """Devuelve un stub de subprocess.run que simula ffprobe."""

    def _run(_cmd, **_kw):
        stdout = json.dumps(payload) if payload is not None else ""
        return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    return _run


def _quemar_ok(contenido=b"FAKEMP4DATA"):
    def _q(target):
        target.write_bytes(contenido)
        return 1.5

    return _q


def _no_part_residual(directory):
    """No quedan temporales: el subdir privado .render_tmp no existe o esta vacio, y no hay
    ningun .part- suelto en el directorio final."""
    tmp = directory / mi.TEMP_DIRNAME
    sin_subdir = not tmp.exists() or not any(tmp.iterdir())
    sin_sueltos = not any(".part-" in p.name for p in directory.iterdir())
    return sin_subdir and sin_sueltos


# ── verificar_video ──────────────────────────────────────────────────────────
def test_verificar_video_valido(tmp_path, monkeypatch):
    monkeypatch.setattr(mi.subprocess, "run", _fake_ffprobe(0, VIDEO_OK))
    f = tmp_path / "ok.mp4"
    f.write_bytes(b"data")
    mi.verificar_video(f)  # no lanza


def test_verificar_video_inexistente(tmp_path):
    with pytest.raises(mi.MediaIntegrityError):
        mi.verificar_video(tmp_path / "no-existe.mp4")


def test_verificar_video_cero_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(mi.subprocess, "run", _fake_ffprobe(0, VIDEO_OK))
    f = tmp_path / "vacio.mp4"
    f.write_bytes(b"")
    with pytest.raises(mi.MediaIntegrityError):
        mi.verificar_video(f)


def test_verificar_video_ffprobe_rechaza(tmp_path, monkeypatch):
    monkeypatch.setattr(mi.subprocess, "run", _fake_ffprobe(1, None))
    f = tmp_path / "roto.mp4"
    f.write_bytes(b"data")
    with pytest.raises(mi.MediaIntegrityError):
        mi.verificar_video(f)


def test_verificar_video_json_invalido(tmp_path, monkeypatch):
    monkeypatch.setattr(
        mi.subprocess,
        "run",
        lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="no-json", stderr=""),
    )
    f = tmp_path / "x.mp4"
    f.write_bytes(b"data")
    with pytest.raises(mi.MediaIntegrityError):
        mi.verificar_video(f)


@pytest.mark.parametrize("payload", [SIN_VIDEO, DUR_CERO, DUR_NAN, SIN_DUR])
def test_verificar_video_invalidos(tmp_path, monkeypatch, payload):
    monkeypatch.setattr(mi.subprocess, "run", _fake_ffprobe(0, payload))
    f = tmp_path / "x.mp4"
    f.write_bytes(b"data")
    with pytest.raises(mi.MediaIntegrityError):
        mi.verificar_video(f)


# ── ruta_temporal ────────────────────────────────────────────────────────────
def test_ruta_temporal_unica_privada_y_mp4(tmp_path):
    final = tmp_path / "video.mp4"
    a = mi.ruta_temporal(final)
    b = mi.ruta_temporal(final)
    assert a != b  # dos operaciones nunca reutilizan el mismo temporal
    assert a.suffix == ".mp4"
    # Vive en el subdir PRIVADO reservado del mismo directorio del final (mismo volumen).
    assert a.parent == final.parent / mi.TEMP_DIRNAME
    assert a.parent.name.startswith(".")
    # No incluye el stem privado del usuario.
    assert "video" not in a.name


# ── publicar_mp4_atomico ─────────────────────────────────────────────────────
def test_publica_output_valido(tmp_path, monkeypatch):
    monkeypatch.setattr(mi.subprocess, "run", _fake_ffprobe(0, VIDEO_OK))
    final = tmp_path / "out.mp4"
    elapsed = mi.publicar_mp4_atomico(final, _quemar_ok(b"NUEVO"))
    assert elapsed == 1.5
    assert final.read_bytes() == b"NUEVO"
    assert _no_part_residual(tmp_path)


def test_reemplaza_final_anterior(tmp_path, monkeypatch):
    monkeypatch.setattr(mi.subprocess, "run", _fake_ffprobe(0, VIDEO_OK))
    final = tmp_path / "out.mp4"
    final.write_bytes(b"VIEJO")
    mi.publicar_mp4_atomico(final, _quemar_ok(b"NUEVO"))
    assert final.read_bytes() == b"NUEVO"
    assert _no_part_residual(tmp_path)


def test_ffmpeg_returncode_no_cero_conserva_final(tmp_path, monkeypatch):
    monkeypatch.setattr(mi.subprocess, "run", _fake_ffprobe(0, VIDEO_OK))
    final = tmp_path / "out.mp4"
    final.write_bytes(b"VIEJO")

    def _quemar_falla(target):
        target.write_bytes(b"PARCIAL")
        raise RuntimeError("FFmpeg error: boom")

    with pytest.raises(RuntimeError):
        mi.publicar_mp4_atomico(final, _quemar_falla)
    assert final.read_bytes() == b"VIEJO"  # el final anterior queda intacto
    assert _no_part_residual(tmp_path)  # temporal parcial borrado


def test_ffmpeg_excepcion_sin_final_previo(tmp_path, monkeypatch):
    monkeypatch.setattr(mi.subprocess, "run", _fake_ffprobe(0, VIDEO_OK))
    final = tmp_path / "out.mp4"

    def _quemar_boom(_target):
        raise RuntimeError("crash")

    with pytest.raises(RuntimeError):
        mi.publicar_mp4_atomico(final, _quemar_boom)
    assert not final.exists()
    assert _no_part_residual(tmp_path)


def test_temp_cero_bytes_no_publica(tmp_path, monkeypatch):
    monkeypatch.setattr(mi.subprocess, "run", _fake_ffprobe(0, VIDEO_OK))
    final = tmp_path / "out.mp4"
    final.write_bytes(b"VIEJO")
    with pytest.raises(mi.MediaIntegrityError):
        mi.publicar_mp4_atomico(final, _quemar_ok(b""))
    assert final.read_bytes() == b"VIEJO"
    assert _no_part_residual(tmp_path)


def test_temp_inexistente_no_publica(tmp_path, monkeypatch):
    monkeypatch.setattr(mi.subprocess, "run", _fake_ffprobe(0, VIDEO_OK))
    final = tmp_path / "out.mp4"

    def _quemar_nada(_target):
        return 1.0  # no crea el archivo

    with pytest.raises(mi.MediaIntegrityError):
        mi.publicar_mp4_atomico(final, _quemar_nada)
    assert not final.exists()
    assert _no_part_residual(tmp_path)


def test_ffprobe_invalido_no_publica(tmp_path, monkeypatch):
    monkeypatch.setattr(mi.subprocess, "run", _fake_ffprobe(0, SIN_VIDEO))
    final = tmp_path / "out.mp4"
    final.write_bytes(b"VIEJO")
    with pytest.raises(mi.MediaIntegrityError):
        mi.publicar_mp4_atomico(final, _quemar_ok(b"NUEVO"))
    assert final.read_bytes() == b"VIEJO"
    assert _no_part_residual(tmp_path)


# ── Integracion: el worker de render deja el job en error (no done) y saneado ──
def test_render_worker_integridad_rota_job_error(tmp_path, monkeypatch):
    trans = tmp_path / "transcripts"
    out = tmp_path / "output"
    trans.mkdir()
    out.mkdir()
    monkeypatch.setattr(jobs_render, "TRANSCRIPTS", trans)
    monkeypatch.setattr(jobs_render, "OUTPUT_DIR", out)
    grp = trans / "demo_groups.json"
    grp.write_text(
        json.dumps([{"id": 0, "start": 0.0, "end": 1.0, "words": [], "text": ""}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(core, "get_video_info", lambda _p: {"width": 1080, "height": 1920})
    monkeypatch.setattr(core, "build_ass", lambda *a, **k: None)

    def _burn_integridad(*_a, **_k):
        raise mi.MediaIntegrityError("el archivo quedo en 0 bytes")

    monkeypatch.setattr(core, "burn_video", _burn_integridad)

    jid = jobs_registry.new_job("render demo")
    jobs_render.run_render(jid, out / "demo.mp4", grp, "demo", "hormozi", None)
    job = jobs_registry.get_job(jid)
    assert job["status"] == "error" and job["result"] is None
    assert "0 bytes" in job["message"]  # mensaje tipado saneado (sin ruta ni comando)
    assert str(tmp_path) not in job["message"]
