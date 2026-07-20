"""transcript_provenance.py — Procedencia del video en el artefacto de timings (S36-C2A1, D38).

Liga `{stem}_words.json` al video EXACTO del que salieron los timings. El stem NO identifica
el video (un `.mp4` y un `.mov` con el mismo stem son videos distintos); sin esta procedencia,
un render SRT del video seleccionado podría alinear el texto oficial contra timings de otro
archivo (subtítulos mal-timed silenciosos). El bloque `source_video` fija filename exacto +
size + mtime del video, de modo que endpoint y worker puedan rechazar timings ajenos.

Capa PURA: sin FastAPI, sin jobs, sin FFmpeg, sin Auto, sin UI, sin red. Solo lee `stat()`
del video esperado. Nunca incluye rutas absolutas ni contenido del video en errores.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from studio_srt_manifest import is_safe_basename

PROVENANCE_VERSION = 1
_ALLOWED_VIDEO_EXT = frozenset({".mp4", ".mov"})
# Namespace privado de artefactos de transcripcion SRT (aislado del stem-root historico).
SRT_TIMINGS_DIR = "studio_srt_timings"


class TimingProvenanceError(Exception):
    """El artefacto de timings no declara/coincide con la procedencia del video esperado.

    Error de CONTRATO (no bug): el llamador de dominio lo traduce a un error tipado del
    runtime SRT (409 en HTTP). El mensaje nunca refleja valores manipulados ni rutas.
    """


def _strict_int(value: object) -> int | None:
    """int estricto (rechaza bool y no-int). None si no es un entero limpio."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


# ─── Productor ─────────────────────────────────────────────────────────────────
def build_video_provenance(video_path: Path) -> dict:
    """Bloque `source_video` v1 del video EXACTO (solo basename + size + mtime en ns)."""
    video_path = Path(video_path)
    st = video_path.stat()
    return {
        "version": PROVENANCE_VERSION,
        "filename": video_path.name,
        "size_bytes": int(st.st_size),
        "mtime_ns": int(st.st_mtime_ns),
    }


def attach_video_provenance(transcript: dict, video_path: Path) -> dict:
    """Copia del transcript con `source_video` del video exacto (no muta el original)."""
    return {**transcript, "source_video": build_video_provenance(video_path)}


# ─── Validador ─────────────────────────────────────────────────────────────────
def validate_video_provenance(
    transcript: object, *, expected_video: Path, expected_filename: str
) -> None:
    """Exige que el transcript declare provenir del video EXACTO esperado.

    Verifica estructura, `version==1`, filename basename seguro == expected_filename ==
    expected_video.name, extensión permitida, y que size_bytes/mtime_ns coincidan con el
    `stat()` real del video esperado (que debe seguir siendo un archivo regular). Cualquier
    violación (incluida procedencia AUSENTE = words legacy) lanza TimingProvenanceError.
    """
    if not isinstance(transcript, dict) or not isinstance(transcript.get("words"), list):
        raise TimingProvenanceError("transcript invalido")
    sv = transcript.get("source_video")
    if not isinstance(sv, dict):
        raise TimingProvenanceError("timings sin procedencia de video")
    if (
        _strict_int(sv.get("version")) != PROVENANCE_VERSION
    ):  # int estricto (rechaza bool/float/str)
        raise TimingProvenanceError("version de procedencia invalida")
    filename = sv.get("filename")
    if not is_safe_basename(filename):
        raise TimingProvenanceError("filename de procedencia invalido")
    if Path(filename).suffix.lower() not in _ALLOWED_VIDEO_EXT:
        raise TimingProvenanceError("extension de procedencia no permitida")
    expected_video = Path(expected_video)
    if filename != expected_filename or filename != expected_video.name:
        raise TimingProvenanceError("los timings no pertenecen al video seleccionado")
    size = _strict_int(sv.get("size_bytes"))
    mtime = _strict_int(sv.get("mtime_ns"))
    if size is None or size < 0 or mtime is None or mtime <= 0:
        raise TimingProvenanceError("procedencia con valores invalidos")
    try:
        st = expected_video.stat()
    except OSError:
        raise TimingProvenanceError("el video esperado no esta disponible") from None
    if not expected_video.is_file():
        raise TimingProvenanceError("el video esperado no es un archivo regular")
    if size != int(st.st_size) or mtime != int(st.st_mtime_ns):
        raise TimingProvenanceError("los timings no corresponden al video actual")


# ─── Namespace privado de artefactos SRT (aislado por filename EXACTO) ──────────
@dataclass(frozen=True)
class SrtTimingArtifacts:
    """Rutas confinadas de los timings SRT de un video EXACTO. `key` = sha256(filename)."""

    key: str
    directory: Path
    words_path: Path
    groups_path: Path


def srt_artifact_key(video_filename: str) -> str:
    """Clave determinista del namespace = SHA256 completo del filename exacto (no del stem)."""
    return hashlib.sha256(video_filename.encode("utf-8")).hexdigest()


def resolve_srt_timing_artifacts(
    *, transcripts_dir: Path, video_stem: str, video_filename: str
) -> SrtTimingArtifacts:
    """Namespace privado `transcripts/studio_srt_timings/{stem}/{sha256(filename)}/` confinado.

    Un `.mp4` y un `.mov` con el mismo stem dan directorios DISTINTOS (la key es del filename).
    Valida stem/filename como basename seguro, extensión .mp4/.mov y `stem == video_stem`. No
    acepta paths de HTTP, no usa glob ni busca por stem. Nunca expone rutas en errores.
    """
    if not is_safe_basename(video_stem) or not is_safe_basename(video_filename):
        raise TimingProvenanceError("nombre de video inseguro")
    name_path = Path(video_filename)
    if name_path.suffix.lower() not in _ALLOWED_VIDEO_EXT:
        raise TimingProvenanceError("extension de video no permitida")
    if name_path.stem != video_stem:
        raise TimingProvenanceError("el filename no corresponde al video")
    key = srt_artifact_key(video_filename)
    base = Path(transcripts_dir) / SRT_TIMINGS_DIR / video_stem / key
    try:
        base.resolve().relative_to((Path(transcripts_dir) / SRT_TIMINGS_DIR).resolve())
    except ValueError:
        raise TimingProvenanceError("namespace de timings fuera del root") from None
    return SrtTimingArtifacts(
        key=key,
        directory=base,
        words_path=base / "words.json",
        groups_path=base / "groups.json",
    )


__all__ = [
    "PROVENANCE_VERSION",
    "SRT_TIMINGS_DIR",
    "SrtTimingArtifacts",
    "TimingProvenanceError",
    "build_video_provenance",
    "attach_video_provenance",
    "validate_video_provenance",
    "srt_artifact_key",
    "resolve_srt_timing_artifacts",
]
