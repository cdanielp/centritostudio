"""srt_align_partial.py — Cues parcialmente alineados: timing real + huecos interpolados (S38).

El alineador historico es todo-o-nada: si un solo token del cue no ancla, el cue entero cae
a estatico. Con un SRT corregido a mano eso deja la mayoria de los cues sin animar aunque el
80% de sus palabras SI tenga timing real.

Este modulo rellena SOLO los huecos. Las reglas son duras y no se negocian:

  1. Un token anclado JAMAS se mueve: conserva su timing real, al ms.
  2. Los tokens sin ancla se reparten UNIFORMEMENTE en el hueco que dejan sus vecinos
     anclados (o el borde del cue, si estan al principio o al final).
  3. Nada se sale del rango [cue_start, cue_end].
  4. Monotonia estricta: cada palabra empieza donde termino la anterior o despues.
  5. Si el hueco no da ni 1 ms por token, NO se inventa nada: se devuelve None y el
     llamador cae a `cue_fallback` estatico honesto.

Puro (solo stdlib). No decide CUANDO interpolar: eso es del porton en `srt_align`.
"""

from __future__ import annotations

# Duracion minima de un token interpolado. Por debajo, el reparto es indistinguible de
# "sin timing" y es mas honesto caer a estatico.
MIN_MS_POR_TOKEN = 1


def _rachas_sin_ancla(anclados: set[int], n_tok: int) -> list[tuple[int, int]]:
    """Rachas contiguas [ini, fin] de tokens SIN ancla, en orden."""
    rachas: list[tuple[int, int]] = []
    for i in range(n_tok):
        if i in anclados:
            continue
        if rachas and rachas[-1][1] == i - 1:
            rachas[-1] = (rachas[-1][0], i)
        else:
            rachas.append((i, i))
    return rachas


def _limites(
    ini: int, fin: int, anclas: dict[int, tuple[int, int]], cue_start: int, cue_end: int
) -> tuple[int, int]:
    """(lo, hi) disponibles para una racha: entre el ancla previa y la siguiente.

    Los bordes que vienen de un ancla son tiempo REAL y no se recortan; los que vienen del
    cue (racha inicial o final) sí son el limite del cue.
    """
    previas = [i for i in anclas if i < ini]
    siguientes = [i for i in anclas if i > fin]
    lo = anclas[max(previas)][1] if previas else cue_start
    hi = anclas[min(siguientes)][0] if siguientes else cue_end
    return lo, hi


def anclas_utilizables(
    anclas: dict[int, tuple[int, int]], cue_start_ms: int, cue_end_ms: int
) -> bool:
    """True si las anclas van en orden, no se solapan y ninguna EMPIEZA antes del cue.

    Un ancla nunca se recorta (regla 1: no se mueve un timing real). `_claim_window` reclama
    por punto MEDIO, asi que una palabra real puede desbordar el cue por cualquiera de los
    dos lados, y los dos lados NO son equivalentes:

    - Desbordar por el FINAL es inofensivo: `core_ass.build_ass` cierra el evento de la
      ultima palabra en `group["end"]`, asi que el exceso se recorta al pintar. Se acepta.
    - Desbordar por el INICIO si importa: el caption apareceria ANTES de su cue y podria
      solaparse con el cue anterior (dos lineas en pantalla). Se rechaza -> estatico.

    `cue_end_ms` se conserva en la firma porque el llamador razona con el rango completo.
    """
    ultimo = cue_start_ms
    for i in sorted(anclas):
        s, e = anclas[i]
        if e <= s or s < cue_start_ms or s < ultimo:
            return False
        ultimo = e
    return True


def interpolar_tramos(
    n_tok: int, anclas: dict[int, tuple[int, int]], cue_start_ms: int, cue_end_ms: int
) -> dict[int, tuple[int, int]] | None:
    """Timings (start_ms, end_ms) de los tokens SIN ancla. None si no caben.

    `anclas` mapea indice_de_token -> (start_ms, end_ms) REALES y no se modifica.
    """
    anclados = set(anclas)
    relleno: dict[int, tuple[int, int]] = {}
    for ini, fin in _rachas_sin_ancla(anclados, n_tok):
        n = fin - ini + 1
        lo, hi = _limites(ini, fin, anclas, cue_start_ms, cue_end_ms)
        if hi - lo < n * MIN_MS_POR_TOKEN:
            return None  # sin hueco: no se inventa timing
        paso = (hi - lo) / n
        for k in range(n):
            s = int(lo + paso * k)
            e = int(lo + paso * (k + 1)) if k < n - 1 else int(hi)
            if e <= s:  # redondeo degenerado
                return None
            relleno[ini + k] = (s, e)
    return relleno


def construir_cue_parcial(cue, tokens, accepted, stats) -> object | None:
    """AlignedCue en modo `word_partial`, o None si el cue no admite interpolacion honesta.

    `accepted` mapea indice_de_token -> (timing_word, kind). `stats` es
    (n_tok, n_matched, n_exact, n_sub, n_rejected). Import diferido de `srt_align` para no
    crear un ciclo: este modulo es el detalle, `srt_align` es la API.
    """
    from srt_align import AlignedCue, AlignedWord, _timings_validos  # noqa: PLC0415

    n_tok, n_matched, n_exact, n_sub, n_rejected = stats
    anclas = {i: (w["s_ms"], w["e_ms"]) for i, (w, _k) in accepted.items()}
    if not anclas or not anclas_utilizables(anclas, cue.start_ms, cue.end_ms):
        return None
    relleno = interpolar_tramos(n_tok, anclas, cue.start_ms, cue.end_ms)
    if relleno is None:
        return None

    kinds = {i: k for i, (_w, k) in accepted.items()}
    words = tuple(
        AlignedWord(
            tokens[i][0],
            *(anclas[i] if i in anclas else relleno[i]),
            tokens[i][1],
            kinds.get(i, "interpolado"),
        )
        for i in range(n_tok)
    )
    if not _timings_validos(words):
        return None
    return AlignedCue(
        cue.index,
        cue.start_ms,
        cue.end_ms,
        cue.lines,
        "word_partial",
        words,
        n_tok,
        n_matched,
        round(n_matched / n_tok, 4) if n_tok else 0.0,
        "interpolacion_parcial",
        n_exact,
        n_sub,
        n_rejected,
    )


__all__ = [
    "MIN_MS_POR_TOKEN",
    "anclas_utilizables",
    "interpolar_tramos",
    "construir_cue_parcial",
]
