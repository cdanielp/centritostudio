"""HF-4 Formato dual: `motion_capa.plan_para_otro_formato` y el enganche `plan_precomputado`
de `clips_de_motion`/`_clips_de_motion`.

El contrato central: una pierna EXTRA de formato reusa el plan TEMPORAL de la pierna primaria
(piezas/tiempos/textos) y SOLO redistribuye banda -- cero llamadas al LLM ni a Pexels. Estos
tests no tocan HyperFrames real (eso lo cubre `tests/test_hf4_formato_real.py`, `hf_real`).
"""

from __future__ import annotations

from pathlib import Path

import motion_capa as mc
import motion_plan as mp

RAIZ = Path(__file__).resolve().parents[1]


def _pieza(nombre="hook", t0=0, dur=2500, texto=None, banda=mp.BANDA_CENTRO):
    return mp.Pieza(nombre, t0, t0 + dur, texto or {"kicker": "", "titulo": "T"}, banda=banda)


# ── plan_para_otro_formato: re-banda sin tocar tiempo/texto/plantilla ────────


def test_reusa_piezas_temporales_solo_cambia_banda():
    base = mp.PlanMotion(
        orientacion="vertical",
        piezas=(
            _pieza("hook", 0, banda=mp.BANDA_CENTRO),
            _pieza("cierre", 10000, banda=mp.BANDA_ARRIBA),
        ),
    )
    plan, origen = mc.plan_para_otro_formato(
        base,
        clip_mp4=None,
        duracion_ms=20000,
        orientacion="horizontal",
        tray_csv=None,
        catalogo=set(),
    )
    assert origen == "automatico"
    assert plan.orientacion == "horizontal"
    assert [p.plantilla for p in plan.piezas] == ["hook", "cierre"]
    assert [p.t0_ms for p in plan.piezas] == [0, 10000]
    assert [p.t1_ms for p in plan.piezas] == [2500, 12500]
    assert [p.texto for p in plan.piezas] == [
        {"kicker": "", "titulo": "T"},
        {"kicker": "", "titulo": "T"},
    ]
    # horizontal siempre manda a la banda superior, sea cual sea la banda de la primaria
    assert {p.banda for p in plan.piezas} == {mp.BANDA_ARRIBA}


def test_no_llama_al_llm_ni_toca_disco_sin_clip_mp4():
    """Sin clip_mp4 no hay sidecar que consultar ni sellar: la funcion es pura."""
    base = mp.PlanMotion(orientacion="vertical", piezas=(_pieza(),))
    plan, origen = mc.plan_para_otro_formato(
        base,
        clip_mp4=None,
        duracion_ms=20000,
        orientacion="horizontal",
        tray_csv=None,
        catalogo=set(),
    )
    assert origen == "automatico"
    assert len(plan.piezas) == 1


def test_preserva_las_omisiones_de_la_pierna_primaria():
    base = mp.PlanMotion(
        orientacion="vertical",
        piezas=(_pieza(),),
        omisiones=(mp.Omision("titulo_seccion", "sin_hueco_que_rellenar"),),
    )
    plan, _ = mc.plan_para_otro_formato(
        base,
        clip_mp4=None,
        duracion_ms=20000,
        orientacion="horizontal",
        tray_csv=None,
        catalogo=set(),
    )
    assert plan.omisiones == base.omisiones


def test_pieza_que_invade_captions_en_este_formato_se_omite_con_motivo(monkeypatch):
    """Caso limite (no alcanzable hoy con los 5 templates reales, pero el mecanismo debe
    existir): si `banda_invade_captions` dice que la banda asignada pisa la franja de captions
    DE ESTE formato, la pieza se cae de `piezas` y entra a `omisiones` con motivo propio."""
    monkeypatch.setattr(mc.mps, "banda_invade_captions", lambda banda, orientacion: True)
    base = mp.PlanMotion(orientacion="vertical", piezas=(_pieza("hook"), _pieza("cierre", 10000)))
    plan, _ = mc.plan_para_otro_formato(
        base,
        clip_mp4=None,
        duracion_ms=20000,
        orientacion="horizontal",
        tray_csv=None,
        catalogo=set(),
    )
    assert plan.piezas == ()
    motivos = {o.motivo for o in plan.omisiones}
    assert motivos == {mc.MOTIVO_BANDA_INVADE_CAPTIONS_EN_FORMATO}
    assert {o.plantilla for o in plan.omisiones} == {"hook", "cierre"}


def test_un_plan_editado_para_este_clip_manda_sobre_el_derivado(tmp_path, monkeypatch):
    import motion_edicion as me

    clip = tmp_path / "clip_16x9.mp4"
    clip.write_bytes(b"x")
    editado = mp.PlanMotion(
        orientacion="horizontal", piezas=(_pieza("hook", banda=mp.BANDA_ARRIBA),)
    )
    monkeypatch.setattr(
        me, "cargar", lambda *a, **kw: editado if kw.get("orientacion") == "horizontal" else None
    )
    base = mp.PlanMotion(orientacion="vertical", piezas=(_pieza("cierre", 10000),))
    plan, origen = mc.plan_para_otro_formato(
        base,
        clip_mp4=clip,
        duracion_ms=20000,
        orientacion="horizontal",
        tray_csv=None,
        catalogo=set(),
    )
    assert origen == me.ORIGEN_EDITADO
    assert [p.plantilla for p in plan.piezas] == ["hook"]  # el editado, no el derivado


# ── clips_de_motion(plan_precomputado=...) salta resolver_plan ───────────────


def test_plan_precomputado_nunca_llama_a_resolver_plan(monkeypatch, tmp_path):
    def explota(**kw):
        raise AssertionError("resolver_plan no debe llamarse con plan_precomputado")

    monkeypatch.setattr(mc, "resolver_plan", explota)
    plan_vacio = mp.PlanMotion(orientacion="horizontal", piezas=())
    r = mc.clips_de_motion(
        opciones=mc.OpcionesMotion(enabled=True),
        ancho=1920,
        alto=1080,
        fps=30,
        duracion_s=20.0,
        raiz_cache=tmp_path,
        root=RAIZ,
        plan_precomputado=(plan_vacio, "automatico"),
    )
    # plan vacio -> corta ANTES de tocar HyperFrames (sin piezas no hay nada que pedir)
    assert r.clips == ()
    assert r.informe["plan"]["piezas"] == []


def test_sin_plan_precomputado_si_llama_a_resolver_plan(monkeypatch, tmp_path):
    llamado = []
    plan_vacio = mp.PlanMotion(orientacion="horizontal", piezas=())

    def fake_resolver_plan(**kw):
        llamado.append(kw.get("orientacion"))
        return plan_vacio, "automatico"

    monkeypatch.setattr(mc, "resolver_plan", fake_resolver_plan)
    mc.clips_de_motion(
        opciones=mc.OpcionesMotion(enabled=True),
        ancho=1080,
        alto=1920,
        fps=30,
        duracion_s=20.0,
        raiz_cache=tmp_path,
        root=RAIZ,
    )
    assert llamado == ["vertical"]
