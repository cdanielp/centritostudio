"""srt_caption.py — Adaptador entre el SRT alineado y el motor de captions (S36-B).

Convierte el resultado de `srt_align` en `groups` que consume `core.build_ass`, valida
el SRT contra la duracion real del video y escribe el sidecar de auditoria. El TEXTO del
SRT es la fuente oficial (D36B-1); Whisper solo aporta timings.

Sin logica de FFmpeg, estilos ni red. Los groups de fallback llevan
`timing_mode="cue_fallback"` para que el motor los pinte estaticos (sin karaoke falso,
D36B-3). Los groups word-aligned son groups normales del motor (mismo contrato que
`core.group_words`) con `timing_mode="word_aligned"` (el motor lo ignora).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from srt_align import DEFAULT_MIN_COVERAGE, AlignmentResult, align_srt_to_words
from srt_import import SrtError, load_srt, validate_srt


def _basename(name: str | None) -> str | None:
    if not name:
        return None
    return Path(str(name)).name


# ─────────────────────────────────────────────────────────────────────────────
# SRT -> groups del motor
# ─────────────────────────────────────────────────────────────────────────────


def _word_group(gi: int, cue) -> dict:
    words = [
        {
            "text": w.text,
            "start": round(w.start_ms / 1000, 3),
            "end": round(w.end_ms / 1000, 3),
            "line_idx": w.line_idx,
        }
        for w in cue.words
    ]
    return {
        "id": gi,
        "start": round(cue.start_ms / 1000, 3),
        "end": round(cue.end_ms / 1000, 3),
        "text": " ".join(w.text for w in cue.words),
        "words": words,
        "timing_mode": "word_aligned",
    }


def _fallback_group(gi: int, cue) -> dict:
    start_s = round(cue.start_ms / 1000, 3)
    end_s = round(cue.end_ms / 1000, 3)
    words = [
        {"text": line, "start": start_s, "end": end_s, "line_idx": li}
        for li, line in enumerate(cue.lines)
    ]
    return {
        "id": gi,
        "start": start_s,
        "end": end_s,
        "text": "\n".join(cue.lines),
        "words": words,
        "timing_mode": "cue_fallback",
    }


def construir_groups(result: AlignmentResult) -> list[dict]:
    """Convierte un AlignmentResult en groups compatibles con `core.build_ass`."""
    groups: list[dict] = []
    for gi, cue in enumerate(result.cues):
        if cue.mode == "word_aligned":
            groups.append(_word_group(gi, cue))
        else:
            groups.append(_fallback_group(gi, cue))
    return groups


# ─────────────────────────────────────────────────────────────────────────────
# Validacion (D36B-4): errores estructurales abortan; warnings no
# ─────────────────────────────────────────────────────────────────────────────


def validar_o_abortar(document, *, video_duration_ms: int | None) -> tuple[int, int]:
    """Revalida el SRT contra la duracion del video. Aborta si hay errores estructurales.

    Devuelve (n_errors, n_warnings) considerando parseo + validacion independiente.
    """
    diags = tuple(document.diagnostics) + validate_srt(
        document, video_duration_ms=video_duration_ms
    )
    n_err = sum(1 for d in diags if d.severity == "error")
    n_warn = sum(1 for d in diags if d.severity == "warning")
    if not document.cues:
        raise SrtError("el SRT no contiene cues utilizables")
    if n_err:
        raise SrtError(
            f"el SRT tiene {n_err} error(es) estructural(es); corrige antes de renderizar"
        )
    return n_err, n_warn


# ─────────────────────────────────────────────────────────────────────────────
# Sidecar de auditoria (atomico, sin rutas absolutas, sin secretos)
# ─────────────────────────────────────────────────────────────────────────────


def alignment_a_sidecar(
    result: AlignmentResult,
    *,
    source_name: str | None,
    encoding: str,
    words_file: str | None,
    n_warnings: int = 0,
) -> dict:
    """Contrato JSON v1 del sidecar de alineacion. Solo basenames, tiempos int ms."""
    return {
        "version": 1,
        "source": {
            "format": "srt",
            "name": _basename(source_name),
            "sha256": result.source_sha256,
            "encoding": encoding,
        },
        "timing_source": {
            "type": result.timing_source,
            "words_file": _basename(words_file),
        },
        "summary": {
            "n_cues": result.n_cues,
            "word_aligned": result.word_aligned,
            "cue_fallback": result.cue_fallback,
            "coverage": result.coverage,
            "min_coverage": result.min_coverage,
            "exact_matches": result.n_exact,
            "substitution_matches": result.n_substitution,
            "rejected_substitutions": result.n_rejected_sub,
            "n_warnings": n_warnings,
        },
        "cues": [
            {
                "cue_index": c.cue_index,
                "start_ms": c.start_ms,
                "end_ms": c.end_ms,
                "mode": c.mode,
                "n_tokens": c.n_tokens,
                "n_matched": c.n_matched,
                "coverage": c.coverage,
                "exact_matches": c.n_exact,
                "substitution_matches": c.n_substitution,
                "rejected_substitutions": c.n_rejected_sub,
                "fallback_reason": c.reason if c.mode == "cue_fallback" else None,
                "reason": c.reason,
                "text": c.text,
            }
            for c in result.cues
        ],
    }


def escribir_sidecar(payload: dict, destination: Path) -> None:
    """Escribe el sidecar de forma atomica. Regenera (sobreescribe) el del mismo stem.

    No deja `.tmp` tras un error. El destino vive confinado en transcripts/ (gitignored).
    """
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_name(destination.name + ".tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, destination)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


# ─────────────────────────────────────────────────────────────────────────────
# Orquestacion: cargar SRT + validar + alinear + groups
# ─────────────────────────────────────────────────────────────────────────────


def preparar_desde_srt(
    srt_path: Path,
    timing_words: list[dict],
    *,
    video_duration_ms: int | None = None,
    min_coverage: float | None = None,
    words_file: str | None = None,
) -> tuple[list[dict], AlignmentResult, dict]:
    """Carga y valida el SRT, alinea con timings y devuelve (groups, result, sidecar_payload).

    Lanza SrtError si el SRT es estructuralmente invalido (no arranca el render).
    """
    mc = DEFAULT_MIN_COVERAGE if min_coverage is None else min_coverage
    document = load_srt(Path(srt_path))
    _n_err, n_warn = validar_o_abortar(document, video_duration_ms=video_duration_ms)
    result = align_srt_to_words(
        document, timing_words, video_duration_ms=video_duration_ms, min_coverage=mc
    )
    groups = construir_groups(result)
    payload = alignment_a_sidecar(
        result,
        source_name=document.source_name,
        encoding=document.encoding,
        words_file=words_file,
        n_warnings=n_warn,
    )
    return groups, result, payload


__all__ = [
    "construir_groups",
    "validar_o_abortar",
    "alignment_a_sidecar",
    "escribir_sidecar",
    "preparar_desde_srt",
]
