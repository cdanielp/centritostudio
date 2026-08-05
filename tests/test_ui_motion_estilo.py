"""HF-4: selector de "Estilo de letreros" en el Studio (Automatico v2).

No renderiza ni levanta un navegador: fija el HTML/JS del bloque tal como vive en
`static/index.html` contra las reglas duras del brief (espanol, sin em dash, cuatro
miniaturas, lectura fresca del radio marcado en vez de una variable cacheada).
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")


def _visibles(desde: str, hasta: str) -> str:
    """Texto de un bloque de UI (el que ve una persona), igual que en test_ui_srt_parcial.

    Busca `hasta` DESPUES del final de `desde`, no desde su inicio: si `hasta` fuera una
    subcadena generica que tambien aparece dentro de `desde` (p.ej. "async function "
    contra "async function startAuto()"), buscar desde `i` encontraria el propio `desde`
    y devolveria un bloque vacio.
    """
    i = HTML.index(desde)
    return HTML[i : HTML.index(hasta, i + len(desde))]


def _bloque_selector() -> str:
    return _visibles('id="auto-motion-estilo-grupo"', "usa PMS.</span>") + "usa PMS.</span>"


def test_el_selector_de_estilo_existe_con_cuatro_opciones():
    bloque = _bloque_selector()
    for valor in ("pms", "claro", "minimo", "rudo"):
        assert f'value="{valor}"' in bloque, f"falta la opcion de estilo '{valor}'"


def test_pms_es_la_opcion_marcada_por_default():
    bloque = _bloque_selector()
    i = bloque.index('value="pms"')
    # El atributo checked vive en el mismo <input> que value="pms": entre el value y el
    # siguiente '>' no puede haber otro '<input', o checked pertenece a otra opcion.
    cierre = bloque.index(">", i)
    assert "checked" in bloque[i:cierre], "PMS no es el default marcado"
    for valor in ("claro", "minimo", "rudo"):
        j = bloque.index(f'value="{valor}"')
        cierre_j = bloque.index(">", j)
        assert "checked" not in bloque[j:cierre_j], f"'{valor}' no deberia venir marcado"


def test_cada_opcion_de_estilo_lleva_miniatura():
    """Paso 4: elegir viendo, no leyendo. Un selector solo de texto no cumple esto."""
    bloque = _bloque_selector()
    assert bloque.count("<img") == 4, "cada una de las cuatro opciones debe traer un <img>"
    for valor, archivo in (
        ("pms", "estilo_pms.png"),
        ("claro", "estilo_claro.png"),
        ("minimo", "estilo_minimo.png"),
        ("rudo", "estilo_rudo.png"),
    ):
        assert archivo in bloque, f"falta la miniatura de '{valor}'"
        assert (ROOT / "static" / "previews" / archivo).is_file(), (
            f"la miniatura {archivo} no existe en disco"
        )


def test_las_etiquetas_del_selector_estan_en_espanol():
    bloque = _bloque_selector()
    assert "Estilo de letreros" not in HTML or 'aria-label="Estilo de letreros"' in bloque
    for etiqueta in ("PMS", "Claro", "Mínimo", "Rudo"):
        assert etiqueta in bloque, f"falta la etiqueta en espanol '{etiqueta}'"


def test_el_bloque_del_selector_no_lleva_em_dash():
    bloque = _bloque_selector()
    for linea in bloque.splitlines():
        visible = linea.strip()
        if visible.startswith("//") or visible.startswith("<!--"):
            continue
        assert "—" not in visible, visible


def test_el_valor_se_lee_del_radio_marcado_no_de_una_variable_cacheada():
    """Leccion de D45/D49: el estado no debe vivir suelto en una variable JS que un repintado
    del DOM pueda dejar desactualizada. `autoMotionEstiloValue()` debe consultar el DOM cada vez."""
    bloque_js = _visibles("function autoMotionEstiloValue()", "function setAutoControlsLocked")
    assert "querySelector" in bloque_js, "debe leer el radio marcado del DOM, no una variable"
    assert ":checked" in bloque_js


def test_start_auto_lee_el_estilo_fresco_en_el_envio():
    bloque = _visibles("async function startAuto()", "async function ")
    assert "autoMotionEstiloValue()" in bloque
    assert "motion_estilo" in bloque
