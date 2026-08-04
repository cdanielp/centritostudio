"""HF-2: render REAL de las cinco plantillas del catalogo. Excluido por default.

Se corre a mano antes de cada PR de HyperFrames (regla de gate de D50.4):

    venv\\Scripts\\python -m pytest tests/test_hf2_real.py -m hf_real -q

Por plantilla se fijan cuatro cosas, ninguna por pixeles ni sha concreto:
1. Canario de influencia (D50.5): mismo proyecto, dos textos, sha256 DISTINTO.
2. La pieza sale en vertical (1080x1920) desde el proyecto del catalogo y en
   horizontal (1920x1080) desde su gemelo `horizontal/`. Un solo proyecto NO puede
   servir ambos tamanos: HyperFrames fija el lienzo con los data-width/height
   estaticos del HTML (hallazgo de HF-2, detalle en test_hf2_catalogo).
3. La duracion se adapta: la duracion natural del ejemplo y su mitad producen MOV
   cuya duracion real pasa la verificacion de HF-1 (tolerancia 120 ms).
4. pix_fmt yuva444p12le: el alfa sobrevive (HF-0).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from hyperframes import pedir_pieza
from hyperframes.catalogo import Catalogo, Plantilla

pytestmark = pytest.mark.hf_real

RAIZ = Path(__file__).resolve().parents[1]
CATALOGO = Catalogo.desde_archivo(RAIZ / "motion" / "catalogo.json")
NOMBRES = ("cierre", "dato_destacado", "hook", "lower_third", "titulo_seccion")

# Catalogo ad-hoc para el gemelo 16:9: mismas plantillas, proyecto + "/horizontal".
# Es la convencion que HF-3 tendra que adoptar mientras el catalogo no exprese
# un proyecto por orientacion (decision pendiente de K, ver D51).
CATALOGO_H = Catalogo(
    [
        Plantilla(
            nombre=p["nombre"],
            version=p["version"],
            slots_texto=tuple(p["slots_texto"]),
            proyecto=p["proyecto"] + "/horizontal",
        )
        for p in json.loads((RAIZ / "motion" / "catalogo.json").read_text(encoding="utf-8"))
    ]
)


def _ejemplo(nombre: str) -> dict:
    ruta = RAIZ / "motion" / "ejemplos" / f"{nombre}.json"
    return json.loads(ruta.read_text(encoding="utf-8"))


def _pedir(dato: dict, cache: Path, catalogo: Catalogo = CATALOGO):
    tamano = dato["tamano"]
    return pedir_pieza(
        dato,
        destino=(tamano["ancho"], tamano["alto"]),
        catalogo=catalogo,
        raiz_cache=cache,
        timeout_s=300,
    )


@pytest.mark.skipif(shutil.which("npx") is None, reason="npx no esta instalado")
@pytest.mark.parametrize("nombre", NOMBRES)
def test_canario_de_influencia_por_plantilla(nombre, tmp_path):
    """D50.5: cambiar el texto de un slot debe cambiar el sha256 del MOV."""
    base = _ejemplo(nombre)
    primer_slot = sorted(base["texto"])[0]
    variante = dict(base, texto=dict(base["texto"], **{primer_slot: "Texto canario distinto"}))

    uno = _pedir(base, tmp_path / "cache")
    otro = _pedir(variante, tmp_path / "cache")

    assert uno.razon_fallo is None, f"{nombre}: {uno.razon_fallo} {uno.detalle}"
    assert otro.razon_fallo is None, f"{nombre}: {otro.razon_fallo} {otro.detalle}"
    assert uno.hash != otro.hash
    assert uno.sha256 != otro.sha256, (
        f"{nombre}: el slot {primer_slot!r} no llego a la plantilla, "
        "esta pintando su valor por defecto (el fallo de D50.1)"
    )
    assert uno.pix_fmt == "yuva444p12le"


@pytest.mark.skipif(shutil.which("npx") is None, reason="npx no esta instalado")
@pytest.mark.parametrize("nombre", NOMBRES)
def test_ambos_tamanos_y_media_duracion(nombre, tmp_path):
    """9:16 con el catalogo real y 16:9 con el gemelo, a duracion natural y mitad."""
    base = _ejemplo(nombre)
    casos = [
        (dict(base, tamano={"ancho": 1920, "alto": 1080}), CATALOGO_H),
        (dict(base, duracion_ms=base["duracion_ms"] // 2), CATALOGO),
        (
            dict(
                base,
                tamano={"ancho": 1920, "alto": 1080},
                duracion_ms=base["duracion_ms"] // 2,
            ),
            CATALOGO_H,
        ),
    ]
    for dato, catalogo in casos:
        r = _pedir(dato, tmp_path / "cache", catalogo)
        assert r.razon_fallo is None, f"{nombre}: {r.razon_fallo} {r.detalle}"
        assert r.pix_fmt == "yuva444p12le"
        assert abs(r.duracion_ms_real - dato["duracion_ms"]) <= 120
