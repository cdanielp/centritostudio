"""HF-4, paso 3: control de posicion (Arriba/Centro/Abajo) del editor de letreros en el Studio.

Leccion de D49 (S41, `srt_modo_parcial`): un parametro que la API acepta pero que la UI nunca
deja elegir es, para K, un parametro que no existe. Estos tests fijan que el control vive de
verdad en `static/index.html` -no solo que `motion_edicion.validar_plan` acepte la banda- y que
"Abajo" no se esconde del selector aunque el backend la rechace por pisar los captions.

No renderiza ni levanta un navegador: es analisis estatico del HTML/JS, igual que
`test_ui_motion_estilo.py`.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")


def _visibles(desde: str, hasta: str) -> str:
    i = HTML.index(desde)
    return HTML[i : HTML.index(hasta, i + len(desde))]


def _bloque_editor() -> str:
    return _visibles("const ME_BANDAS", "function meSetTexto")


def test_el_selector_de_posicion_existe_con_tres_opciones():
    bloque = _bloque_editor()
    assert "<select" in bloque
    for valor in ("superior", "centro", "inferior"):
        assert f"'{valor}'" in bloque or f'"{valor}"' in bloque, f"falta la banda '{valor}'"


def test_las_etiquetas_de_posicion_estan_en_espanol():
    bloque = _bloque_editor()
    for etiqueta in ("Arriba", "Centro", "Abajo", "Posición"):
        assert etiqueta in bloque, f"falta la etiqueta en espanol '{etiqueta}'"


def test_abajo_no_se_esconde_del_selector():
    """El backend rechaza 'inferior' por pisar captions, pero el selector la sigue ofreciendo:
    K tiene que poder elegirla y ver el motivo, no encontrarse con una opcion que desaparecio."""
    bloque = _bloque_editor()
    assert "ME_BANDAS" in bloque
    definicion = _visibles("const ME_BANDAS", ";")
    assert "inferior" in definicion, "la banda 'inferior' (Abajo) esta oculta del selector"


def test_el_selector_esta_cableado_a_meSetBanda():
    bloque = _bloque_editor()
    assert 'onchange="meSetBanda(' in bloque or "onchange='meSetBanda(" in bloque


def test_meSetBanda_muta_el_plan_en_memoria():
    cuerpo = _visibles("function meSetBanda(", "\n}")
    assert "mePlan.piezas[i].banda" in cuerpo


def test_el_bloque_del_editor_no_lleva_em_dash():
    bloque = _bloque_editor()
    for linea in bloque.splitlines():
        visible = linea.strip()
        if visible.startswith("//") or visible.startswith("<!--"):
            continue
        assert "—" not in visible, visible


def test_el_guardado_sigue_mandando_las_piezas_completas():
    """Si guardarPlanLetreros empezara a filtrar campos, 'banda' podria quedarse fuera sin que
    ningun test de motion_edicion lo note: ese validador nunca ve lo que la UI no le manda."""
    bloque = _visibles(
        "async function guardarPlanLetreros()", "async function descartarPlanLetreros"
    )
    assert "piezas: mePlan.piezas" in bloque
