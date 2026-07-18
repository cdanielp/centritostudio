"""test_srt_align.py — Contrato de la alineacion SRT<->timings (S36-B, D36B-1/2/3).

Sin red, sin GPU, sin FFmpeg. El TEXTO del SRT es la autoridad; Whisper solo aporta
timings. No se inventan timings word-by-word: los cues sin cobertura total caen a
fallback honesto. Solo texto SINTETICO.
"""

from __future__ import annotations

import copy

from srt_align import (
    AlignedCue,
    align_srt_to_words,
    normalize_token,
)
from srt_import import parse_srt_text


def _cue_doc(text: str, start: str = "00:00:00,000", end: str = "00:00:02,000"):
    return parse_srt_text(f"1\n{start} --> {end}\n{text}\n")


def _tw(*triples):
    return [{"w": w, "s": s, "e": e, "prob": 1.0} for (w, s, e) in triples]


def _one(result) -> AlignedCue:
    assert len(result.cues) == 1
    return result.cues[0]


# ============================== NORMALIZACION ==============================


def test_normalize_casefold():
    assert normalize_token("HOLA") == normalize_token("hola")


def test_normalize_acentos():
    assert normalize_token("café") == normalize_token("cafe")


def test_normalize_puntuacion_pegada():
    assert normalize_token("hola,") == normalize_token("hola")


def test_normalize_signos_apertura():
    assert normalize_token("¿café?") == normalize_token("cafe")


def test_normalize_numero_se_conserva():
    assert normalize_token("2024") == "2024"


def test_normalize_emoji_se_conserva():
    assert "😀" in normalize_token("😀")


# ============================== MATCH EXACTO / CASE / PUNTUACION ==============================


def test_match_exacto():
    doc = _cue_doc("hola mundo")
    r = align_srt_to_words(doc, _tw(("hola", 0.0, 0.5), ("mundo", 0.6, 1.0)))
    c = _one(r)
    assert c.mode == "word_aligned"
    assert [w.text for w in c.words] == ["hola", "mundo"]
    assert all(w.kind == "exact_match" for w in c.words)
    assert c.coverage == 1.0


def test_mayusculas_alinean():
    doc = _cue_doc("Hola MUNDO")
    c = _one(align_srt_to_words(doc, _tw(("hola", 0.0, 0.5), ("mundo", 0.6, 1.0))))
    assert c.mode == "word_aligned"
    assert [w.text for w in c.words] == ["Hola", "MUNDO"]  # texto ORIGINAL preservado


def test_puntuacion_corregida_alinea():
    doc = _cue_doc("hola, mundo.")
    c = _one(align_srt_to_words(doc, _tw(("hola", 0.0, 0.5), ("mundo", 0.6, 1.0))))
    assert c.mode == "word_aligned"
    assert [w.text for w in c.words] == ["hola,", "mundo."]  # signos preservados


def test_signos_apertura_cierre():
    doc = _cue_doc("¿Café listo?")
    c = _one(align_srt_to_words(doc, _tw(("cafe", 0.0, 0.5), ("listo", 0.6, 1.0))))
    assert c.mode == "word_aligned"
    assert c.words[0].text == "¿Café"


def test_acentos_preservados_en_output():
    doc = _cue_doc("acción rápida")
    c = _one(align_srt_to_words(doc, _tw(("accion", 0.0, 0.5), ("rapida", 0.6, 1.0))))
    assert [w.text for w in c.words] == ["acción", "rápida"]


# ==================== SUSTITUCION / INSERCION / ELIMINACION ====================


def test_sustitucion_1a1():
    doc = _cue_doc("el gato negro")
    c = _one(
        align_srt_to_words(doc, _tw(("el", 0.0, 0.3), ("pato", 0.4, 0.7), ("negro", 0.8, 1.1)))
    )
    assert c.mode == "word_aligned"
    assert c.words[1].text == "gato"  # SRT manda el texto
    assert c.words[1].kind == "substitution_match"


def test_insercion_en_srt_degrada_a_fallback():
    doc = _cue_doc("hola gran mundo")
    c = _one(align_srt_to_words(doc, _tw(("hola", 0.0, 0.5), ("mundo", 0.6, 1.0))))
    assert c.mode == "cue_fallback"  # "gran" no tiene ancla real -> no se inventa timing
    assert c.text == "hola gran mundo"


def test_eliminacion_whisper_extra_no_rompe():
    doc = _cue_doc("hola mundo")
    c = _one(
        align_srt_to_words(doc, _tw(("hola", 0.0, 0.5), ("gran", 0.55, 0.8), ("mundo", 0.9, 1.2)))
    )
    assert c.mode == "word_aligned"
    assert [w.text for w in c.words] == ["hola", "mundo"]


def test_palabra_repetida():
    doc = _cue_doc("muy muy bien")
    c = _one(align_srt_to_words(doc, _tw(("muy", 0.0, 0.3), ("muy", 0.4, 0.7), ("bien", 0.8, 1.1))))
    assert c.mode == "word_aligned"
    assert [w.text for w in c.words] == ["muy", "muy", "bien"]


def test_no_reutiliza_timing_word_dos_veces():
    doc = _cue_doc("sí sí")
    # solo hay UNA timing word "si": no puede anclar las dos -> fallback (no doble uso)
    c = _one(align_srt_to_words(doc, _tw(("si", 0.0, 0.5))))
    assert c.mode == "cue_fallback"
    assert c.n_matched == 1


def test_numeros_alinean():
    doc = _cue_doc("son 3 gatos")
    c = _one(align_srt_to_words(doc, _tw(("son", 0.0, 0.3), ("3", 0.4, 0.6), ("gatos", 0.7, 1.0))))
    assert c.mode == "word_aligned"
    assert c.words[1].text == "3"


def test_emoji_preservado_en_fallback():
    doc = _cue_doc("hola 😀 mundo")
    c = _one(align_srt_to_words(doc, _tw(("hola", 0.0, 0.5), ("mundo", 0.6, 1.0))))
    assert "😀" in c.text  # el emoji visible nunca se pierde


# ============================== VENTANAS / MULTILINEA ==============================


def test_cue_multilinea_conserva_line_idx():
    doc = _cue_doc("linea uno\nlinea dos")
    c = _one(
        align_srt_to_words(
            doc,
            _tw(
                ("linea", 0.0, 0.3),
                ("uno", 0.4, 0.6),
                ("linea", 0.7, 0.9),
                ("dos", 1.0, 1.2),
            ),
        )
    )
    assert c.mode == "word_aligned"
    assert [w.line_idx for w in c.words] == [0, 0, 1, 1]


def test_cue_sin_words_en_ventana_fallback():
    doc = _cue_doc("hola mundo", end="00:00:01,000")
    # timing words muy despues del cue -> ventana vacia -> fallback
    c = _one(align_srt_to_words(doc, _tw(("hola", 50.0, 50.5), ("mundo", 50.6, 51.0))))
    assert c.mode == "cue_fallback"


def test_words_fuera_del_cue_se_ignoran():
    doc = _cue_doc("hola mundo", end="00:00:02,000")
    tw = _tw(("basura", 30.0, 30.5), ("hola", 0.0, 0.5), ("mundo", 0.6, 1.0))
    c = _one(align_srt_to_words(doc, tw))
    assert c.mode == "word_aligned" and c.n_tokens == 2


def test_orden_monotonico():
    doc = _cue_doc("uno dos tres")
    c = _one(align_srt_to_words(doc, _tw(("uno", 0.0, 0.4), ("dos", 0.5, 0.9), ("tres", 1.0, 1.4))))
    starts = [w.start_ms for w in c.words]
    assert starts == sorted(starts)
    for w in c.words:
        assert w.end_ms > w.start_ms


# ============================== DETERMINISMO / COBERTURA / THRESHOLD ==============================


def test_tie_breaking_determinista():
    doc = _cue_doc("a a a")
    tw = _tw(("a", 0.0, 0.3), ("a", 0.4, 0.7), ("a", 0.8, 1.1))
    r1 = align_srt_to_words(doc, tw)
    r2 = align_srt_to_words(doc, tw)
    assert r1 == r2


def test_cobertura_total():
    doc = _cue_doc("hola mundo")
    r = align_srt_to_words(doc, _tw(("hola", 0.0, 0.5), ("mundo", 0.6, 1.0)))
    assert r.coverage == 1.0 and r.word_aligned == 1 and r.cue_fallback == 0


def test_threshold_no_inventa_timing():
    doc = _cue_doc("hola gran mundo")
    # aun con umbral bajo, un token sin ancla NO se inventa: sigue en fallback
    c = _one(
        align_srt_to_words(doc, _tw(("hola", 0.0, 0.5), ("mundo", 0.6, 1.0)), min_coverage=0.5)
    )
    assert c.mode == "cue_fallback"


def test_fallback_conserva_texto_y_tiempos():
    doc = _cue_doc("texto imposible", start="00:00:01,000", end="00:00:03,000")
    c = _one(align_srt_to_words(doc, _tw(("otra", 90.0, 90.5))))
    assert c.mode == "cue_fallback"
    assert c.text == "texto imposible"
    assert c.start_ms == 1000 and c.end_ms == 3000


def test_no_equal_spacing():
    # dos cues, uno aligned con tiempos reales distintos, otro fallback sin words
    doc = parse_srt_text(
        "1\n00:00:00,000 --> 00:00:02,000\nhola mundo\n\n"
        "2\n00:00:03,000 --> 00:00:05,000\ntexto sin audio\n"
    )
    r = align_srt_to_words(doc, _tw(("hola", 0.0, 0.5), ("mundo", 1.5, 1.9)))
    aligned = r.cues[0]
    # los word starts reflejan los timings reales, NO una division uniforme del cue
    assert aligned.words[0].start_ms == 0 and aligned.words[1].start_ms == 1500
    assert r.cues[1].mode == "cue_fallback"


# ============ INMUTABILIDAD / SERIALIZACION / PROVENANCE ============


def test_entrada_no_mutada():
    doc = _cue_doc("hola mundo")
    tw = _tw(("hola", 0.0, 0.5), ("mundo", 0.6, 1.0))
    tw_copia = copy.deepcopy(tw)
    align_srt_to_words(doc, tw)
    assert tw == tw_copia


def test_documento_largo_acotado():
    # 200 cues x 3 tokens: debe terminar rapido y ser determinista
    bloques = []
    tw = []
    for i in range(200):
        s = i * 2
        a = f"00:{s // 60:02d}:{s % 60:02d},000"
        b = f"00:{(s + 1) // 60:02d}:{(s + 1) % 60:02d},000"
        bloques.append(f"{i + 1}\n{a} --> {b}\nuno dos tres\n")
        tw += _tw(("uno", s + 0.0, s + 0.3), ("dos", s + 0.4, s + 0.6), ("tres", s + 0.7, s + 0.9))
    doc = parse_srt_text("\n".join(bloques))
    r = align_srt_to_words(doc, tw)
    assert r.n_cues == 200 and r.word_aligned == 200


def test_tiempos_int_ms():
    doc = _cue_doc("hola mundo")
    c = _one(align_srt_to_words(doc, _tw(("hola", 0.0, 0.5), ("mundo", 0.6, 1.0))))
    for w in c.words:
        assert isinstance(w.start_ms, int) and isinstance(w.end_ms, int)


def test_provenance_exacta():
    doc = _cue_doc("el gato")
    c = _one(align_srt_to_words(doc, _tw(("el", 0.0, 0.3), ("pato", 0.4, 0.7))))
    assert c.words[0].kind == "exact_match"
    assert c.words[1].kind == "substitution_match"


def test_source_sha256_propagado():
    doc = _cue_doc("hola mundo")
    r = align_srt_to_words(doc, _tw(("hola", 0.0, 0.5), ("mundo", 0.6, 1.0)))
    assert r.source_sha256 == doc.source_sha256 and len(r.source_sha256) == 64


def test_timing_words_vacio_todo_fallback():
    doc = _cue_doc("hola mundo")
    r = align_srt_to_words(doc, [])
    assert r.word_aligned == 0 and r.cue_fallback == 1


# ============ S36-B ENDURECIMIENTO: substitution conservador + timestamps ============


def test_tres_palabras_no_relacionadas_fallback():
    # igual numero de tokens pero texto arbitrario: NO debe alcanzar cobertura 1.0
    doc = _cue_doc("gatos verdes corren")
    c = _one(
        align_srt_to_words(
            doc, _tw(("lunes", 0.0, 0.3), ("martes", 0.4, 0.7), ("miercoles", 0.8, 1.1))
        )
    )
    assert c.mode == "cue_fallback"
    assert c.reason == "solo_sustituciones_sin_ancla_exacta"
    assert c.n_rejected_sub == 3


def test_un_token_distinto_fallback():
    doc = _cue_doc("hola")
    c = _one(align_srt_to_words(doc, _tw(("adios", 0.0, 0.5))))
    assert c.mode == "cue_fallback"  # sin ancla exacta, no puede ser substitution


def test_todas_sustituciones_fallback():
    doc = _cue_doc("casa roja")  # cosa/rojo son similares pero NO hay ningun exact_match
    c = _one(align_srt_to_words(doc, _tw(("cosa", 0.0, 0.4), ("rojo", 0.5, 0.9))))
    assert c.mode == "cue_fallback"
    assert c.n_exact == 0


def test_sustitucion_similar_con_ancla_exacta_word_aligned():
    doc = _cue_doc("hola munda")  # "munda" ~ "mundo" (sim alta) + ancla exacta "hola"
    c = _one(align_srt_to_words(doc, _tw(("hola", 0.0, 0.4), ("mundo", 0.5, 0.9))))
    assert c.mode == "word_aligned"
    assert c.words[1].kind == "substitution_match"
    assert c.words[1].text == "munda"  # texto del SRT, no de Whisper


def test_sustitucion_poco_similar_con_ancla_fallback():
    doc = _cue_doc("hola xyzzyq")  # segundo token no se parece a "planeta"
    c = _one(align_srt_to_words(doc, _tw(("hola", 0.0, 0.4), ("planeta", 0.5, 0.9))))
    assert c.mode == "cue_fallback"  # la sustitucion se rechaza -> cobertura incompleta
    assert c.n_rejected_sub == 1
    assert c.reason == "sustitucion_poco_similar"


def test_timestamps_exactos_preservados():
    doc = _cue_doc("uno dos")
    c = _one(align_srt_to_words(doc, _tw(("uno", 0.123, 0.456), ("dos", 0.789, 1.111))))
    assert (c.words[0].start_ms, c.words[0].end_ms) == (123, 456)
    assert (c.words[1].start_ms, c.words[1].end_ms) == (789, 1111)


def test_timestamps_no_monotonicos_fallback():
    # "uno" corto y tardio, "dos" largo y temprano: al anclar, el start decrece -> fallback
    doc = _cue_doc("uno dos", end="00:00:08,000")
    c = _one(align_srt_to_words(doc, _tw(("uno", 3.0, 3.1), ("dos", 0.0, 7.0))))
    assert c.mode == "cue_fallback"
    assert c.reason == "non_monotonic_timings"


def test_ningun_mas_uno_ms():
    # timing word con e==s: end no se empuja a s+1; el cue cae a fallback honesto
    doc = _cue_doc("uno dos")
    c = _one(align_srt_to_words(doc, _tw(("uno", 1.0, 1.0), ("dos", 1.2, 1.5))))
    assert c.mode == "cue_fallback"
    assert c.reason == "non_monotonic_timings"


def test_ninguna_timing_word_reutilizada_dos_cues():
    # una sola "hola" no puede anclar dos cues distintos
    doc = parse_srt_text(
        "1\n00:00:00,000 --> 00:00:01,000\nhola\n\n2\n00:00:01,000 --> 00:00:02,000\nhola\n"
    )
    r = align_srt_to_words(doc, _tw(("hola", 0.2, 0.6)))
    modes = [c.mode for c in r.cues]
    assert modes.count("word_aligned") == 1 and modes.count("cue_fallback") == 1


def test_agregados_provenance_en_result():
    doc = _cue_doc("hola munda")
    r = align_srt_to_words(doc, _tw(("hola", 0.0, 0.4), ("mundo", 0.5, 0.9)))
    assert r.n_exact == 1 and r.n_substitution == 1 and r.n_rejected_sub == 0
