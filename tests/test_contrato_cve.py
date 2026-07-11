"""Tests de contrato del caption_viral_engine (F6, s29).

Cubren: resolucion de presets (fail-safe), fallback total a captions simples,
deteccion determinista de keywords, marcas manuales tolerantes, fit de escala,
y extensiones aditivas del motor ASS (punch_scale por palabra + glow, default off).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import core_ass
import cve
import cve_keywords as ck
from styles import get_style


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


# ─────────────────────────────────────────────────────────────────────────────
# Resolucion de presets
# ─────────────────────────────────────────────────────────────────────────────


def test_presets_v1_resuelven():
    assert cve.list_presets() == [
        "clean_podcast",
        "karaoke_highlight",
        "keyword_punch",
        "viral_bounce",
    ]
    for nombre in cve.list_presets():
        plan = cve.resolve_preset(nombre)
        assert plan.preset == nombre
        assert plan.style_cfg.name in {"clean", "hormozi", "karaoke"}


def test_preset_desconocido_error_accionable():
    with pytest.raises(ValueError, match="Opciones"):
        cve.resolve_preset("mega_viral")


def test_intensidad_invalida_cae_a_la_del_preset():
    # keyword_punch default calibrado (D21) = clean (130, sin glow, densidad baja)
    plan = cve.resolve_preset("keyword_punch", "explosiva")
    assert plan.kw_glow is False
    assert plan.kw_punch_scale == 130
    assert plan.kw_densidad == "baja"


def test_keyword_punch_calibrado_d21():
    # Default sobrio: 130 + densidad baja; 145+glow sigue disponible como opcion fuerte
    plan = cve.resolve_preset("keyword_punch")
    assert plan.kw_punch_scale == 130 and plan.kw_glow is False
    assert plan.kw_densidad == "baja"
    fuerte = cve.resolve_preset("keyword_punch", "viral", "alta")
    assert fuerte.kw_punch_scale == 145 and fuerte.kw_glow is True
    assert fuerte.kw_densidad == "alta"
    # densidad invalida cae a la del preset (fail-safe por campo)
    assert cve.resolve_preset("keyword_punch", None, "turbo").kw_densidad == "baja"


def test_matriz_intensidades():
    minimal = cve.resolve_preset("keyword_punch", "minimal")
    assert minimal.style_cfg.pop_scale == pytest.approx(1.0)  # pop off
    assert minimal.kw_glow is False
    assert minimal.kw_punch_scale == ck.KW_SCALE_BASE  # sin punch especial
    clean = cve.resolve_preset("keyword_punch", "clean")
    assert clean.kw_glow is False  # glow solo en viral
    assert clean.kw_punch_scale == 130  # POP_LEVELS medio
    viral = cve.resolve_preset("keyword_punch", "viral")
    assert viral.kw_glow is True and viral.style_cfg.kw_glow is True
    assert viral.kw_punch_scale == 145  # POP_LEVELS fuerte


def test_clean_podcast_envuelve_clean_sin_keywords():
    plan = cve.resolve_preset("clean_podcast")
    assert plan.style_cfg.name == "clean"
    assert plan.keywords_mode == "off"
    grupos = [_grupo(["hola", "mundo"])]
    assert cve.aplicar_engine(grupos, plan, 1080, 1920) == grupos


def test_viral_bounce_envuelve_hormozi_con_rebote():
    plan = cve.resolve_preset("viral_bounce")
    assert plan.style_cfg.name == "hormozi"
    assert plan.style_cfg.pop_scale == pytest.approx(1.08)  # D20
    assert plan.style_cfg.overshoot is True
    assert plan.keywords_mode == "brain"


# ─────────────────────────────────────────────────────────────────────────────
# karaoke_highlight (S30): envoltura del modo karaoke + past color + fallback timing
# ─────────────────────────────────────────────────────────────────────────────


def test_karaoke_highlight_resuelve():
    plan = cve.resolve_preset("karaoke_highlight")
    assert plan.style_cfg.name == "karaoke"
    assert plan.style_cfg.animation_type == "karaoke"
    assert plan.style_cfg.karaoke_past_color == "&H00FFFF00"  # dichas quedan marcadas
    assert plan.keywords_mode == "off"  # sobrio: el karaoke ES el enfasis


def test_karaoke_past_color_marca_las_dichas():
    plan = cve.resolve_preset("karaoke_highlight")
    gw = _grupo(["una", "dos", "tres"])["words"]
    txt = core_ass._word_event_text(gw, 1, plan.style_cfg)  # activa: "dos"
    pasada, activa, futura = txt.split(" ")
    assert "\\c&H00FFFF00" in pasada  # ya dicha: marcada con past color
    assert "\\kf" in activa  # activa: relleno progresivo
    assert futura == "tres"  # siguiente: color base, sin tags


def test_karaoke_sin_past_color_byte_identico():
    # El ESTILO karaoke clasico (sin past color) conserva su salida historica exacta
    cfg = get_style("karaoke")
    assert cfg.karaoke_past_color is None
    gw = _grupo(["una", "dos", "tres"])["words"]
    txt = core_ass._word_event_text(gw, 1, cfg)
    pasada, activa, futura = txt.split(" ")
    assert pasada == "una" and futura == "tres"  # sin tags nuevos
    assert "\\kf" in activa


def test_karaoke_past_secundario_es_el_primario(tmp_path):
    # Con past color, el SecondaryColour del .ass = primario (futuras EN BASE, no rojas);
    # el estilo karaoke clasico conserva el default (byte-identico, aprobado en s1).
    import pysubs2

    plan = cve.resolve_preset("karaoke_highlight")
    g = _grupo(["una", "dos"])
    con = tmp_path / "con.ass"
    core_ass.build_ass([g], 1080, 1920, plan.style_cfg, con)
    estilo = pysubs2.load(str(con)).styles["Default"]
    assert (estilo.secondarycolor.r, estilo.secondarycolor.g, estilo.secondarycolor.b) == (
        255,
        255,
        255,
    )  # primario blanco
    sin = tmp_path / "sin.ass"
    core_ass.build_ass([g], 1080, 1920, get_style("karaoke"), sin)
    clasico = pysubs2.load(str(sin)).styles["Default"]
    assert clasico.secondarycolor == pysubs2.SSAStyle().secondarycolor  # default intacto


def test_karaoke_fallback_sin_timing_cae_a_highlight():
    plan = cve.resolve_preset("karaoke_highlight")
    sin_timing = [{"id": 0, "text": "hola mundo", "words": [{"text": "hola"}, {"text": "mundo"}]}]
    ajustado = cve.ajustar_plan_a_groups(plan, sin_timing)
    assert ajustado.style_cfg.animation_type == "highlight"  # captions simples: jamas sin captions
    assert ajustado.style_cfg.karaoke_past_color is None


def test_karaoke_con_timing_plan_intacto():
    plan = cve.resolve_preset("karaoke_highlight")
    con_timing = [_grupo(["hola", "mundo"])]
    assert cve.ajustar_plan_a_groups(plan, con_timing) is plan


def test_ajustar_plan_no_toca_presets_no_karaoke():
    plan = cve.resolve_preset("keyword_punch")
    sin_timing = [{"id": 0, "text": "x", "words": [{"text": "x"}]}]
    assert cve.ajustar_plan_a_groups(plan, sin_timing) is plan


# ─────────────────────────────────────────────────────────────────────────────
# Studio (S30): /api/presets + ruta de preset del worker de render
# ─────────────────────────────────────────────────────────────────────────────


def test_info_presets_contrato():
    infos = {i["id"]: i for i in cve.info_presets()}
    assert sorted(infos) == cve.list_presets()
    assert infos["keyword_punch"]["usa_brain"] is True
    assert infos["viral_bounce"]["usa_brain"] is True
    assert infos["clean_podcast"]["usa_brain"] is False
    assert infos["karaoke_highlight"]["usa_keywords"] is False
    assert infos["keyword_punch"]["intensidad_default"] == "clean"  # calibracion D21


def test_api_presets_shape():
    import app as studio

    data = studio.list_presets_cve()
    assert [p["id"] for p in data["presets"]] == cve.list_presets()
    assert all(p.get("label") for p in data["presets"])
    assert [i["id"] for i in data["intensidades"]] == ["minimal", "clean", "viral"]


def test_resolver_preset_seguro_failsafe():
    # Fuente unica CLI+Studio (regla #10): invalido -> (None, aviso accionable)
    plan, aviso = cve.resolver_preset_seguro("karaoke_highlight", "clean")
    assert aviso is None and plan.preset == "karaoke_highlight"
    plan, aviso = cve.resolver_preset_seguro("inexistente", None)
    assert plan is None and "Preset no resuelto" in aviso
    assert cve.resolver_preset_seguro(None, None) == (None, None)


def test_aplicar_preset_sin_brain_avisa_pero_rinde(tmp_path):
    grupos = [_grupo(["gana", "500", "pesos"])]
    plan, _ = cve.resolver_preset_seguro("keyword_punch", "viral")
    brain_inexistente = tmp_path / "nadie.brain.json"
    out, plan2, aviso = cve.aplicar_preset(grupos, plan, brain_inexistente, 1080, 1920)
    assert aviso and "brain" in aviso  # regla 16: el aviso lo dice
    assert any(w.get("is_keyword") for w in out[0]["words"])  # reglas R1-R7 rinden igual


def test_tag_variante_consistente_cli_studio():
    assert cve.tag_variante("karaoke_highlight", None) == "_karaoke_highlight"
    assert cve.tag_variante("keyword_punch", "viral") == "_keyword_punch_viral"
    assert cve.tag_variante("keyword_punch", "clean", "media") == "_keyword_punch_clean_media"


# ─────────────────────────────────────────────────────────────────────────────
# Fallback total (nivel 3: engine falla -> grupos originales)
# ─────────────────────────────────────────────────────────────────────────────


def test_engine_falla_devuelve_grupos_originales():
    plan = cve.resolve_preset("keyword_punch")
    rotos = [{"id": 0, "text": "sin words"}]  # malformado: sin 'words'
    assert cve.aplicar_engine(rotos, plan, 1080, 1920) == rotos


def test_engine_sin_candidatos_devuelve_grupos_intactos():
    plan = cve.resolve_preset("keyword_punch")
    grupos = [_grupo(["la", "de", "que"])]  # solo stopwords
    assert cve.aplicar_engine(grupos, plan, 1080, 1920) == grupos


# ─────────────────────────────────────────────────────────────────────────────
# Deteccion determinista (R1-R7) sobre transcript sintetico
# ─────────────────────────────────────────────────────────────────────────────


def test_deteccion_numeros_y_dinero():
    grupos = [_grupo(["gana", "500", "pesos"]), _grupo(["son", "tres", "pasos"], 1)]
    reglas = {(c[0], c[3]) for c in ck.detectar_candidatos(grupos)}
    assert (0, "R2") in reglas  # pesos
    assert (0, "R1") in reglas  # 500
    assert (1, "R1") in reglas  # tres


def test_deteccion_negacion_y_contraste():
    grupos = [_grupo(["nunca", "hagas", "esto"]), _grupo(["pero", "existe", "solucion"], 1)]
    cands = ck.detectar_candidatos(grupos)
    assert any(c[0] == 0 and c[3] == "R5" for c in cands)  # nunca
    r6 = [c for c in cands if c[3] == "R6"]
    assert r6 and grupos[1]["words"][r6[0][1]]["text"] == "existe"  # la que SIGUE a pero


def test_deteccion_pregunta_marca_contenido():
    g = _grupo(["y", "como", "funciona", "esto?"], texto="y como funciona esto?")
    cands = [c for c in ck.detectar_candidatos([g]) if c[3] == "R4"]
    assert cands and g["words"][cands[0][1]]["text"] == "funciona"


def test_deteccion_repetidas_con_tope():
    grupos = [_grupo(["workflow", "ya"], i) for i in range(4)]  # workflow x4, ya=stopword
    r7 = [c for c in ck.detectar_candidatos(grupos) if c[3] == "R7"]
    assert len(r7) == ck.REPETIDA_MAX_MARCAS  # solo las primeras 2 apariciones
    assert {c[0] for c in r7} == {0, 1}


def test_stopwords_nunca_son_keyword():
    grupos = [_grupo(["el", "la", "que", "para"])]
    assert ck.detectar_candidatos(grupos) == []


def test_merge_un_keyword_por_grupo_y_densidad():
    # dinero (95) debe ganarle a numero (90) dentro del mismo grupo
    grupos = [_grupo(["500", "pesos", "hoy"])]
    elegidos = ck.elegir_keywords(ck.detectar_candidatos(grupos), 1)
    assert len(elegidos) == 1
    w_idx, score, regla = elegidos[0]
    assert regla == "R2" and grupos[0]["words"][w_idx]["text"] == "pesos"
    # densidad: 10 grupos todos con candidato -> max 4 (40%)
    muchos = [_grupo(["gana", f"{i}00", "pesos"], i) for i in range(10)]
    assert len(ck.elegir_keywords(ck.detectar_candidatos(muchos), 10)) <= 4


def test_densidad_doble_freno_clip_corto_manda_pct():
    # 10 grupos, todos con candidato: baja = min(5, 15% de 10 = 1) -> manda el %
    grupos = [_grupo(["gana", f"{i}00", "pesos"], i) for i in range(10)]
    cands = ck.detectar_candidatos(grupos)
    assert len(ck.elegir_keywords(cands, 10, "baja")) == 1
    assert len(ck.elegir_keywords(cands, 10, "media")) == 2  # min(10, 20% de 10)
    assert len(ck.elegir_keywords(cands, 10, "alta")) == 3  # min(15, 30% de 10)


def test_densidad_doble_freno_clip_largo_manda_tope():
    # 100 grupos con candidato: baja = min(5, 15) -> manda el tope absoluto
    assert ck.max_keywords_auto(100, "baja") == 5
    assert ck.max_keywords_auto(100, "media") == 10
    assert ck.max_keywords_auto(100, "alta") == 15
    # sin densidad: ruta historica 40% intacta
    assert ck.max_keywords_auto(100, None) == 40


def test_manual_exenta_del_freno_de_densidad():
    # 10 grupos: 8 candidatos auto + 3 manuales -> baja deja 1 auto y TODAS las manuales
    cands = [(i, 0, ck.SCORE_R1_NUMEROS, "R1") for i in range(8)]
    cands += [(i, 1, ck.SCORE_MANUAL, "manual") for i in (7, 8, 9)]
    elegidos = ck.elegir_keywords(cands, 10, "baja")
    manuales = [g for g, v in elegidos.items() if v[2] == "manual"]
    autos = [g for g, v in elegidos.items() if v[2] == "R1"]
    assert sorted(manuales) == [7, 8, 9]  # voto #34: saturar es decision del usuario
    assert len(autos) == 1


def test_manual_exenta_tambien_en_ruta_historica():
    # D21: la exencion manual cubre TODAS las rutas, incluida densidad=None (40%).
    # 5 grupos: cap 40% = 2 autos; las 3 manuales sobreviven completas ademas.
    cands = [(i, 0, ck.SCORE_R1_NUMEROS, "R1") for i in range(5)]
    cands += [(i, 1, ck.SCORE_MANUAL, "manual") for i in (0, 1, 2)]
    elegidos = ck.elegir_keywords(cands, 5, None)
    manuales = [g for g, v in elegidos.items() if v[2] == "manual"]
    autos = [g for g, v in elegidos.items() if v[2] == "R1"]
    assert sorted(manuales) == [0, 1, 2]
    assert len(autos) == 2  # max(int(5*0.40),1) = 2, solo automaticas


def test_sidecar_seleccion_construir_y_escribir(tmp_path):
    # D21: el sidecar registra palabra, timestamp, grupo/frase, regla, fuente, preset, densidad
    grupos = [_grupo(["gana", "500", "pesos"]), _grupo(["texto", "normal", "sigue"], 1)]
    plan = cve.resolve_preset("keyword_punch")
    out = cve.aplicar_engine(grupos, plan, 1080, 1920)
    data = cve.construir_seleccion(out, plan)
    assert data["preset"] == "keyword_punch" and data["densidad"] == "baja"
    assert len(data["keywords"]) == 1
    kw = data["keywords"][0]
    assert kw["palabra"] == "pesos" and kw["regla"] == "R2" and kw["fuente"] == "regla"
    assert kw["grupo"] == 0 and "pesos" in kw["frase"] and kw["timestamp"] is not None

    video = tmp_path / "demo_keyword_punch.mp4"
    sidecar = cve.escribir_sidecar_seleccion(out, plan, video)
    assert sidecar is not None and sidecar.name == "demo_keyword_punch.keyword_selection.json"
    assert sidecar.exists()


def test_sidecar_no_aplica_con_keywords_off(tmp_path):
    plan = cve.resolve_preset("clean_podcast")
    assert cve.escribir_sidecar_seleccion([], plan, tmp_path / "x.mp4") is None
    assert cve.escribir_sidecar_seleccion([], None, tmp_path / "x.mp4") is None


# ─────────────────────────────────────────────────────────────────────────────
# Filtro de keywords debiles (D22, BLOQUE 2): brain no mete stopwords/cortas
# ─────────────────────────────────────────────────────────────────────────────


def test_es_keyword_debil_clasifica():
    assert ck.es_keyword_debil("en") is True  # stopword
    assert ck.es_keyword_debil("un") is True
    assert ck.es_keyword_debil("de") is True
    assert ck.es_keyword_debil("ya") is True  # corta + stopword
    assert ck.es_keyword_debil("workflow") is False  # contenido
    # senales fuertes nunca son debiles (aunque sean cortas)
    assert ck.es_keyword_debil("500") is False  # numero
    assert ck.es_keyword_debil("$5") is False  # dinero
    assert ck.es_keyword_debil("nunca") is False  # negacion
    assert ck.es_keyword_debil("hoy") is False  # fecha (corta pero fuerte)


def test_brain_no_mete_stopwords_debiles():
    # El brain reancla por kw_ts; si apunta a "en"/"un" el filtro las rechaza
    grupos = [_grupo(["gana", "en", "un"], 0)]
    ts_en = grupos[0]["words"][1]["start"]  # "en"
    ts_un = grupos[0]["words"][2]["start"]  # "un"
    brain = {"groups": [{"kw_ts": ts_en}, {"kw_ts": ts_un}]}
    cands = ck.candidatos_brain(grupos, brain)
    assert cands == []  # ambas debiles: ninguna entra


def test_brain_registra_descartadas():
    grupos = [_grupo(["gana", "en", "premios"], 0)]
    ts_en = grupos[0]["words"][1]["start"]
    brain = {"groups": [{"kw_ts": ts_en}]}
    descartadas = []
    cands = ck.candidatos_brain(grupos, brain, descartadas)
    assert cands == []
    assert len(descartadas) == 1
    d = descartadas[0]
    assert d["palabra"] == "en" and d["razon"] == "stopword" and d["fuente"] == "brain"
    assert d["grupo"] == 0 and d["timestamp"] == ts_en


def test_brain_palabra_fuerte_si_entra():
    # brain apuntando a palabra de contenido entra normal (no se filtra)
    grupos = [_grupo(["compra", "ahora", "gratis"], 0)]
    ts = grupos[0]["words"][2]["start"]  # "gratis" (dinero R2)
    brain = {"groups": [{"kw_ts": ts}]}
    assert ck.candidatos_brain(grupos, brain) == [(0, 2, ck.SCORE_BRAIN, "brain")]


def test_sidecar_no_incluye_basura_y_registra_descartadas(tmp_path):
    # keyword_punch con brain apuntando a stopword: no entra al render y queda registrada
    grupos = [_grupo(["gana", "en", "premios"], 0), _grupo(["texto", "normal", "aqui"], 1)]
    ts_en = grupos[0]["words"][1]["start"]
    brain = {"groups": [{"kw_ts": ts_en}]}
    plan = cve.resolve_preset("keyword_punch")
    out = cve.aplicar_engine(grupos, plan, 1080, 1920, brain_data=brain)
    data = cve.construir_seleccion(out, plan)
    palabras = [k["palabra"] for k in data["keywords"]]
    assert "en" not in palabras  # basura fuera del sidecar
    assert len(data["descartadas"]) == 1 and data["descartadas"][0]["palabra"] == "en"


def test_brain_gana_a_reglas_en_el_mismo_grupo():
    grupos = [_grupo(["gana", "500", "rapido"])]
    brain = {"groups": [{"g": 0, "kw": 2, "kw_ts": grupos[0]["words"][2]["start"]}]}
    cands = ck.detectar_candidatos(grupos) + ck.candidatos_brain(grupos, brain)
    elegidos = ck.elegir_keywords(cands, 1)
    w_idx, _score, regla = elegidos[0]
    assert regla == "brain" and grupos[0]["words"][w_idx]["text"] == "rapido"


# ─────────────────────────────────────────────────────────────────────────────
# Marcas manuales: tolerancia total
# ─────────────────────────────────────────────────────────────────────────────


def test_marca_strong_aplica_a_la_palabra_siguiente():
    limpio, marcas, center = ck.parsear_marcas("esto es [strong]magia pura")
    assert limpio == "esto es magia pura"
    assert marcas == {2: "strong"} and center is False


def test_marca_center_es_de_grupo():
    limpio, marcas, center = ck.parsear_marcas("[center]el titulo grande")
    assert limpio == "el titulo grande" and center is True and marcas == {}


def test_marca_invalida_jamas_rompe():
    casos = [
        "hola [fuego]mundo",  # marca desconocida
        "final huerfano [strong]",  # huerfana al final
        "[big][strong]doble palabra",  # anidada/duplicada
        "texto [/strong]cierre suelto",  # cierre sin apertura
        "sin marcas normales",
    ]
    for texto in casos:
        limpio, _marcas, _c = ck.parsear_marcas(texto)
        assert "[" not in limpio and "]" not in limpio


def test_marca_manual_gana_a_brain_y_reglas():
    g = _grupo(["gana", "500", "rapido"], texto="gana 500 [strong]rapido")
    plan = cve.resolve_preset("keyword_punch")
    out = cve.aplicar_engine([g], plan, 1080, 1920)
    assert out[0]["words"][2].get("is_keyword") is True  # rapido (manual), no 500


def test_marcas_invalidas_jamas_visibles_en_ass(tmp_path):
    """Voto #34: [/strong] y cualquier marca invalida JAMAS es texto visible en el ASS.

    Las words llevan las marcas incrustadas (asi las deja rebalance_timestamps tras
    editar en el Studio) — el engine debe consumirlas en TODOS los presets.
    """
    textos = ["di [strong]hola mundo", "esto [fuego]arde fuerte", "cierre [/strong] suelto"]
    grupos = [_grupo(t.split(), i, texto=t) for i, t in enumerate(textos)]
    plan = cve.resolve_preset("clean_podcast")  # keywords off: la limpieza no depende del modo
    out = cve.aplicar_engine(grupos, plan, 1080, 1920)
    ass = tmp_path / "marcas.ass"
    core_ass.build_ass(out, 1080, 1920, plan.style_cfg, ass)
    contenido = ass.read_text(encoding="utf-8")
    for marca in ("[strong]", "[/strong]", "[fuego]"):
        assert marca not in contenido
    assert "hola" in contenido and "arde" in contenido and "suelto" in contenido


def test_marca_standalone_se_consume_y_aplica():
    # "[strong]" como token suelto: desaparece como palabra y marca a la siguiente
    g = _grupo("gana [strong] todo".split(), texto="gana [strong] todo")
    plan = cve.resolve_preset("keyword_punch")
    out = cve.aplicar_engine([g], plan, 1080, 1920)
    assert [w["text"] for w in out[0]["words"]] == ["gana", "todo"]
    assert out[0]["words"][1].get("is_keyword") is True


# ─────────────────────────────────────────────────────────────────────────────
# Marcado manual v1 por sidecar {stem}_keywords.json (D22, BLOQUE 3)
# ─────────────────────────────────────────────────────────────────────────────


def test_candidatos_manuales_palabra_exacta():
    grupos = [_grupo(["compra", "gratis", "hoy"], 0)]
    cands = ck.candidatos_manuales(grupos, [{"palabra": "gratis"}])
    assert cands == [(0, 1, ck.SCORE_MANUAL, "manual")]


def test_candidatos_manuales_frase_corta():
    grupos = [_grupo(["esto", "sin", "costo", "extra"], 0)]
    cands = ck.candidatos_manuales(grupos, [{"frase": "sin costo"}])
    assert cands == [(0, 1, ck.SCORE_MANUAL, "manual")]  # 1er token del match


def test_candidatos_manuales_intensidad_big():
    grupos = [_grupo(["mira", "esto"], 0)]
    cands = ck.candidatos_manuales(grupos, [{"palabra": "esto", "intensidad": "big"}])
    assert cands == [(0, 1, ck.SCORE_MANUAL, "manual_big")]


def test_candidatos_manuales_acota_por_grupo():
    grupos = [_grupo(["repetida", "aqui"], 0), _grupo(["repetida", "alla"], 1)]
    cands = ck.candidatos_manuales(grupos, [{"palabra": "repetida", "grupo": 1}])
    assert cands == [(1, 0, ck.SCORE_MANUAL, "manual")]


def test_manual_aparece_aunque_el_sistema_no_la_elegiria():
    # "de" es stopword: jamas la elegiria el sistema, pero manual la fuerza
    grupos = [_grupo(["algo", "de", "valor"], 0)]
    plan = cve.resolve_preset("keyword_punch")
    out = cve.aplicar_engine(grupos, plan, 1080, 1920, manual_entries=[{"palabra": "de"}])
    assert out[0]["words"][1].get("is_keyword") is True  # stopword forzada por manual


def test_manual_gana_prioridad_sobre_brain_y_reglas():
    grupos = [_grupo(["gana", "500", "rapido"], 0)]  # 500 = R1, rapido nada
    brain = {"groups": [{"kw_ts": grupos[0]["words"][1]["start"]}]}  # brain -> 500
    plan = cve.resolve_preset("keyword_punch")
    out = cve.aplicar_engine(
        grupos, plan, 1080, 1920, brain_data=brain, manual_entries=[{"palabra": "rapido"}]
    )
    kw = [w for w in out[0]["words"] if w.get("is_keyword")]
    assert len(kw) == 1 and kw[0]["text"] == "rapido"  # manual gana, no 500


def test_manual_se_registra_en_sidecar_como_manual():
    grupos = [_grupo(["algo", "de", "valor"], 0)]
    plan = cve.resolve_preset("keyword_punch")
    out = cve.aplicar_engine(grupos, plan, 1080, 1920, manual_entries=[{"palabra": "valor"}])
    data = cve.construir_seleccion(out, plan)
    assert len(data["keywords"]) == 1
    kw = data["keywords"][0]
    assert kw["palabra"] == "valor" and kw["regla"] == "manual" and kw["fuente"] == "manual"


def test_manual_invalido_fail_open_no_rompe():
    grupos = [_grupo(["texto", "normal"], 0)]
    plan = cve.resolve_preset("keyword_punch")
    basura = [{"sin": "palabra"}, "no soy dict", {"palabra": "inexistente"}, 42]
    out = cve.aplicar_engine(grupos, plan, 1080, 1920, manual_entries=basura)
    assert [w["text"] for w in out[0]["words"]] == ["texto", "normal"]  # render intacto


def test_cargar_manual_keywords_failopen(tmp_path):
    assert cve.cargar_manual_keywords(tmp_path / "no_existe.json") == []
    roto = tmp_path / "roto_keywords.json"
    roto.write_text("{no es json", encoding="utf-8")
    assert cve.cargar_manual_keywords(roto) == []
    # acepta lista directa y {"keywords": [...]}
    lista = tmp_path / "lista_keywords.json"
    lista.write_text('[{"palabra": "x"}]', encoding="utf-8")
    assert cve.cargar_manual_keywords(lista) == [{"palabra": "x"}]
    envuelto = tmp_path / "env_keywords.json"
    envuelto.write_text('{"keywords": [{"palabra": "y"}]}', encoding="utf-8")
    assert cve.cargar_manual_keywords(envuelto) == [{"palabra": "y"}]


def test_manual_funciona_aun_con_keywords_off():
    # clean_podcast tiene keywords off; el marcado manual explicito igual destaca
    grupos = [_grupo(["titulo", "importante"], 0)]
    plan = cve.resolve_preset("clean_podcast")
    out = cve.aplicar_engine(grupos, plan, 1080, 1920, manual_entries=[{"palabra": "importante"}])
    assert out[0]["words"][1].get("is_keyword") is True


# ─────────────────────────────────────────────────────────────────────────────
# Fit de escala contra safe zones (reducir -> desactivar)
# ─────────────────────────────────────────────────────────────────────────────


def test_fit_reduce_hasta_caber():
    # 10 chars: a 145 no cabe en 875px, reducida si (145 -> 135 -> 125)
    escala = ck.ajustar_escala_punch("produccion", fontsize=90, ancho_util_px=875, escala=145)
    assert escala is not None and ck.KW_SCALE_BASE <= escala < 145


def test_fit_imposible_desactiva():
    assert ck.ajustar_escala_punch("palabrota", 90, ancho_util_px=100, escala=145) is None


def test_fit_palabra_corta_conserva_escala():
    assert ck.ajustar_escala_punch("hoy", 90, ancho_util_px=875, escala=145) == 145


# ─────────────────────────────────────────────────────────────────────────────
# Extensiones del motor ASS: punch_scale + glow (default off = byte-identico)
# ─────────────────────────────────────────────────────────────────────────────


def test_punch_scale_por_palabra_en_ass():
    cfg = get_style("hormozi", "off")  # sin pop: escala persistente pura
    gw = _grupo(["gran", "OFERTA", "hoy"])["words"]
    gw[1]["is_keyword"] = True
    gw[1]["punch_scale"] = 145
    txt = core_ass._word_event_text(gw, 0, cfg)  # keyword NO activa: persistente
    assert "\\fscx145\\fscy145" in txt and "\\fscx122" not in txt


def test_sin_punch_scale_conserva_122():
    cfg = get_style("hormozi", "off")
    gw = _grupo(["gran", "OFERTA", "hoy"])["words"]
    gw[1]["is_keyword"] = True
    txt = core_ass._word_event_text(gw, 0, cfg)
    assert "\\fscx122\\fscy122" in txt  # comportamiento historico intacto


def test_punch_scale_invalido_failsafe():
    assert core_ass._kw_scale({"punch_scale": 999}) == 122
    assert core_ass._kw_scale({"punch_scale": "grande"}) == 122
    assert core_ass._kw_scale({"punch_scale": True}) == 122
    assert core_ass._kw_scale({}) == 122
    assert core_ass._kw_scale({"punch_scale": 145}) == 145


def test_glow_off_no_cambia_eventos(tmp_path):
    cfg = get_style("hormozi")
    assert cfg.kw_glow is False  # default del builtin
    g = _grupo(["gran", "OFERTA", "hoy"])
    g["words"][1]["is_keyword"] = True
    out = tmp_path / "off.ass"
    core_ass.build_ass([g], 1080, 1920, cfg, out)
    import pysubs2

    subs = pysubs2.load(str(out))
    assert len(subs.events) == 3  # un evento por palabra, sin gemelos
    assert all(ev.layer == 0 for ev in subs.events)


def test_glow_on_agrega_capa_detras(tmp_path):
    from dataclasses import replace

    cfg = replace(get_style("hormozi"), kw_glow=True)
    g = _grupo(["gran", "OFERTA", "hoy"])
    g["words"][1]["is_keyword"] = True
    out = tmp_path / "glow.ass"
    core_ass.build_ass([g], 1080, 1920, cfg, out)
    import pysubs2

    subs = pysubs2.load(str(out))
    assert len(subs.events) == 6  # gemelo de glow por cada evento de palabra
    glow = [ev for ev in subs.events if ev.layer == 0]
    texto = [ev for ev in subs.events if ev.layer == 1]
    assert len(glow) == 3 and len(texto) == 3
    assert all("\\blur" in ev.text and "\\alpha&HFF&" in ev.text for ev in glow)


def test_glow_on_sin_keywords_no_agrega_nada(tmp_path):
    from dataclasses import replace

    cfg = replace(get_style("hormozi"), kw_glow=True)
    g = _grupo(["sin", "keywords", "aqui"])
    out = tmp_path / "nokw.ass"
    core_ass.build_ass([g], 1080, 1920, cfg, out)
    import pysubs2

    subs = pysubs2.load(str(out))
    assert len(subs.events) == 3 and all(ev.layer == 0 for ev in subs.events)


# ─────────────────────────────────────────────────────────────────────────────
# avoid_faces: senal binaria desde CSV (sin senal = None, fail-open)
# ─────────────────────────────────────────────────────────────────────────────


def test_csv_ausente_sin_senal(tmp_path):
    assert cve.hay_cara_en_rango(tmp_path / "no_existe.csv", 0, 10) is None


def test_csv_sin_columna_conf_sin_senal(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("t,cam_center_x,face_x_asignada,distancia\n1.0,500,510,10\n", encoding="utf-8")
    assert cve.hay_cara_en_rango(p, 0, 10) is None


def test_csv_con_conf_da_senal(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text(
        "t,cam_center_x,face_x_asignada,distancia,conf_asignada\n"
        "1.0,500,510,10,0.91\n5.0,500,510,10,\n",
        encoding="utf-8",
    )
    assert cve.hay_cara_en_rango(p, 0.0, 2.0) is True  # deteccion viva en rango
    assert cve.hay_cara_en_rango(p, 4.0, 6.0) is False  # solo hold en rango


# ─────────────────────────────────────────────────────────────────────────────
# E2E del engine sobre grupos sinteticos (keyword_punch completo)
# ─────────────────────────────────────────────────────────────────────────────


def test_keyword_punch_e2e_marca_y_escala():
    # 5 grupos con 2 candidatos, densidad baja (D21): min(5, 15% de 5)=1 -> gana el
    # de mayor score (pesos R2=95); nunca (R5=85) cae por el freno de seleccion.
    grupos = [
        _grupo(["gana", "500", "pesos"], 0),
        _grupo(["nunca", "pares", "aqui"], 1),
        _grupo(["la", "de", "que"], 2),
        _grupo(["cosas", "sueltas", "van"], 3),
        _grupo(["texto", "normal", "sigue"], 4),
    ]
    plan = cve.resolve_preset("keyword_punch", "viral")
    out = cve.aplicar_engine(grupos, plan, 1080, 1920)
    kw0 = [w for w in out[0]["words"] if w.get("is_keyword")]
    assert kw0 and kw0[0]["text"] == "pesos" and kw0[0].get("punch_scale", 0) > 122
    assert not any(w.get("is_keyword") for w in out[1]["words"])  # freno densidad baja
    assert not any(w.get("is_keyword") for w in out[2]["words"])
    assert grupos[0]["words"][1].get("is_keyword") is None  # originales no mutados
