"""HF-3: los textos de los letreros los escribe el LLM, con las reglas de respaldo.

Ninguna prueba de aqui toca la red: el proveedor se sustituye por un doble. Lo que se fija es
el CONTRATO, no las frases concretas: que la respuesta se sanee campo a campo, que la cache no
vuelva a llamar, que un fallo caiga a las reglas y que el planificador siga decidiendo DONDE va
cada pieza aunque el modelo escriba QUE dice.
"""

from __future__ import annotations

import json

import pytest

import motion_plan as mp
import motion_textos_llm as tl

TRAMOS = [
    mp.Tramo(0, 3000, "hoy hablamos de la desercion escolar"),
    mp.Tramo(9000, 12000, "diez y medio por ciento de los alumnos la dejaron"),
    mp.Tramo(30000, 34000, "y por eso los traslados importan tanto"),
]
DUR = 60000

RESPUESTA = {
    "hook_titulo": "La desercion escolar se disparo",
    "hook_kicker": "DATO",
    "secciones": [{"t0_ms": 30000, "titulo": "Los traslados son el problema"}],
    "dato_cifra": "10.5%",
    "dato_etiqueta": "de alumnos dejo la escuela",
    "dato_t0_ms": 9000,
    "cierre_titulo": "Sin transporte no hay escuela",
}


@pytest.fixture
def llm(monkeypatch, tmp_path):
    """Doble del proveedor que cuenta llamadas, y `transcripts/` redirigido al tmp."""
    import brain

    llamadas = []

    def _dispatch(messages):
        llamadas.append(messages)
        return json.loads(json.dumps(RESPUESTA)), {"total": 100}

    monkeypatch.setattr(brain, "_dispatch", _dispatch)
    monkeypatch.setattr(tl, "TRANSCRIPTS", tmp_path)
    return llamadas


# ── La llamada y su cache ────────────────────────────────────────────────────


def test_la_primera_corrida_llama_y_devuelve_los_textos(llm):
    textos = tl.pedir_textos(TRAMOS, DUR, stem="clip")
    assert len(llm) == 1
    assert textos.hook_titulo == "La desercion escolar se disparo"
    assert textos.dato_cifra == "10.5%"
    assert textos.secciones == ((30000, "Los traslados son el problema"),)


def test_la_segunda_corrida_no_llama_al_llm(llm):
    tl.pedir_textos(TRAMOS, DUR, stem="clip")
    tl.pedir_textos(TRAMOS, DUR, stem="clip")
    assert len(llm) == 1, "la segunda corrida volvio a llamar al proveedor"


def test_la_segunda_corrida_devuelve_lo_mismo(llm):
    uno = tl.pedir_textos(TRAMOS, DUR, stem="clip")
    otro = tl.pedir_textos(TRAMOS, DUR, stem="clip")
    assert uno.a_dict() == otro.a_dict()


def test_forzar_salta_la_cache(llm):
    tl.pedir_textos(TRAMOS, DUR, stem="clip")
    tl.pedir_textos(TRAMOS, DUR, stem="clip", forzar=True)
    assert len(llm) == 2


def test_cambiar_el_texto_invalida_la_cache(llm):
    tl.pedir_textos(TRAMOS, DUR, stem="clip")
    otros = [*TRAMOS, mp.Tramo(40000, 42000, "una frase mas que antes no estaba")]
    tl.pedir_textos(otros, DUR, stem="clip")
    assert len(llm) == 2


def test_mover_un_tramo_invalida_la_cache(llm):
    """Al reves que en el brain: aqui el modelo VE los tiempos y los devuelve en `t0_ms`."""
    tl.pedir_textos(TRAMOS, DUR, stem="clip")
    movidos = [mp.Tramo(t.t0_ms + 500, t.t1_ms + 500, t.texto) for t in TRAMOS]
    tl.pedir_textos(movidos, DUR, stem="clip")
    assert len(llm) == 2


def test_editar_el_prompt_invalida_la_cache(llm, monkeypatch):
    tl.pedir_textos(TRAMOS, DUR, stem="clip")
    monkeypatch.setattr(tl, "_SYSTEM", tl._SYSTEM + " Se muy breve.")
    tl.pedir_textos(TRAMOS, DUR, stem="clip")
    assert len(llm) == 2


def test_cambiar_de_modelo_invalida_la_cache(llm, monkeypatch):
    import brain

    tl.pedir_textos(TRAMOS, DUR, stem="clip")
    monkeypatch.setattr(brain, "MODEL", "otro-modelo")
    tl.pedir_textos(TRAMOS, DUR, stem="clip")
    assert len(llm) == 2


# ── Fail-open ────────────────────────────────────────────────────────────────


def test_una_respuesta_vacia_cae_a_las_reglas(monkeypatch, tmp_path):
    import brain

    monkeypatch.setattr(tl, "TRANSCRIPTS", tmp_path)
    monkeypatch.setattr(brain, "_dispatch", lambda m: ({}, {}))
    assert tl.pedir_textos(TRAMOS, DUR, stem="clip") is None


def test_un_proveedor_que_explota_cae_a_las_reglas(monkeypatch, tmp_path):
    import brain

    def explota(_m):
        raise RuntimeError("sin clave")

    monkeypatch.setattr(tl, "TRANSCRIPTS", tmp_path)
    monkeypatch.setattr(brain, "_dispatch", explota)
    assert tl.pedir_textos(TRAMOS, DUR, stem="clip") is None


def test_sin_tramos_no_se_llama(llm):
    assert tl.pedir_textos([], DUR, stem="clip") is None
    assert llm == []


def test_un_sidecar_corrupto_no_tumba_nada(llm, tmp_path):
    tl.ruta_sidecar("clip").write_text("{no es json", encoding="utf-8")
    assert tl.pedir_textos(TRAMOS, DUR, stem="clip") is not None
    assert len(llm) == 1


# ── Saneado campo a campo ────────────────────────────────────────────────────


def test_un_campo_malo_no_tira_la_respuesta_entera():
    """Si el modelo acerta con el hook y falla con la cifra, se usa el hook."""
    textos = tl.sanear({**RESPUESTA, "dato_cifra": 42}, DUR)
    assert textos.hook_titulo == RESPUESTA["hook_titulo"]
    assert textos.dato_cifra == ""


def test_un_texto_que_no_cabe_se_descarta():
    largo = "x" * (tl.LIMITES["hook_titulo"] + 1)
    assert tl.sanear({**RESPUESTA, "hook_titulo": largo}, DUR).hook_titulo == ""


def test_una_etiqueta_sin_cifra_se_descarta():
    """Una etiqueta suelta no significa nada: acompana a un numero que no esta."""
    textos = tl.sanear({**RESPUESTA, "dato_cifra": ""}, DUR)
    assert textos.dato_etiqueta == ""
    assert textos.dato_t0_ms is None


def test_una_seccion_fuera_del_clip_se_descarta():
    mala = {**RESPUESTA, "secciones": [{"t0_ms": DUR + 5000, "titulo": "Fuera de rango"}]}
    assert tl.sanear(mala, DUR).secciones == ()


def test_las_secciones_salen_ordenadas_y_acotadas():
    muchas = [{"t0_ms": 1000 * i, "titulo": f"Tema numero {i} del clip"} for i in range(20, 0, -1)]
    secciones = tl.sanear({**RESPUESTA, "secciones": muchas}, DUR).secciones
    assert len(secciones) <= tl.MAX_SECCIONES
    assert list(secciones) == sorted(secciones, key=lambda x: x[0])


def test_una_respuesta_sin_nada_util_es_none():
    assert tl.sanear({"hook_titulo": "", "secciones": []}, DUR) is None
    assert tl.sanear("no es un objeto", DUR) is None


# ── El LLM propone, el planificador dispone ──────────────────────────────────


def _textos_marca():
    return mp.TextosMarca(titulo="Titulo de reglas", nombre="N", rol="R", cta="C")


def test_los_textos_del_llm_sustituyen_a_los_de_las_reglas():
    llm = tl.sanear(RESPUESTA, DUR)
    plan = mp.planificar(
        duracion_ms=DUR, orientacion="horizontal", textos=_textos_marca(), tramos=TRAMOS, llm=llm
    )
    hook = next(p for p in plan.piezas if p.plantilla == "hook")
    assert hook.texto["titulo"] == RESPUESTA["hook_titulo"]
    assert hook.texto["kicker"] == RESPUESTA["hook_kicker"]
    cierre = next(p for p in plan.piezas if p.plantilla == "cierre")
    assert cierre.texto["titulo"] == RESPUESTA["cierre_titulo"]


def test_el_llm_coloca_el_dato_que_las_reglas_no_reconocen():
    """ "diez y medio por ciento" no lleva unidad literal: la regla lo descarta, el modelo no."""
    sin_llm = mp.planificar(
        duracion_ms=DUR, orientacion="horizontal", textos=_textos_marca(), tramos=TRAMOS
    )
    assert "dato_destacado" not in [p.plantilla for p in sin_llm.piezas]

    con_llm = mp.planificar(
        duracion_ms=DUR,
        orientacion="horizontal",
        textos=_textos_marca(),
        tramos=TRAMOS,
        llm=tl.sanear(RESPUESTA, DUR),
    )
    dato = next(p for p in con_llm.piezas if p.plantilla == "dato_destacado")
    assert dato.texto["cifra"] == "10.5%"


def test_el_planificador_sigue_decidiendo_donde_va_cada_pieza():
    """El modelo escribe; el techo, la separacion y los limites del clip no los toca."""
    llm = tl.sanear(RESPUESTA, DUR)
    plan = mp.planificar(
        duracion_ms=DUR, orientacion="horizontal", textos=_textos_marca(), tramos=TRAMOS, llm=llm
    )
    piezas = sorted(plan.piezas, key=lambda p: p.t0_ms)
    assert len(piezas) <= mp.techo_de_piezas(DUR)
    for previa, siguiente in zip(piezas, piezas[1:], strict=False):
        assert siguiente.t0_ms - previa.t1_ms >= mp.SEPARACION_MIN_MS
    for pieza in piezas:
        assert pieza.t1_ms <= DUR
        assert pieza.duracion_ms == mp.DURACION_MS[pieza.plantilla]


def test_sin_llm_el_plan_es_exactamente_el_de_las_reglas():
    """El respaldo no se toco: pasar `llm=None` da el mismo plan de siempre."""
    a = mp.planificar(
        duracion_ms=DUR, orientacion="horizontal", textos=_textos_marca(), tramos=TRAMOS
    )
    b = mp.planificar(
        duracion_ms=DUR, orientacion="horizontal", textos=_textos_marca(), tramos=TRAMOS, llm=None
    )
    assert a.a_dict() == b.a_dict()


def test_un_campo_vacio_del_llm_cae_al_respaldo_de_reglas():
    """Campo a campo: si el modelo no trae hook, manda el titulo del clipper."""
    parcial = tl.sanear({**RESPUESTA, "hook_titulo": ""}, DUR)
    plan = mp.planificar(
        duracion_ms=DUR,
        orientacion="horizontal",
        textos=_textos_marca(),
        tramos=TRAMOS,
        llm=parcial,
    )
    hook = next(p for p in plan.piezas if p.plantilla == "hook")
    assert hook.texto["titulo"] == "Titulo de reglas"


# ── El flag ──────────────────────────────────────────────────────────────────


def test_el_default_es_usar_el_llm():
    import motion_capa
    from auto_config import AutoConfig

    assert motion_capa.OpcionesMotion().textos_llm is True
    assert AutoConfig().motion_textos_llm is True


def test_la_cli_puede_apagar_el_llm():
    from caption_args import build_parser, motion_opts_de_args

    args = build_parser().parse_args(["input/x.mp4", "--motion", "--motion-sin-llm"])
    assert motion_opts_de_args(args).textos_llm is False
    args = build_parser().parse_args(["input/x.mp4", "--motion"])
    assert motion_opts_de_args(args).textos_llm is True


def test_apagar_el_llm_sin_la_capa_es_error():
    from caption_args import build_parser, motion_opts_de_args

    args = build_parser().parse_args(["input/x.mp4", "--motion-sin-llm"])
    with pytest.raises(SystemExit, match="--motion-sin-llm"):
        motion_opts_de_args(args)


def test_con_la_capa_apagada_el_flag_no_entra_al_fingerprint():
    from auto_config import AutoConfig

    base = AutoConfig(mode="v2")
    assert base.fingerprint() == AutoConfig(mode="v2", motion_textos_llm=False).fingerprint()
    assert "motion_textos_llm" not in base.to_dict()


def test_con_la_capa_encendida_el_flag_si_cambia_el_fingerprint():
    from auto_config import AutoConfig

    con = AutoConfig(mode="v2", motion_enabled=True)
    sin = AutoConfig(mode="v2", motion_enabled=True, motion_textos_llm=False)
    assert con.fingerprint() != sin.fingerprint()
