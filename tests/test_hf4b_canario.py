"""HF-4b: canario D50.5 sobre CADA plantilla tocada en esta sesion, en los dos sentidos.

Plantillas tocadas: hook, cierre, titulo_seccion y dato_destacado (ancla del Paso 1, en la
regla base de `index.html` que rige su gemelo horizontal) y lower_third_minimo (contraste del
rol, Paso 4, vertical Y horizontal). Mismo patron que
`test_hf4_estilo_real.py::test_canario_de_influencia_por_estilo_nuevo`:

1. Mismo pedido, dos veces -> mismo sha256 (el render es reproducible; sin esto el canario
   de abajo no puede detectar nada).
2. Un campo de texto distinto -> sha256 DISTINTO (el cambio de verdad llega a la plantilla).

    venv\\Scripts\\python -m pytest tests/test_hf4b_canario.py -m hf_real -q
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pytestmark = pytest.mark.hf_real

RAIZ = Path(__file__).resolve().parents[1]

# (plantilla, orientacion, ancho, alto, texto_base, campo_a_variar)
CASOS = [
    (
        "hook", "horizontal", 1920, 1080,
        {"kicker": "DATO", "titulo": "Un titulo cualquiera"}, "titulo",
    ),
    ("cierre", "horizontal", 1920, 1080, {"titulo": "Un cierre", "cta": "Sigue"}, "titulo"),
    ("titulo_seccion", "horizontal", 1920, 1080, {"titulo": "Una seccion"}, "titulo"),
    (
        "dato_destacado", "horizontal", 1920, 1080,
        {"cifra": "42%", "etiqueta": "crecimiento"}, "etiqueta",
    ),
    (
        "lower_third_minimo",
        "vertical",
        1080,
        1920,
        {"nombre": "Carlos Daniel Penagos", "rol": "Prompt Models Studio"},
        "rol",
    ),
    (
        "lower_third_minimo",
        "horizontal",
        1920,
        1080,
        {"nombre": "Carlos Daniel Penagos", "rol": "Prompt Models Studio"},
        "rol",
    ),
]


def _pedir(plantilla, orientacion, ancho, alto, texto, tmp_path):
    import motion_capa as mc
    import motion_plan as mp
    from hyperframes import pedir_pieza
    from hyperframes.catalogo import Catalogo

    nombre_pieza, estilo = (
        (plantilla.replace("_minimo", ""), "minimo")
        if plantilla.endswith("_minimo")
        else (plantilla, None)
    )
    dur = mp.DURACION_MS[nombre_pieza]
    pieza = mp.Pieza(nombre_pieza, 0, dur, dict(texto), banda=mp.BANDA_CENTRO)
    versiones = mc.versiones_del_catalogo(RAIZ / "motion" / "catalogo.json")
    kwargs = {"estilo": estilo} if estilo else {}
    if estilo:
        nombre_resuelto, version_resuelta, cayo = mc.resolver_estilo(
            nombre_pieza, estilo, versiones
        )
        assert not cayo, f"'{estilo}' deberia existir para {nombre_pieza}"
    else:
        nombre_resuelto, version_resuelta = nombre_pieza, versiones[nombre_pieza]
    dato = mc.contrato_de_pieza(
        pieza,
        version=version_resuelta,
        nombre_plantilla=nombre_resuelto,
        ancho=ancho,
        alto=alto,
        fps=30,
        marca=mc.marca_de(nombre_resuelto, mc.MARCA),
        **kwargs,
    )
    catalogo = Catalogo.desde_archivo(RAIZ / "motion" / "catalogo.json", orientacion)
    return pedir_pieza(
        dato, destino=(ancho, alto), catalogo=catalogo, raiz_cache=tmp_path, timeout_s=180
    )


@pytest.mark.skipif(shutil.which("npx") is None, reason="npx no esta instalado")
@pytest.mark.parametrize(
    "plantilla,orientacion,ancho,alto,texto,campo", CASOS, ids=[f"{c[0]}-{c[1]}" for c in CASOS]
)
def test_canario_de_influencia(plantilla, orientacion, ancho, alto, texto, campo, tmp_path):
    variante = dict(texto, **{campo: texto[campo] + " (variante del canario)"})

    uno = _pedir(plantilla, orientacion, ancho, alto, texto, tmp_path / "cache")
    testigo = _pedir(plantilla, orientacion, ancho, alto, texto, tmp_path / "cache_testigo")
    otro = _pedir(plantilla, orientacion, ancho, alto, variante, tmp_path / "cache")

    assert uno.razon_fallo is None, f"{plantilla}/{orientacion}: {uno.razon_fallo} {uno.detalle}"
    assert testigo.razon_fallo is None, f"{plantilla}/{orientacion}: {testigo.razon_fallo}"
    assert otro.razon_fallo is None, f"{plantilla}/{orientacion}: {otro.razon_fallo} {otro.detalle}"

    assert uno.sha256 == testigo.sha256, (
        f"{plantilla}/{orientacion}: el render no es reproducible, el canario no detecta nada"
    )
    assert uno.sha256 != otro.sha256, (
        f"{plantilla}/{orientacion}: el campo {campo!r} no llego a la plantilla"
    )
