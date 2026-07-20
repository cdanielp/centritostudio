"""Tests de phrase spans (F6 esencial, PASO B — pendiente #34).

Contrato pre-firmado (#34, voto arquitecto s30; SPEC_K_CVE.md:144):
- Un span de varias palabras `[strong]esto cambio todo[/strong]` aplica el enfasis a
  CADA palabra del span (no solo al ancla).
- Compatibilidad total con la marca de una palabra (apertura sin cierre = next-word).
- Las marcas manuales quedan EXENTAS de kw_max_por_grupo y de densidad (manual gana).
- Timings derivados de las words reales; nunca se inventa texto.
- Resolucion determinista de solapamientos (span mas corto/interno gana; empate -> big).
- Ninguna marca ([...]) aparece jamas como texto visible (voto #34).
- Sin regresion en la ruta SRT (cue_fallback / texto sin marcas intacto).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import core_ass
import cve
import cve_keywords as ck
import cve_sidecar


def _grupo(palabras: list[str], g_id: int = 0, texto: str | None = None) -> dict:
    t0 = g_id * 10.0
    words = [
        {"text": p, "start": t0 + i * 0.5, "end": t0 + i * 0.5 + 0.4, "line_idx": 0}
        for i, p in enumerate(palabras)
    ]
    return {
        "id": g_id,
        "start": t0,
        "end": t0 + len(palabras) * 0.5,
        "text": texto if texto is not None else " ".join(palabras),
        "words": words,
    }


# ── Parser de spans ──────────────────────────────────────────────────────────


def test_span_cerrado_marca_cada_palabra():
    limpio, marcas, center = ck.parsear_marcas("[strong]esto cambio todo[/strong]")
    assert limpio == "esto cambio todo"
    assert marcas == {0: "strong", 1: "strong", 2: "strong"}
    assert center is False


def test_span_big_cerrado_en_medio():
    limpio, marcas, _c = ck.parsear_marcas("gana [big]diez millones[/big] ya")
    assert limpio == "gana diez millones ya"
    assert marcas == {1: "big", 2: "big"}


def test_span_abierto_sin_cierre_es_next_word():
    # Compatibilidad con la marca de una palabra: apertura sin cierre = solo la siguiente
    limpio, marcas, _c = ck.parsear_marcas("[strong]hola mundo")
    assert limpio == "hola mundo" and marcas == {0: "strong"}


def test_span_sin_marcas_no_toca_nada():
    assert ck.parsear_marcas("hola mundo claro") == ("hola mundo claro", {}, False)


def test_spans_solapados_innermost_gana():
    # Anidado impropio: 'b' cae bajo strong(a,b,c) y big(b); gana el mas corto/interno
    limpio, marcas, _c = ck.parsear_marcas("[strong]a [big]b[/big] c[/strong]")
    assert limpio == "a b c"
    assert marcas == {0: "strong", 1: "big", 2: "strong"}


def test_spans_duplicados_ambos_marcados():
    limpio, marcas, _c = ck.parsear_marcas("[strong]uno[/strong] [strong]uno[/strong]")
    assert limpio == "uno uno"
    assert marcas == {0: "strong", 1: "strong"}


def test_span_cierre_sin_apertura_se_ignora_sin_romper():
    limpio, marcas, center = ck.parsear_marcas("hola todo[/strong]")
    assert limpio == "hola todo" and marcas == {} and center is False
    assert "[" not in limpio and "]" not in limpio


def test_center_cerrado_sigue_siendo_flag_de_grupo():
    limpio, marcas, center = ck.parsear_marcas("[center]la frase principal[/center]")
    assert limpio == "la frase principal" and center is True and marcas == {}


# ── Motor: span marca cada palabra, exento de 1-por-grupo y densidad ──────────


def test_engine_span_marca_cada_palabra():
    g = _grupo(["esto", "cambio", "todo"], texto="[strong]esto cambio todo[/strong]")
    plan = cve.resolve_preset("keyword_punch")
    out = cve.aplicar_engine([g], plan, 1080, 1920)
    assert [w.get("is_keyword") for w in out[0]["words"]] == [True, True, True]
    assert all(w.get("kw_regla") == "manual" for w in out[0]["words"])


def test_engine_span_exento_de_densidad():
    # densidad baja no recorta manuales: las 3 palabras del span quedan marcadas
    g = _grupo(["uno", "dos", "tres"], texto="[strong]uno dos tres[/strong]")
    plan = cve.resolve_preset("keyword_punch")  # densidad default "baja"
    out = cve.aplicar_engine([g], plan, 1080, 1920)
    assert sum(bool(w.get("is_keyword")) for w in out[0]["words"]) == 3


def test_engine_span_manual_gana_a_auto_en_el_grupo():
    # 500/pesos dispararian reglas auto, pero el span manual gana y suprime el auto
    g = _grupo(["gana", "500", "pesos", "rapido"], texto="[strong]gana 500 pesos[/strong] rapido")
    plan = cve.resolve_preset("keyword_punch")
    out = cve.aplicar_engine([g], plan, 1080, 1920)
    flags = [bool(w.get("is_keyword")) for w in out[0]["words"]]
    assert flags == [True, True, True, False]
    assert all(out[0]["words"][i]["kw_regla"] == "manual" for i in (0, 1, 2))


def test_engine_span_timings_reales_sin_inventar_texto():
    g = _grupo(["esto", "cambio", "todo"], texto="[big]esto cambio todo[/big]")
    starts = [w["start"] for w in g["words"]]
    plan = cve.resolve_preset("keyword_punch")
    out = cve.aplicar_engine([g], plan, 1080, 1920)
    assert [w["text"] for w in out[0]["words"]] == ["esto", "cambio", "todo"]
    assert [w["start"] for w in out[0]["words"]] == starts  # timings intactos


def test_engine_span_fit_no_desaparece_texto():
    # Palabra larguisima en video angosto: el punch se desactiva, el texto NUNCA se pierde
    larga = "supercalifragilisticoexpialidoso"
    g = _grupo([larga, "ya"], texto=f"[big]{larga} ya[/big]")
    plan = cve.resolve_preset("keyword_punch")
    out = cve.aplicar_engine([g], plan, 200, 400)  # angosto a proposito
    assert out[0]["words"][0]["text"] == larga  # texto intacto
    assert out[0]["words"][0].get("is_keyword") is True


def test_engine_marcas_span_jamas_visibles_en_ass(tmp_path):
    g = _grupo(["gana", "todo", "ya"], texto="[strong]gana todo[/strong] ya")
    plan = cve.resolve_preset("keyword_punch")
    out = cve.aplicar_engine([g], plan, 1080, 1920)
    ass = tmp_path / "span.ass"
    core_ass.build_ass(out, 1080, 1920, plan.style_cfg, ass)
    contenido = ass.read_text(encoding="utf-8")
    for marca in ("[strong]", "[/strong]", "[big]", "[/big]"):
        assert marca not in contenido
    bajo = contenido.lower()  # el estilo hormozi rota a mayusculas
    assert "gana" in bajo and "todo" in bajo and "ya" in bajo


# ── Sidecar {stem}_keywords.json: frase = span (cada palabra) ─────────────────


def test_sidecar_frase_marca_cada_palabra():
    grupos = [_grupo(["esto", "sin", "costo", "extra"], 0)]
    cands = ck.candidatos_manuales(grupos, [{"frase": "sin costo"}])
    assert cands == [
        (0, 1, ck.SCORE_MANUAL, "manual"),
        (0, 2, ck.SCORE_MANUAL, "manual"),
    ]


def test_sidecar_frase_sin_match_no_marca():
    grupos = [_grupo(["hola", "mundo"], 0)]
    assert ck.candidatos_manuales(grupos, [{"frase": "no existe"}]) == []


def test_sidecar_frase_big_marca_cada_palabra_big():
    grupos = [_grupo(["mira", "sin", "costo"], 0)]
    cands = ck.candidatos_manuales(grupos, [{"frase": "sin costo", "intensidad": "big"}])
    assert cands == [
        (0, 1, ck.SCORE_MANUAL, "manual_big"),
        (0, 2, ck.SCORE_MANUAL, "manual_big"),
    ]


# ── Sin regresion SRT ─────────────────────────────────────────────────────────


def test_srt_texto_sin_marcas_no_se_marca():
    # Un cue SRT (texto autoritativo, sin marcas) no gana keywords espurias
    g = _grupo(["hola", "esto", "es", "un", "cue"], texto="hola esto es un cue")
    plan = cve.resolve_preset("clean_podcast")  # keywords off
    out = cve.aplicar_engine([g], plan, 1080, 1920)
    assert all(not w.get("is_keyword") for w in out[0]["words"])


def test_srt_cue_fallback_intacto_con_engine(tmp_path):
    g = {
        "id": 0,
        "start": 0.0,
        "end": 2.0,
        "text": "cue completo",
        "timing_mode": "cue_fallback",
        "words": [
            {"text": "cue", "start": 0.0, "end": 1.0, "line_idx": 0},
            {"text": "completo", "start": 1.0, "end": 2.0, "line_idx": 0},
        ],
    }
    plan = cve.resolve_preset("clean_podcast")
    out = cve.aplicar_engine([g], plan, 1080, 1920)
    ass = tmp_path / "cue.ass"
    core_ass.build_ass(out, 1080, 1920, plan.style_cfg, ass)
    assert ass.exists() and "cue completo" in ass.read_text(encoding="utf-8")


# ── Sidecar de seleccion saneado ─────────────────────────────────────────────


def test_sidecar_seleccion_span_saneado():
    g = _grupo(["esto", "cambio", "todo"], texto="[strong]esto cambio todo[/strong]")
    plan = cve.resolve_preset("keyword_punch")
    out = cve.aplicar_engine([g], plan, 1080, 1920)
    data = cve_sidecar.construir_seleccion(out, plan)
    kws = data["keywords"]
    assert len(kws) == 3
    for kw in kws:
        assert set(kw) == {"palabra", "timestamp", "grupo", "frase", "regla", "fuente"}
        assert kw["fuente"] == "manual"
        assert not any(k in kw for k in ("path", "ruta", "file", "archivo"))
    # timestamps = starts reales de las words (no inventados)
    assert [kw["timestamp"] for kw in kws] == [w["start"] for w in g["words"]]


# ── Puntuacion en spans (P2 revision PR #23) ──────────────────────────────────
# La puntuacion pegada a una palabra marcada debe conservarse EN esa palabra y NO
# contar como palabra extra (si no, _consumir_marcas descarta la marca por conteo).


def test_span_big_con_coma_final():
    assert ck.parsear_marcas("[big]gratis[/big],") == ("gratis,", {0: "big"}, False)


def test_span_strong_con_punto_final():
    limpio, marcas, _c = ck.parsear_marcas("[strong]sin costo[/strong].")
    assert limpio == "sin costo." and marcas == {0: "strong", 1: "strong"}


def test_span_con_interrogacion():
    limpio, marcas, _c = ck.parsear_marcas("[strong]esto funciona[/strong]?")
    assert limpio == "esto funciona?" and marcas == {0: "strong", 1: "strong"}


def test_span_con_signos_de_apertura_y_cierre():
    limpio, marcas, _c = ck.parsear_marcas("¡[big]ahora mismo[/big]!")
    assert limpio == "¡ahora mismo!" and marcas == {0: "big", 1: "big"}


def test_span_entre_comillas():
    limpio, marcas, _c = ck.parsear_marcas('"[strong]texto marcado[/strong]"')
    assert limpio == '"texto marcado"' and marcas == {0: "strong", 1: "strong"}


def test_span_seguido_de_dos_signos():
    limpio, marcas, _c = ck.parsear_marcas("[big]ya[/big]?!")
    assert limpio == "ya?!" and marcas == {0: "big"}


def test_span_dentro_de_frase_normal():
    limpio, marcas, _c = ck.parsear_marcas("mira [strong]esto clave[/strong] ahora")
    assert limpio == "mira esto clave ahora" and marcas == {1: "strong", 2: "strong"}


def test_marca_una_palabra_historica_con_coma():
    # Apertura sin cierre + coma: marca esa palabra, conserva la coma
    assert ck.parsear_marcas("[strong]gratis,") == ("gratis,", {0: "strong"}, False)


def test_span_unicode_y_acentos():
    limpio, marcas, _c = ck.parsear_marcas("[big]café años[/big].")
    assert limpio == "café años." and marcas == {0: "big", 1: "big"}


def test_center_con_span_y_puntuacion():
    limpio, marcas, center = ck.parsear_marcas("[center][strong]la clave[/strong].")
    assert limpio == "la clave." and marcas == {0: "strong", 1: "strong"} and center is True


def test_texto_sin_marcas_con_puntuacion_intacto():
    # Sin marcas: la puntuacion no se toca y no hay marcas espurias
    assert ck.parsear_marcas("hola, mundo.") == ("hola, mundo.", {}, False)


# ── El bug real: la marca NO se pierde por conteo (aplicar_engine) ─────────────


def test_engine_span_con_puntuacion_no_se_descarta():
    # words con puntuacion pegada (como las entrega whisper): la marca sobrevive
    g = _grupo(["sin", "costo."], texto="[strong]sin costo[/strong].")
    plan = cve.resolve_preset("keyword_punch")
    out = cve.aplicar_engine([g], plan, 1080, 1920)
    assert [w.get("is_keyword") for w in out[0]["words"]] == [True, True]


def test_engine_marca_una_palabra_con_coma_no_se_descarta():
    g = _grupo(["gana", "gratis,"], texto="gana [big]gratis[/big],")
    plan = cve.resolve_preset("keyword_punch")
    out = cve.aplicar_engine([g], plan, 1080, 1920)
    assert out[0]["words"][1].get("is_keyword") is True
    assert out[0]["words"][1]["kw_regla"] == "manual_big"
