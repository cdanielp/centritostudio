"""HF-4b: ninguna pieza horizontal puede salir CORTADA, con cualquier largo de texto.

El Paso 1 de HF-4 subio los letreros horizontales a la banda superior (-34pp de
desplazamiento). Cuatro de las cinco plantillas (hook, cierre, titulo_seccion,
dato_destacado) centraban su contenido nativamente en ~32% de la altura: sumarle el
desplazamiento las mandaba a top negativo, y el borde superior de la pieza se recortaba
contra el borde del lienzo. `lower_third` se salvaba porque su ancla nativa (bottom:32%,
igual que el carril vertical 54-68%) ya estaba donde el desplazamiento la esperaba.

Este test mide el ALFA REAL del MOV renderizado (no el CSS declarado, que puede mentir por
como el texto envuelve) con un titulo deliberadamente largo de tres lineas, y exige que el
bbox final (ya desplazado por la banda) quede COMPLETO dentro del lienzo y fuera de la franja
de captions. Es `hf_real`: renderiza de verdad contra HyperFrames.

    venv\\Scripts\\python -m pytest tests/test_hf4b_recorte_horizontal.py -m hf_real -q
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.hf_real

RAIZ = Path(__file__).resolve().parents[1]
ANCHO, ALTO, FPS = 1920, 1080, 30

# Deliberadamente largo: fuerza tres lineas o mas en cualquiera de los campos de texto de las
# cinco plantillas (los mas anchos son hook/cierre/titulo_seccion, con placas de ~84% de ancho).
TEXTO_LARGO = (
    "Este titulo es deliberadamente larguisimo para forzar tres lineas completas de texto "
    "envuelto dentro de la placa y asi medir si algo se corta de verdad"
)

# (plantilla, campo que se alarga, resto de campos con texto corto)
CASOS = [
    ("hook", "titulo", {"kicker": "DATO"}),
    ("cierre", "titulo", {"cta": "Sigue para más"}),
    ("titulo_seccion", "titulo", {}),
    ("dato_destacado", "etiqueta", {"cifra": "42%"}),
    ("lower_third", "rol", {"nombre": "Carlos Daniel Penagos"}),
]

# Margen minimo exigido, en fraccion de alto, a cada lado del bbox final.
MARGEN_SUPERIOR = 0.02
MARGEN_CAPTIONS = 0.02


def _pieza_con_texto_largo(plantilla: str, campo_largo: str, resto: dict):
    import motion_plan as mp

    texto = dict(resto)
    texto[campo_largo] = TEXTO_LARGO
    return mp.Pieza(plantilla, 0, mp.DURACION_MS[plantilla], texto, banda=mp.BANDA_CENTRO)


@pytest.mark.skipif(__import__("shutil").which("npx") is None, reason="npx no esta instalado")
@pytest.mark.parametrize("plantilla,campo_largo,resto", CASOS, ids=[c[0] for c in CASOS])
def test_la_pieza_horizontal_no_se_corta_con_texto_de_tres_lineas(plantilla, campo_largo, resto):
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
    catalogo = Catalogo.desde_archivo(RAIZ / "motion" / "catalogo.json", "horizontal")

    # El automatico siempre manda horizontal a la banda superior (Paso 1 de HF-4); el bbox se
    # exige DESPUES de ese desplazamiento, que es lo que de verdad se compone en el video.
    banda_automatica = mp.BANDA_ARRIBA

    with tempfile.TemporaryDirectory(prefix="hf4b_test_") as tmp:
        r = pedir_pieza(
            dato,
            destino=(ANCHO, ALTO),
            catalogo=catalogo,
            raiz_cache=Path(tmp),
            timeout_s=180,
        )
        assert r.razon_fallo is None, f"{plantilla}: {r.razon_fallo} {r.detalle}"

        bbox = mc.bbox_alfa(Path(r.ruta_mov), pieza.duracion_ms * 0.0006, ANCHO, ALTO)
        assert bbox is not None, f"{plantilla}: no se pudo medir el alfa de la pieza"
        y0, y1 = bbox
        dy = (mc.desplazamiento_de_banda(banda_automatica, ALTO) or (0, 0))[1]
        y0, y1 = y0 + dy, y1 + dy

        assert y0 >= ALTO * MARGEN_SUPERIOR, (
            f"{plantilla}: el borde superior queda en {y0 / ALTO:.4f} "
            f"({y0}px), cortado (o casi) contra el borde superior del lienzo"
        )
        assert y1 <= ALTO, (
            f"{plantilla}: el borde inferior queda en {y1 / ALTO:.4f} ({y1}px), "
            f"fuera del lienzo ({ALTO}px)"
        )
        import motion_plan as mp2

        zona_horizontal = mp2.ZONA_CAPTIONS_POR_ORIENTACION["horizontal"][0]
        limite_captions = zona_horizontal - MARGEN_CAPTIONS
        assert y1 / ALTO <= limite_captions, (
            f"{plantilla}: el borde inferior queda en {y1 / ALTO:.4f}, invade la franja de "
            f"captions (empieza en {zona_horizontal:.3f})"
        )
