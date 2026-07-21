"""video_encoder.py — Deteccion y seleccion centralizada del codificador de video (NVENC/CPU).

Fase GPU pre-HyperFrames: mueve la CODIFICACION H.264 a NVIDIA NVENC cuando esta disponible,
con fallback seguro a libx264 (CPU). NO toca filtros, audio, tracking, deteccion facial,
resolucion, FPS ni Whisper: solo sustituye los argumentos del ENCODER de video. Los argumentos
CPU son BYTE-IDENTICOS a los historicos (tests de contrato). Fuente unica para no duplicar
deteccion ni argumentos entre depurador, captions, overlays y reframe. Comandos como listas
(nunca shell=True); encoder de enum cerrado; nunca expone stderr completo, rutas ni variables.
"""

from __future__ import annotations

import contextlib
import functools
import os
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

ENV_VAR = "CENTRITO_VIDEO_ENCODER"
PROBE_TIMEOUT_S = 20  # micro-probe y listado de encoders acotados
_PROBE_SIZE = "256x256"  # NVENC rechaza dimensiones menores (min-dimension del driver)


class EncoderMode(StrEnum):
    """Modo solicitado (enum cerrado). El default es auto."""

    AUTO = "auto"
    NVENC = "nvenc"
    CPU = "cpu"


class EncoderProfile(StrEnum):
    """Perfil de calidad por pipeline (quality = captions/depuracion; fast = reframe)."""

    QUALITY = "quality"
    FAST = "fast"


class EncoderConfigurationError(Exception):
    """Configuracion invalida (modo/perfil/encoder fuera del enum cerrado)."""


class NVENCUnavailable(Exception):
    """Se pidio NVENC explicito pero el runtime no esta disponible (mensaje accionable)."""


class VideoEncodeError(RuntimeError):
    """FFmpeg fallo la codificacion; el detalle tecnico queda saneado.

    Subclase de RuntimeError para preservar los `except RuntimeError` historicos del pipeline.
    """


# ── Argumentos del encoder ──────────────────────────────────────────────────────
# CPU: byte-identico al historico (depurador/core_ass/core_overlays usan quality; reframe fast).
_CPU_ARGS = {
    EncoderProfile.QUALITY: ["-c:v", "libx264", "-preset", "medium", "-crf", "18"],
    EncoderProfile.FAST: ["-c:v", "libx264", "-crf", "18", "-preset", "fast"],
}


# NVENC: validado localmente contra `ffmpeg -h encoder=h264_nvenc` en la RTX de destino.
# quality/fast solo difieren en el preset (p5 vs p4); el resto es identico (DRY).
def _nvenc_args(preset: str) -> list[str]:
    return [
        "-c:v",
        "h264_nvenc",
        "-preset",
        preset,
        "-tune",
        "hq",
        "-rc",
        "vbr",
        "-cq",
        "18",
        "-b:v",
        "0",
        "-pix_fmt",
        "yuv420p",
    ]


_NVENC_ARGS = {EncoderProfile.QUALITY: _nvenc_args("p5"), EncoderProfile.FAST: _nvenc_args("p4")}

# Mensajes de UI saneados (sin stderr, sin rutas, sin driver interno).
MSG_OK = "NVIDIA NVENC disponible."
MSG_NO_ENCODER = "Esta instalacion de FFmpeg no incluye h264_nvenc."
MSG_RUNTIME = (
    "NVIDIA NVENC esta incluido en FFmpeg, pero no pudo inicializarse. Revisa el driver NVIDIA."
)
MSG_NO_FFMPEG = "FFmpeg no esta instalado."

# Marcadores de fallo de INICIALIZACION de NVENC: solo estos permiten fallback auto -> CPU.
# Son especificos de la sesion NVENC; un error de input/filtro/ASS/EDL/audio NUNCA coincide aqui,
# asi que jamas se reintenta en CPU un error que CPU tambien fallaria (regla de la FASE 4).
_NVENC_INIT_MARKERS = (
    "initializeencoder failed",
    "openencodesessionex failed",
    "no capable devices found",
    "cannot load nvcuda",
    "cannot load libnvidia-encode",
    "minimum required nvidia driver",
    "cannot load nvencodeapi",
    "no nvenc capable devices",
)


@dataclass(frozen=True)
class NvencStatus:
    """Resultado cacheado de la deteccion de NVENC."""

    available: bool
    reason: str  # codigo interno: ok | no_ffmpeg | no_encoder | runtime
    message: str  # mensaje de UI en espanol (saneado)


@dataclass(frozen=True)
class EncoderSelection:
    """Instantanea inmutable de la decision de encoder para un encode."""

    requested: str  # auto | nvenc | cpu
    selected: str  # nvenc | cpu
    encoder: str  # h264_nvenc | libx264
    profile: str  # quality | fast
    reason: str
    fallback_used: bool = False


# ── Deteccion real de NVENC (cacheada por proceso, refrescable) ─────────────────
_lock = threading.Lock()
_cache: NvencStatus | None = None


def _encoder_listed(ffmpeg: str) -> bool | None:
    """None si FFmpeg no esta instalado; True/False si h264_nvenc esta compilado."""
    try:
        r = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_S,
        )
    except OSError:
        return None
    except subprocess.TimeoutExpired:
        return False
    return "h264_nvenc" in (r.stdout or "")


def _runtime_probe_ok(ffmpeg: str) -> bool:
    """Micro-probe real: codifica 1s de 256x256 sin audio a un temporal del sistema y lo valida.

    No usa red, no requiere nvidia-smi, no escribe en input/ ni output/, limpia siempre.
    """
    tmp = Path(tempfile.mkdtemp(prefix="nvenc_probe_"))
    out = tmp / "probe.mp4"
    # fmt: off
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"color=c=black:s={_PROBE_SIZE}:d=1:r=30", "-an",
        *_NVENC_ARGS[EncoderProfile.FAST], str(out),
    ]
    # fmt: on
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=PROBE_TIMEOUT_S)
        return r.returncode == 0 and out.exists() and out.stat().st_size > 0
    except (OSError, subprocess.TimeoutExpired):
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _probe_nvenc(ffmpeg: str) -> NvencStatus:
    """Distingue: FFmpeg ausente, sin h264_nvenc, runtime no funcional, o funcional."""
    listed = _encoder_listed(ffmpeg)
    if listed is None:
        return NvencStatus(False, "no_ffmpeg", MSG_NO_FFMPEG)
    if not listed:
        return NvencStatus(False, "no_encoder", MSG_NO_ENCODER)
    if _runtime_probe_ok(ffmpeg):
        return NvencStatus(True, "ok", MSG_OK)
    return NvencStatus(False, "runtime", MSG_RUNTIME)


def detect_nvenc(*, force: bool = False, ffmpeg: str = "ffmpeg") -> NvencStatus:
    """Deteccion cacheada por proceso. `force=True` la recalcula (tests/diagnostico)."""
    global _cache
    with _lock:
        if _cache is not None and not force:
            return _cache
        _cache = _probe_nvenc(ffmpeg)
        return _cache


def refresh_nvenc(*, ffmpeg: str = "ffmpeg") -> NvencStatus:
    """Forma controlada de refrescar la cache (usada por tests y diagnostico)."""
    return detect_nvenc(force=True, ffmpeg=ffmpeg)


def _reset_cache_for_tests() -> None:
    """Limpia la cache de deteccion (solo para pruebas: sin FFmpeg real)."""
    global _cache
    with _lock:
        _cache = None


# ── Modo por defecto y snapshot por job ─────────────────────────────────────────
def _mode_from_env() -> EncoderMode:
    """CENTRITO_VIDEO_ENCODER -> modo. Valor invalido cae a auto con warning local saneado."""
    raw = (os.environ.get(ENV_VAR) or "").strip().lower()
    if not raw:
        return EncoderMode.AUTO
    try:
        return EncoderMode(raw)
    except ValueError:
        print(f"[encoder] {ENV_VAR} invalido; se usa 'auto'")
        return EncoderMode.AUTO


_default_mode = _mode_from_env()
_snapshot = threading.local()


def coerce_mode(value: str | EncoderMode) -> EncoderMode:
    """Normaliza a EncoderMode; valor fuera del enum -> EncoderConfigurationError (API estricta)."""
    if isinstance(value, EncoderMode):
        return value
    raw = (value or "").strip().lower()
    try:
        return EncoderMode(raw)
    except ValueError:
        raise EncoderConfigurationError(f"modo de encoder invalido: {value!r}") from None


def _coerce_profile(value: str | EncoderProfile) -> EncoderProfile:
    if isinstance(value, EncoderProfile):
        return value
    try:
        return EncoderProfile((value or "").strip().lower())
    except ValueError:
        raise EncoderConfigurationError(f"perfil de encoder invalido: {value!r}") from None


def get_default_mode() -> EncoderMode:
    """Modo por defecto actual en memoria (autoridad del backend para jobs NUEVOS)."""
    return _default_mode


def set_default_mode(value: str | EncoderMode) -> EncoderMode:
    """Actualiza el default en memoria (PUT). Afecta solo jobs nuevos; los activos no cambian."""
    global _default_mode
    _default_mode = coerce_mode(value)
    return _default_mode


@contextlib.contextmanager
def snapshot_job(mode: str | EncoderMode | None = None):
    """Fija una instantania inmutable del modo para todo un job (thread-local).

    Un cambio de default via PUT durante el job NO altera esta instantania.
    """
    prev = getattr(_snapshot, "mode", None)
    _snapshot.mode = coerce_mode(mode) if mode is not None else _default_mode
    try:
        yield _snapshot.mode
    finally:
        _snapshot.mode = prev


def active_mode() -> EncoderMode:
    """Modo efectivo del contexto actual: la instantania del job si existe, si no el default."""
    m = getattr(_snapshot, "mode", None)
    return m if m is not None else _default_mode


def con_snapshot(func):
    """Decorador de worker: corre la funcion dentro de un snapshot inmutable del modo (por job)."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with snapshot_job():
            return func(*args, **kwargs)

    return wrapper


# ── Seleccion y argumentos ──────────────────────────────────────────────────────
def _cpu_selection(
    requested: EncoderMode, profile: EncoderProfile, reason: str, *, fallback: bool = False
) -> EncoderSelection:
    return EncoderSelection(requested.value, "cpu", "libx264", profile.value, reason, fallback)


def _nvenc_selection(
    requested: EncoderMode, profile: EncoderProfile, reason: str
) -> EncoderSelection:
    return EncoderSelection(requested.value, "nvenc", "h264_nvenc", profile.value, reason, False)


def select_encoder(
    mode: str | EncoderMode, profile: str | EncoderProfile, *, status: NvencStatus | None = None
) -> EncoderSelection:
    """Resuelve (modo, perfil) -> EncoderSelection. Modo nvenc no disponible -> NVENCUnavailable."""
    mode = coerce_mode(mode)
    profile = _coerce_profile(profile)
    if mode == EncoderMode.CPU:
        return _cpu_selection(mode, profile, "modo cpu solicitado")
    st = status or detect_nvenc()
    if mode == EncoderMode.NVENC:
        if not st.available:
            raise NVENCUnavailable(st.message)
        return _nvenc_selection(mode, profile, "modo nvenc solicitado")
    # auto: NVENC si funcional, si no CPU (nunca es error fatal).
    if st.available:
        return _nvenc_selection(mode, profile, "auto: NVENC disponible")
    return _cpu_selection(mode, profile, f"auto: {st.message}")


def build_video_args(selection: EncoderSelection) -> list[str]:
    """Argumentos del ENCODER de video para el comando FFmpeg (solo -c:v y opciones propias)."""
    profile = _coerce_profile(selection.profile)
    if selection.encoder == "h264_nvenc":
        return list(_NVENC_ARGS[profile])
    if selection.encoder == "libx264":
        return list(_CPU_ARGS[profile])
    raise EncoderConfigurationError(f"encoder no permitido: {selection.encoder!r}")


def selection_telemetry(selection: EncoderSelection, encode_time_s: float | None = None) -> dict:
    """Telemetria saneada para el resultado de un job (sin rutas ni stderr)."""
    out = {
        "video_encoder": selection.encoder,
        "encoder_mode": selection.requested,
        "fallback_used": selection.fallback_used,
    }
    if encode_time_s is not None:
        out["encode_time_s"] = round(encode_time_s, 2)
    return out


# ── Clasificacion de errores y fallback ─────────────────────────────────────────
def is_nvenc_init_failure(stderr: str) -> bool:
    """True si el stderr indica un fallo de INICIALIZACION de NVENC (permite fallback)."""
    low = (stderr or "").lower()
    return any(m in low for m in _NVENC_INIT_MARKERS)


def sanitize_encoder_error(stderr: str) -> str:
    """Mensaje corto y saneado del fallo de FFmpeg (sin rutas, sin stderr completo, sin env)."""
    if is_nvenc_init_failure(stderr):
        return MSG_RUNTIME
    return "La codificacion de video no pudo completarse."


@dataclass(frozen=True)
class EncodeOutcome:
    """Resultado de un encode ejecutado: seleccion efectiva + tiempo."""

    selection: EncoderSelection
    elapsed: float


def _run_cmd(cmd: list[str]) -> tuple[int, str, float]:
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, (r.stderr or ""), round(time.time() - t0, 2)


def run_ffmpeg_encode(
    selection: EncoderSelection,
    build_cmd: Callable[[list[str]], list[str]],
    *,
    cleanup: Callable[[], None] | None = None,
) -> EncodeOutcome:
    """Ejecuta un encode FFmpeg. En modo auto reintenta UNA vez en CPU si NVENC falla al iniciar.

    `build_cmd(video_args)` devuelve el comando FFmpeg completo (lista) que escribe al destino.
    `cleanup` (opcional) borra el parcial NVENC antes del reintento en CPU. Un error de
    input/filtro/ASS/EDL/audio NUNCA reintenta: se propaga saneado.
    """
    rc, stderr, elapsed = _run_cmd(build_cmd(build_video_args(selection)))
    if rc == 0:
        return EncodeOutcome(selection, elapsed)
    auto_nvenc = selection.requested == EncoderMode.AUTO.value and selection.selected == "nvenc"
    if auto_nvenc and is_nvenc_init_failure(stderr):
        return _fallback_cpu(selection, build_cmd, cleanup)
    raise VideoEncodeError(sanitize_encoder_error(stderr))


def _fallback_cpu(
    selection: EncoderSelection,
    build_cmd: Callable[[list[str]], list[str]],
    cleanup: Callable[[], None] | None,
) -> EncodeOutcome:
    """Reintento unico en CPU tras un fallo de inicializacion de NVENC (solo modo auto)."""
    if cleanup is not None:
        cleanup()
    cpu_sel = _cpu_selection(
        EncoderMode.AUTO,
        _coerce_profile(selection.profile),
        "fallback: NVENC no pudo completar la codificacion; se uso CPU.",
        fallback=True,
    )
    rc, stderr, elapsed = _run_cmd(build_cmd(build_video_args(cpu_sel)))
    if rc != 0:
        raise VideoEncodeError(sanitize_encoder_error(stderr))
    print("[encoder] NVENC no pudo completar la codificacion; se uso CPU.")
    return EncodeOutcome(cpu_sel, elapsed)


# ── Payloads para API / capacidades ─────────────────────────────────────────────
def encoder_status(mode: str | EncoderMode | None = None) -> dict:
    """Payload de /api/system/video-encoder (no lanza: para GET/PUT y guards informativos)."""
    m = coerce_mode(mode) if mode is not None else _default_mode
    st = detect_nvenc()
    use_nvenc = st.available and m != EncoderMode.CPU
    return {
        "requested": m.value,
        "selected": "nvenc" if use_nvenc else "cpu",
        "encoder": "h264_nvenc" if use_nvenc else "libx264",
        "nvenc": {"available": st.available, "message": st.message},
    }


def capability() -> dict:
    """Capacidad `nvenc` para /api/system/capabilities. Su ausencia NO degrada la app."""
    st = detect_nvenc()
    return {"available": st.available, "message": st.message}
