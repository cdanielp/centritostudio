"""media_integrity.py — Publicacion ATOMICA + verificacion de integridad de MP4 (H1).

Fuente UNICA para publicar un video final: se quema a un temporal en el MISMO directorio del
output y solo se renombra al nombre final (`os.replace`) DESPUES de validar que el archivo es
publicable (returncode 0, tamano > 0, ffprobe OK, >=1 stream de video, duracion finita > 0).

Cierra P1-OUT-1 (outputs no validados) y P1-OUT-2 (FFmpeg escribiendo directo al nombre final:
una interrupcion dejaba un MP4 truncado con el nombre definitivo que el resume daba por bueno).

NO exige audio: el pipeline admite fuentes legitimamente sin pista de audio (`has_audio=False`)
y `burn_video` usa `-c:a copy` (sin audio de entrada -> sin audio de salida). Requerir audio
romperia esos casos validos. Los mensajes son genericos: no se filtran rutas ni comandos.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import uuid
from collections.abc import Callable
from pathlib import Path


class MediaIntegrityError(Exception):
    """Un video recien escrito no cumple el contrato de integridad y NO es publicable."""


TEMP_DIRNAME = ".render_tmp"  # subdir PRIVADO reservado para temporales de publicacion (H1)


def ruta_temporal(final: Path) -> Path:
    """Ruta temporal UNICA en un subdir PRIVADO del mismo directorio del final, `.mp4`.

    Vive en `<dir_final>/.render_tmp/<uuid>.mp4` (mismo volumen -> `os.replace` sigue siendo
    atomico) para que un temporal en curso o abandonado tras un hard-kill NO sea servido por
    `/output` ni listado como render (P2 del review: los `/output/*.mp4` sueltos exponian
    parciales). Termina en `.mp4` porque FFmpeg elige el muxer por la extension; no incluye el
    stem privado del usuario. El uuid garantiza que dos operaciones nunca reutilicen el temporal.
    """
    final = Path(final)
    tmp_dir = final.parent / TEMP_DIRNAME
    tmp_dir.mkdir(exist_ok=True)
    return tmp_dir / f"{uuid.uuid4().hex}.mp4"


def _ffprobe(path: Path) -> dict:
    """Corre ffprobe (streams + format) y devuelve el dict JSON. Lanza MediaIntegrityError."""
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                "-show_format",
                str(path),
            ],
            capture_output=True,
            text=True,
        )
    except OSError:
        raise MediaIntegrityError("no se pudo ejecutar ffprobe") from None
    if r.returncode != 0:
        raise MediaIntegrityError("ffprobe rechazo el archivo")
    try:
        data = json.loads(r.stdout or "")
    except ValueError:
        raise MediaIntegrityError("ffprobe no devolvio JSON valido") from None
    if not isinstance(data, dict):
        raise MediaIntegrityError("ffprobe devolvio un formato inesperado")
    return data


def _duracion_finita_positiva(data: dict, streams: list) -> bool:
    """True si hay una duracion finita > 0 en format o en algun stream (rechaza NaN/Inf/0)."""
    candidatos = [data.get("format", {}).get("duration") if isinstance(data, dict) else None]
    candidatos += [s.get("duration") for s in streams]
    for c in candidatos:
        try:
            v = float(c)
        except (TypeError, ValueError):
            continue
        if math.isfinite(v) and v > 0:
            return True
    return False


def verificar_video(path: Path) -> None:
    """Valida un video recien escrito. Lanza MediaIntegrityError si NO es publicable.

    Exige archivo regular, tamano > 0, ffprobe OK, al menos un stream de video y una duracion
    finita y positiva. Sirve tanto para el output del render (.mp4) como para validar un upload
    (.mp4/.mov) antes de aceptarlo.
    """
    p = Path(path)
    if not p.is_file():
        raise MediaIntegrityError("el archivo no existe o no es regular")
    try:
        size = p.stat().st_size
    except OSError:
        raise MediaIntegrityError("no se pudo consultar el archivo") from None
    if size <= 0:
        raise MediaIntegrityError("el archivo quedo en 0 bytes")
    data = _ffprobe(p)
    streams = data.get("streams", [])
    if not isinstance(streams, list):
        raise MediaIntegrityError("ffprobe devolvio streams invalidos")
    if not any(isinstance(s, dict) and s.get("codec_type") == "video" for s in streams):
        raise MediaIntegrityError("el archivo no tiene stream de video")
    if not _duracion_finita_positiva(data, streams):
        raise MediaIntegrityError("el archivo no tiene duracion valida")


def video_reanudable(path: Path) -> bool:
    """Wrapper FAIL-CLOSED de `verificar_video` para los predicados de resume (H2, P1-OUT-3).

    Devuelve True SOLO si el archivo es un video publicable (regular, tamano > 0, ffprobe OK,
    stream de video, duracion finita > 0). Cualquier fallo (inexistente, 0-byte, truncado, sin
    stream, duracion 0/NaN/Inf, ffprobe ausente) devuelve False -> el clip se re-renderiza. No
    lanza: convierte el contrato de integridad en un booleano seguro para los gates de reanudacion
    (`_clip_incompleto`, reuso classic, checkpoint SRT, checkpoint v2). Nunca borra el archivo.
    """
    try:
        verificar_video(path)
        return True
    except MediaIntegrityError:
        return False


def _borrar_silencioso(p: Path) -> None:
    """Borra un archivo ignorando errores (no debe enmascarar la excepcion real que se propaga)."""
    try:
        Path(p).unlink()
    except OSError:
        pass


def publicar_mp4_atomico(final: Path, quemar: Callable[[Path], float]) -> float:
    """Quema a un temporal, lo verifica y lo PUBLICA con `os.replace(temp, final)`.

    `quemar(temp)` recibe la ruta temporal (misma carpeta, `.mp4`), corre FFmpeg alli y devuelve
    el tiempo transcurrido; DEBE lanzar si returncode != 0. Ante cualquier fallo (quemar o
    verificacion) se borra el temporal, el `final` anterior queda INTACTO y se propaga la
    excepcion tipada (RuntimeError de FFmpeg o MediaIntegrityError). Nunca deja temporales ni
    publica un nombre final nuevo si la verificacion no paso. Devuelve el tiempo de quemado.
    """
    final = Path(final)
    temp = ruta_temporal(final)
    try:
        elapsed = quemar(temp)
        verificar_video(temp)
    except BaseException:
        _borrar_silencioso(temp)
        raise
    try:
        os.replace(temp, final)
    except OSError:
        _borrar_silencioso(temp)
        raise MediaIntegrityError("no se pudo publicar el output final") from None
    return elapsed
