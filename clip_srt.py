"""clip_srt.py — SRT derivado por clip (S36-C2A2). Reutiliza `srt_slice` (S36-B) SIN duplicar.

Dado un SRT del video padre y el rango del clip `[source_start_ms, source_end_ms)`, devuelve un
SRT NUEVO con los cues de ese segmento, rebasados a t=0 y renumerados desde 1. Añade sobre
`srt_slice` el contrato de C2A2: descartar cues degenerados (< 50 ms tras el recorte). Conserva el
texto EXACTO del SRT; no inventa cues, no traduce, no corrige. PURO: sin disco, sin FFmpeg, sin red.

Intersección (heredada de srt_slice): new_start = max(start, clip_start) - clip_start,
new_end = min(end, clip_end) - clip_start; incluido solo si new_end > new_start. Cues parcialmente
solapados se conservan recortados. Semántica de intervalo [start, end) (fin exclusivo).
"""

from __future__ import annotations

import srt_slice
from srt_types import SrtCue, SrtDocument

MIN_CLIP_CUE_MS = 50  # cues más cortos que esto tras el recorte se descartan (degenerados)


def derive_clip_srt(document: SrtDocument, source_start_ms: int, source_end_ms: int) -> SrtDocument:
    """SRT del clip `[source_start_ms, source_end_ms)`, rebasado a t=0 y renumerado desde 1.

    Reutiliza `srt_slice.slice_srt` (recorte + rebase + reindex) y descarta los cues cuya duración
    tras el recorte sea < MIN_CLIP_CUE_MS. Nunca modifica `document` (devuelve uno nuevo, frozen).
    Lanza `SrtError` (vía srt_slice) si el rango es inválido (end<=start, start<0, no enteros).
    """
    sliced = srt_slice.slice_srt(
        document, source_start_ms, source_end_ms, rebase=True, reindex=True
    )
    kept: list[SrtCue] = []
    for cue in sliced.cues:
        if cue.end_ms - cue.start_ms < MIN_CLIP_CUE_MS:
            continue  # degenerado tras el recorte: se descarta
        kept.append(SrtCue(len(kept) + 1, cue.start_ms, cue.end_ms, cue.lines, len(kept)))
    return SrtDocument(
        cues=tuple(kept),
        encoding=sliced.encoding,
        source_sha256=sliced.source_sha256,
        diagnostics=(),
        source_name=None,
    )


__all__ = ["MIN_CLIP_CUE_MS", "derive_clip_srt"]
