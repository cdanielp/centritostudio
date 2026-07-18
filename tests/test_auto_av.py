"""test_auto_av.py — Compuertas duras de audio y A/V del Modo Automatico v2 (S37-B, #47d).

Mezcla dos niveles:
- Archivos REALES generados con FFmpeg local (lavfi, 2s, 64x64): integridad por hash de
  paquetes de verdad, sin red ni GPU.
- Matematica de tolerancias con `_stream_meta` monkeypatcheado: casos dentro/fuera de
  cada compuerta de forma determinista.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import auto_av
from auto_av import (
    AudioIntegrityError,
    AutoAVError,
    AVSyncError,
    verificar_av,
    verificar_integridad,
    verificar_sync,
)


@pytest.fixture(autouse=True)
def _sin_red(monkeypatch):
    import socket

    def _bloqueado(*a, **k):
        raise RuntimeError("red bloqueada en tests (S37-B)")

    monkeypatch.setattr(socket.socket, "connect", _bloqueado)


def _ffmpeg(*args):
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", *args], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-500:]


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    """Fixtures sinteticas: fuente con audio, copia con audio intacto, variantes rotas."""
    d = tmp_path_factory.mktemp("av")
    src = d / "src.mp4"
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "color=c=blue:size=64x64:rate=30",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=44100",
        "-t",
        "2",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "30",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(src),
    )
    ok = d / "ok.mp4"  # re-encode de video + AUDIO COPIADO (lo que hace el render real)
    _ffmpeg(
        "-i",
        str(src),
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "35",
        "-c:a",
        "copy",
        str(ok),
    )
    reenc = d / "reenc.mp4"  # audio RE-ENCODEADO: payload distinto
    _ffmpeg("-i", str(src), "-c:v", "copy", "-c:a", "aac", "-b:a", "96k", str(reenc))
    noaudio = d / "noaudio.mp4"
    _ffmpeg("-i", str(src), "-c:v", "copy", "-an", str(noaudio))
    corto = d / "corto.mp4"  # menos paquetes de audio
    _ffmpeg("-i", str(src), "-t", "1.2", "-c:v", "copy", "-c:a", "copy", str(corto))
    return {"src": src, "ok": ok, "reenc": reenc, "noaudio": noaudio, "corto": corto}


# ── Integridad con archivos reales ───────────────────────────────────────────


def test_integridad_payload_identico_pass(media):
    res = verificar_integridad(media["src"], media["ok"])
    assert res["status"] == "pass"
    assert res["packet_count_source"] == res["packet_count_output"] > 0
    assert len(res["payload_sha256"]) == 64


def test_integridad_payload_distinto_fail(media):
    with pytest.raises(AudioIntegrityError):
        verificar_integridad(media["src"], media["reenc"])


def test_integridad_conteo_distinto_fail(media):
    with pytest.raises(AudioIntegrityError):
        verificar_integridad(media["src"], media["corto"])


def test_integridad_salida_sin_audio_fail(media):
    with pytest.raises(AudioIntegrityError):
        verificar_integridad(media["src"], media["noaudio"])


def test_integridad_fuente_sin_audio_fail(media):
    with pytest.raises(AudioIntegrityError):
        verificar_integridad(media["noaudio"], media["src"])


def test_integridad_ambos_sin_audio_pass(media):
    res = verificar_integridad(media["noaudio"], media["noaudio"])
    assert res["status"] == "no_audio"


def test_integridad_hashes_reales(media):
    hashes = auto_av.audio_packet_hashes(media["src"])
    assert hashes and all(h.startswith("SHA256:") for h in hashes)


def test_integridad_fallback_bytes_pass(media, monkeypatch):
    """Si ffprobe no expusiera data_hash, el fallback por bytes extraidos verifica igual."""
    monkeypatch.setattr(auto_av, "audio_packet_hashes", lambda p: None)
    res = verificar_integridad(media["src"], media["ok"])
    assert res["status"] == "pass" and res["method"] == "stream_copy_bytes"


def test_integridad_fallback_detecta_diferencia(media, monkeypatch):
    monkeypatch.setattr(auto_av, "audio_packet_hashes", lambda p: None)
    with pytest.raises(AudioIntegrityError):
        verificar_integridad(media["src"], media["reenc"])


# ── Sync con archivos reales ─────────────────────────────────────────────────


def test_sync_render_tipico_pass(media):
    res = verificar_sync(media["src"], media["ok"])
    assert res["status"] == "pass"
    assert res["audio_start_delta_s"] <= 0.05
    assert res["av_end_drift_s"] <= res["allowed_end_drift_s"]


def test_sync_ambos_sin_audio_pass(media):
    assert verificar_sync(media["noaudio"], media["noaudio"])["status"] == "no_audio"


def test_sync_solo_un_lado_con_audio_fail(media):
    with pytest.raises(AVSyncError):
        verificar_sync(media["src"], media["noaudio"])


def test_verificar_av_completo(media):
    res = verificar_av(media["src"], media["ok"])
    assert res["integrity"]["status"] == "pass" and res["sync"]["status"] == "pass"


# ── Matematica de tolerancias (metadata controlada) ──────────────────────────


def _meta(monkeypatch, a_src, a_out, v_out):
    tabla = {("src", "a:0"): a_src, ("out", "a:0"): a_out, ("out", "v:0"): v_out}

    def fake(path, selector):
        return tabla[(Path(path).name, selector)]

    monkeypatch.setattr(auto_av, "_stream_meta", fake)


def test_sync_start_delta_dentro(monkeypatch):
    _meta(
        monkeypatch,
        {"start": 0.0, "duration": 10.0, "fps": None},
        {"start": 0.04, "duration": 10.0, "fps": None},
        {"start": 0.0, "duration": 10.0, "fps": 30.0},
    )
    assert verificar_sync(Path("src"), Path("out"))["status"] == "pass"


def test_sync_start_delta_fuera(monkeypatch):
    _meta(
        monkeypatch,
        {"start": 0.0, "duration": 10.0, "fps": None},
        {"start": 0.08, "duration": 10.0, "fps": None},
        {"start": 0.0, "duration": 10.0, "fps": 30.0},
    )
    with pytest.raises(AVSyncError, match="start de audio"):
        verificar_sync(Path("src"), Path("out"))


def test_sync_duracion_dentro(monkeypatch):
    _meta(
        monkeypatch,
        {"start": 0.0, "duration": 10.0, "fps": None},
        {"start": 0.0, "duration": 10.04, "fps": None},
        {"start": 0.0, "duration": 10.0, "fps": 30.0},
    )
    assert verificar_sync(Path("src"), Path("out"))["status"] == "pass"


def test_sync_duracion_fuera(monkeypatch):
    _meta(
        monkeypatch,
        {"start": 0.0, "duration": 10.0, "fps": None},
        {"start": 0.0, "duration": 10.2, "fps": None},
        {"start": 0.0, "duration": 10.0, "fps": 30.0},
    )
    with pytest.raises(AVSyncError, match="duracion de audio"):
        verificar_sync(Path("src"), Path("out"))


def test_sync_av_start_fuera(monkeypatch):
    _meta(
        monkeypatch,
        {"start": 0.0, "duration": 10.0, "fps": None},
        {"start": 0.0, "duration": 10.0, "fps": None},
        {"start": 0.15, "duration": 10.0, "fps": 30.0},
    )
    with pytest.raises(AVSyncError, match="delta inicial"):
        verificar_sync(Path("src"), Path("out"))


def test_sync_drift_final_fuera(monkeypatch):
    _meta(
        monkeypatch,
        {"start": 0.0, "duration": 10.0, "fps": None},
        {"start": 0.0, "duration": 10.0, "fps": None},
        {"start": 0.0, "duration": 10.3, "fps": 30.0},
    )
    with pytest.raises(AVSyncError, match="drift final"):
        verificar_sync(Path("src"), Path("out"))


def test_sync_tolerancia_dinamica_por_fps(monkeypatch):
    # fps 10 -> drift permitido max(0.12, 2/10)=0.2; un drift de 0.18 debe PASAR
    _meta(
        monkeypatch,
        {"start": 0.0, "duration": 10.0, "fps": None},
        {"start": 0.0, "duration": 10.0, "fps": None},
        {"start": 0.0, "duration": 10.18, "fps": 10.0},
    )
    res = verificar_sync(Path("src"), Path("out"))
    assert res["status"] == "pass" and res["allowed_end_drift_s"] == 0.2


def test_sync_valores_reportados(monkeypatch):
    _meta(
        monkeypatch,
        {"start": 0.0, "duration": 10.0, "fps": None},
        {"start": 0.02, "duration": 10.01, "fps": None},
        {"start": 0.0, "duration": 10.0, "fps": 30.0},
    )
    res = verificar_sync(Path("src"), Path("out"))
    assert res["audio_start_delta_s"] == 0.02
    assert res["audio_duration_delta_s"] == 0.01


def test_metadata_sin_duracion_avsyncerror(monkeypatch):
    monkeypatch.setattr(
        auto_av,
        "_ffprobe_json",
        lambda a, p: {"streams": [{"start_time": "0.0"}], "format": {}},
    )
    with pytest.raises(AVSyncError, match="duracion no disponible"):
        auto_av._stream_meta(Path("x.mp4"), "a:0")


# ── Contratos de excepcion ───────────────────────────────────────────────────


def test_jerarquia_de_excepciones():
    assert issubclass(AudioIntegrityError, AutoAVError)
    assert issubclass(AVSyncError, AutoAVError)
    assert issubclass(AutoAVError, RuntimeError)
    assert not issubclass(AutoAVError, SystemExit)


def test_ffprobe_inexistente_autoaverror(tmp_path):
    with pytest.raises(AutoAVError):
        auto_av.audio_packet_hashes(tmp_path / "no-existe.mp4")


def test_fallback_solo_aac(monkeypatch, tmp_path):
    monkeypatch.setattr(auto_av, "_codec_audio", lambda p: "mp3")
    with pytest.raises(AutoAVError, match="solo soporta AAC"):
        auto_av._audio_stream_bytes_sha256(tmp_path / "x.mp4")


def test_parse_fps():
    assert auto_av._parse_fps("30000/1001") == pytest.approx(29.97, abs=0.01)
    assert auto_av._parse_fps("0/0") is None
    assert auto_av._parse_fps(None) is None
    assert auto_av._parse_fps("25") == 25.0
