"""srt_align_partial.py — Cues con timing real + huecos repartidos (S38).

Adaptador entre el alineador (`srt_align`) y el motor de reparto (`srt_eventos`). Convierte
tokens + anclas en el `AlignedCue` que consume el motor de captions.

Reglas (las garantiza `srt_eventos`, aqui solo se traducen a `AlignedWord`):

  1. El cue manda sobre CUANDO aparece el caption: el primer evento arranca en `cue.start_ms`
     y el ultimo cierra en `cue.end_ms`, siempre.
  2. Un token anclado conserva su tiempo medido mientras quepa; si el ancla desborda el cue
     (`_claim_window` reclama por punto MEDIO, asi que puede pasar por los dos lados) se acota
     al rango del cue en vez de tirar el cue entero a estatico.
  3. Ningun evento baja de `min_evento_ms`; un token que no alcanza el minimo se ABSORBE en el
     anterior — se pierde su resalte, nunca su texto.
  4. Eventos contiguos, estrictamente crecientes y sin duplicados.

Este modulo NO decide que cues se animan. Ese porton es `min_coverage`, y vive en `srt_align`.

Puro: solo stdlib, sin IO.
"""

from __future__ import annotations

import srt_eventos

MIN_EVENTO_MS = srt_eventos.MIN_EVENTO_MS

# Como se etiqueta cada evento en el sidecar de auditoria.
KIND_INTERPOLADO = "interpolado"
KIND_ABSORBIDO = "absorbido"


def _kind(indices: tuple[int, ...], kinds: dict[int, str]) -> str:
    """Etiqueta del evento: absorbido > ancla real > interpolado."""
    if len(indices) > 1:
        return KIND_ABSORBIDO
    return kinds.get(indices[0], KIND_INTERPOLADO)


def construir_cue_layout(cue, tokens, accepted, stats, modo: str, min_evento_ms: int):
    """AlignedCue con el reparto normalizado, o None si el cue no da ni para un evento.

    `tokens` es [(texto, line_idx)]; `accepted` mapea indice_de_token -> (timing_word, kind);
    `stats` es (n_tok, n_matched, n_exact, n_sub, n_rejected). Import diferido de `srt_align`
    para no crear un ciclo: este modulo es el detalle, `srt_align` es la API.
    """
    from srt_align import AlignedCue, AlignedWord, _timings_validos  # noqa: PLC0415

    n_tok, n_matched, n_exact, n_sub, n_rejected = stats
    anclas = {i: (w["s_ms"], w["e_ms"]) for i, (w, _k) in accepted.items()}
    eventos = srt_eventos.distribuir_eventos(n_tok, anclas, cue.start_ms, cue.end_ms, min_evento_ms)
    if eventos is None:
        return None

    kinds = {i: k for i, (_w, k) in accepted.items()}
    words = tuple(
        AlignedWord(
            " ".join(tokens[i][0] for i in ev.indices),
            ev.start_ms,
            ev.end_ms,
            tokens[ev.indices[0]][1],
            _kind(ev.indices, kinds),
        )
        for ev in eventos
    )
    if not _timings_validos(words):  # red de seguridad: el motor ya lo garantiza
        return None
    return AlignedCue(
        cue.index,
        cue.start_ms,
        cue.end_ms,
        cue.lines,
        modo,
        words,
        n_tok,
        n_matched,
        round(n_matched / n_tok, 4) if n_tok else 0.0,
        "all_tokens_anchored" if modo == "word_aligned" else "interpolacion_parcial",
        n_exact,
        n_sub,
        n_rejected,
    )


__all__ = ["MIN_EVENTO_MS", "KIND_INTERPOLADO", "KIND_ABSORBIDO", "construir_cue_layout"]
