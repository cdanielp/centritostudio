"""srt_eventos.py — Reparto de eventos dentro de un cue (S38-v2, tras el gate visual de K).

K rechazo la primera version del alineado parcial: el TEXTO era correcto, el TIMING dentro del
cue no. Cuatro defectos medidos sobre el render real:

  D1 El caption entraba tarde: el primer evento arrancaba en la primera ancla, no en el inicio
     del cue (hasta +0.57 s). El final si respetaba `cue_end_ms`.
  D2 30 de 173 eventos duraban menos de 120 ms (12 de ellos 50 ms): destellos.
  D3 8 pares de eventos consecutivos se pisaban; uno se emitia dos veces identico.
  D4 Habia dos portones NO documentados decidiendo el fallback, no `min_coverage`.

Este modulo concentra el reparto y garantiza, por construccion:

  * `eventos[0].start_ms == cue_start_ms` y `eventos[-1].end_ms == cue_end_ms`;
  * cada evento dura `>= min_evento_ms`;
  * los eventos son CONTIGUOS (`e[i].end == e[i+1].start`), estrictamente crecientes y unicos.

Un token que no alcanza el minimo se ABSORBE en el evento anterior: se pierde su resalte, nunca
su texto. Las anclas se acotan al rango del cue: el cue manda sobre cuando aparece el caption,
y una palabra reclamada por punto MEDIO puede desbordarlo por cualquiera de los dos lados.

Puro: solo stdlib, sin IO. NO decide QUE cues se animan (eso es el porton de `srt_align`);
solo reparte los que le pasan.
"""

from __future__ import annotations

from dataclasses import dataclass

# Duracion minima de un evento en pantalla. Por debajo de ~150 ms una palabra resaltada se
# lee como un destello, no como enfasis. Configurable por si un preset quiere otro ritmo.
MIN_EVENTO_MS = 150


@dataclass(frozen=True)
class Evento:
    """Un evento de caption: los tokens que muestra y su ventana exacta en ms."""

    indices: tuple[int, ...]  # >1 indice = tokens absorbidos (pierden resalte, no texto)
    start_ms: int
    end_ms: int


def _deseados(n_tok: int, anclas: dict[int, tuple[int, int]], ini: int, fin: int) -> list[float]:
    """Inicio deseado de cada token: anclas acotadas al cue, huecos repartidos uniformemente."""
    pinned = {i: min(max(anclas[i][0], ini), fin) for i in sorted(anclas) if 0 <= i < n_tok}
    if not pinned:
        paso = (fin - ini) / n_tok
        return [ini + paso * i for i in range(n_tok)]
    d: list[float] = [0.0] * n_tok
    idx = sorted(pinned)
    for i in idx:
        d[i] = float(pinned[i])
    # Racha inicial (antes del primer ancla): arranca en el inicio del cue (D1).
    primero = idx[0]
    for j in range(primero):
        d[j] = ini + (pinned[primero] - ini) * j / primero
    # Rachas intermedias: reparto uniforme entre las dos anclas que las encierran.
    for a, b in zip(idx, idx[1:], strict=False):
        k = b - a - 1
        for j in range(k):
            d[a + 1 + j] = pinned[a] + (pinned[b] - pinned[a]) * (j + 1) / (k + 1)
    # Racha final: reparto uniforme entre la ultima ancla y el fin del cue.
    ultimo = idx[-1]
    k = n_tok - 1 - ultimo
    for j in range(k):
        d[ultimo + 1 + j] = pinned[ultimo] + (fin - pinned[ultimo]) * (j + 1) / (k + 1)
    d[0] = float(ini)  # D1: pase lo que pase, el cue arranca cuando dice el cue
    return d


def _agrupar(d: list[float], n_ev: int, anclados: set[int]) -> list[list[int]]:
    """Fusiona tokens hasta dejar `n_ev` grupos, empezando por los mas apretados (D2)."""
    grupos = [[i] for i in range(len(d))]
    while len(grupos) > n_ev:
        # Se absorbe el grupo cuyo hueco con el anterior es menor; a igualdad, el que NO
        # tiene ancla (perder el resalte de una palabra medida cuesta mas informacion).
        mejor, mejor_clave = 1, None
        for k in range(1, len(grupos)):
            hueco = d[grupos[k][0]] - d[grupos[k - 1][0]]
            clave = (any(i in anclados for i in grupos[k]), hueco, k)
            if mejor_clave is None or clave < mejor_clave:
                mejor, mejor_clave = k, clave
        grupos[mejor - 1].extend(grupos.pop(mejor))
    return grupos


def _bordes(starts: list[float], ini: int, fin: int, min_ms: int) -> list[int]:
    """Inicios enteros, estrictamente crecientes, con `min_ms` de separacion (D2 + D3)."""
    s = [float(x) for x in starts]
    s[0] = float(ini)
    for k in range(1, len(s)):  # empuja hacia adelante
        s[k] = max(s[k], s[k - 1] + min_ms)
    if s[-1] > fin - min_ms:  # y luego hacia atras, si el empuje se paso del final
        s[-1] = float(fin - min_ms)
        for k in range(len(s) - 2, 0, -1):
            s[k] = min(s[k], s[k + 1] - min_ms)
        s[0] = float(ini)
    out = [int(round(x)) for x in s]
    valido = out[0] == ini and all(out[k] - out[k - 1] >= min_ms for k in range(1, len(out)))
    if not valido or fin - out[-1] < min_ms:
        # Caso patologico (anclas imposibles de respetar): reparto uniforme, que siempre
        # cumple porque el numero de eventos ya se acoto a `cap`.
        paso = (fin - ini) / len(out)
        out = [int(ini + paso * k) for k in range(len(out))]
    return out


def distribuir_eventos(
    n_tok: int,
    anclas: dict[int, tuple[int, int]],
    cue_start_ms: int,
    cue_end_ms: int,
    min_evento_ms: int = MIN_EVENTO_MS,
) -> tuple[Evento, ...] | None:
    """Reparte `n_tok` tokens en eventos contiguos que cubren [cue_start_ms, cue_end_ms).

    `anclas` mapea indice_de_token -> (start_ms, end_ms) medidos. No se muta.
    Devuelve None SOLO si el cue no da ni para un evento del minimo (el llamador cae a
    estatico honesto). Nunca devuelve eventos degenerados, solapados ni duplicados.
    """
    dur = cue_end_ms - cue_start_ms
    if n_tok <= 0 or dur < min_evento_ms:
        return None
    cap = max(1, dur // min_evento_ms)
    d = _deseados(n_tok, anclas, cue_start_ms, cue_end_ms)
    grupos = _agrupar(d, min(n_tok, cap), set(anclas))
    starts = _bordes([d[g[0]] for g in grupos], cue_start_ms, cue_end_ms, min_evento_ms)
    fines = [*starts[1:], cue_end_ms]
    return tuple(Evento(tuple(g), s, e) for g, s, e in zip(grupos, starts, fines, strict=True))


__all__ = ["MIN_EVENTO_MS", "Evento", "distribuir_eventos"]
