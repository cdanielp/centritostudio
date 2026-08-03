"""Estimador de offset por anclas (S38-1).

El offset se DETECTA y se PROPONE; NUNCA se auto-aplica. Un offset mal estimado
desincroniza el video entero en silencio, asi que la funcion pura devuelve tambien
numero de anclas, dispersion y confianza para que el llamador decida.

Cobertura: offset positivo / negativo / cero, material sin anclas suficientes,
material con contenido distinto (confianza baja) y ausencia de auto-aplicacion.
"""

from __future__ import annotations

import pytest

import srt_offset
from srt_types import SrtCue, SrtDocument

# ── Fixtures sinteticos (nunca material privado) ──────────────────────────────

FRASES = [
    "el zorro marron salta",
    "sobre el perro perezoso",
    "mientras la cigueña vuela",
    "hacia el norte lejano",
    "con paciencia infinita hoy",
    "y regresa cada primavera",
    "buscando semillas frescas",
    "entre ramas altas secas",
    "durante tardes muy tranquilas",
    "bajo cielos despejados azules",
]


def _doc(frases=FRASES, cue_ms=2000, gap_ms=0):
    """SrtDocument sintetico: un cue por frase, cues consecutivos."""
    cues = []
    t = 0
    for i, f in enumerate(frases, 1):
        cues.append(SrtCue(i, t, t + cue_ms, (f,), i))
        t += cue_ms + gap_ms
    return SrtDocument(tuple(cues), "utf-8", "sha-sintetico", (), "sintetico.srt")


def _words(frases=FRASES, cue_ms=2000, gap_ms=0, offset_s=0.0):
    """Timing words alineadas con `_doc` y desplazadas `offset_s` segundos."""
    out = []
    t = 0.0
    for f in frases:
        toks = f.split()
        dur = (cue_ms / 1000) / len(toks)
        for k, tok in enumerate(toks):
            s = t + dur * k + offset_s
            out.append({"w": tok, "s": s, "e": s + dur * 0.9, "prob": 0.9})
        t += (cue_ms + gap_ms) / 1000
    return out


# ── Deteccion del offset ──────────────────────────────────────────────────────


@pytest.mark.parametrize("offset_s", [0.0, 5.28, -3.5, 12.0, -0.75])
def test_detecta_offset_constante(offset_s):
    est = srt_offset.estimar_offset(_doc(), _words(offset_s=offset_s))
    assert est.n_anclas >= srt_offset.MIN_ANCLAS
    assert abs(est.offset_ms - round(offset_s * 1000)) <= 60, est
    assert est.confianza >= 0.9
    assert est.aplicable is True
    assert est.metodo == "anclas_token_unico"


def test_offset_cero_queda_dentro_de_la_resolucion():
    """Sin desfase real, la propuesta es ~0.

    No se exige 0 exacto: el SRT no trae timing por palabra, asi que el estimador reparte
    el cue uniformemente y esa aproximacion deja un sesgo de decenas de ms. Por eso el
    contrato es "dentro de la resolucion", no igualdad, y la tolerancia real es de 1 s.
    """
    est = srt_offset.estimar_offset(_doc(), _words(offset_s=0.0))
    assert abs(est.offset_ms) <= 60
    assert est.dispersion_ms <= 60


def test_dispersion_baja_con_offset_constante():
    est = srt_offset.estimar_offset(_doc(), _words(offset_s=5.28))
    assert est.dispersion_ms <= 60, "un desfase constante no debe dispersar"


# ── Casos en los que NO se puede proponer nada ────────────────────────────────


def test_sin_anclas_suficientes_no_es_aplicable():
    est = srt_offset.estimar_offset(_doc(FRASES[:1]), _words(FRASES[:1]))
    assert est.n_anclas < srt_offset.MIN_ANCLAS
    assert est.aplicable is False
    assert est.motivo == "anclas_insuficientes"
    assert est.offset_ms == 0, "sin anclas suficientes NO se propone desplazamiento"


def test_transcript_vacio_no_revienta():
    est = srt_offset.estimar_offset(_doc(), [])
    assert est.n_anclas == 0
    assert est.offset_ms == 0
    assert est.aplicable is False


def test_documento_sin_cues_no_revienta():
    doc = SrtDocument((), "utf-8", "sha", (), None)
    est = srt_offset.estimar_offset(doc, _words())
    assert est.n_anclas == 0
    assert est.aplicable is False


def test_contenido_distinto_da_confianza_baja():
    otras = [f"palabra{i} distinta{i} totalmente{i} ajena{i}" for i in range(10)]
    est = srt_offset.estimar_offset(_doc(), _words(otras))
    assert est.aplicable is False


def test_desfase_erratico_baja_la_confianza():
    """Cada cue con su propio desplazamiento: no hay UN offset que sirva."""
    palabras = []
    t = 0.0
    for i, f in enumerate(FRASES):
        toks = f.split()
        dur = 2.0 / len(toks)
        deriva = i * 3.0  # el desfase crece cue a cue
        for k, tok in enumerate(toks):
            s = t + dur * k + deriva
            palabras.append({"w": tok, "s": s, "e": s + dur * 0.9, "prob": 0.9})
        t += 2.0
    est = srt_offset.estimar_offset(_doc(), palabras)
    assert est.confianza < srt_offset.CONFIANZA_MIN
    assert est.aplicable is False


# ── Contrato de no-mutacion / no-auto-aplicacion ──────────────────────────────


def test_no_muta_las_entradas():
    doc, words = _doc(), _words(offset_s=5.0)
    copia = [dict(w) for w in words]
    starts = [c.start_ms for c in doc.cues]
    srt_offset.estimar_offset(doc, words)
    assert words == copia, "las timing words no se tocan"
    assert [c.start_ms for c in doc.cues] == starts, "el SRT no se desplaza solo"


def test_serializacion_saneada_sin_texto():
    est = srt_offset.estimar_offset(_doc(), _words(offset_s=5.28))
    d = srt_offset.offset_a_dict(est)
    assert set(d) == {
        "offset_ms",
        "n_anclas",
        "dispersion_ms",
        "confianza",
        "aplicable",
        "metodo",
        "motivo",
    }
    plano = repr(d).lower()
    for tok in ("zorro", "cigueña", "perezoso"):
        assert tok not in plano, "el sidecar/API nunca publica texto del SRT"
