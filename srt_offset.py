"""srt_offset.py — Estimador de desfase temporal entre un SRT y sus timing words (S38).

Un SRT corregido a mano suele venir de un timeline distinto al del transcript (recorte de
silencios, exportacion desde otra herramienta). Ese desfase es CONSTANTE y basta para que
el alineador no ancle NADA aunque el texto coincida casi palabra por palabra.

Este modulo DETECTA y PROPONE el desfase. **Nunca lo aplica.** Un offset mal estimado
desincroniza el video entero en silencio, sin error visible, y el usuario solo lo descubre
al ver el render. Por eso `estimar_offset` es puro y devuelve, ademas del numero,
el material para decidir: cuantas anclas lo sostienen, cuanto dispersan y que confianza hay.

Metodo: anclas de token UNICO. Un token que aparece exactamente una vez en el SRT y una
vez en el transcript es un par sin ambiguedad; la MEDIANA de las diferencias resiste
outliers (una palabra repetida mal emparejada no mueve el resultado). Solo stdlib.
"""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass

from srt_align import normalize_token

# Minimo de anclas para que una propuesta sea defendible. Con menos, la mediana la fija
# un puñado de coincidencias y puede ser ruido.
MIN_ANCLAS = 20
# Un ancla "concuerda" si cae a menos de esto de la mediana. 1 s es holgado para
# tolerar la imprecision de repartir el tiempo del cue entre sus tokens.
TOLERANCIA_MS = 1000
# Fraccion minima de anclas concordantes para proponer el offset.
CONFIANZA_MIN = 0.80

METODO = "anclas_token_unico"


@dataclass(frozen=True)
class OffsetEstimate:
    """Propuesta de desfase. `aplicable` NO significa aplicado: el llamador decide."""

    offset_ms: int
    n_anclas: int
    dispersion_ms: int
    confianza: float
    motivo: str = ""
    metodo: str = METODO

    @property
    def aplicable(self) -> bool:
        """True si hay anclas suficientes y concuerdan entre si."""
        return self.n_anclas >= MIN_ANCLAS and self.confianza >= CONFIANZA_MIN


def _vacio(motivo: str) -> OffsetEstimate:
    """Propuesta nula: offset 0 explicito para que nadie desplace nada por accidente."""
    return OffsetEstimate(0, 0, 0, 0.0, motivo)


def _tiempos_srt(document) -> list[tuple[str, float]]:
    """(token_normalizado, ms_estimado) repartiendo cada cue entre sus tokens.

    El SRT no trae timing por palabra: se asume reparto uniforme dentro del cue y se toma
    el punto MEDIO de cada token. Es una aproximacion, y por eso la tolerancia es de 1 s.
    """
    out: list[tuple[str, float]] = []
    for cue in document.cues:
        toks = [t for line in cue.lines for t in line.split()]
        if not toks:
            continue
        dur = (cue.end_ms - cue.start_ms) / len(toks)
        for i, tok in enumerate(toks):
            norm = normalize_token(tok)
            if norm:
                out.append((norm, cue.start_ms + dur * (i + 0.5)))
    return out


def _tiempos_words(timing_words: list[dict]) -> list[tuple[str, float]]:
    """(token_normalizado, ms_medio) de las timing words. No muta la entrada."""
    out: list[tuple[str, float]] = []
    for w in timing_words:
        try:
            s_ms = float(w["s"]) * 1000
            e_ms = float(w["e"]) * 1000
        except (KeyError, TypeError, ValueError):
            continue
        norm = normalize_token(str(w.get("w", "")))
        if norm:
            out.append((norm, (s_ms + e_ms) / 2))
    return out


def _diferencias(srt_t: list[tuple[str, float]], asr_t: list[tuple[str, float]]) -> list[float]:
    """Diferencias ms (asr - srt) de los tokens que aparecen UNA sola vez en ambos lados."""
    c_srt = Counter(t for t, _ in srt_t)
    c_asr = Counter(t for t, _ in asr_t)
    unicos = {t for t, n in c_srt.items() if n == 1 and c_asr.get(t) == 1}
    if not unicos:
        return []
    m_srt = {t: ms for t, ms in srt_t if t in unicos}
    m_asr = {t: ms for t, ms in asr_t if t in unicos}
    return sorted(m_asr[t] - m_srt[t] for t in unicos)


def estimar_offset(document, timing_words: list[dict]) -> OffsetEstimate:
    """Propone el desfase ms (positivo = el audio va DESPUES de lo que dice el SRT).

    Funcion PURA: no muta el documento ni las timing words, no toca disco y no aplica
    nada. El llamador decide si pasa el valor como `offset_ms` explicito al alineador.
    """
    if not getattr(document, "cues", ()) or not timing_words:
        return _vacio("sin_material")

    difs = _diferencias(_tiempos_srt(document), _tiempos_words(timing_words))
    if not difs:
        return _vacio("sin_anclas")

    mediana = statistics.median(difs)
    dispersion = statistics.median([abs(d - mediana) for d in difs])
    concordantes = sum(1 for d in difs if abs(d - mediana) <= TOLERANCIA_MS)
    confianza = round(concordantes / len(difs), 4)

    if len(difs) < MIN_ANCLAS:
        return OffsetEstimate(
            0, len(difs), int(round(dispersion)), confianza, "anclas_insuficientes"
        )
    if confianza < CONFIANZA_MIN:
        # Hay anclas, pero no describen UN desfase: probablemente deriva o material distinto.
        return OffsetEstimate(
            0, len(difs), int(round(dispersion)), confianza, "desfase_no_constante"
        )
    return OffsetEstimate(int(round(mediana)), len(difs), int(round(dispersion)), confianza)


def offset_a_dict(est: OffsetEstimate) -> dict:
    """Forma saneada para sidecar y API: solo numeros y codigos, nunca texto del SRT."""
    return {
        "offset_ms": est.offset_ms,
        "n_anclas": est.n_anclas,
        "dispersion_ms": est.dispersion_ms,
        "confianza": est.confianza,
        "aplicable": est.aplicable,
        "metodo": est.metodo,
        "motivo": est.motivo,
    }


__all__ = [
    "MIN_ANCLAS",
    "TOLERANCIA_MS",
    "CONFIANZA_MIN",
    "OffsetEstimate",
    "estimar_offset",
    "offset_a_dict",
]
