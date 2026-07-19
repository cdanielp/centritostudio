"""srt_slice.py — Recorte, rebase y reindexado de un SRT contra un intervalo (S36-B).

Usado por el round-trip del clipper (D36B-8/D36B-9): cuando el clipper corta un clip
en [start, end), se genera un SRT derivado con los cues de ESE segmento, rebasados al
cero temporal del clip (el `clip.start` REAL, con padding, no la primera palabra).

Modulo PURO: sin disco, sin red, sin FFmpeg, sin mutacion. Tiempos en ms enteros.
Semantica de intervalo: [start_ms, end_ms) (fin exclusivo). Nunca modifica la fuente:
devuelve un SrtDocument NUEVO con cues nuevos (frozen).
"""

from __future__ import annotations

from srt_types import SrtCue, SrtDocument, SrtError


def slice_srt(
    document: SrtDocument,
    start_ms: int,
    end_ms: int,
    *,
    rebase: bool = True,
    reindex: bool = True,
) -> SrtDocument:
    """Devuelve un SRT nuevo con los cues que intersectan [start_ms, end_ms).

    - Recorta los cues a los bordes del intervalo.
    - Con rebase=True resta start_ms (el clip arranca en t=0).
    - Con reindex=True renumera los cues desde 1 en orden.
    - Preserva lineas y texto exactos. Nunca modifica `document`.
    """
    if not isinstance(start_ms, int) or not isinstance(end_ms, int):
        raise SrtError("start_ms y end_ms deben ser enteros (ms)")
    if end_ms <= start_ms:
        raise SrtError(f"intervalo invalido: end_ms ({end_ms}) <= start_ms ({start_ms})")
    if start_ms < 0:
        raise SrtError(f"start_ms negativo: {start_ms}")

    kept: list[SrtCue] = []
    for cue in document.cues:
        lo = max(cue.start_ms, start_ms)
        hi = min(cue.end_ms, end_ms)
        if hi <= lo:  # sin solape real (incluye tocar el borde exacto)
            continue
        if rebase:
            lo -= start_ms
            hi -= start_ms
        idx = len(kept) + 1 if reindex else cue.index
        kept.append(SrtCue(idx, lo, hi, cue.lines, len(kept)))

    return SrtDocument(
        cues=tuple(kept),
        encoding=document.encoding,
        source_sha256=document.source_sha256,
        diagnostics=(),
        source_name=None,
    )


__all__ = ["slice_srt"]
