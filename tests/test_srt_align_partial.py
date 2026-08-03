"""Alineado PARCIAL de cues + offset explicito en el alineador (S38).

Dos cambios, un archivo de contrato:

1. `offset_ms` desplaza el SRT sobre el timeline del video. Sin `offset_ms` la salida es
   byte-identica a la historica.
2. `modo_parcial` hace que el porton por cue HONRE `min_coverage`. Los tokens con ancla usan
   su timing REAL; los que no la tienen se reparten en el hueco entre sus vecinos anclados.
   Un cue sin NINGUNA ancla sigue cayendo a `cue_fallback` estatico honesto.

**Contrato v2 (tras el rechazo visual de K).** El reparto lo hace `srt_eventos` y garantiza:
el primer evento arranca en `cue.start_ms` y el ultimo cierra en `cue.end_ms`; ningun evento
baja de 150 ms; los eventos son contiguos y estrictamente crecientes. Consecuencia directa:
el `end_ms` de una palabra ya NO es el de su ancla, sino el inicio de la siguiente — los
eventos no dejan huecos. Lo que se conserva del ancla es su INICIO.

Sin `modo_parcial` la salida sigue siendo byte-identica a la historica.
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


def _invariantes(cue):
    """D1 + D2 + D3 sobre un cue con palabras: arranque, cierre, minimo y monotonia."""
    ws = cue.words
    assert ws, "un cue animado siempre tiene eventos"
    assert ws[0].start_ms == cue.start_ms, "D1: no arranca en cue.start"
    assert ws[-1].end_ms == cue.end_ms, "D1: no cierra en cue.end"
    for w in ws:
        assert w.end_ms - w.start_ms >= 150, f"D2: evento degenerado {w}"
    for a, b in zip(ws, ws[1:], strict=False):
        assert a.end_ms == b.start_ms, "D3: hueco o solape"
        assert b.start_ms > a.start_ms, "D3: starts no crecientes"


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
    doc = _doc([_cue(1, 4000, 5000, "hola mundo cruel")])
    r = srt_align.align_srt_to_words(doc, _words_simple(), offset_ms=-4000)
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


def _parcial(**kw):
    kw.setdefault("modo_parcial", True)
    kw.setdefault("min_coverage", 0.5)
    return srt_align.align_srt_to_words(_doc_parcial(), _words_parcial(), **kw)


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
    c = _parcial().cues[0]
    assert c.mode == "word_partial"
    assert len(c.words) == 4
    assert [w.text for w in c.words] == ["uno", "dos", "tres", "cuatro"]
    assert c.reason == "interpolacion_parcial"
    _invariantes(c)


def test_tokens_anclados_conservan_su_INICIO_real():
    """El ancla fija el INICIO. El final lo marca el evento siguiente (contigüidad, D3)."""
    ws = {w.text: w for w in _parcial().cues[0].words}
    assert ws["uno"].start_ms == 0
    assert ws["cuatro"].start_ms == 3000, "el ancla real manda sobre el reparto"
    assert ws["uno"].kind == "exact_match"
    assert ws["dos"].kind == "interpolado"


def test_interpolados_se_reparten_en_el_hueco():
    ws = {w.text: w for w in _parcial().cues[0].words}
    # hueco entre el inicio del cue (0) y el ancla de "cuatro" (3000), repartido en 3
    assert 0 < ws["dos"].start_ms < ws["tres"].start_ms < 3000
    assert abs(ws["dos"].start_ms - 1000) <= 5
    assert abs(ws["tres"].start_ms - 2000) <= 5


def test_ultimo_evento_cierra_en_cue_end():
    ws = _parcial().cues[0].words
    assert ws[-1].end_ms == 4000


def test_cue_sin_ninguna_ancla_sigue_estatico():
    doc = _doc([_cue(1, 0, 4000, "alfa beta gamma delta")])
    words = [_w("zeta", 0.1, 0.5), _w("omega", 1.0, 1.4)]
    r = srt_align.align_srt_to_words(doc, words, modo_parcial=True, min_coverage=0.0)
    c = r.cues[0]
    assert c.mode == "cue_fallback"
    assert c.words == ()


# ── 3. Casos de borde (contrato v2, tras el rechazo de K) ────────────────────


def test_anclas_solo_al_inicio():
    doc = _doc([_cue(1, 0, 4000, "uno dos tres cuatro")])
    words = [_w("uno", 0.0, 0.5), _w("dos", 0.6, 1.0)]
    r = srt_align.align_srt_to_words(doc, words, modo_parcial=True, min_coverage=0.5)
    c = r.cues[0]
    assert c.mode == "word_partial"
    _invariantes(c)


def test_anclas_solo_al_final():
    doc = _doc([_cue(1, 0, 4000, "uno dos tres cuatro")])
    words = [_w("tres", 2.5, 3.0), _w("cuatro", 3.1, 3.6)]
    r = srt_align.align_srt_to_words(doc, words, modo_parcial=True, min_coverage=0.5)
    c = r.cues[0]
    assert c.mode == "word_partial"
    _invariantes(c)
    assert c.words[0].start_ms == 0, "D1: arranca en el cue, no en la primera ancla"


def test_una_sola_ancla_en_medio():
    doc = _doc([_cue(1, 0, 4000, "uno dos tres cuatro cinco")])
    words = [_w("tres", 2.0, 2.4)]
    r = srt_align.align_srt_to_words(doc, words, modo_parcial=True, min_coverage=0.2)
    c = r.cues[0]
    assert c.mode == "word_partial"
    assert len(c.words) == 5
    assert {w.text: w for w in c.words}["tres"].start_ms == 2000
    _invariantes(c)


def test_ancla_que_desborda_por_el_FINAL_se_acota():
    """Antes tumbaba el cue entero; ahora el cue manda y el ancla se acota."""
    doc = _doc([_cue(1, 0, 2000, "uno dos tres")])
    words = [_w("uno", 0.0, 0.4), _w("tres", 1.70, 2.28)]
    c = srt_align.align_srt_to_words(doc, words, modo_parcial=True, min_coverage=0.5).cues[0]
    assert c.mode == "word_partial"
    _invariantes(c)


def test_ancla_que_empieza_ANTES_del_cue_ya_no_tumba_el_cue():
    """Regla eliminada (D4): tumbaba 219 cues reales con cobertura de sobra."""
    doc = _doc([_cue(1, 1000, 3000, "uno dos tres")])
    words = [_w("uno", 0.9, 1.3), _w("tres", 2.0, 2.4)]
    c = srt_align.align_srt_to_words(doc, words, modo_parcial=True, min_coverage=0.5).cues[0]
    assert c.mode == "word_partial"
    _invariantes(c)


def test_anclas_solapadas_ya_no_tumban_el_cue():
    doc = _doc([_cue(1, 0, 3000, "uno dos tres")])
    words = [_w("uno", 0.0, 1.5), _w("tres", 1.0, 1.8)]
    c = srt_align.align_srt_to_words(doc, words, modo_parcial=True, min_coverage=0.5).cues[0]
    assert c.mode == "word_partial"
    _invariantes(c)


def test_cue_mas_corto_que_el_minimo_cae_a_estatico_con_razon_real():
    """30 ms no dan ni un evento de 150 ms: estatico, y el `reason` lo dice."""
    doc = _doc([_cue(1, 0, 30, "a b c d e")])
    words = [_w("a", 0.0, 0.001)]
    c = srt_align.align_srt_to_words(doc, words, modo_parcial=True, min_coverage=0.0).cues[0]
    assert c.mode == "cue_fallback"
    assert c.reason == "cue_demasiado_corto"


def test_muchos_tokens_en_poco_tiempo_se_absorben():
    """26 tokens en 900 ms: 6 eventos de 150 ms, ningun token perdido."""
    texto = "a b c d e f g h i j k l m n o p q r s t u v w x y z"
    doc = _doc([_cue(1, 0, 900, texto)])
    words = [_w("a", 0.0, 0.05)]
    c = srt_align.align_srt_to_words(doc, words, modo_parcial=True, min_coverage=0.0).cues[0]
    assert c.mode == "word_partial"
    _invariantes(c)
    assert " ".join(w.text for w in c.words).split() == texto.split(), "ningun token se pierde"


# ── 4. El porton es min_coverage y nada mas (D4) ─────────────────────────────


def test_porton_solo_min_coverage():
    """Mismo cue, dos umbrales: el modo depende SOLO de si la cobertura los alcanza."""
    doc = _doc([_cue(1, 0, 4000, "uno dos tres cuatro")])  # 2/4 = 0.5 de cobertura
    words = _words_parcial()
    bajo = srt_align.align_srt_to_words(doc, words, modo_parcial=True, min_coverage=0.5)
    alto = srt_align.align_srt_to_words(doc, words, modo_parcial=True, min_coverage=0.75)
    assert bajo.cues[0].mode == "word_partial"
    assert alto.cues[0].mode == "cue_fallback"
    assert alto.cues[0].reason == "cobertura_insuficiente", "aqui SI falta cobertura"


def test_reason_no_miente_cuando_sobra_cobertura():
    """El bug que K midio: 293 cues decian `cobertura_insuficiente` con cobertura 0.67-0.89."""
    doc = _doc([_cue(1, 0, 4000, "uno dos tres cuatro")])
    r = srt_align.align_srt_to_words(doc, _words_parcial(), modo_parcial=False, min_coverage=0.5)
    c = r.cues[0]
    assert c.mode == "cue_fallback" and c.coverage >= 0.5
    assert c.reason == "modo_parcial_desactivado", f"reason miente: {c.reason}"


# ── 5. Contratos agregados ───────────────────────────────────────────────────


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


def test_invariantes_en_los_tres_modos():
    """D1 vale para todo cue animado, sea completo o parcial (el estatico ya cubre el cue)."""
    doc = _doc(
        [
            _cue(1, 0, 1000, "hola mundo cruel"),
            _cue(2, 1000, 5000, "uno dos tres cuatro"),
            _cue(3, 5000, 6000, "alfa beta gamma"),
        ]
    )
    words = _words_simple() + [_w("uno", 1.0, 1.5), _w("cuatro", 4.0, 4.5)] + [_w("zeta", 5.1, 5.5)]
    r = srt_align.align_srt_to_words(doc, words, modo_parcial=True, min_coverage=0.5)
    for c in r.cues:
        if c.words:
            _invariantes(c)


def test_combinacion_offset_mas_parcial():
    doc = _doc([_cue(1, 0, 4000, "uno dos tres cuatro")])
    words = [_w("uno", 7.0, 7.5), _w("cuatro", 10.0, 10.5)]
    r = srt_align.align_srt_to_words(
        doc, words, offset_ms=7000, modo_parcial=True, min_coverage=0.5
    )
    c = r.cues[0]
    assert c.mode == "word_partial"
    assert (c.start_ms, c.end_ms) == (7000, 11000)
    _invariantes(c)


def test_min_evento_configurable_desde_la_api():
    doc = _doc([_cue(1, 0, 4000, "uno dos tres cuatro")])
    r = srt_align.align_srt_to_words(
        doc, _words_parcial(), modo_parcial=True, min_coverage=0.5, min_evento_ms=900
    )
    c = r.cues[0]
    for w in c.words:
        assert w.end_ms - w.start_ms >= 900
