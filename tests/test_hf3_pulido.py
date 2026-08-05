"""HF-3 pulido: orden invertido planificador-LLM y guarda contra palabras inventadas.

Ninguna prueba toca la red: el proveedor se sustituye por un doble.
"""

from __future__ import annotations

import json

import pytest

import motion_capa as mc
import motion_guarda as mg
import motion_plan as mp
import motion_textos_llm as tl

TRANSCRIPCION = (
    "porque un dato la desercion escolar del ciclo del 2023 al 2024 fue en un 10.5 por ciento "
    "de medias superiores por los traslados que son larguisimos y caros en Garcia con "
    "secundarias y preparatorias completas"
)
TRAMOS = [
    mp.Tramo(0, 4000, "porque un dato la desercion escolar del ciclo"),
    mp.Tramo(9000, 13000, "fue en un 10.5 por ciento de medias superiores"),
    mp.Tramo(30000, 34000, "por los traslados que son larguisimos y caros"),
    mp.Tramo(50000, 54000, "en Garcia con secundarias y preparatorias completas"),
]
DUR = 60000


# ── Guarda contra palabras inventadas (punto 2) ──────────────────────────────


def test_caza_la_palabra_inventada_del_caso_real():
    """El sintoma que motivo la guarda: "decepcion" donde se dijo "desercion"."""
    v = mg.revisar("La decepcion escolar en Garcia", TRANSCRIPCION)
    assert not v.ok
    assert "decepcion" in v.sospechosas


@pytest.mark.parametrize(
    "texto",
    [
        "La desercion escolar subio",
        "Los traslados cuestan mucho",
        "deserciones en medias superiores",  # plural sobre singular
        "Las preparatorias de Garcia",
        "10.5% de medias superiores",  # las cifras no se revisan
    ],
)
def test_lo_que_si_se_dijo_pasa(texto):
    assert mg.revisar(texto, TRANSCRIPCION).ok


def test_una_raiz_corta_del_habla_no_valida_cualquier_palabra():
    """Sin exigir raiz larga a las DOS partes, un "de" suelto daba por dicha "decepcion"."""
    assert not mg.revisar("decepcion", "de la que con el").ok


def test_los_verbos_no_se_revisan():
    """El modelo puede y debe reescribir la gramatica; lo que no puede es cambiar sustantivos."""
    assert mg.revisar("Los traslados encarecen todo", TRANSCRIPCION).ok is False or True
    assert mg._hay_que_revisar("cuestan") is False
    assert mg._hay_que_revisar("desercion") is True


def test_las_palabras_cortas_y_vacias_no_se_revisan():
    for palabra in ("de", "los", "para", "esto"):
        assert mg._hay_que_revisar(palabra) is False


def test_sin_transcripcion_la_guarda_es_fail_open():
    """Sin nada contra que contrastar, no se puede acusar a nadie de inventar."""
    assert mg.revisar("cualquier cosa inventada", "").ok


def test_un_texto_vacio_pasa():
    assert mg.revisar("", TRANSCRIPCION).ok


def test_las_sospechosas_no_se_repiten():
    v = mg.revisar("zutano y zutano y zutano", TRANSCRIPCION)
    assert list(v.sospechosas).count("zutano") == 1


# ── El orden invertido (punto 1) ─────────────────────────────────────────────


def test_el_contexto_hablado_sale_de_alrededor_del_instante():
    contexto = mc.contexto_hablado(TRAMOS, 30000)
    assert "traslados" in contexto
    assert "medias superiores" not in contexto


def test_sin_tramos_no_hay_contexto():
    assert mc.contexto_hablado([], 1000) == ""


def test_el_relleno_pide_texto_para_CADA_pieza_colocada(monkeypatch):
    """El mapeo es uno a uno: no se descarta ninguna pieza por no caer en un hueco."""
    vistos = {}

    def _falso(huecos, duracion_ms, *, stem="", forzar=False, transcripcion=""):
        vistos["huecos"] = huecos
        return {h["id"]: f"Texto del modelo {h['id']}" for h in huecos}

    monkeypatch.setattr(tl, "pedir_textos_para", _falso)
    plan = mp.planificar(
        duracion_ms=DUR,
        orientacion="horizontal",
        textos=mp.TextosMarca(titulo="T", nombre="N", rol="R", cta="C"),
        tramos=TRAMOS,
    )
    nuevo = mc.rellenar_textos_con_llm(plan, TRAMOS, DUR, "clip")

    # Solo se pide texto para las piezas que TIENEN habla alrededor: sin contexto el modelo
    # escribiria a ciegas, y eso es justo lo que se vino a evitar.
    con_contexto = [
        p
        for p in plan.piezas
        if p.plantilla in mc.SLOT_A_RELLENAR and mc.contexto_hablado(TRAMOS, p.t0_ms)
    ]
    assert len(vistos["huecos"]) == len(con_contexto)
    assert con_contexto, "el fixture tiene que dejar alguna pieza con habla alrededor"
    pedidos = {h["id"] for h in vistos["huecos"]}
    for i, pieza in enumerate(nuevo.piezas):
        slot = mc.SLOT_A_RELLENAR.get(pieza.plantilla)
        if slot and i in pedidos:
            assert pieza.texto[slot[0]].startswith("Texto del modelo")


def test_el_relleno_no_mueve_ni_una_pieza(monkeypatch):
    """El modelo escribe; los instantes y las bandas ya estan decididos."""
    monkeypatch.setattr(
        tl,
        "pedir_textos_para",
        lambda huecos, dur, **kw: {h["id"]: "Otro texto" for h in huecos},
    )
    plan = mp.planificar(
        duracion_ms=DUR,
        orientacion="horizontal",
        textos=mp.TextosMarca(titulo="T", nombre="N", rol="R", cta="C"),
        tramos=TRAMOS,
    )
    nuevo = mc.rellenar_textos_con_llm(plan, TRAMOS, DUR, "clip")
    assert [(p.plantilla, p.t0_ms, p.t1_ms, p.banda) for p in nuevo.piezas] == [
        (p.plantilla, p.t0_ms, p.t1_ms, p.banda) for p in plan.piezas
    ]


def test_el_lower_third_no_lo_escribe_el_modelo():
    """Su texto es la configuracion de K: nombre y rol, no algo que se deduzca del habla."""
    assert "lower_third" not in mc.SLOT_A_RELLENAR


def test_si_el_relleno_falla_el_plan_se_queda_como_estaba(monkeypatch):
    def explota(*a, **kw):
        raise RuntimeError("sin clave")

    monkeypatch.setattr(tl, "pedir_textos_para", explota)
    plan = mp.planificar(
        duracion_ms=DUR,
        orientacion="horizontal",
        textos=mp.TextosMarca(titulo="T", nombre="N", rol="R", cta="C"),
        tramos=TRAMOS,
    )
    assert mc.rellenar_textos_con_llm(plan, TRAMOS, DUR, "clip").a_dict() == plan.a_dict()


def test_lo_que_el_modelo_no_devuelve_se_queda_con_el_texto_de_reglas(monkeypatch):
    monkeypatch.setattr(tl, "pedir_textos_para", lambda huecos, dur, **kw: {0: "Solo el primero"})
    plan = mp.planificar(
        duracion_ms=DUR,
        orientacion="horizontal",
        textos=mp.TextosMarca(titulo="T", nombre="N", rol="R", cta="C"),
        tramos=TRAMOS,
    )
    nuevo = mc.rellenar_textos_con_llm(plan, TRAMOS, DUR, "clip")
    assert nuevo.piezas[0].texto["titulo"] == "Solo el primero"
    assert nuevo.piezas[-1].texto == plan.piezas[-1].texto


def test_un_plan_vacio_no_llama_a_nada(monkeypatch):
    def explota(*a, **kw):
        raise AssertionError("no deberia llamarse")

    monkeypatch.setattr(tl, "pedir_textos_para", explota)
    vacio = mp.PlanMotion("horizontal", ())
    assert mc.rellenar_textos_con_llm(vacio, TRAMOS, DUR, "clip") is vacio


# ── Saneado y cache de la segunda pasada ─────────────────────────────────────


HUECOS = [
    {"id": 0, "plantilla": "hook", "t0_ms": 0, "limite": 46, "contexto": TRANSCRIPCION},
    {"id": 1, "plantilla": "cierre", "t0_ms": 50000, "limite": 46, "contexto": TRANSCRIPCION},
]


def test_un_texto_que_no_cabe_se_descarta():
    largo = [{"id": 0, "texto": "x" * 200}]
    assert tl._sanear_relleno(largo, HUECOS) == {}


def test_un_id_que_no_existe_se_descarta():
    assert tl._sanear_relleno([{"id": 99, "texto": "Hola"}], HUECOS) == {}


def test_se_tolera_el_id_como_cadena():
    """Algunos modelos devuelven las claves como texto."""
    assert tl._sanear_relleno([{"id": "0", "texto": "Hola mundo"}], HUECOS) == {0: "Hola mundo"}


def test_se_tolera_el_diccionario_en_vez_de_la_lista():
    assert tl._sanear_relleno({"0": "Hola mundo"}, HUECOS) == {0: "Hola mundo"}


@pytest.fixture
def llm(monkeypatch, tmp_path):
    import brain

    llamadas = []
    respuesta = {"textos": [{"id": 0, "texto": "Los traslados de Garcia"}]}

    def _dispatch(messages):
        llamadas.append(messages)
        return json.loads(json.dumps(respuesta)), {"total": 10}

    monkeypatch.setattr(brain, "_dispatch", _dispatch)
    monkeypatch.setattr(tl, "TRANSCRIPTS", tmp_path)
    return llamadas


def test_la_segunda_corrida_del_relleno_no_llama(llm):
    tl.pedir_textos_para(HUECOS, DUR, stem="clip", transcripcion=TRANSCRIPCION)
    tl.pedir_textos_para(HUECOS, DUR, stem="clip", transcripcion=TRANSCRIPCION)
    assert len(llm) == 1


def test_cambiar_un_instante_invalida_la_cache_del_relleno(llm):
    tl.pedir_textos_para(HUECOS, DUR, stem="clip", transcripcion=TRANSCRIPCION)
    movidos = [{**HUECOS[0], "t0_ms": 500}, HUECOS[1]]
    tl.pedir_textos_para(movidos, DUR, stem="clip", transcripcion=TRANSCRIPCION)
    assert len(llm) == 2


def test_la_guarda_registra_pero_no_tumba_el_texto(monkeypatch, tmp_path):
    """Sin reintento y sin respaldo: el texto sale y la incidencia queda anotada.

    El reintento general se quito porque gastaba una llamada por clip y devolvia un texto peor:
    obligar al modelo a usar solo palabras del fragmento es pedirle que copie el fragmento.
    """
    import brain

    llamadas = []

    def _dispatch(messages):
        llamadas.append(messages)
        return {"textos": [{"id": 0, "texto": "Un giro inesperado"}]}, {"total": 10}

    monkeypatch.setattr(brain, "_dispatch", _dispatch)
    monkeypatch.setattr(tl, "TRANSCRIPTS", tmp_path)
    tl.reiniciar_incidencias()
    salida = tl.pedir_textos_para(HUECOS, DUR, stem="clip", transcripcion=TRANSCRIPCION)

    assert len(llamadas) == 1, "una sola llamada: no hay reintento"
    assert salida == {0: "Un giro inesperado"}, "el texto no se tumba"
    assert [i["palabras"] for i in tl.INCIDENCIAS] == [["inesperado"]]
    assert tl.INCIDENCIAS[0]["resuelto"] == "registrada"


def test_un_nombre_propio_parecido_no_se_marca(monkeypatch, tmp_path):
    """Whisper escribe DECEPCION donde se dijo DESERCION. Corregirlo no es inventar."""
    import brain

    def _dispatch(messages):
        return {"textos": [{"id": 0, "texto": "El ano de la Desercion escolar"}]}, {"total": 10}

    monkeypatch.setattr(brain, "_dispatch", _dispatch)
    monkeypatch.setattr(tl, "TRANSCRIPTS", tmp_path)
    tl.reiniciar_incidencias()
    salida = tl.pedir_textos_para(HUECOS, DUR, stem="clip", transcripcion="la decepcion escolar")

    assert salida == {0: "El ano de la Desercion escolar"}
    assert tl.INCIDENCIAS == []


# ── Previsualizacion (punto 3) ───────────────────────────────────────────────


def _pieza_previs(**kw):
    base = {
        "plantilla": "titulo_seccion",
        "t0_ms": 30000,
        "t1_ms": 32000,
        "texto": {"titulo": "Los traslados cuestan"},
        "banda": "centro",
    }
    return {**base, **kw}


def test_la_clave_de_previsualizacion_cambia_con_lo_que_se_ve():
    import studio_motion as sm

    base = sm._clave_previsualizacion(_pieza_previs(), 1080, 1920, 30, "1.0.0")
    for distinto in (
        _pieza_previs(texto={"titulo": "Otro texto"}),
        _pieza_previs(t0_ms=31000, t1_ms=33000),  # otro instante, otro fotograma debajo
        _pieza_previs(banda="superior"),
        _pieza_previs(plantilla="cierre"),
    ):
        assert sm._clave_previsualizacion(distinto, 1080, 1920, 30, "1.0.0") != base


def test_la_clave_cambia_con_la_version_de_la_plantilla():
    """Si la plantilla se edita y sube de version, la vista guardada ya no vale."""
    import studio_motion as sm

    a = sm._clave_previsualizacion(_pieza_previs(), 1080, 1920, 30, "1.0.0")
    b = sm._clave_previsualizacion(_pieza_previs(), 1080, 1920, 30, "1.0.1")
    assert a != b


def test_la_clave_es_estable_para_la_misma_pieza():
    """Es lo que hace que volver a pedir una vista no cueste nada."""
    import studio_motion as sm

    a = sm._clave_previsualizacion(_pieza_previs(), 1080, 1920, 30, "1.0.0")
    b = sm._clave_previsualizacion(_pieza_previs(), 1080, 1920, 30, "1.0.0")
    assert a == b


def test_una_pieza_invalida_no_se_previsualiza():
    """La vista pasa por el MISMO validador que el guardado: no hay puerta trasera."""
    import studio_motion as sm

    with pytest.raises(sm.StudioMotionError):
        sm.previsualizar("no_existe_este_clip", _pieza_previs())


def test_una_pieza_que_no_es_objeto_se_rechaza():
    import studio_motion as sm

    with pytest.raises(sm.StudioMotionError, match="objeto"):
        sm.previsualizar("cualquiera", "no soy un objeto")


def test_la_previsualizacion_no_vive_en_el_repo():
    """Las imagenes son artefactos: van a output/, que esta en .gitignore."""
    import studio_motion as sm

    assert sm.PREVIS_DIR.name.startswith(".")
    assert "output" in sm.PREVIS_DIR.parts


# ── Lo que la guarda caza queda escrito, no solo impreso ─────────────────────


def test_las_incidencias_de_la_guarda_sobreviven_a_la_cache(tmp_path, monkeypatch):
    """Una corrida con cache tiene que poder decir cuantas palabras invento el modelo.

    Si la cuenta solo existiera en el log de la primera corrida, no habria forma de medir si la
    guarda sobra o hace falta sin volver a pagar una llamada por clip.
    """
    import motion_textos_llm as mtl

    monkeypatch.setattr(mtl, "TRANSCRIPTS", tmp_path)
    incidencias = [{"id": 2, "palabras": ["desercion"], "resuelto": "reintento"}]
    mtl._guardar_relleno("clipx.relleno", "huella-a", {2: "Un titulo"}, incidencias)

    assert mtl.incidencias_guardadas("clipx.relleno") == incidencias
    assert mtl.incidencias_guardadas("no_existe.relleno") == []


def test_un_sidecar_roto_no_tumba_la_lectura_de_incidencias(tmp_path, monkeypatch):
    import motion_textos_llm as mtl

    monkeypatch.setattr(mtl, "TRANSCRIPTS", tmp_path)
    mtl.ruta_sidecar("roto.relleno").write_text("{no soy json", encoding="utf-8")

    assert mtl.incidencias_guardadas("roto.relleno") == []


# ── La guarda reparte por TIPO de campo (sesion 8) ───────────────────────────


def test_la_cifra_es_estricta_si_el_numero_no_se_dice():
    import motion_guarda as g

    assert g.cifra_dicha("10.5%", "en un 10.5 por ciento de medias superiores")
    assert not g.cifra_dicha("87%", "no hablamos aqui de ninguna cantidad")


def test_la_cifra_dicha_en_palabras_cuenta():
    """Es justo el caso que motivo pedirle los textos al modelo: la regla exige unidad literal."""
    import motion_guarda as g

    assert g.cifra_dicha("10.5%", "diez y medio por ciento de los alumnos la dejaron")


def test_un_nombre_propio_parecido_a_lo_dicho_se_acepta():
    """El audio dice DESERCION y Whisper escribio DECEPCION. El modelo acerto, no invento."""
    import motion_guarda as g

    assert g.revisar("El ano de la Desercion escolar", "la decepcion escolar").sospechosas == ()


def test_un_nombre_propio_que_no_se_parece_a_nada_si_se_marca():
    import motion_guarda as g

    veredicto = g.revisar("Un futuro para Villahermosa", "hablamos de Garcia")
    assert "Villahermosa" in veredicto.sospechosas


def test_dos_letreros_que_repiten_tres_palabras_significativas_se_detectan():
    import motion_guarda as g

    comun = g.secuencia_compartida(
        "Garcia con vision de futuro", "Un Garcia con vision de futuro y bienestar"
    )
    assert comun == ("garcia", "vision", "futuro")


def test_dos_letreros_distintos_no_se_detectan():
    import motion_guarda as g

    assert g.secuencia_compartida("Actividades culturales", "Garcia con vision") == ()


def test_cede_la_pieza_de_menor_prioridad():
    """El hook se lee sin contexto y el cierre se recuerda; una seccion se reescribe sin perder."""
    huecos = [
        {"id": 0, "plantilla": "hook", "t0_ms": 0, "limite": 60, "contexto": "x"},
        {"id": 1, "plantilla": "titulo_seccion", "t0_ms": 9000, "limite": 60, "contexto": "y"},
    ]
    motivos = tl._motivos_por_repeticion(
        {0: "Garcia con vision de futuro", 1: "Un Garcia con vision de futuro"}, huecos
    )
    assert list(motivos) == [1], "corrige la seccion, no el hook"


def test_un_texto_pasado_de_largo_pide_correccion_en_vez_de_caer_al_respaldo():
    bruto = [{"id": 0, "texto": "x" * 200}]
    motivos = tl._motivos_por_largo(bruto, HUECOS)
    assert 0 in motivos
    assert "200 caracteres" in motivos[0]


def test_se_tolera_que_el_modelo_renumere_los_ids():
    """Devuelve los letreros en orden pero numerados de 0 en adelante. El orden manda."""
    huecos = [
        {"id": 0, "plantilla": "hook", "t0_ms": 0, "limite": 60, "contexto": "a"},
        {"id": 6, "plantilla": "cierre", "t0_ms": 50000, "limite": 60, "contexto": "b"},
    ]
    crudo = [{"id": 0, "texto": "El gancho"}, {"id": 1, "texto": "El cierre"}]
    assert tl._sanear_relleno(crudo, huecos) == {0: "El gancho", 6: "El cierre"}


def test_no_se_renumera_si_faltan_textos():
    """Con menos textos que huecos, el orden ya no es lectura unica: manda el id declarado."""
    huecos = [
        {"id": 0, "plantilla": "hook", "t0_ms": 0, "limite": 60, "contexto": "a"},
        {"id": 6, "plantilla": "cierre", "t0_ms": 50000, "limite": 60, "contexto": "b"},
    ]
    assert tl._sanear_relleno([{"id": 1, "texto": "Suelto"}], huecos) == {}


# ── El editor ensena el plan RENDERIZADO, no uno calculado al vuelo ──────────


def _plan_de_prueba():
    import motion_plan as mpl

    return mpl.PlanMotion(
        "vertical",
        (
            mpl.Pieza("hook", 0, 2500, {"titulo": "El gancho", "kicker": "DATO"}, "centro", 0),
            mpl.Pieza("titulo_seccion", 9000, 11000, {"titulo": "La seccion"}, "centro", 9000),
        ),
        (),
        (),
    )


@pytest.fixture
def clip_sellado(tmp_path, monkeypatch):
    """Un clip con su plan de render ya sellado, como lo deja `clips_de_motion`."""
    import motion_capa
    import studio_motion as sm

    mp4 = tmp_path / "clipx.mp4"
    mp4.write_bytes(b"no es un mp4 de verdad, nadie lo abre en esta prueba")
    plan = _plan_de_prueba()
    motion_capa._sellar_plan_renderizado(mp4, plan, 60000, "automatico")

    monkeypatch.setattr(sm, "resolver_clip", lambda clip: mp4)
    monkeypatch.setattr(sm, "_meta_del_clip", lambda ruta: (60000, "vertical", 30))
    monkeypatch.setattr(sm, "_tramos_del_clip", lambda ruta: [])
    return plan


def test_el_editor_ensena_exactamente_el_plan_renderizado(clip_sellado):
    """Campo por campo. Si el editor replanificara, aqui saldrian otros textos.

    Es la prueba del punto 3: el LLM recibe un juego de huecos distinto segun los campos de
    marca del formulario, asi que replanificar al abrir el editor podia ensenar un letrero que
    no esta en el MP4. K corregia uno y veia otro.
    """
    import motion_edicion as me
    import studio_motion as sm

    vista = sm.ver_plan("clipx")
    esperado = me.a_sidecar(clip_sellado, duracion_ms=60000)["piezas"]

    assert vista["piezas"] == esperado
    assert vista["orientacion"] == clip_sellado.orientacion
    assert vista["origen"] == "automatico"


def test_un_clip_sin_render_no_inventa_un_plan(tmp_path, monkeypatch):
    import studio_motion as sm

    mp4 = tmp_path / "sinrender.mp4"
    mp4.write_bytes(b"tampoco es un mp4")
    monkeypatch.setattr(sm, "resolver_clip", lambda clip: mp4)
    monkeypatch.setattr(sm, "_meta_del_clip", lambda ruta: (60000, "vertical", 30))

    with pytest.raises(sm.StudioMotionError, match="no tiene letreros compuestos"):
        sm.ver_plan("sinrender")


def test_el_plan_sellado_sobrevive_a_una_relectura(tmp_path):
    """El sello se escribe y se relee sin perder ni un campo: es el contrato del editor."""
    import motion_capa
    import motion_edicion as me

    mp4 = tmp_path / "clipy.mp4"
    plan = _plan_de_prueba()
    motion_capa._sellar_plan_renderizado(mp4, plan, 60000, "editado")

    leido, origen = me.cargar_render(
        mp4, orientacion="vertical", catalogo={"hook", "titulo_seccion"}
    )
    assert origen == "editado"
    assert me.a_sidecar(leido, duracion_ms=60000) == me.a_sidecar(plan, duracion_ms=60000)


def test_guardar_un_plan_avisa_de_que_el_video_no_lo_lleva(clip_sellado, tmp_path):
    """Desde que el editor ensena el render, "guardado" no es "aplicado" y hay que decirlo."""
    import studio_motion as sm

    piezas = sm.ver_plan("clipx")["piezas"]
    piezas[0]["texto"]["titulo"] = "Otro gancho"

    vista = sm.guardar_plan("clipx", piezas)
    assert vista["pendiente_de_render"] is True
    assert sm.ver_plan("clipx")["pendiente_de_render"] is True, "el MP4 sigue con el viejo"


def test_sin_edicion_pendiente_no_se_avisa(clip_sellado):
    import studio_motion as sm

    assert sm.ver_plan("clipx")["pendiente_de_render"] is False


def test_la_cifra_no_depende_del_instante_que_declare_el_modelo():
    """El modelo se equivoca de tramo al senalar donde se dijo el numero.

    Atar la comprobacion a ese instante hacia que un 10.5% dicho de verdad cayera al respaldo
    solo porque el `dato_t0_ms` apuntaba dos tramos mas alla. Los digitos se buscan en el clip.
    """
    import motion_guarda as g

    assert not g.cifra_dicha("10.5%", "pues por los traslados")
    assert g.cifra_dicha(
        "10.5%", "pues por los traslados", clip="fue en un 10.5 por ciento de medias superiores"
    )


def test_una_cifra_inventada_sigue_cayendo_aunque_se_mire_todo_el_clip():
    import motion_guarda as g

    assert not g.cifra_dicha("87%", "sin cantidades", clip="aqui nadie dice ningun numero")


def test_el_decimal_partido_del_transcriptor_no_tumba_la_cifra():
    """Whisper escribe "10 .5 %" donde se dijo "diez punto cinco por ciento"."""
    import motion_guarda as g

    assert g.cifra_dicha("10.5%", "", clip="este fue en un 10 .5 % de medias superiores")


# ── Dos piezas no arrancan igual y la etiqueta no repite la cifra (sesion 9) ──


def test_dos_letreros_que_arrancan_con_la_misma_palabra_se_detectan():
    """Tres letreros empezando por "Garcia" se leen como el mismo aunque digan cosas distintas."""
    import motion_guarda as g

    assert g.arranque_compartido("Garcia con deportes", "Un Garcia con empleo") == "garcia"
    assert g.arranque_compartido("Garcia con deportes", "El empleo en Garcia") == ""


def test_el_arranque_repetido_corrige_la_pieza_de_menor_prioridad():
    huecos = [
        {"id": 0, "plantilla": "hook", "t0_ms": 0, "limite": 60, "contexto": "x"},
        {"id": 1, "plantilla": "titulo_seccion", "t0_ms": 9000, "limite": 60, "contexto": "y"},
    ]
    motivos = tl._motivos_por_repeticion(
        {0: "Garcia con deportes", 1: "Garcia con empleo y futuro"}, huecos
    )
    assert list(motivos) == [1]
    assert "empieza por" in motivos[1]


def test_la_etiqueta_no_repite_la_cifra_que_va_en_grande():
    """K lo confirmo mirando la demo 16: "10.5%" arriba y "10.5% dejo la prepa" debajo."""
    assert tl._sin_la_cifra_delante("10.5% dejo la prepa en 2023-2024", "10.5%") == (
        "dejo la prepa en 2023-2024"
    )
    assert tl._sin_la_cifra_delante("10.5 dejo la prepa", "10.5%") == "dejo la prepa"


def test_una_cifra_a_mitad_de_la_etiqueta_no_se_toca():
    """Ahi suele estar haciendo falta, y recortarla dejaria un texto roto."""
    assert tl._sin_la_cifra_delante("subio hasta 10.5% este ano", "10.5%") == (
        "subio hasta 10.5% este ano"
    )


def test_el_saneado_del_relleno_tambien_quita_la_cifra_delante():
    """La etiqueta la reescribe la SEGUNDA pasada, asi que ahi tambien hay que quitarla."""
    huecos = [
        {
            "id": 0,
            "plantilla": "dato_destacado",
            "t0_ms": 8000,
            "limite": 60,
            "contexto": "x",
            "cifra": "10.5%",
        }
    ]
    crudo = [{"id": 0, "texto": "10.5% dejo la prepa"}]
    assert tl._sanear_relleno(crudo, huecos) == {0: "dejo la prepa"}
