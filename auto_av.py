"""auto_av.py — Verificacion DURA de integridad de audio y sincronizacion A/V (S37-B, #47d).

Dos compuertas independientes sobre el clip 9:16 de entrada al render y el video final:

INTEGRIDAD: el payload de audio comprimido debe ser IDENTICO (mismos paquetes, mismos
hashes SHA256, mismo orden). El audio del b-roll jamas entra (`-map 0:a` + `-c:a copy`).
Se compara via `ffprobe -show_packets -show_data_hash sha256` (payload puro, sin exigir
PTS identicos); fallback por extraccion `-c copy` a ADTS si la version local de ffprobe
no expusiera data_hash.

SINCRONIZACION: tolerancias vinculantes de #47d — start de audio <=0.050s, duracion de
audio <=0.050s, delta inicial A/V <=0.120s, drift final <= max(0.120s, 2/fps_final).

Errores TIPADOS (`AudioIntegrityError`/`AVSyncError`, ambos RuntimeError): un clip que
altera el audio NO es valido y la excepcion se PROPAGA (nunca fail-open, nunca SystemExit).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

# Tolerancias #47d (segundos)
AUDIO_START_TOL_S = 0.050
AUDIO_DURATION_TOL_S = 0.050
AV_START_TOL_S = 0.120
AV_END_DRIFT_BASE_S = 0.120


class AutoAVError(RuntimeError):
    """Base de errores de verificacion A/V del Modo Automatico v2."""


class AudioIntegrityError(AutoAVError):
    """El payload de audio del video final difiere del clip fuente."""


class AVSyncError(AutoAVError):
    """La sincronizacion A/V del video final excede las tolerancias de #47d."""


def _ffprobe_json(args: list[str], path: Path) -> dict:
    """Corre ffprobe -of json y devuelve el dict. Fallo del proceso -> AutoAVError."""
    cmd = ["ffprobe", "-v", "quiet", *args, "-of", "json", str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise AutoAVError(f"ffprobe fallo sobre {Path(path).name}: {r.stderr[-300:]}")
    try:
        return json.loads(r.stdout)
    except ValueError as e:
        raise AutoAVError(f"ffprobe devolvio JSON invalido para {Path(path).name}: {e}") from e


def audio_packet_hashes(path: Path) -> list[str] | None:
    """Hashes SHA256 del payload de cada paquete de audio (orden del stream).

    [] = el archivo no tiene stream de audio. Si ffprobe no expone data_hash en esta
    version, devuelve None para que el caller use el fallback por extraccion.
    """
    data = _ffprobe_json(
        [
            "-select_streams",
            "a:0",
            "-show_packets",
            "-show_entries",
            "packet=data_hash",
            "-show_data_hash",
            "sha256",
        ],
        path,
    )
    packets = data.get("packets", [])
    hashes = [p.get("data_hash") for p in packets]
    if packets and any(h is None for h in hashes):
        return None  # version de ffprobe sin data_hash -> fallback
    return hashes


def _audio_stream_bytes_sha256(path: Path) -> tuple[int, str] | None:
    """Fallback: extrae el stream de audio con -c copy (ADTS para AAC) y hashea los bytes.

    Devuelve (packet_count, sha256) o None si no hay stream de audio. Solo soporta AAC
    (el codec del pipeline); otro codec sin data_hash -> AutoAVError (no se adivina).
    """
    codec = _codec_audio(path)
    if codec is None:
        return None
    if codec != "aac":
        raise AutoAVError(f"fallback de integridad solo soporta AAC, codec={codec}")
    count = _conteo_paquetes_audio(path)
    with tempfile.TemporaryDirectory() as tmp:
        destino = Path(tmp) / "a.adts"
        cmd = [
            "ffmpeg",
            "-y",
            "-v",
            "quiet",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-c",
            "copy",
            "-f",
            "adts",
            str(destino),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise AutoAVError(f"extraccion de audio fallo: {r.stderr[-300:]}")
        return count, hashlib.sha256(destino.read_bytes()).hexdigest()


def _codec_audio(path: Path) -> str | None:
    data = _ffprobe_json(["-select_streams", "a:0", "-show_entries", "stream=codec_name"], path)
    streams = data.get("streams", [])
    return streams[0].get("codec_name") if streams else None


def _conteo_paquetes_audio(path: Path) -> int:
    data = _ffprobe_json(
        ["-select_streams", "a:0", "-count_packets", "-show_entries", "stream=nb_read_packets"],
        path,
    )
    streams = data.get("streams", [])
    return int(streams[0].get("nb_read_packets", 0)) if streams else 0


def verificar_integridad(source: Path, output: Path) -> dict:
    """Compuerta de INTEGRIDAD: payload de audio identico entre fuente y salida.

    PASS -> dict serializable. FAIL -> AudioIntegrityError. Sin audio en ambos ->
    PASS con status "no_audio"; audio en solo uno -> FAIL.
    """
    h_src = audio_packet_hashes(source)
    h_out = audio_packet_hashes(output)
    if h_src is None or h_out is None:  # ffprobe sin data_hash -> fallback por bytes
        return _integridad_fallback(source, output)
    if not h_src and not h_out:
        return {"status": "no_audio", "packet_count_source": 0, "packet_count_output": 0}
    if bool(h_src) != bool(h_out):
        raise AudioIntegrityError(
            f"solo un lado tiene audio (fuente={len(h_src)} paquetes, salida={len(h_out)})"
        )
    if len(h_src) != len(h_out):
        raise AudioIntegrityError(
            f"numero de paquetes de audio distinto: {len(h_src)} != {len(h_out)}"
        )
    if h_src != h_out:
        primera = next(i for i, (a, b) in enumerate(zip(h_src, h_out, strict=True)) if a != b)
        raise AudioIntegrityError(f"payload de audio difiere (primer paquete distinto: #{primera})")
    digest = hashlib.sha256("".join(h_src).encode("ascii")).hexdigest()
    return {
        "status": "pass",
        "packet_count_source": len(h_src),
        "packet_count_output": len(h_out),
        "payload_sha256": digest,
    }


def _integridad_fallback(source: Path, output: Path) -> dict:
    """Integridad sin data_hash: bytes del stream extraido con -c copy (documentado)."""
    src = _audio_stream_bytes_sha256(source)
    out = _audio_stream_bytes_sha256(output)
    if src is None and out is None:
        return {"status": "no_audio", "packet_count_source": 0, "packet_count_output": 0}
    if (src is None) != (out is None):
        raise AudioIntegrityError("solo un lado tiene audio (fallback por bytes)")
    if src[0] != out[0]:
        raise AudioIntegrityError(f"numero de paquetes distinto: {src[0]} != {out[0]}")
    if src[1] != out[1]:
        raise AudioIntegrityError("payload de audio difiere (sha256 del stream extraido)")
    return {
        "status": "pass",
        "method": "stream_copy_bytes",
        "packet_count_source": src[0],
        "packet_count_output": out[0],
        "payload_sha256": out[1],
    }


def _parse_fps(raw: str | None) -> float | None:
    if not raw or raw in ("0/0", "N/A"):
        return None
    if "/" in raw:
        num, den = raw.split("/", 1)
        try:
            return float(num) / float(den) if float(den) else None
        except ValueError:
            return None
    try:
        return float(raw)
    except ValueError:
        return None


def _stream_meta(path: Path, selector: str) -> dict | None:
    """{start, duration, fps} del stream `a:0`/`v:0`; usa format.duration como fallback.

    None = el archivo no tiene ese stream. Metadata irrecuperable -> AVSyncError
    (no se declara PASS sin evidencia).
    """
    data = _ffprobe_json(
        [
            "-select_streams",
            selector,
            "-show_entries",
            "stream=start_time,duration,avg_frame_rate,r_frame_rate",
            "-show_entries",
            "format=duration",
        ],
        path,
    )
    streams = data.get("streams", [])
    if not streams:
        return None
    s = streams[0]

    def _num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    start = _num(s.get("start_time"))
    dur = _num(s.get("duration")) or _num(data.get("format", {}).get("duration"))
    if start is None:
        start = 0.0  # contenedores sin start_time explicito: MP4 arranca en 0
    if dur is None:
        raise AVSyncError(f"duracion no disponible para {selector} de {Path(path).name}")
    fps = _parse_fps(s.get("avg_frame_rate")) or _parse_fps(s.get("r_frame_rate"))
    return {"start": start, "duration": dur, "fps": fps}


def verificar_sync(source: Path, output: Path) -> dict:
    """Compuerta de SINCRONIZACION (#47d). PASS -> dict serializable; FAIL -> AVSyncError."""
    a_src = _stream_meta(source, "a:0")
    a_out = _stream_meta(output, "a:0")
    v_out = _stream_meta(output, "v:0")
    if a_src is None and a_out is None:
        return {"status": "no_audio"}
    if a_src is None or a_out is None:
        raise AVSyncError("solo un lado tiene stream de audio")
    if v_out is None:
        raise AVSyncError("el video final no tiene stream de video")
    fps_out = v_out["fps"] or 30.0
    allowed_drift = max(AV_END_DRIFT_BASE_S, 2.0 / fps_out)

    start_delta = abs(a_out["start"] - a_src["start"])
    dur_delta = abs(a_out["duration"] - a_src["duration"])
    av_start = abs(a_out["start"] - v_out["start"])
    end_audio = a_out["start"] + a_out["duration"]
    end_video = v_out["start"] + v_out["duration"]
    drift_end = abs(end_audio - end_video)

    resultado = {
        "status": "pass",
        "audio_start_delta_s": round(start_delta, 4),
        "audio_duration_delta_s": round(dur_delta, 4),
        "av_start_delta_s": round(av_start, 4),
        "av_end_drift_s": round(drift_end, 4),
        "allowed_end_drift_s": round(allowed_drift, 4),
        "fps_output": round(fps_out, 4),
    }
    if start_delta > AUDIO_START_TOL_S:
        raise AVSyncError(f"start de audio se movio {start_delta:.4f}s (> {AUDIO_START_TOL_S}s)")
    if dur_delta > AUDIO_DURATION_TOL_S:
        raise AVSyncError(f"duracion de audio cambio {dur_delta:.4f}s (> {AUDIO_DURATION_TOL_S}s)")
    if av_start > AV_START_TOL_S:
        raise AVSyncError(f"delta inicial A/V {av_start:.4f}s (> {AV_START_TOL_S}s)")
    if drift_end > allowed_drift:
        raise AVSyncError(f"drift final A/V {drift_end:.4f}s (> {allowed_drift:.4f}s)")
    return resultado


def verificar_av(source: Path, output: Path) -> dict:
    """Ambas compuertas. Devuelve {"integrity": ..., "sync": ...}; FAIL -> excepcion tipada."""
    return {
        "integrity": verificar_integridad(source, output),
        "sync": verificar_sync(source, output),
    }


__all__ = [
    "AutoAVError",
    "AudioIntegrityError",
    "AVSyncError",
    "audio_packet_hashes",
    "verificar_integridad",
    "verificar_sync",
    "verificar_av",
]
