"""Alineado PARCIAL de cues + offset explicito en el alineador (S38-2).

Dos cambios, un archivo de contrato:

1. `offset_ms` desplaza el SRT sobre el timeline del video. Sin `offset_ms` la salida
   es byte-identica a la historica.
2. `modo_parcial` hace que el porton por cue HONRE `min_coverage` en vez de exigir
   `n_matched == n_tok`. Los tokens con ancla usan su timing REAL; los que no la tienen
   se reparten proporcionalmente en el hueco entre sus vecinos anclados, sin romper
   monotonia y sin salirse del rango del cue. Un cue sin NINGUNA ancla sigue cayendo a
   `cue_fallback` estatico honesto.

Sin `modo_parcial` la salida tambien es byte-identica a la historica.
"""

from __future__ import annotations

import srt_align
from srt_types import SrtCue, SrtDocument


def _doc(cues):
    return SrtDocument(tuple(cues), "utf-8", "sha-sintetico", (), "sintetico.srt")


def _cue(idx, start_ms, end_ms, texto):
    return SrtCue(idx, start_ms, end_ms, (texto,), idx)


def _w(tok, s, e):
    return {"w": tok, "s": s, "e": e, "prob": 0.9}


# ── 1. OFFSET ────────────────────────────────────────────────────────────────


def _doc_simple():
    return _doc([_cue(1, 0, 1000, "hola mundo cruel")])


def _words_simple(off=0.0):
    return [
        _w("hola", 0.0 + off, 0.3 + off),
        _w("mundo", 0.35 + off, 0.6 + off),
        _w("cruel", 0.65 + off, 0.95 + off),
    ]


def test_sin_offset_alinea():
    r = srt_align.align_srt_to_words(_doc_simple(), _words_simple())
    assert r.cues[0].mode == "word_aligned"
    assert r.offset_ms == 0


def test_offset_positivo_rescata_el_cue():
    """El audio va 5 s por delante del SRT: sin offset no ancla; con offset si."""
    words = _words_simple(off=5.0)
    sin = srt_align.align_srt_to_words(_doc_simple(), words)
    assert sin.cues[0].mode == "cue_fallback"

    con = srt_align.align_srt_to_words(_doc_simple(), words, offset_ms=5000)
    c = con.cues[0]
    assert c.mode == "word_aligned"
    assert con.offset_ms == 5000
    # El cue se publica en tiempo de VIDEO (desplazado), no en tiempo de SRT.
    assert (c.start_ms, c.end_ms) == (5000, 6000)
    assert c.words[0].start_ms == 5000


def test_offset_negativo():
    words = _words_simple(off=-0.0) + []
    doc = _doc([_cue(1, 4000, 5000, "hola mundo cruel")])
    r = srt_align.align_srt_to_words(doc, words, offset_ms=-4000)
    c = r.cues[0]
    assert c.mode == "word_aligned"
    assert (c.start_ms, c.end_ms) == (0, 1000)


def test_offset_cero_es_byte_identico():
    doc, words = _doc_simple(), _words_simple()
    a = srt_align.align_srt_to_words(doc, words)
    b = srt_align.align_srt_to_words(doc, words, offset_ms=0)
    assert a == b


def test_offset_nunca_produce_tiempos_negativos():
    doc = _doc([_cue(1, 0, 1000, "hola mundo cruel")])
    r = srt_align.align_srt_to_words(doc, _words_simple(), offset_ms=-9000)
    assert r.cues[0].start_ms >= 0
    assert r.cues[0].end_ms > r.cues[0].start_ms


# ── 2. ALINEADO PARCIAL ──────────────────────────────────────────────────────


def _doc_parcial():
    # 4 tokens; solo "uno" y "cuatro" existen en el audio.
    return _doc([_cue(1, 0, 4000, "uno dos tres cuatro")])


def _words_parcial():
    return [_w("uno", 0.0, 0.5), _w("cuatro", 3.0, 3.5)]


def test_default_sigue_cayendo_a_fallback():
    r = srt_align.align_srt_to_words(_doc_parcial(), _words_parcial())
    assert r.cues[0].mode == "cue_fallback"
    assert r.word_partial == 0


def test_modo_parcial_sin_bajar_min_coverage_no_cambia_nada():
    """min_coverage=1.0 (default) + modo_parcial = salida historica.

    Se comparan los CUES (lo que se renderiza), no el objeto entero: el resultado tambien
    lleva el flag `modo_parcial` como metadato de auditoria para el sidecar, y ese si debe
    diferir. Lo que no puede cambiar es un solo ms de la salida.
    """
    doc, words = _doc_parcial(), _words_parcial()
    a = srt_align.align_srt_to_words(doc, words)
    b = srt_align.align_srt_to_words(doc, words, modo_parcial=True)
    assert a.cues == b.cues
    assert (a.word_aligned, a.word_partial, a.cue_fallback) == (
        b.word_aligned,
        b.word_partial,
        b.cue_fallback,
    )
    assert a.coverage == b.coverage
    assert b.modo_parcial is True and a.modo_parcial is False


def test_modo_parcial_con_umbral_bajo_anima_el_cue():
    r = srt_align.align_srt_to_words(
        _doc_parcial(), _words_parcial(), modo_parcial=True, min_coverage=0.5
    )
    c = r.cues[0]
    assert c.mode == "word_partial"
    assert r.word_partial == 1
    assert len(c.words) == 4
    assert [w.text for w in c.words] == ["uno", "dos", "tres", "cuatro"]
    assert c.reason == "interpolacion_parcial"


def test_tokens_anclados_conservan_su_timing_real():
    r = srt_align.align_srt_to_words(
        _doc_parcial(), _words_parcial(), modo_parcial=True, min_coverage=0.5
    )
    ws = {w.text: w for w in r.cues[0].words}
    assert (ws["uno"].start_ms, ws["uno"].end_ms) == (0, 500)
    assert (ws["cuatro"].start_ms, ws["cuatro"].end_ms) == (3000, 3500)
    assert ws["uno"].kind == "exact_match"
    assert ws["dos"].kind == "interpolado"


def test_interpolados_se_reparten_en_el_hueco():
    r = srt_align.align_srt_to_words(
        _doc_parcial(), _words_parcial(), modo_parcial=True, min_coverage=0.5
    )
    ws = {w.text: w for w in r.cues[0].words}
    # hueco real = [500, 3000]; dos tokens => ~1250 ms cada uno
    assert 500 <= ws["dos"].start_ms < ws["dos"].end_ms <= ws["tres"].start_ms
    assert ws["tres"].end_ms <= 3000
    assert abs((ws["dos"].end_ms - ws["dos"].start_ms) - 1250) <= 5


def test_monotonia_estricta():
    r = srt_align.align_srt_to_words(
        _doc_parcial(), _words_parcial(), modo_parcial=True, min_coverage=0.5
    )
    ws = r.cues[0].words
    for a, b in zip(ws, ws[1:], strict=False):
        assert a.end_ms <= b.start_ms, f"{a.text} pisa a {b.text}"
        assert a.start_ms < a.end_ms


def test_nada_INTERPOLADO_se_sale_del_rango_del_cue():
    r = srt_align.align_srt_to_words(
        _doc_parcial(), _words_parcial(), modo_parcial=True, min_coverage=0.5
    )
    c = r.cues[0]
    for w in c.words:
        if w.kind == "interpolado":
            assert c.start_ms <= w.start_ms and w.end_ms <= c.end_ms


def test_ancla_que_desborda_por_el_FINAL_se_acepta():
    """El evento de la ultima palabra lo cierra `build_ass` en group["end"]: el exceso se recorta.

    Rechazar estos cues costaba 154 cues reales del material de K sin ganar nada.
    """
    # El punto MEDIO debe caer dentro del cue (asi lo reclama `_claim_window`); lo que
    # desborda es el final: mid("tres") = 1990 < 2000, pero termina en 2280.
    doc = _doc([_cue(1, 0, 2000, "uno dos tres")])
    words = [_w("uno", 0.0, 0.4), _w("tres", 1.70, 2.28)]
    r = srt_align.align_srt_to_words(doc, words, modo_parcial=True, min_coverage=0.5)
    c = r.cues[0]
    assert c.mode == "word_partial"
    assert {w.text: w.end_ms for w in c.words}["tres"] == 2280, "el timing real no se recorta"


def test_ancla_que_desborda_por_el_INICIO_cae_a_estatico():
    """Aparecer antes del propio cue puede solapar con el cue anterior: se rechaza."""
    # mid("uno") = 1100 (dentro del cue) pero arranca en 900, antes del cue.
    doc = _doc([_cue(1, 1000, 3000, "uno dos tres")])
    words = [_w("uno", 0.9, 1.3), _w("tres", 2.0, 2.4)]
    r = srt_align.align_srt_to_words(doc, words, modo_parcial=True, min_coverage=0.5)
    assert r.cues[0].mode == "cue_fallback"


def test_anclas_solapadas_caen_a_estatico():
    doc = _doc([_cue(1, 0, 3000, "uno dos tres")])
    words = [_w("uno", 0.0, 1.5), _w("tres", 1.0, 1.8)]  # "tres" empieza dentro de "uno"
    r = srt_align.align_srt_to_words(doc, words, modo_parcial=True, min_coverage=0.5)
    assert r.cues[0].mode == "cue_fallback"


# ── Casos de borde de la interpolacion ───────────────────────────────────────


def test_anclas_solo_al_inicio():
    doc = _doc([_cue(1, 0, 4000, "uno dos tres cuatro")])
    words = [_w("uno", 0.0, 0.5), _w("dos", 0.6, 1.0)]
    r = srt_align.align_srt_to_words(doc, words, modo_parcial=True, min_coverage=0.5)
    c = r.cues[0]
    assert c.mode == "word_partial"
    ws = {w.text: w for w in c.words}
    assert ws["tres"].start_ms >= 1000  # despues del ultimo ancla
    assert ws["cuatro"].end_ms <= 4000  # dentro del cue


def test_anclas_solo_al_final():
    doc = _doc([_cue(1, 0, 4000, "uno dos tres cuatro")])
    words = [_w("tres", 2.5, 3.0), _w("cuatro", 3.1, 3.6)]
    r = srt_align.align_srt_to_words(doc, words, modo_parcial=True, min_coverage=0.5)
    c = r.cues[0]
    assert c.mode == "word_partial"
    ws = {w.text: w for w in c.words}
    assert ws["uno"].start_ms >= 0
    assert ws["dos"].end_ms <= 2500  # antes del primer ancla


def test_una_sola_ancla_en_medio():
    doc = _doc([_cue(1, 0, 4000, "uno dos tres cuatro cinco")])
    words = [_w("tres", 2.0, 2.4)]
    r = srt_align.align_srt_to_words(doc, words, modo_parcial=True, min_coverage=0.2)
    c = r.cues[0]
    assert c.mode == "word_partial"
    assert len(c.words) == 5
    ws = {w.text: w for w in c.words}
    assert (ws["tres"].start_ms, ws["tres"].end_ms) == (2000, 2400)
    for a, b in zip(c.words, c.words[1:], strict=False):
        assert a.end_ms <= b.start_ms


def test_cue_sin_ninguna_ancla_sigue_estatico():
    doc = _doc([_cue(1, 0, 4000, "alfa beta gamma delta")])
    words = [_w("zeta", 0.1, 0.5), _w("omega", 1.0, 1.4)]
    r = srt_align.align_srt_to_words(doc, words, modo_parcial=True, min_coverage=0.0)
    c = r.cues[0]
    assert c.mode == "cue_fallback"
    assert c.words == ()


def test_hueco_insuficiente_cae_a_fallback():
    """Mas tokens sin ancla que milisegundos disponibles: no se inventa timing.

    Cue de 10 ms, 26 tokens, ancla en [0,1]: quedan 9 ms para 25 tokens y el minimo es
    1 ms por token. No cabe => estatico honesto, nunca palabras de duracion cero.
    """
    doc = _doc([_cue(1, 0, 10, "a b c d e f g h i j k l m n o p q r s t u v w x y z")])
    words = [_w("a", 0.0, 0.001)]
    r = srt_align.align_srt_to_words(doc, words, modo_parcial=True, min_coverage=0.0)
    assert r.cues[0].mode == "cue_fallback"


def test_hueco_justo_si_alcanza_interpola():
    """Contraprueba del anterior: con 1 ms por token exacto, si se interpola."""
    doc = _doc([_cue(1, 0, 30, "a b c d e f g h i j k l m n o p q r s t u v w x y z")])
    words = [_w("a", 0.0, 0.001)]
    r = srt_align.align_srt_to_words(doc, words, modo_parcial=True, min_coverage=0.0)
    c = r.cues[0]
    assert c.mode == "word_partial"
    for w in c.words:
        assert w.end_ms > w.start_ms


# ── 3. Contratos agregados ───────────────────────────────────────────────────


def test_resultado_cuenta_las_tres_familias():
    doc = _doc(
        [
            _cue(1, 0, 1000, "hola mundo cruel"),  # completo
            _cue(2, 1000, 5000, "uno dos tres cuatro"),  # parcial
            _cue(3, 5000, 6000, "alfa beta gamma"),  # sin anclas
        ]
    )
    words = _words_simple() + [_w("uno", 1.0, 1.5), _w("cuatro", 4.0, 4.5)] + [_w("zeta", 5.1, 5.5)]
    r = srt_align.align_srt_to_words(doc, words, modo_parcial=True, min_coverage=0.5)
    assert (r.word_aligned, r.word_partial, r.cue_fallback) == (1, 1, 1)
    assert r.n_cues == 3


def test_combinacion_offset_mas_parcial():
    doc = _doc([_cue(1, 0, 4000, "uno dos tres cuatro")])
    words = [_w("uno", 7.0, 7.5), _w("cuatro", 10.0, 10.5)]
    r = srt_align.align_srt_to_words(
        doc, words, offset_ms=7000, modo_parcial=True, min_coverage=0.5
    )
    c = r.cues[0]
    assert c.mode == "word_partial"
    assert (c.start_ms, c.end_ms) == (7000, 11000)
    for w in c.words:
        assert c.start_ms <= w.start_ms and w.end_ms <= c.end_ms
