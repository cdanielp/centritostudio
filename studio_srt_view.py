"""studio_srt_view.py — View model saneado único de la selección SRT para Studio (S36-C2B).

Capa PURA que compone en UN solo resumen el estado que la UI necesita para operar el SRT:
si hay selección, el nombre de la fuente, el estado de los timings y si el video está listo
para render normal o para Auto. Reutiliza la MISMA resolución que usa el worker de render
(`studio_srt_runtime`) para que el badge de la UI refleje exactamente lo que pasará al render;
no reimplementa integridad, procedencia ni binding.

Sin FastAPI, sin HTML, sin jobs, sin FFmpeg, sin red. NUNCA devuelve rutas, cues, hashes
completos ni tracebacks: solo enums saneados, un basename opcional y flags booleanos.
"""

from __future__ import annotations

from pathlib import Path

import studio_srt
import studio_srt_runtime as runtime
import transcript_provenance

# Estados de timings expuestos a la UI (enums cerrados, sin texto libre).
TIMINGS_NONE = "none"  # no aplica: no hay selección SRT
TIMINGS_MISSING = "missing"  # falta el transcript de palabras del video exacto
TIMINGS_VALID = "valid"  # words presentes y ligadas al video exacto
TIMINGS_MISMATCH = "mismatch"  # words de otro archivo/versión (retranscribir)
TIMINGS_CORRUPT = "corrupt"  # el SRT administrado o el manifiesto están rotos

# Acción sugerida (la UI la traduce a copy en español; enum cerrado).
ACTION_SELECT = "select_srt"
ACTION_REPLACE = "replace_srt"
ACTION_RESTORE_VIDEO = "restore_video"
ACTION_TRANSCRIBE = "transcribe"
ACTION_RETRANSCRIBE = "retranscribe"
ACTION_READY = "ready"


def _timings_state(video_path: Path, *, transcripts_dir: Path, selection) -> str:
    """Estado de los timings del video EXACTO asociado, con la misma verificación del render."""
    try:
        arts = transcript_provenance.resolve_srt_timing_artifacts(
            transcripts_dir=Path(transcripts_dir),
            video_stem=selection.video_stem,
            video_filename=selection.video_filename,
        )
        runtime.verify_timing_provenance(
            video_path, words_path=arts.words_path, expected_filename=selection.video_filename
        )
    except runtime.StudioSrtTimingMissing:
        return TIMINGS_MISSING
    except runtime.StudioSrtTimingSourceMismatch:
        return TIMINGS_MISMATCH
    except (transcript_provenance.TimingProvenanceError, studio_srt.StudioSrtError):
        return TIMINGS_CORRUPT
    return TIMINGS_VALID


def _srt_block(
    name: str, *, input_dir: Path, storage_root: Path, manifest_dir: Path, transcripts_dir: Path
) -> dict:
    """Bloque `srt` del view model: estado de selección + timings + readiness + acción."""
    try:
        selection = runtime.resolve_selected_srt(
            name, storage_root=Path(storage_root), manifest_dir=Path(manifest_dir)
        )
    except studio_srt.StudioSrtError:
        # Manifiesto/almacenamiento del SRT roto: hay algo asociado pero no es usable.
        return {
            "selected": True,
            "source_name": None,
            "timings": TIMINGS_CORRUPT,
            "video_available": False,
            "ready_render": False,
            "ready_auto": False,
            "action": ACTION_REPLACE,
        }
    if selection is None:
        return {
            "selected": False,
            "source_name": None,
            "timings": TIMINGS_NONE,
            "video_available": False,
            "ready_render": False,
            "ready_auto": False,
            "action": ACTION_SELECT,
        }

    source_name = selection.source_name if isinstance(selection.source_name, str) else None
    try:
        video_path = runtime.resolve_selected_video(selection, input_dir=Path(input_dir))
    except runtime.StudioSrtSelectedVideoMissing:
        return {
            "selected": True,
            "source_name": source_name,
            "timings": TIMINGS_NONE,
            "video_available": False,
            "ready_render": False,
            "ready_auto": False,
            "action": ACTION_RESTORE_VIDEO,
        }
    except studio_srt.StudioSrtError:
        return {
            "selected": True,
            "source_name": source_name,
            "timings": TIMINGS_CORRUPT,
            "video_available": False,
            "ready_render": False,
            "ready_auto": False,
            "action": ACTION_REPLACE,
        }

    timings = _timings_state(video_path, transcripts_dir=transcripts_dir, selection=selection)
    ready = timings == TIMINGS_VALID
    action = {
        TIMINGS_MISSING: ACTION_TRANSCRIBE,
        TIMINGS_MISMATCH: ACTION_RETRANSCRIBE,
        TIMINGS_CORRUPT: ACTION_REPLACE,
        TIMINGS_VALID: ACTION_READY,
    }[timings]
    return {
        "selected": True,
        "source_name": source_name,
        "timings": timings,
        "video_available": True,
        "ready_render": ready,
        "ready_auto": ready,
        "action": action,
    }


def build_srt_view(
    name: str,
    *,
    input_dir: Path,
    storage_root: Path,
    manifest_dir: Path,
    transcripts_dir: Path,
    caption_source: str = "transcript",
) -> dict:
    """View model saneado único para la UI. `caption_source` refleja la fuente elegida (default
    transcript). Nunca lanza por estado del SRT: cualquier rotura se reporta como enum saneado."""
    source = "srt" if caption_source == "srt" else "transcript"
    return {
        "caption_source": source,
        "srt": _srt_block(
            name,
            input_dir=Path(input_dir),
            storage_root=Path(storage_root),
            manifest_dir=Path(manifest_dir),
            transcripts_dir=Path(transcripts_dir),
        ),
    }


__all__ = [
    "TIMINGS_NONE",
    "TIMINGS_MISSING",
    "TIMINGS_VALID",
    "TIMINGS_MISMATCH",
    "TIMINGS_CORRUPT",
    "ACTION_SELECT",
    "ACTION_REPLACE",
    "ACTION_RESTORE_VIDEO",
    "ACTION_TRANSCRIBE",
    "ACTION_RETRANSCRIBE",
    "ACTION_READY",
    "build_srt_view",
]
