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
def test_entre_6000_y_6700_el_cierre_no_cabe_detras_del_hook(dur):
    """Zona muerta REAL de las reglas, medida y no inventada: no es un bug del planificador.

    El hook ocupa 0-2500. El cierre pide 3500 ms terminando 200 ms antes del final, o sea que
    arranca en dur-3700. Para respetar los 500 ms de aire hace falta dur>=6700. Entre 6000 y
    6700 las dos reglas se contradicen, y quien cae es el cierre porque tiene menos prioridad
    que el hook. Se omite entero: nunca se encima ni se le recorta la duracion.
    """
    plan = _plan(dur)
    assert _nombres(plan) == ["hook"]
    assert _motivos(plan)["cierre"] == mp.MOTIVO_SIN_AIRE


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
    plan = _plan(30000, tramos=_tramos((1000, "arranca con un 90% de acierto")))
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
    assert "dato_destacado" in _nombres(_plan(30000, tramos=tramos))


def test_sin_cifra_no_hay_dato_destacado_y_se_dice_por_que():
    plan = _plan(30000, tramos=_tramos((8000, "sin numeros por ninguna parte")))
    assert "dato_destacado" not in _nombres(plan)
    assert _motivos(plan)["dato_destacado"] == mp.MOTIVO_SIN_CIFRA


def test_dato_destacado_arranca_al_inicio_del_tramo_con_cifra():
    plan = _plan(30000, tramos=_tramos((5000, "nada"), (9000, "cayo 42% el costo")))
    dato = next(p for p in plan.piezas if p.plantilla == "dato_destacado")
    assert dato.t0_ms == 9000
    assert dato.texto["cifra"] == "42%"
    assert dato.texto["etiqueta"] == "cayo 42% el costo"


def test_si_el_primer_tramo_con_cifra_no_cabe_se_prueba_el_siguiente():
    """La regla habla de 'algun tramo': quedarse en el primero la dejaria practicamente muerta,
    porque los primeros segundos casi siempre los ocupa el hook."""
    plan = _plan(30000, tramos=_tramos((500, "el 10% inicial"), (14000, "y luego 55%")))
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
def test_en_vertical_una_cara_centrada_o_baja_invade_el_carril(tmp_path, fraccion):
    """El carril de las piezas es 54-68% del alto: los buckets center y bottom lo cruzan."""
    plan = _plan(20000, orientacion="vertical", tray_csv=_csv_cara(tmp_path, fraccion))
    assert plan.piezas == ()
    for plantilla in ("hook", "lower_third", "cierre"):
        assert _motivos(plan)[plantilla] == mp.MOTIVO_CARA


def test_en_vertical_sin_csv_la_franja_se_considera_ocupada():
    """Fail-open conservador: sin dato de la cara no se puede afirmar que el letrero no la tape."""
    plan = _plan(20000, orientacion="vertical", tray_csv=None)
    assert plan.piezas == ()
    for plantilla in ("hook", "lower_third", "cierre"):
        assert _motivos(plan)[plantilla] == mp.MOTIVO_CARA


def test_en_vertical_un_csv_legacy_sin_columna_vertical_tambien_ocupa(tmp_path):
    ruta = tmp_path / "trayectoria_legacy.csv"
    ruta.write_text("t,x,y\n0.0,1,2\n1.0,1,2\n", encoding="utf-8")
    assert _plan(20000, orientacion="vertical", tray_csv=ruta).piezas == ()


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
    assert plan.piezas[-1].texto["cta"] == TEXTOS.cta


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
