"""HF-3 bloque 2: las dos deudas que arrastraba la capa desde HF-1 y HF-2.

2.1 `semilla` entraba a la clave de cache y NINGUNA plantilla la lee. Cambiarla invalidaba la
    cache para producir un archivo identico al que ya estaba guardado.
2.2 Los cinco gemelos horizontales declaraban el lienzo dos veces con valores distintos.
    (Se fija en `test_hf2_catalogo`, junto al resto del contrato del catalogo.)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from hf_dobles import ENTORNO
from hf_dobles import pieza as _pieza

from hyperframes import contrato as ct

RAIZ = Path(__file__).resolve().parents[1]
PIEZAS = ("hook", "lower_third", "titulo_seccion", "dato_destacado", "cierre")


def test_la_semilla_no_entra_a_la_clave_de_cache():
    """Dos contratos que solo difieren en semilla comparten pieza, luego comparten clave."""
    a = ct.calcular_hash(_pieza(semilla=0), ENTORNO)
    b = ct.calcular_hash(_pieza(semilla=7), ENTORNO)
    assert a == b


def test_lo_que_si_influye_sigue_cambiando_la_clave():
    """El freno del punto anterior no puede haberse llevado por delante nada mas."""
    base = ct.calcular_hash(_pieza(), ENTORNO)
    for cambio in (
        {"duracion_ms": 9999},
        {"fps": 24},
        {"fit": "cover"},
        {"audio": True},
        {"tamano": {"ancho": 1080, "alto": 1920}},
        {"texto": {"kicker": "otra", "titulo": "cosa"}},
        {"marca": {"primario": "#000000", "secundario": "#111111", "texto": "#FFFFFF"}},
        {"plantilla": {"nombre": "hook", "version": "9.9.9"}},
    ):
        assert ct.calcular_hash(_pieza(**cambio), ENTORNO) != base, cambio


def test_la_semilla_sigue_siendo_un_campo_obligatorio_del_contrato():
    """Sacarla del hash no la saca del esquema: las plantillas siguen declarandola."""
    assert "semilla" in ct.ESQUEMA
    assert ct.CAMPOS_FUERA_DEL_HASH == ("semilla",)


def test_ninguna_plantilla_del_catalogo_consume_la_semilla():
    """La premisa de 2.1, comprobada contra el catalogo real y no de memoria.

    Se declara en las diez plantillas por el aplanado de variables, pero ningun script la lee.
    El dia que una la use, este test truena y hay que sacarla de CAMPOS_FUERA_DEL_HASH.
    """
    usos = []
    for nombre in PIEZAS:
        for sufijo in ("", "/horizontal"):
            html = (RAIZ / "motion" / nombre / sufijo.lstrip("/") / "index.html").read_text(
                encoding="utf-8"
            )
            cuerpo = html.split("data-composition-variables=", 1)[-1].split("]'>", 1)[-1]
            if re.search(r"\bv\.semilla\b|\bsemilla\b\s*[)\].,;]", cuerpo):
                usos.append(f"{nombre}{sufijo}")
    assert usos == [], f"estas plantillas ya consumen semilla: {usos}"


def test_las_diez_plantillas_declaran_la_semilla():
    for nombre in PIEZAS:
        for sufijo in ("", "horizontal"):
            html = (RAIZ / "motion" / nombre / sufijo / "index.html").read_text(encoding="utf-8")
            assert '"id":"semilla"' in html, f"{nombre}/{sufijo}"


def test_el_catalogo_declara_un_proyecto_por_orientacion():
    """Decision 1 del arranque de HF-3: la orientacion es un CAMPO, no una convencion de ruta."""
    datos = json.loads((RAIZ / "motion" / "catalogo.json").read_text(encoding="utf-8"))
    for d in datos:
        assert set(d["proyecto"]) == {"vertical", "horizontal"}
        assert (RAIZ / d["proyecto"]["vertical"] / "index.html").is_file()
        assert (RAIZ / d["proyecto"]["horizontal"] / "index.html").is_file()
