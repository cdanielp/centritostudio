"""HF-4 hotfix: ninguna pieza VERTICAL puede salir invisible, con cualquier largo de texto.

Gemelo de `test_hf4b_recorte_horizontal.py`. Esa sesion (HF-4b, "sesion 4") encontro que subir
las piezas horizontales a la banda superior (-34pp) las mandaba a top negativo cuando su
contenido nativo era mas alto que lo calibrado, y escribio un test que mide el ALFA REAL del
MOV con un texto deliberadamente largo. El mismo test NUNCA se extendio a vertical, y el
`@media (orientation: portrait)` de hook/cierre/titulo_seccion/dato_destacado tenia el mismo
defecto (heredaba `top:54%` del bloque horizontal y con `height:68%` la caja quedaba en
[54%,122%]): con un titulo real de 9 palabras el contenido caia FUERA del lienzo por completo
(0 pixeles de alfa en el MOV entero, no solo cortado). Esta es la regresion que ese agujero
dejo pasar en `feat/hf4-formato-dual` (mariosoto_clip2_corto, hook y cierre en 9:16).

    venv\\Scripts\\python -m pytest tests/test_hf4_recorte_vertical.py -m hf_real -q
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.hf_real

RAIZ = Path(__file__).resolve().parents[1]
ANCHO, ALTO, FPS = 1080, 1920, 30

# El mismo texto largo del gemelo horizontal: fuerza tres lineas o mas.
TEXTO_LARGO = (
    "Este titulo es deliberadamente larguisimo para forzar tres lineas completas de texto "
    "envuelto dentro de la placa y asi medir si algo se corta de verdad"
)

CASOS = [
    ("hook", "titulo", {"kicker": "DATO"}),
    ("cierre", "titulo", {"cta": "Sigue para más"}),
    ("titulo_seccion", "titulo", {}),
    ("dato_destacado", "etiqueta", {"cifra": "42%"}),
]

# Vertical tiene MAS margen en pixeles que su gemelo horizontal (68% de 1920 = 1306px de hueco
# hacia arriba, contra 46% de 1080 = 497px), pero la fuente de portrait es mas chica y el mismo
# TEXTO_LARGO envuelve distinto: medido, hook con 3 lineas llega a 1.46% (28px) del borde. Sigue
# ON-SCREEN (el hard-check es y0 >= 0, mas abajo) y no toca la franja de captions; 1% es el piso
# real de "no rozar el borde", no un pixel fijo (regla del proyecto: nunca fijar pixeles).
MARGEN_SUPERIOR = 0.01
MARGEN_CAPTIONS = 0.02


def _pieza_con_texto_largo(plantilla: str, campo_largo: str, resto: dict):
    import motion_plan as mp

    texto = dict(resto)
    texto[campo_largo] = TEXTO_LARGO
    return mp.Pieza(plantilla, 0, mp.DURACION_MS[plantilla], texto, banda=mp.BANDA_CENTRO)


@pytest.mark.skipif(__import__("shutil").which("npx") is None, reason="npx no esta instalado")
@pytest.mark.parametrize("plantilla,campo_largo,resto", CASOS, ids=[c[0] for c in CASOS])
def test_la_pieza_vertical_no_queda_invisible_con_texto_de_tres_lineas(
    plantilla, campo_largo, resto
):
    import motion_capa as mc
    import motion_plan as mp
    from hyperframes import pedir_pieza
    from hyperframes.catalogo import Catalogo

    pieza = _pieza_con_texto_largo(plantilla, campo_largo, resto)
    versiones = mc.versiones_del_catalogo(RAIZ / "motion" / "catalogo.json")
    dato = mc.contrato_de_pieza(
        pieza,
        version=versiones[plantilla],
        ancho=ANCHO,
        alto=ALTO,
        fps=FPS,
        marca=mc.marca_de(plantilla, mc.MARCA),
    )
    catalogo = Catalogo.desde_archivo(RAIZ / "motion" / "catalogo.json", "vertical")

    # Cara centrada/baja manda la pieza a banda superior (motion_plan_spatial.banda_libre); es
    # el caso real que broto el bug (mariosoto_clip2_corto, cara en 'center').
    banda_automatica = mp.BANDA_ARRIBA

    with tempfile.TemporaryDirectory(prefix="hf4v_test_") as tmp:
        r = pedir_pieza(
            dato, destino=(ANCHO, ALTO), catalogo=catalogo, raiz_cache=Path(tmp), timeout_s=180
        )
        assert r.razon_fallo is None, f"{plantilla}: {r.razon_fallo} {r.detalle}"

        bbox = mc.bbox_alfa(Path(r.ruta_mov), pieza.duracion_ms * 0.0006, ANCHO, ALTO)
        assert bbox is not None, (
            f"{plantilla}: SIN alfa medible en el MOV entero -- la pieza rindio invisible, "
            "exactamente el bug de mariosoto_clip2_corto (hook/cierre en 9:16)"
        )
        y0, y1 = bbox
        dy = (mc.desplazamiento_de_banda(banda_automatica, ALTO) or (0, 0))[1]
        y0, y1 = y0 + dy, y1 + dy

        assert y0 >= 0, (
            f"{plantilla}: el borde superior queda en {y0 / ALTO:.4f} ({y0}px), coordenada "
            "negativa: el contenido se sale por arriba del lienzo"
        )
        assert y0 >= ALTO * MARGEN_SUPERIOR, (
            f"{plantilla}: el borde superior queda en {y0 / ALTO:.4f} "
            f"({y0}px), cortado (o casi) contra el borde superior del lienzo"
        )
        assert y1 <= ALTO, (
            f"{plantilla}: el borde inferior queda en {y1 / ALTO:.4f} ({y1}px), "
            f"fuera del lienzo ({ALTO}px)"
        )
        import motion_plan as mp2

        zona_vertical = mp2.ZONA_CAPTIONS_POR_ORIENTACION["vertical"][0]
        limite_captions = zona_vertical - MARGEN_CAPTIONS
        assert y1 / ALTO <= limite_captions, (
            f"{plantilla}: el borde inferior queda en {y1 / ALTO:.4f}, invade la franja de "
            f"captions (empieza en {zona_vertical:.3f})"
        )
