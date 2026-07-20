"""auto_srt_artifacts.py — Namespace y artefactos privados POR CLIP para Auto SRT (S36-C2A2).

Deriva, por cada clip de un run de Auto `caption_source=srt`, los artefactos aislados del
video padre (S36-C2A1): SRT rebasado, words/groups rebasados y procedencia por clip. Los escribe
en un namespace privado confinado por `{source_stem}/{sha256(source_filename)}/{run_id}/{clip_id}/`,
que NUNCA pisa los `{stem}_words/groups` históricos ni colisiona entre runs. Orquesta la foundation
(`clip_srt`, `clip_transcript`) y `srt_serialize`; no reimplementa el alineador/parser.

PURO: sin FFmpeg, sin Auto, sin red, sin UI. Escrituras atómicas (temporal + os.replace). Nunca
expone rutas absolutas en errores ni en el resumen público.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import clip_srt
import clip_transcript
import srt_serialize
from studio_srt_manifest import is_safe_basename
from transcript_provenance import srt_artifact_key

SRT_CLIPS_DIR = "studio_srt_clips"
_ALLOWED_VIDEO_EXT = frozenset({".mp4", ".mov"})


class AutoSrtArtifactError(Exception):
    """Contrato del namespace por clip inválido (id inseguro, escape, rango). Sin rutas."""


@dataclass(frozen=True)
class ClipArtifacts:
    """Rutas confinadas de los artefactos privados de UN clip. INTERNO (no sale por API)."""

    clip_id: str
    directory: Path
    srt_path: Path
    words_path: Path
    groups_path: Path
    manifest_path: Path
    alignment_path: Path


def _safe_id(value: str, etiqueta: str) -> str:
    if not is_safe_basename(value):
        raise AutoSrtArtifactError(f"{etiqueta} inseguro")
    return value


def resolve_run_dir(
    *, transcripts_dir: Path, source_stem: str, source_filename: str, run_id: str
) -> Path:
    """Directorio del run: `transcripts/studio_srt_clips/{stem}/{sha256(filename)}/{run_id}/`.

    Confinado (resolve + relative_to). key del filename EXACTO (mp4 y mov -> dirs distintos).
    """
    _safe_id(source_stem, "source_stem")
    _safe_id(source_filename, "source_filename")
    _safe_id(run_id, "run_id")
    if Path(source_filename).suffix.lower() not in _ALLOWED_VIDEO_EXT:
        raise AutoSrtArtifactError("extension de video no permitida")
    if Path(source_filename).stem != source_stem:
        raise AutoSrtArtifactError("filename no corresponde al stem")
    root = Path(transcripts_dir) / SRT_CLIPS_DIR
    run_dir = root / source_stem / srt_artifact_key(source_filename) / run_id
    try:
        run_dir.resolve().relative_to(root.resolve())
    except ValueError:
        raise AutoSrtArtifactError("run fuera del namespace") from None
    return run_dir


def resolve_clip_artifacts(run_dir: Path, clip_id: str) -> ClipArtifacts:
    """Rutas de los artefactos de un clip bajo `{run_dir}/clips/{clip_id}/`. Confinado."""
    _safe_id(clip_id, "clip_id")
    clips_root = Path(run_dir) / "clips"
    directory = clips_root / clip_id
    try:
        directory.resolve().relative_to(clips_root.resolve())
    except ValueError:
        raise AutoSrtArtifactError("clip fuera del run") from None
    return ClipArtifacts(
        clip_id=clip_id,
        directory=directory,
        srt_path=directory / "clip.srt",
        words_path=directory / "words.json",
        groups_path=directory / "groups.json",
        manifest_path=directory / "manifest.json",
        alignment_path=directory / "alignment.json",
    )


def _atomic_write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def derive_clip_artifacts(
    arts: ClipArtifacts,
    *,
    srt_document,
    parent_words: list[dict],
    parent_video: Path,
    output_clip: Path,
    source_start_ms: int,
    source_end_ms: int,
) -> dict:
    """Deriva y escribe SRT/words/groups/manifest del clip desde los timings del PADRE.

    Reutiliza `clip_srt.derive_clip_srt`, `clip_transcript.*` y `srt_serialize`. Todos los
    tiempos del clip quedan rebasados a t=0. Devuelve un resumen PÚBLICO saneado (conteos y
    ratios, sin cues/texto/rutas). Escritura atómica; no muta las entradas.
    """
    clip_doc = clip_srt.derive_clip_srt(srt_document, source_start_ms, source_end_ms)
    clip_words = clip_transcript.derive_clip_words(parent_words, source_start_ms, source_end_ms)
    clip_groups = clip_transcript.derive_clip_groups(clip_words)
    manifest = clip_transcript.build_clip_provenance(
        parent_video,
        source_start_ms=source_start_ms,
        source_end_ms=source_end_ms,
        output_clip=output_clip,
    )
    manifest["clip_id"] = arts.clip_id
    manifest["n_cues"] = len(clip_doc.cues)

    arts.directory.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(arts.srt_path, srt_serialize.serialize_srt(clip_doc))
    _atomic_write_text(arts.words_path, json.dumps({"words": clip_words}, ensure_ascii=False))
    _atomic_write_text(arts.groups_path, json.dumps(clip_groups, ensure_ascii=False))
    _atomic_write_text(arts.manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2))

    # coverage = fracción de la duración del clip cubierta por cues del SRT (rebasados a t=0).
    dur_ms = source_end_ms - source_start_ms
    cubierto = sum(c.end_ms - c.start_ms for c in clip_doc.cues)
    coverage = round(min(cubierto / dur_ms, 1.0), 3) if dur_ms > 0 else 0.0
    return {
        "clip_id": arts.clip_id,
        "n_cues": len(clip_doc.cues),
        "n_words": len(clip_words),
        "n_groups": len(clip_groups),
        "duration_ms": dur_ms,
        "caption_coverage": coverage,
    }


def persist_alignment(arts: ClipArtifacts, payload) -> None:
    """Escribe el sidecar de alineación SRT->timings del clip (word_aligned/substitution/
    cue_fallback). Atómico y confinado; INTERNO (no sale por API). No muta `payload`."""
    _atomic_write_text(arts.alignment_path, json.dumps(payload, ensure_ascii=False, indent=2))


__all__ = [
    "SRT_CLIPS_DIR",
    "AutoSrtArtifactError",
    "ClipArtifacts",
    "resolve_run_dir",
    "resolve_clip_artifacts",
    "derive_clip_artifacts",
    "persist_alignment",
]
