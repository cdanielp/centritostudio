"""srt_validate.py — Validacion estructurada de un SrtDocument (S36-A).

No muta el documento. Diagnosticos DETERMINISTAS y en orden fuente (no dependen de
hash randomization). Los overlaps se DIAGNOSTICAN como warning, no se corrigen.
"""

from __future__ import annotations

from srt_types import (
    ERR_DOCUMENT_EMPTY,
    ERR_EMPTY_CUE_TEXT,
    ERR_END_LE_START,
    ERR_INDEX_NON_POSITIVE,
    ERR_NEGATIVE_START,
    ERR_NUL_CHARACTER,
    LAST_CUE_GAP_MS,
    MAX_CHARS_PER_LINE,
    MAX_CUE_DURATION_MS,
    MAX_LINES_PER_CUE,
    WARN_CONTROL_CHARACTERS,
    WARN_CUE_AFTER_VIDEO,
    WARN_CUE_DURATION_EXCESSIVE,
    WARN_CUE_PARTIALLY_OUT,
    WARN_INDEX_DUPLICATE,
    WARN_INDEX_NOT_CONSECUTIVE,
    WARN_LAST_CUE_FAR,
    WARN_LINE_TOO_LONG,
    WARN_OVERLAP,
    WARN_TIME_NOT_MONOTONIC,
    WARN_TOO_MANY_LINES,
    SrtDiagnostic,
    SrtDocument,
    diag,
)


def _has_control(s: str) -> bool:
    return any(ord(c) < 0x20 and c not in "\t\x00" for c in s)


def _check_index(cue, prev, seen):
    out = []
    if cue.index <= 0:
        out.append(
            diag(ERR_INDEX_NON_POSITIVE, "error", "indice <= 0", cue.source_position, cue.index)
        )
    if cue.index in seen:
        out.append(
            diag(
                WARN_INDEX_DUPLICATE, "warning", "indice duplicado", cue.source_position, cue.index
            )
        )
    elif prev is not None and cue.index != prev.index + 1:
        out.append(
            diag(
                WARN_INDEX_NOT_CONSECUTIVE,
                "warning",
                "indice no consecutivo",
                cue.source_position,
                cue.index,
            )
        )
    return out


def _check_time(cue, prev):
    out = []
    if cue.start_ms < 0:
        out.append(
            diag(ERR_NEGATIVE_START, "error", "start negativo", cue.source_position, cue.index)
        )
    if cue.end_ms <= cue.start_ms:
        out.append(diag(ERR_END_LE_START, "error", "end <= start", cue.source_position, cue.index))
    if cue.end_ms - cue.start_ms > MAX_CUE_DURATION_MS:
        out.append(
            diag(
                WARN_CUE_DURATION_EXCESSIVE,
                "warning",
                "duracion de cue excesiva",
                cue.source_position,
                cue.index,
            )
        )
    if prev is not None and cue.start_ms < prev.start_ms:
        out.append(
            diag(
                WARN_TIME_NOT_MONOTONIC,
                "warning",
                "orden temporal no monotono",
                cue.source_position,
                cue.index,
            )
        )
    if prev is not None and cue.start_ms < prev.end_ms:
        out.append(
            diag(
                WARN_OVERLAP,
                "warning",
                "solapa con el cue anterior",
                cue.source_position,
                cue.index,
            )
        )
    return out


def _check_text(cue):
    out = []
    if not cue.lines or all(ln.strip() == "" for ln in cue.lines):
        out.append(
            diag(ERR_EMPTY_CUE_TEXT, "error", "cue sin texto", cue.source_position, cue.index)
        )
    if "\x00" in cue.text:
        out.append(
            diag(
                ERR_NUL_CHARACTER,
                "error",
                "caracter NUL en el texto",
                cue.source_position,
                cue.index,
            )
        )
    if any(_has_control(ln) for ln in cue.lines):
        out.append(
            diag(
                WARN_CONTROL_CHARACTERS,
                "warning",
                "caracteres de control",
                cue.source_position,
                cue.index,
            )
        )
    if len(cue.lines) > MAX_LINES_PER_CUE:
        out.append(
            diag(
                WARN_TOO_MANY_LINES, "warning", "demasiadas lineas", cue.source_position, cue.index
            )
        )
    if any(len(ln) > MAX_CHARS_PER_LINE for ln in cue.lines):
        out.append(
            diag(
                WARN_LINE_TOO_LONG,
                "warning",
                "linea excesivamente larga",
                cue.source_position,
                cue.index,
            )
        )
    return out


def _check_video(cue, vdur):
    if vdur is None:
        return []
    if cue.start_ms >= vdur:
        return [
            diag(
                WARN_CUE_AFTER_VIDEO,
                "warning",
                "cue posterior al fin del video",
                cue.source_position,
                cue.index,
            )
        ]
    if cue.end_ms > vdur:
        return [
            diag(
                WARN_CUE_PARTIALLY_OUT,
                "warning",
                "cue parcialmente fuera del video",
                cue.source_position,
                cue.index,
            )
        ]
    return []


def validate_srt(
    document: SrtDocument, *, video_duration_ms: int | None = None
) -> tuple[SrtDiagnostic, ...]:
    """Revalida un documento de forma independiente. Determinista, en orden fuente."""
    if not document.cues:
        return (diag(ERR_DOCUMENT_EMPTY, "error", "el documento no contiene cues"),)
    diags: list[SrtDiagnostic] = []
    seen: set[int] = set()
    prev = None
    for cue in document.cues:
        diags.extend(_check_index(cue, prev, seen))
        diags.extend(_check_time(cue, prev))
        diags.extend(_check_text(cue))
        diags.extend(_check_video(cue, video_duration_ms))
        seen.add(cue.index)
        prev = cue
    last = document.cues[-1]
    if video_duration_ms is not None and video_duration_ms - last.end_ms > LAST_CUE_GAP_MS:
        diags.append(
            diag(
                WARN_LAST_CUE_FAR,
                "warning",
                "ultimo cue lejos del fin del video",
                last.source_position,
                last.index,
            )
        )
    return tuple(diags)
