"""auto_srt_run.py — Contexto SRT de un run de Auto `caption_source=srt` (S36-C2A2).

Resuelve y verifica, una sola vez por run, TODO lo necesario para que Auto derive y renderice
clips desde el SRT seleccionado del video padre (S36-C2A1): selección explícita + integridad,
binding del video EXACTO (TOCTOU), timings privados del padre + procedencia, SRT oficial y el
namespace del run. NUNCA cae al transcript; sin selección/video/timings válidos, lanza el error
tipado del runtime (el llamador lo traduce a HTTP). No serializa el contexto por API.

PURO respecto de FFmpeg/Auto/UI/red: solo lee la selección, los timings privados y el SRT del
disco (rutas confinadas). Reutiliza `studio_srt_runtime`, `transcript_provenance`, `srt_import`
y `auto_srt_artifacts`; no reimplementa nada.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import auto_srt_artifacts
import studio_srt_runtime as rt
import transcript_provenance
from srt_import import load_srt


@dataclass(frozen=True)
class AutoSrtRunContext:
    """Contexto verificado de un run SRT. INTERNO: contiene Paths/objetos, no sale por API."""

    run_id: str
    source_stem: str
    source_filename: str
    binding: object  # studio_srt_runtime.SelectedVideoBinding
    srt_document: object  # srt_types.SrtDocument (SRT oficial del padre)
    parent_words: list  # words exactas del padre (solo timings), del namespace privado
    run_dir: Path  # transcripts/studio_srt_clips/{stem}/{key}/{run_id}/


def resolve_auto_srt_context(
    name: str, run_id: str, *, input_dir: Path, transcripts_dir: Path
) -> AutoSrtRunContext:
    """Resuelve el contexto SRT del run o lanza el error tipado del runtime.

    Pasos: selección activa -> binding del video exacto -> timings privados + procedencia ->
    SRT oficial del padre -> namespace del run. Sin selección -> StudioSrtSelectionMissing (400);
    video ausente -> StudioSrtSelectedVideoMissing (409); timings faltantes/mismatch ->
    StudioSrtTimingMissing/StudioSrtTimingSourceMismatch (409); storage corrupto -> StorageError
    (500). Nunca cae al transcript.
    """
    transcripts_dir = Path(transcripts_dir)
    selection = rt.resolve_selected_srt(
        name, storage_root=transcripts_dir / "studio_srt", manifest_dir=transcripts_dir
    )
    if selection is None:
        raise rt.StudioSrtSelectionMissing("no hay un SRT seleccionado para este video")
    binding = rt.bind_selected_video(selection, input_dir=input_dir)
    arts = transcript_provenance.resolve_srt_timing_artifacts(
        transcripts_dir=transcripts_dir,
        video_stem=name,
        video_filename=selection.video_filename,
    )
    rt.verify_timing_provenance(
        binding.path, words_path=arts.words_path, expected_filename=selection.video_filename
    )
    raw = json.loads(Path(arts.words_path).read_text(encoding="utf-8"))
    parent_words = raw["words"] if isinstance(raw, dict) else raw
    srt_document = load_srt(selection.managed_path)
    run_dir = auto_srt_artifacts.resolve_run_dir(
        transcripts_dir=transcripts_dir,
        source_stem=name,
        source_filename=selection.video_filename,
        run_id=run_id,
    )
    return AutoSrtRunContext(
        run_id=run_id,
        source_stem=name,
        source_filename=selection.video_filename,
        binding=binding,
        srt_document=srt_document,
        parent_words=parent_words,
        run_dir=run_dir,
    )


__all__ = ["AutoSrtRunContext", "resolve_auto_srt_context"]
