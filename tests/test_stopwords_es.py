"""Contrato de `stopwords_es` (S39, capa 1).

La lista BASE es la historica del motor de keywords: si cambia, cambia que palabras destaca
la ruta clasica de captions. Se congela aqui contra el literal que vivia en `cve_keywords`.
La lista AMPLIADA solo la consume el gate de cues parciales y no puede pisar las senales
fuertes del motor (numeros, dinero, fechas, negaciones).
"""

from __future__ import annotations

import cve_keywords as ck
import stopwords_es

# Literal EXACTO que vivia en cve_keywords.STOPWORDS antes de la extraccion (S39).
# No se "actualiza" si el modulo cambia: es el testigo de la byte-identidad clasica.
_HISTORICO = frozenset(
    "el la los las un una unas unos de en que y o a con por para se me te le les "
    "es son fue era ser estar esta este esto esa ese eso al del lo mi tu su sus "
    "como mas muy ya si no nos hay han ha he va van voy vas todo toda todos todas "
    "pero aunque embargo entonces cuando donde porque".split()
)


def test_base_es_identica_a_la_lista_historica():
    assert stopwords_es.STOPWORDS_BASE == _HISTORICO


def test_cve_keywords_reexporta_el_mismo_objeto():
    """No una copia: el motor clasico y el gate comparten la misma lista base."""
    assert ck.STOPWORDS is stopwords_es.STOPWORDS_BASE


def _historico(t: str) -> str:
    """Implementacion EXACTA que vivia en `cve_keywords._normalizar` antes de S39."""
    return t.lower().strip(".,!?;:¿¡\"'()").translate(str.maketrans("áéíóúü", "aeiouu"))


def test_normalizar_conserva_la_logica_historica():
    historico = _historico
    for palabra in ("Hola", "¿QUE?", "más", "'gratis',", "PNG", "", "50%", "Ñandú"):
        assert stopwords_es.normalizar(palabra) == historico(palabra)


def test_ampliada_contiene_a_la_base():
    assert stopwords_es.STOPWORDS_BASE < stopwords_es.STOPWORDS_ES


def test_ampliada_no_pisa_las_senales_fuertes_del_motor():
    """Un numero, un monto, una fecha o una negacion SIGNIFICAN algo: jamas son vacias."""
    fuertes = ck.NUMERALES | ck.DINERO_PCT | ck.FECHAS | ck.NEGACIONES
    nuevas = stopwords_es.STOPWORDS_ES - stopwords_es.STOPWORDS_BASE
    assert nuevas & fuertes == frozenset()


def test_ampliada_esta_normalizada():
    """Sin acentos ni mayusculas: se compara contra formas ya normalizadas."""
    for palabra in stopwords_es.STOPWORDS_ES:
        assert stopwords_es.normalizar(palabra) == palabra


def test_es_stopword_default_es_la_lista_historica():
    # "quiza" solo es vacia en la lista ampliada; la ruta clasica no la conoce.
    assert stopwords_es.es_stopword("quiza") is False
    assert stopwords_es.es_stopword("quiza", ampliada=True) is True
    assert stopwords_es.es_stopword("QUIZÁ,", ampliada=True) is True
    assert stopwords_es.es_stopword("de") is True
