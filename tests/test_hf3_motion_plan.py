"""HF-3 bloque 3: el planificador de letreros, entero y sin renderizar un solo frame.

Las reglas de colocacion las fijo K y no se interpretan. Cada una tiene aqui su test, y
tambien lo tienen los casos que NO deben colocar nada: una pieza omitida en silencio y sin
motivo registrado seria indistinguible de un bug.
"""

from __future__ import annotations

import csv

import pytest

import motion_plan as mp

TEXTOS = mp.TextosMarca(
    titulo="Entrena tu LoRA en 20 minutos",
    kicker="",
    nombre="Carlos Daniel Penagos",
    rol="Prompt Models Studio",
    cta="Sigue para mas",
)


def _plan(dur_ms, **kw):
    kw.setdefault("orientacion", "horizontal")  # 16:9 no consulta la cara: aisla la regla temporal
    kw.setdefault("textos", TEXTOS)
    return mp.planificar(duracion_ms=dur_ms, **kw)


def _nombres(plan):
    return [p.plantilla for p in plan.piezas]


def _motivos(plan):
    return {o.plantilla: o.motivo for o in plan.omisiones}


def _csv_cara(tmp_path, fraccion, t_max=60.0):
    """Trayectoria del reframe con la cara a una altura fija. Mismo formato que produce F6."""
    ruta = tmp_path / "trayectoria_x.csv"
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "conf_asignada", "face_y_asignada"])
        t = 0.0
        while t <= t_max:
            w.writerow([f"{t:.2f}", "0.9", f"{fraccion:.3f}"])
            t += 0.5
    return ruta


# ── Regla por duracion ───────────────────────────────────────────────────────


def test_clip_corto_solo_lleva_hook_en_cero():
    plan = _plan(5000)
    assert _nombres(plan) == ["hook"]
    assert plan.piezas[0].t0_ms == 0
    assert _motivos(plan) == {
        "cierre": mp.MOTIVO_CLIP_CORTO,
        "lower_third": mp.MOTIVO_CLIP_CORTO,
        "dato_destacado": mp.MOTIVO_CLIP_CORTO,
    }


@pytest.mark.parametrize("dur", [6700, 9000, 12000])
def test_clip_medio_lleva_hook_y_cierre_terminando_200ms_antes(dur):
    plan = _plan(dur)
    assert _nombres(plan) == ["hook", "cierre"]
    cierre = plan.piezas[-1]
    assert cierre.t1_ms == dur - mp.MARGEN_FINAL_MS
    assert cierre.duracion_ms == mp.DURACION_MS["cierre"]


@pytest.mark.parametrize("dur", [6000, 6300, 6699])
def test_por_debajo_de_6700_el_cierre_no_cabe_y_el_umbral_lo_dice(dur):
    """El umbral es 6700 porque es donde la aritmetica lo permite, no 6000 por costumbre.

    El hook ocupa 0-2500. El cierre pide 3500 ms terminando 200 ms antes del final, o sea que
    arranca en dur-3700, y necesita dur-3700 >= 2500+500. De ahi dur >= 6700. Con el umbral en
    6000 el cierre se proponia y se omitia SIEMPRE entre 6000 y 6700; ahora ni se propone, y el
    motivo que se registra es el correcto.
    """
    plan = _plan(dur)
    assert _nombres(plan) == ["hook"]
    assert _motivos(plan)["cierre"] == mp.MOTIVO_CLIP_CORTO


def test_el_umbral_del_cierre_es_exactamente_el_que_dicta_la_aritmetica():
    """Si alguien mueve una duracion o la separacion, este test dice el numero nuevo."""
    minimo = mp.DURACION_MS["hook"] + mp.SEPARACION_MIN_MS + mp.MARGEN_FINAL_MS
    minimo += mp.DURACION_MS["cierre"]
    assert mp.UMBRAL_CORTO_MS == minimo == 6700
    assert "cierre" in _nombres(_plan(mp.UMBRAL_CORTO_MS))
    assert "cierre" not in _nombres(_plan(mp.UMBRAL_CORTO_MS - 1))


def test_el_umbral_de_12000_pertenece_al_tramo_medio():
    """La regla dice 'de 6000 a 12000' y 'mas de 12000': 12000 clavado NO lleva lower_third."""
    assert "lower_third" not in _nombres(_plan(12000))
    assert "lower_third" in _nombres(_plan(12001))


def test_clip_largo_lleva_hook_lower_third_y_cierre():
    plan = _plan(20000)
    assert _nombres(plan) == ["hook", "lower_third", "cierre"]
    lower = plan.piezas[1]
    assert lower.t0_ms == mp.LOWER_THIRD_T0_MS
    assert plan.piezas[-1].t1_ms == 20000 - mp.MARGEN_FINAL_MS


def test_ninguna_pieza_cruza_el_final_del_clip():
    for dur in (3000, 6000, 12500, 20000, 60000):
        for pieza in _plan(dur).piezas:
            assert pieza.t1_ms <= dur, (dur, pieza)


def test_las_piezas_conservan_su_duracion_nativa_nunca_se_recortan():
    for pieza in _plan(20000).piezas:
        assert pieza.duracion_ms == mp.DURACION_MS[pieza.plantilla]


def test_titulo_seccion_no_se_coloca_automaticamente():
    for dur in (3000, 9000, 20000, 120000):
        assert "titulo_seccion" not in _nombres(_plan(dur))


# ── Separacion minima y prioridad ────────────────────────────────────────────


def test_hay_al_menos_500ms_entre_todas_las_piezas():
    piezas = sorted(_plan(20000).piezas, key=lambda p: p.t0_ms)
    for previa, siguiente in zip(piezas, piezas[1:], strict=False):
        assert siguiente.t0_ms - previa.t1_ms >= mp.SEPARACION_MIN_MS


def test_cuando_no_hay_aire_cae_la_pieza_de_menor_prioridad():
    """El unico tramo con cifra cae dentro del hook: quien se omite es el dato, no el hook.

    Es el caso mas limpio de la regla de prioridad, porque las dos piezas quieren el mismo
    instante y la de arriba de la lista gana sin discusion.
    """
    plan = _plan(90000, tramos=_tramos((1000, "arranca con un 90% de acierto")))
    assert "hook" in _nombres(plan)
    assert plan.piezas[0].t0_ms == 0
    assert "dato_destacado" not in _nombres(plan)
    assert _motivos(plan)["dato_destacado"] == mp.MOTIVO_SIN_AIRE


def test_con_clip_largo_las_tres_piezas_base_siempre_conviven():
    """Comprobado en barrido, no de memoria: por encima de 12000 ms nunca compiten entre si."""
    for dur in range(12001, 60000, 977):
        assert _nombres(_plan(dur)) == ["hook", "lower_third", "cierre"], dur


def test_el_orden_de_prioridad_es_el_declarado():
    assert mp.PRIORIDAD == ("hook", "cierre", "lower_third", "dato_destacado")


def test_una_pieza_omitida_siempre_deja_su_motivo():
    plan = _plan(3000)
    assert plan.omisiones
    for o in plan.omisiones:
        assert o.motivo, o


# ── dato_destacado ───────────────────────────────────────────────────────────


def _tramos(*pares):
    return [mp.Tramo(t0, t0 + 2000, texto) for t0, texto in pares]


def test_dato_destacado_exige_clip_largo_y_una_cifra():
    tramos = _tramos((8000, "subio un 87% en tres meses"))
    assert "dato_destacado" not in _nombres(_plan(9000, tramos=tramos))
    assert "dato_destacado" in _nombres(_plan(90000, tramos=tramos))


def test_sin_cifra_no_hay_dato_destacado_y_se_dice_por_que():
    plan = _plan(90000, tramos=_tramos((8000, "sin numeros por ninguna parte")))
    assert "dato_destacado" not in _nombres(plan)
    assert _motivos(plan)["dato_destacado"] == mp.MOTIVO_SIN_CIFRA


def test_dato_destacado_arranca_al_inicio_del_tramo_con_cifra():
    plan = _plan(90000, tramos=_tramos((5000, "nada"), (9000, "cayo 42% el costo")))
    dato = next(p for p in plan.piezas if p.plantilla == "dato_destacado")
    assert dato.t0_ms == 9000
    assert dato.texto["cifra"] == "42%"
    assert dato.texto["etiqueta"] == "cayo 42% el costo"


def test_si_el_primer_tramo_con_cifra_no_cabe_se_prueba_el_siguiente():
    """La regla habla de 'algun tramo': quedarse en el primero la dejaria practicamente muerta,
    porque los primeros segundos casi siempre los ocupa el hook."""
    plan = _plan(
        90000,
        tramos=_tramos(
            (500, "el 10% inicial ya era mucho"),
            (14000, "luego subio hasta el 55% del total"),
        ),
    )
    dato = next(p for p in plan.piezas if p.plantilla == "dato_destacado")
    assert dato.t0_ms == 14000


def test_si_ningun_tramo_con_cifra_cabe_se_omite_no_se_encima():
    plan = _plan(13000, tramos=_tramos((0, "arranca con 90%"), (100, "otra vez 90%")))
    assert "dato_destacado" not in _nombres(plan)
    assert _motivos(plan)["dato_destacado"] in (mp.MOTIVO_SIN_AIRE, mp.MOTIVO_FUERA_DE_CLIP)


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("subio 87%", "87%"),
        ("cuesta $1,299 al mes", "$1,299"),
        ("son 3 horas", "3"),
        ("el 0.5 por ciento", "0.5"),
        ("sin cifras aqui", None),
        ("", None),
    ],
)
def test_busqueda_de_cifra(texto, esperado):
    assert mp.buscar_cifra(texto) == esperado


# ── Zona de la cara (solo 9:16) ──────────────────────────────────────────────


def test_en_vertical_una_cara_alta_deja_libre_el_carril(tmp_path):
    plan = _plan(20000, orientacion="vertical", tray_csv=_csv_cara(tmp_path, 0.25))
    assert _nombres(plan) == ["hook", "lower_third", "cierre"]


@pytest.mark.parametrize("fraccion", [0.50, 0.75])
def test_en_vertical_una_cara_centrada_o_baja_manda_las_piezas_a_la_banda_superior(
    tmp_path, fraccion
):
    """El carril nativo (54-68%) queda invadido por los buckets center y bottom.

    Antes eso omitia la pieza entera y dejaba en cero al 61.9% de los verticales reales. Ahora
    la pieza sube a la banda superior en vez de desaparecer.
    """
    plan = _plan(20000, orientacion="vertical", tray_csv=_csv_cara(tmp_path, fraccion))
    assert _nombres(plan) == ["hook", "lower_third", "cierre"]
    assert {p.banda for p in plan.piezas} == {mp.BANDA_ARRIBA}


def test_con_la_cara_arriba_las_piezas_se_quedan_en_su_carril_nativo(tmp_path):
    plan = _plan(20000, orientacion="vertical", tray_csv=_csv_cara(tmp_path, 0.25))
    assert {p.banda for p in plan.piezas} == {mp.BANDA_CENTRO}


def test_la_banda_superior_no_pisa_ni_la_ui_ni_los_captions():
    """0.20-0.34: por debajo del 10% de UI de TikTok y muy por encima del 70-92% de captions."""
    arriba, abajo = mp.BANDA_SUPERIOR
    assert arriba >= 0.10, "invade la zona segura superior de la UI"
    assert abajo <= mp.ZONA_CAPTIONS[0], "invade la franja de captions"
    assert abajo <= 0.40, "no queda por encima del borde de una cara centrada"
    assert mp.DESPLAZAMIENTO_SUPERIOR == pytest.approx(arriba - mp.CARRIL_VERTICAL[0])


def test_el_desplazamiento_en_pixeles_sube_la_pieza(tmp_path):
    import motion_capa as mc

    assert mc.desplazamiento_de_banda(mp.BANDA_CENTRO, 1920) is None
    x, y = mc.desplazamiento_de_banda(mp.BANDA_ARRIBA, 1920)
    assert x == 0
    assert y < 0, "la banda superior se compone desplazando el overlay hacia ARRIBA"
    assert y == int(round(mp.DESPLAZAMIENTO_SUPERIOR * 1920))


def test_en_vertical_sin_csv_se_coloca_en_el_carril_nativo_y_se_avisa():
    """FAIL-OPEN, no fail-closed: un dato que falta degrada la capa, no la apaga.

    El carril nativo (54-68%) es el que K aprobo en el gate visual de HF-2 justamente por no
    pisar caras, asi que es el destino correcto cuando no se sabe donde esta la cara. Antes esto
    dejaba en cero, para siempre, a los clips derivados que no tienen fuente 16:9 de la que
    sacar una trayectoria.
    """
    plan = _plan(20000, orientacion="vertical", tray_csv=None)
    assert _nombres(plan) == ["hook", "lower_third", "cierre"]
    assert {p.banda for p in plan.piezas} == {mp.BANDA_CENTRO}
    assert plan.incidencias == (mp.INCIDENCIA_SIN_DATO_DE_CARA,)


def test_un_csv_legacy_sin_columna_vertical_es_lo_mismo_que_no_tenerlo(tmp_path):
    ruta = tmp_path / "trayectoria_legacy.csv"
    ruta.write_text("t,x,y\n0.0,1,2\n1.0,1,2\n", encoding="utf-8")
    plan = _plan(20000, orientacion="vertical", tray_csv=ruta)
    assert _nombres(plan) == ["hook", "lower_third", "cierre"]
    assert plan.incidencias == (mp.INCIDENCIA_SIN_DATO_DE_CARA,)


def test_con_dato_de_cara_no_se_registra_incidencia(tmp_path):
    assert (
        _plan(20000, orientacion="vertical", tray_csv=_csv_cara(tmp_path, 0.25)).incidencias == ()
    )


def test_en_16_9_nunca_se_registra_la_incidencia_de_cara():
    """En 16:9 la cara no se consulta, asi que su ausencia no degrada nada."""
    assert _plan(20000, orientacion="horizontal", tray_csv=None).incidencias == ()


def test_ninguna_pieza_se_omite_jamas_por_la_cara(tmp_path):
    """Con el fallback ya no existe ese motivo: la cara MUEVE la pieza, nunca la borra."""
    for fraccion in (0.15, 0.50, 0.75, 0.95):
        plan = _plan(20000, orientacion="vertical", tray_csv=_csv_cara(tmp_path, fraccion))
        assert len(plan.piezas) == 3, fraccion
    assert not hasattr(mp, "MOTIVO_CARA")


def test_en_16_9_la_cara_no_se_consulta(tmp_path):
    """Las bandas del catalogo en 16:9 son disjuntas y no compiten con la cara."""
    plan = _plan(20000, orientacion="horizontal", tray_csv=_csv_cara(tmp_path, 0.55))
    assert _nombres(plan) == ["hook", "lower_third", "cierre"]


# ── Textos ───────────────────────────────────────────────────────────────────


def test_sin_titulo_del_clipper_no_hay_hook_ni_se_inventa_uno():
    plan = _plan(20000, textos=mp.TextosMarca(titulo="", nombre="N", cta="C"))
    assert "hook" not in _nombres(plan)
    assert _motivos(plan)["hook"] == mp.MOTIVO_SIN_TITULO


def test_sin_nombre_configurado_se_omite_el_lower_third_entero():
    """Mejor ninguna tarjeta que una tarjeta en blanco."""
    plan = _plan(20000, textos=mp.TextosMarca(titulo="T", nombre="", cta="C"))
    assert "lower_third" not in _nombres(plan)
    assert _motivos(plan)["lower_third"] == mp.MOTIVO_SIN_NOMBRE


def test_los_textos_llegan_a_los_slots_que_declara_cada_plantilla():
    plan = _plan(20000)
    slots = {p.plantilla: set(p.texto) for p in plan.piezas}
    assert slots["hook"] == {"kicker", "titulo"}
    assert slots["lower_third"] == {"nombre", "rol"}
    assert slots["cierre"] == {"titulo", "cta"}
    assert plan.piezas[0].texto["titulo"] == TEXTOS.titulo
    # El cierre YA NO repite el titulo del hook: manda la CTA.
    assert plan.piezas[-1].texto["titulo"] == TEXTOS.cta


# ── Pureza y determinismo ────────────────────────────────────────────────────


def test_dos_llamadas_iguales_dan_el_mismo_plan(tmp_path):
    args = {
        "duracion_ms": 30000,
        "orientacion": "vertical",
        "textos": TEXTOS,
        "tramos": _tramos((9000, "un 42% mas")),
        "tray_csv": _csv_cara(tmp_path, 0.2),
    }
    assert mp.planificar(**args).a_dict() == mp.planificar(**args).a_dict()


def test_el_plan_es_serializable_a_json():
    import json

    json.dumps(_plan(20000).a_dict())


@pytest.mark.parametrize("mala", [0, -1, 1.5, True, "20000"])
def test_duracion_invalida_es_error_de_contrato(mala):
    with pytest.raises(ValueError, match="duracion_ms"):
        mp.planificar(duracion_ms=mala, orientacion="vertical", textos=TEXTOS)


def test_orientacion_invalida_es_error_de_contrato():
    with pytest.raises(ValueError, match="orientacion"):
        mp.planificar(duracion_ms=20000, orientacion="diagonal", textos=TEXTOS)


def test_la_tabla_de_duraciones_coincide_con_los_ejemplos_del_catalogo():
    """La tabla se copia para que el planificador sea puro; esto impide que se desincronice."""
    import json
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[1] / "motion" / "ejemplos"
    for nombre, ms in mp.DURACION_MS.items():
        ejemplo = json.loads((raiz / f"{nombre}.json").read_text(encoding="utf-8"))
        assert ejemplo["duracion_ms"] == ms, nombre


def test_las_restricciones_espaciales_son_las_medidas_en_hf2():
    assert mp.ZONA_CAPTIONS == (0.70, 0.92)
    assert mp.CARRIL_VERTICAL == (0.54, 0.68)
    assert mp.SEPARACION_MIN_MS == 500
    assert mp.MARGEN_FINAL_MS == 200


# ── Coherencia entre el letrero y lo que se dice (punto 4) ───────────────────


def test_el_cierre_no_repite_el_titulo_del_hook():
    """Con el hook y el cierre diciendo lo mismo, el ultimo letrero no aportaba nada."""
    plan = _plan(20000)
    hook = next(p for p in plan.piezas if p.plantilla == "hook")
    cierre = next(p for p in plan.piezas if p.plantilla == "cierre")
    assert cierre.texto["titulo"] != hook.texto["titulo"]
    assert cierre.texto["titulo"] == TEXTOS.cta


def test_el_secundario_del_cierre_sale_de_lo_ultimo_que_se_dice():
    plan = _plan(20000, tramos=_tramos((2000, "empieza"), (15000, "y aqui termina la idea")))
    cierre = next(p for p in plan.piezas if p.plantilla == "cierre")
    # La "y" inicial se cae: un letrero no arranca colgando de la frase anterior.
    assert cierre.texto["cta"] == "aqui termina la idea"


def test_sin_tramos_el_secundario_del_cierre_va_vacio_y_no_se_inventa():
    cierre = next(p for p in _plan(20000).piezas if p.plantilla == "cierre")
    assert cierre.texto["cta"] == ""


def test_el_dato_destacado_se_coloca_aunque_el_inicio_del_tramo_este_ocupado():
    """Punto 4.3, el caso real: dos cifras habladas dentro del lower_third (3000-7500 ms).

    Antes se omitia entero por `sin_separacion_minima` teniendo hueco 500 ms despues. Ahora la
    ventana llega hasta el final del tramo y la pieza entra sin pisar a nadie.
    """
    tramos = [
        mp.Tramo(3700, 7460, "del 2023 al 2024 fue un 10"),
        mp.Tramo(7460, 10800, "5 % de medias superiores"),
    ]
    plan = _plan(56790, tramos=tramos)
    dato = next(p for p in plan.piezas if p.plantilla == "dato_destacado")
    assert dato.t0_ms >= 8000, "debe arrancar tras el lower_third mas la separacion minima"
    lower = next(p for p in plan.piezas if p.plantilla == "lower_third")
    assert dato.t0_ms - lower.t1_ms >= mp.SEPARACION_MIN_MS


def test_el_dato_sigue_arrancando_al_inicio_del_tramo_cuando_esta_libre():
    """La regla original manda: la ventana es un plan B, no un desplazamiento por gusto."""
    plan = _plan(90000, tramos=_tramos((9000, "cayo 42% el costo")))
    dato = next(p for p in plan.piezas if p.plantilla == "dato_destacado")
    assert dato.t0_ms == 9000


# ── Relleno de huecos (punto 4.4) ────────────────────────────────────────────


def _tramos_largos(dur_ms, paso=2500):
    """Habla continua de principio a fin, para que el hueco sea de piezas y no de texto."""
    return [
        mp.Tramo(t, t + paso - 100, f"frase numero {i} del clip")
        for i, t in enumerate(range(0, dur_ms - paso, paso))
    ]


def _huecos_de(plan, dur):
    piezas = sorted(plan.piezas, key=lambda p: p.t0_ms)
    bordes = [0, *[t for p in piezas for t in (p.t0_ms, p.t1_ms)], dur]
    return [bordes[i + 1] - bordes[i] for i in range(0, len(bordes) - 1, 2)]


def test_el_relleno_gasta_todo_el_presupuesto_y_reduce_el_hueco_maximo():
    """Las dos reglas se contradicen y el TECHO manda: es un limite duro, no una preferencia.

    La regla de los 20 s pasa a ser el OBJETIVO del relleno, no una garantia: con
    `MAX_PIEZAS_POR_MINUTO=5` no siempre alcanza el presupuesto para bajar todos los huecos de
    20 s, y forzarlo seria saltarse el techo. Lo que si se exige es que el presupuesto se gaste
    entero y que el hueco maximo baje de verdad respecto a no rellenar.
    """
    for dur in (56790, 90000, 120000):
        tramos = _tramos_largos(dur)
        plan = _plan(dur, tramos=tramos)
        sin_relleno = _plan(dur, tramos=[])
        assert len(plan.piezas) == mp.techo_de_piezas(dur) or not [
            h for h in _huecos_de(plan, dur) if h > mp.HUECO_MAX_MS
        ], f"dur={dur}: sobro presupuesto y quedaron huecos"
        assert max(_huecos_de(plan, dur)) < max(_huecos_de(sin_relleno, dur)), f"dur={dur}"


def test_el_relleno_se_acerca_al_objetivo_de_20s_aunque_no_siempre_llegue():
    """Numeros medidos, no supuestos: se deja escrito cuanto se queda corto y donde."""
    medido = {56790: 21500, 90000: 19000, 120000: 23000}
    for dur, esperado in medido.items():
        plan = _plan(dur, tramos=_tramos_largos(dur))
        assert max(_huecos_de(plan, dur)) == esperado, f"dur={dur}"


def test_cuando_el_techo_no_deja_presupuesto_el_hueco_se_acepta_y_se_dice():
    dur = 35000
    plan = _plan(dur, tramos=_tramos_largos(dur))
    assert mp.techo_de_piezas(dur) - len(mp.PIEZAS_PROTEGIDAS) <= 0
    assert max(_huecos_de(plan, dur)) > mp.HUECO_MAX_MS
    assert "titulo_seccion" not in _nombres(plan)


def test_el_relleno_usa_titulo_seccion_con_texto_del_tramo_no_del_clip():
    plan = _plan(56790, tramos=_tramos_largos(56790))
    secciones = [p for p in plan.piezas if p.plantilla == "titulo_seccion"]
    assert secciones, "el clip largo necesitaba relleno"
    for s in secciones:
        assert s.texto["titulo"].startswith("frase numero")
        assert s.texto["titulo"] != TEXTOS.titulo


def test_en_clips_cortos_no_se_rellena_nada():
    for dur in (12500, 20000, 30000):
        plan = _plan(dur, tramos=_tramos_largos(dur))
        assert "titulo_seccion" not in _nombres(plan), dur


def test_el_relleno_prefiere_el_tramo_que_llega_tras_una_pausa_larga():
    """Una pausa larga es donde el hablante cambia de tema; ahi es donde va el titulo."""
    tramos = [
        mp.Tramo(0, 3000, "arranque del clip"),
        mp.Tramo(3100, 12000, "sigue la misma idea sin parar"),
        mp.Tramo(14000, 20000, "y aqui empieza el tema nuevo"),
        mp.Tramo(20100, 40000, "que continua sin pausa ninguna"),
    ]
    plan = _plan(45000, tramos=tramos)
    secciones = [p for p in plan.piezas if p.plantilla == "titulo_seccion"]
    assert secciones
    assert secciones[0].texto["titulo"] == "aqui empieza el tema nuevo"


def test_el_relleno_respeta_la_separacion_y_no_se_encima():
    plan = _plan(90000, tramos=_tramos_largos(90000))
    piezas = sorted(plan.piezas, key=lambda p: p.t0_ms)
    for previa, siguiente in zip(piezas, piezas[1:], strict=False):
        assert siguiente.t0_ms - previa.t1_ms >= mp.SEPARACION_MIN_MS


def test_el_relleno_tambien_respeta_la_cara_en_vertical(tmp_path):
    plan = _plan(
        56790,
        orientacion="vertical",
        tramos=_tramos_largos(56790),
        tray_csv=_csv_cara(tmp_path, 0.55, t_max=60.0),
    )
    secciones = [p for p in plan.piezas if p.plantilla == "titulo_seccion"]
    assert secciones
    assert {p.banda for p in secciones} == {mp.BANDA_ARRIBA}


def test_el_texto_de_seccion_se_condensa_a_una_linea():
    largo = "una frase muy larga que no cabe de ninguna manera en una placa de una sola linea"
    plan = _plan(56790, tramos=[mp.Tramo(t, t + 2400, largo) for t in range(0, 54000, 2500)])
    for s in (p for p in plan.piezas if p.plantilla == "titulo_seccion"):
        assert len(s.texto["titulo"]) <= mp.TITULO_SECCION_MAX_CHARS
        assert not s.texto["titulo"].endswith(" ")


# ── Titulos que no sean media frase (punto 2) ────────────────────────────────


@pytest.mark.parametrize(
    ("crudo", "esperado"),
    [
        # Cabe entero y se lee como una unidad: se deja tal cual.
        (
            "La desercion escolar subio, y eso preocupa",
            "La desercion escolar subio, y eso preocupa",
        ),
        # Corte JUSTO ANTES de una conjuncion: la clausula anterior queda entera.
        ("Es que imaginemonos un Garcia, pues por los traslados", "Es que imaginemonos un Garcia"),
        # No puede EMPEZAR por preposicion.
        ("de un Garcia con una vision", "un Garcia con una vision"),
        # No puede ACABAR colgando de una conjuncion.
        ("desarrollo y con preparatorias que", "desarrollo y con preparatorias"),
        # Ni cortando ni recortando sale nada de 12 a 46: se omite.
        ("con secundarias que tenga todas las condiciones", ""),
        # Demasiado corto para decir nada.
        ("Por que?", ""),
        ("", ""),
    ],
)
def test_condensar_en_limite_de_clausula(crudo, esperado):
    assert mp.condensar_clausula(crudo, mp.TITULO_SECCION_MAX_CHARS) == esperado


def test_el_fragmento_nunca_empieza_ni_acaba_por_palabra_debil():
    """Barrido: ninguna salida del condensador puede colgar por ninguno de los dos extremos."""
    frases = [
        "y con preparatorias que tengan todas las condiciones para el desarrollo",
        "de un Garcia con una vision de futuro y con bienestar",
        "porque un dato, la desercion escolar del ciclo del 2023 al 2024",
        "pues por los traslados, que son larguisimos y muy caros",
        "sabemos que eres de Garcia, cierto? y pues bueno, dandole la",
    ]
    for frase in frases:
        for maximo in (28, 46):
            salida = mp.condensar_clausula(frase, maximo)
            if not salida:
                continue
            palabras = salida.split()
            assert palabras[0].lower() not in mp.ARRANQUE_PROHIBIDO, (frase, maximo, salida)
            assert palabras[-1].strip(".,;:!?").lower() not in mp.ARRANQUE_PROHIBIDO, (
                frase,
                maximo,
                salida,
            )
            assert mp.TEXTO_MINIMO_CHARS <= len(salida) <= maximo


def test_si_ningun_tramo_del_hueco_es_titulable_no_se_coloca_nada():
    """Calidad por encima de cobertura: mejor sin letrero que con media frase."""
    basura = [mp.Tramo(t, t + 2400, "y que con las de la y por el") for t in range(0, 54000, 2500)]
    plan = _plan(56790, tramos=basura)
    assert "titulo_seccion" not in _nombres(plan)
    assert _motivos(plan)["titulo_seccion"] == mp.MOTIVO_SIN_TRAMO


def test_si_el_tramo_preferido_no_es_titulable_se_prueba_el_siguiente():
    tramos = [
        mp.Tramo(0, 3000, "arranque limpio del clip que dura un rato"),
        mp.Tramo(9000, 12000, "y que de la con las"),  # tras pausa, pero intitulable
        mp.Tramo(12100, 20000, "Los traslados cuestan mucho dinero"),
        mp.Tramo(20100, 45000, "y siguen subiendo cada ano sin parar"),
    ]
    plan = _plan(50000, tramos=tramos)
    secciones = [p for p in plan.piezas if p.plantilla == "titulo_seccion"]
    assert secciones
    assert secciones[0].texto["titulo"] == "Los traslados cuestan mucho dinero"


def test_el_secundario_del_cierre_usa_la_misma_guarda():
    """Si el ultimo tramo no da clausula limpia, se busca hacia atras; si no, va vacio."""
    plan = _plan(
        20000,
        tramos=[
            mp.Tramo(2000, 5000, "Los traslados cuestan dinero"),
            mp.Tramo(14000, 16000, "de la que con"),
        ],
    )
    cierre = next(p for p in plan.piezas if p.plantilla == "cierre")
    assert cierre.texto["cta"] == "Los traslados cuestan dinero"


def test_el_secundario_del_cierre_va_vacio_si_nada_es_titulable():
    plan = _plan(20000, tramos=[mp.Tramo(2000, 5000, "de la que con y")])
    cierre = next(p for p in plan.piezas if p.plantilla == "cierre")
    assert cierre.texto["cta"] == ""


def test_la_etiqueta_del_dato_tambien_pasa_por_la_guarda():
    plan = _plan(90000, tramos=_tramos((9000, "y el costo subio un 42% este ano")))
    dato = next(p for p in plan.piezas if p.plantilla == "dato_destacado")
    assert dato.texto["etiqueta"] == "el costo subio un 42% este ano"
    assert len(dato.texto["etiqueta"]) <= mp.DATO_ETIQUETA_MAX_CHARS


def test_si_la_cifra_vive_en_un_tramo_intitulable_el_dato_se_omite_con_su_motivo():
    """Hay cifra, pero no hay forma de etiquetarla sin partir la frase."""
    plan = _plan(90000, tramos=_tramos((9000, "con el 42% y de")))
    assert "dato_destacado" not in _nombres(plan)
    assert _motivos(plan)["dato_destacado"] == mp.MOTIVO_ETIQUETA_SUCIA


# ── Techo de densidad (punto 1) ──────────────────────────────────────────────


def test_el_techo_esta_en_una_sola_constante():
    assert mp.MAX_PIEZAS_POR_MINUTO == 5
    assert mp.PIEZAS_PROTEGIDAS == frozenset({"hook", "lower_third", "cierre"})
    assert mp.PIEZAS_OPCIONALES == frozenset({"titulo_seccion", "dato_destacado"})


@pytest.mark.parametrize(
    ("dur_ms", "techo"),
    [(1000, 1), (12000, 1), (24000, 2), (30000, 3), (56790, 5), (60000, 5), (120000, 10)],
)
def test_el_techo_se_prorratea_por_duracion(dur_ms, techo):
    assert mp.techo_de_piezas(dur_ms) == techo


def test_el_redondeo_es_al_alza_desde_la_mitad_no_del_banquero():
    """round(2.5) da 2 en Python: un clip de 30 s daria 2 piezas y nadie lo entenderia."""
    assert mp.techo_de_piezas(30000) == 3


def test_ninguna_pieza_protegida_se_recorta_aunque_pasen_del_techo():
    """En 20 s el techo son 2 piezas y las protegidas son 3: mandan ellas."""
    plan = _plan(20000, tramos=_tramos_largos(20000))
    assert mp.techo_de_piezas(20000) == 2
    assert sorted(_nombres(plan)) == ["cierre", "hook", "lower_third"]


def test_ningun_clip_pasa_del_techo_salvo_por_las_protegidas():
    for dur in (12001, 20000, 35000, 56790, 90000, 120000, 300000):
        plan = _plan(dur, tramos=_tramos_largos(dur))
        opcionales = [p for p in plan.piezas if p.plantilla in mp.PIEZAS_OPCIONALES]
        techo = mp.techo_de_piezas(dur)
        protegidas = [p for p in plan.piezas if p.plantilla in mp.PIEZAS_PROTEGIDAS]
        assert len(opcionales) <= max(techo - len(protegidas), 0), dur


def test_al_recortar_cae_primero_la_pieza_de_menor_sustancia():
    """Se compara una seccion con contenido contra otra hecha de palabras vacias."""
    floja = mp.Pieza("titulo_seccion", 30000, 32000, {"titulo": "y de la que con"})
    fuerte = mp.Pieza("titulo_seccion", 40000, 42000, {"titulo": "desercion escolar por traslados"})
    assert mp.puntos_informativos(fuerte.texto["titulo"]) > mp.puntos_informativos(
        floja.texto["titulo"]
    )
    colocadas = [
        mp.Pieza("hook", 0, 2500, {}),
        mp.Pieza("lower_third", 3000, 7500, {}),
        mp.Pieza("cierre", 50000, 53500, {}),
        floja,
        fuerte,
    ]
    omisiones: list = []
    mp._aplicar_techo(colocadas, omisiones, 48000)  # techo 4, protegidas 3 -> solo 1 opcional
    assert fuerte in colocadas
    assert floja not in colocadas
    assert omisiones[0].motivo == mp.MOTIVO_TECHO_DENSIDAD


def test_el_recorte_deja_su_motivo_nunca_desaparece_en_silencio():
    plan = _plan(35000, tramos=_tramos_largos(35000))
    assert _motivos(plan).get("titulo_seccion") == mp.MOTIVO_TECHO_DENSIDAD


def test_puntos_informativos_ignora_las_palabras_vacias_del_espanol():
    assert mp.puntos_informativos("de la que con y por el") == 0.0
    assert mp.puntos_informativos("desercion escolar") > 0
    # Una cifra siempre cuenta, aunque sea corta.
    assert mp.puntos_informativos("un 42%") > mp.puntos_informativos("un")
