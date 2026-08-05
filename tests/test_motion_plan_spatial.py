"""HF-4 Paso 1: la colocacion espacial (motion_plan_spatial) separada del planificador temporal.

`colocar_bandas` reasigna banda sobre piezas YA temporizadas por `motion_plan.planificar()`, sin
volver a negociar tiempos ni texto. Estos tests fijan dos cosas: (1) que la reasignacion es
identica a lo que `planificar()` ya hacia internamente (el split no cambia el resultado), y
(2) el caso limite de la franja de captions por orientacion (D51 / Paso 1 de HF-4).
"""

from __future__ import annotations

import csv

import motion_plan as mp
import motion_plan_spatial as mps

TEXTOS = mp.TextosMarca(
    titulo="Entrena tu LoRA en 20 minutos",
    kicker="",
    nombre="Carlos Daniel Penagos",
    rol="Prompt Models Studio",
    cta="Sigue para más",
)


def _csv_cara(tmp_path, fraccion, t_max=60.0):
    ruta = tmp_path / "trayectoria_x.csv"
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "conf_asignada", "face_y_asignada"])
        t = 0.0
        while t <= t_max:
            w.writerow([f"{t:.2f}", "0.9", f"{fraccion:.3f}"])
            t += 0.5
    return ruta


# ── El split no cambia el resultado ───────────────────────────────────────────


def test_colocar_bandas_reproduce_exactamente_la_banda_de_planificar_vertical(tmp_path):
    tray_csv = _csv_cara(tmp_path, 0.55)  # cara "center" -> banda superior
    plan = mp.planificar(
        duracion_ms=20000, orientacion="vertical", textos=TEXTOS, tray_csv=tray_csv
    )
    recolocadas = mps.colocar_bandas(plan.piezas, orientacion="vertical", tray_csv=tray_csv)
    assert recolocadas == plan.piezas


def test_colocar_bandas_reproduce_exactamente_la_banda_de_planificar_horizontal():
    plan = mp.planificar(duracion_ms=20000, orientacion="horizontal", textos=TEXTOS)
    recolocadas = mps.colocar_bandas(plan.piezas, orientacion="horizontal", tray_csv=None)
    assert recolocadas == plan.piezas


def test_colocar_bandas_solo_toca_banda_nunca_tiempo_ni_texto_ni_plantilla():
    """El contrato central del Paso 1: temporal una vez, espacial por formato. Un plan sacado
    en vertical y re-colocado en horizontal debe tener LAS MISMAS piezas salvo `banda`."""
    plan_vertical = mp.planificar(duracion_ms=20000, orientacion="vertical", textos=TEXTOS)
    recolocadas = mps.colocar_bandas(plan_vertical.piezas, orientacion="horizontal", tray_csv=None)

    assert [p.plantilla for p in recolocadas] == [p.plantilla for p in plan_vertical.piezas]
    assert [p.t0_ms for p in recolocadas] == [p.t0_ms for p in plan_vertical.piezas]
    assert [p.t1_ms for p in recolocadas] == [p.t1_ms for p in plan_vertical.piezas]
    assert [p.texto for p in recolocadas] == [p.texto for p in plan_vertical.piezas]
    assert [p.tramo_t0 for p in recolocadas] == [p.tramo_t0 for p in plan_vertical.piezas]
    # Horizontal siempre manda a la banda superior (banda_libre), independiente de lo que haya
    # decidido la pasada vertical.
    assert {p.banda for p in recolocadas} == {mps.BANDA_ARRIBA}


def test_colocar_bandas_no_llama_ni_al_llm_ni_a_pexels():
    """Es sincrono y puro: si aceptara algo que no sea la tupla de piezas + orientacion + csv,
    este test lo detectaria por firma. Documentado en vez de mockeado: `colocar_bandas` no
    importa ni `brain`, ni `motion_textos_llm`, ni `auto_broll` en absoluto (ver el modulo)."""
    import inspect

    firma = inspect.signature(mps.colocar_bandas)
    assert set(firma.parameters) == {"piezas", "orientacion", "tray_csv"}


# ── Franja de captions por orientacion (D51 / Paso 1 de HF-4) ────────────────


def test_banda_inferior_sigue_invadiendo_captions_en_vertical_y_en_horizontal():
    """Caso limite verificado a mano: RANGO_INFERIOR = (0.68, 0.82) sigue invadiendo tanto la
    zona vertical (0.802-0.899) como la horizontal (0.725-0.899) con los numeros REALES medidos,
    igual que invadia el (0.70, 0.92) compartido que existia antes del Paso 1."""
    for orientacion in mp.ORIENTACIONES:
        assert mps.banda_invade_captions(mps.BANDA_INFERIOR, orientacion) is True


def test_banda_centro_y_arriba_no_invaden_captions_en_ninguna_orientacion():
    for orientacion in mp.ORIENTACIONES:
        assert mps.banda_invade_captions(mps.BANDA_CENTRO, orientacion) is False
        assert mps.banda_invade_captions(mps.BANDA_ARRIBA, orientacion) is False


def test_la_franja_de_captions_es_distinta_por_orientacion():
    """El motivo de existir del Paso 1: antes las dos orientaciones comparaban contra el mismo
    numero. Ahora horizontal tiene MAS margen (empieza antes, en 0.725) que vertical (0.802)."""
    assert (
        mps.ZONA_CAPTIONS_POR_ORIENTACION["horizontal"][0]
        < mps.ZONA_CAPTIONS_POR_ORIENTACION["vertical"][0]
    )


def test_banda_invade_captions_con_orientacion_desconocida_no_revienta():
    assert mps.banda_invade_captions(mps.BANDA_CENTRO, "diagonal") is False
