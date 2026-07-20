"""clip_transcript.py — words+groups por clip desde los timings del video PADRE (S36-C2A2).

Deriva los timings de un clip `[source_start_ms, source_end_ms)` desde las words exactas del video
padre (S36-C2A1): selecciona las que intersectan el rango, recorta start/end al rango y las desplaza
para que el clip comience en t=0, conservando texto/probabilidad/campos históricos. Los
groups se reconstruyen con el motor histórico (`core.group_words`). NUNCA retranscribe por clip, no
usa words stem-only ambiguos ni cruza MOV/MP4. Añade una PROCEDENCIA por clip que liga el resultado
al video padre + rango + clip extraído.

PURO: sin FFmpeg, sin red, sin Auto. `core.group_words` se importa lazy (sin costo en tests).
Words en segundos (contrato histórico `{"w","s","e","prob"}`); el rango del clip en ms enteros.
"""

from __future__ import annotations

from pathlib import Path

import transcript_provenance

CLIP_PROVENANCE_VERSION = 1


def _es_int_ms(value: object) -> bool:
    """int estricto (bool NO cuenta), como el resto del proyecto (transcript_provenance)."""
    return isinstance(value, int) and not isinstance(value, bool)


def derive_clip_words(words: list[dict], source_start_ms: int, source_end_ms: int) -> list[dict]:
    """Words del clip: intersección temporal con `[source_start_ms, source_end_ms)`, recorte y
    desplazamiento a t=0. Conserva texto/prob/campos; nunca muta la lista/dicts de entrada.

    Una word `[s, e]` (segundos) se incluye recortada si su intersección con el rango es > 0.
    """
    if not _es_int_ms(source_start_ms) or not _es_int_ms(source_end_ms):
        raise ValueError("source_start_ms y source_end_ms deben ser enteros (ms)")
    if source_end_ms <= source_start_ms or source_start_ms < 0:
        raise ValueError("rango de clip invalido")
    cs = source_start_ms / 1000.0
    ce = source_end_ms / 1000.0
    out: list[dict] = []
    for w in words:
        s = float(w["s"])
        e = float(w["e"])
        lo = max(s, cs)
        hi = min(e, ce)
        if hi <= lo:  # sin solape real (incluye tocar el borde)
            continue
        shifted = dict(w)  # copia: no muta la fuente
        shifted["s"] = round(lo - cs, 3)
        shifted["e"] = round(hi - cs, 3)
        out.append(shifted)
    return out


def derive_clip_groups(clip_words: list[dict]) -> list[dict]:
    """Groups del clip con el motor histórico (`core.group_words`). Sin words -> []."""
    if not clip_words:
        return []
    import core  # noqa: PLC0415  (lazy: evita el costo de import en tests puros/offline)

    return core.group_words(clip_words)


def build_clip_provenance(
    parent_video: Path,
    *,
    source_start_ms: int,
    source_end_ms: int,
    output_clip: Path,
) -> dict:
    """Procedencia por clip v1: video padre + rango + clip extraído (solo basenames + size + mtime).

    Liga los timings del clip a (a) el video padre EXACTO y (b) el MP4 del clip extraído, de modo
    que el worker pueda rechazar timings/clip ajenos. Nunca incluye rutas absolutas.
    """
    if not _es_int_ms(source_start_ms) or not _es_int_ms(source_end_ms):
        raise ValueError("source_start_ms y source_end_ms deben ser enteros (ms)")
    if source_end_ms <= source_start_ms or source_start_ms < 0:
        raise ValueError("rango de clip invalido")
    return {
        "version": CLIP_PROVENANCE_VERSION,
        "parent_video": transcript_provenance.build_video_provenance(parent_video),
        "clip": {
            "source_start_ms": int(source_start_ms),
            "source_end_ms": int(source_end_ms),
            "duration_ms": int(source_end_ms - source_start_ms),
        },
        "output_clip": transcript_provenance.build_video_provenance(output_clip),
    }


__all__ = [
    "CLIP_PROVENANCE_VERSION",
    "derive_clip_words",
    "derive_clip_groups",
    "build_clip_provenance",
]
