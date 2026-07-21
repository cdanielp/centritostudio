"""media_deps.py — Deteccion centralizada de FFmpeg/ffprobe + excepciones tipadas (H3).

Fuente UNICA para saber si los binarios multimedia estan disponibles y para fallar con un
mensaje ACCIONABLE (sin rutas privadas, sin comandos completos del usuario, sin variables de
entorno) cuando faltan. Cierra P1-BOOT-1: hoy un FFmpeg/ffprobe ausente revienta con
`FileNotFoundError [WinError 2]` o `JSONDecodeError` que no mencionan la causa.

Regla: `shutil.which` es la fuente de verdad. NO se lanza un subprocess solo para descubrir si
el binario existe cuando `which` ya indica que falta.

Jerarquia:
    MediaDependencyUnavailable   (base; el binario multimedia requerido no esta instalado)
      FFmpegUnavailable
      FFprobeUnavailable
    MediaProbeError              (el binario SI existe pero el archivo de video es invalido)
"""

from __future__ import annotations

import shutil
from collections.abc import Callable


class MediaDependencyUnavailable(Exception):
    """Una dependencia multimedia requerida (ffmpeg/ffprobe) no esta instalada."""


class FFmpegUnavailable(MediaDependencyUnavailable):
    """FFmpeg no esta en el PATH."""


class FFprobeUnavailable(MediaDependencyUnavailable):
    """ffprobe no esta en el PATH."""


class MediaProbeError(Exception):
    """ffprobe existe pero no pudo analizar el archivo (video invalido/corrupto)."""


_FFMPEG_MSG = "FFmpeg no esta disponible. Instala FFmpeg y reinicia Centrito Studio."
_FFPROBE_MSG = "FFprobe no esta disponible. Instala FFmpeg y reinicia Centrito Studio."


def ffmpeg_disponible(which: Callable[[str], str | None] = shutil.which) -> bool:
    """True si ffmpeg esta en el PATH."""
    return which("ffmpeg") is not None


def ffprobe_disponible(which: Callable[[str], str | None] = shutil.which) -> bool:
    """True si ffprobe esta en el PATH."""
    return which("ffprobe") is not None


def require_ffmpeg(which: Callable[[str], str | None] = shutil.which) -> None:
    """Lanza FFmpegUnavailable con mensaje accionable si ffmpeg no esta instalado."""
    if not ffmpeg_disponible(which):
        raise FFmpegUnavailable(_FFMPEG_MSG)


def require_ffprobe(which: Callable[[str], str | None] = shutil.which) -> None:
    """Lanza FFprobeUnavailable con mensaje accionable si ffprobe no esta instalado."""
    if not ffprobe_disponible(which):
        raise FFprobeUnavailable(_FFPROBE_MSG)


__all__ = [
    "MediaDependencyUnavailable",
    "FFmpegUnavailable",
    "FFprobeUnavailable",
    "MediaProbeError",
    "ffmpeg_disponible",
    "ffprobe_disponible",
    "require_ffmpeg",
    "require_ffprobe",
]
