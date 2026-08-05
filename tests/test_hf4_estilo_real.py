"""HF-4: render REAL de las tres variantes de estilo de lower_third. Excluido por default.

Se corre a mano antes de cada PR de HyperFrames (regla de gate D50.4):

    venv\\Scripts\\python -m pytest tests/test_hf4_estilo_real.py -m hf_real -q

Tres cosas, siguiendo el patron de test_hf2_real.py:
1. Canario de influencia (D50.5) por cada plantilla NUEVA: mismo proyecto, texto distinto,
   sha256 DISTINTO. Gate obligatorio de toda plantilla nueva.
2. Cache cruzada entre estilos (Paso 3): el MISMO clip/pieza con dos estilos distintos debe
   dar sha256 de MOV distinto y CERO acierto de cache cruzado.
3. Invariante nueva del Paso 5b: la capa encendida con estilo "pms" (o sin pedir estilo, que
   es el comportamiento historico) resuelve al MISMO sha256 que hoy.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from hyperframes import pedir_pieza
from hyperframes.catalogo import Catalogo

pytestmark = pytest.mark.hf_real

RAIZ = Path(__file__).resolve().parents[1]
CATALOGO = Catalogo.desde_archivo(RAIZ / "motion" / "catalogo.json")
NOMBRES_ESTILO = ("lower_third_claro", "lower_third_minimo", "lower_third_rudo")


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
@pytest.mark.parametrize("nombre", NOMBRES_ESTILO)
def test_canario_de_influencia_por_estilo_nuevo(nombre, tmp_path):
    """D50.5: gate obligatorio de cada plantilla nueva. Mismo patron que test_hf2_real.py."""
    base = _ejemplo(nombre)
    primer_slot = sorted(base["texto"])[0]
    variante = dict(base, texto=dict(base["texto"], **{primer_slot: "Texto canario distinto"}))

    uno = _pedir(base, tmp_path / "cache")
    testigo = _pedir(base, tmp_path / "cache_testigo")
    otro = _pedir(variante, tmp_path / "cache")

    assert uno.razon_fallo is None, f"{nombre}: {uno.razon_fallo} {uno.detalle}"
    assert otro.razon_fallo is None, f"{nombre}: {otro.razon_fallo} {otro.detalle}"
    assert testigo.razon_fallo is None, f"{nombre}: {testigo.razon_fallo} {testigo.detalle}"

    assert uno.sha256 == testigo.sha256, (
        f"{nombre}: el render no es reproducible, este canario no puede detectar nada."
    )
    assert uno.hash != otro.hash
    assert uno.sha256 != otro.sha256, (
        f"{nombre}: el slot {primer_slot!r} no llego a la plantilla (fallo de D50.1)"
    )
    assert uno.pix_fmt == "yuva444p12le"


@pytest.mark.skipif(shutil.which("npx") is None, reason="npx no esta instalado")
def test_cache_no_se_cruza_entre_estilos(tmp_path):
    """Paso 3: el MISMO clip/pieza con dos estilos distintos exige sha256 de MOV distinto y
    cero acierto de cache cruzado. Usa una raiz de cache COMPARTIDA a proposito: si `estilo`
    no entrara a la clave, la segunda peticion seria un hit de cache y devolveria el MOV del
    primer estilo con el nombre del segundo.
    """
    raiz_cache = tmp_path / "cache_compartida"
    pms = _ejemplo("lower_third")
    rudo = dict(
        _ejemplo("lower_third_rudo"),
        pieza_id=pms["pieza_id"],  # el MISMO id de pieza, para que solo el estilo difiera
    )

    r_pms = _pedir(pms, raiz_cache)
    r_rudo = _pedir(rudo, raiz_cache)

    assert r_pms.razon_fallo is None, f"{r_pms.razon_fallo} {r_pms.detalle}"
    assert r_rudo.razon_fallo is None, f"{r_rudo.razon_fallo} {r_rudo.detalle}"
    assert not r_pms.desde_cache, "el primer render no deberia salir de cache"
    assert not r_rudo.desde_cache, (
        "el estilo 'rudo' salio de cache: la clave no esta viendo el estilo/la plantilla "
        "resuelta y esta devolviendo el MOV de 'pms' con otro nombre"
    )
    assert r_pms.hash != r_rudo.hash, "el hash de cache no distingue entre estilos"
    assert r_pms.sha256 != r_rudo.sha256, "los MOV de dos estilos distintos salieron identicos"

    # Repetir 'pms' con la MISMA raiz debe ahora si ser un acierto de cache genuino (propio,
    # no cruzado con 'rudo'), y debe devolver el sha256 original de 'pms'.
    r_pms_otra_vez = _pedir(pms, raiz_cache)
    assert r_pms_otra_vez.desde_cache, "un segundo pedido identico deberia ser un hit de cache"
    assert r_pms_otra_vez.sha256 == r_pms.sha256


@pytest.mark.skipif(shutil.which("npx") is None, reason="npx no esta instalado")
def test_capa_encendida_con_pms_es_byte_identica_a_hoy(tmp_path):
    """Invariante NUEVA del Paso 5b, a nivel de render real.

    `estilo` es obligatorio en el esquema desde HF-4 (no hay ya un contrato "historico" sin
    el campo que pase la validacion), asi que la invariante que SI se puede probar en este
    nivel es: pedir el estilo por DEFAULT (lo que hacia todo el codigo antes de HF-4, via
    `motion_capa.contrato_de_pieza` sin pasar `estilo`) renderiza BYTE A BYTE igual que pedir
    "pms" explicito. El nivel de contrato puro (sin renderizar) vive en
    test_hf4_estilo.py::test_contrato_de_pieza_sin_estilo_es_pms_e_identico_al_historico.
    """
    import motion_plan as mp
    from motion_capa import MARCA, contrato_de_pieza

    pieza = mp.Pieza("lower_third", 0, 4500, {"nombre": "N", "rol": "R"})
    por_default = contrato_de_pieza(
        pieza, version="1.0.3", ancho=1080, alto=1920, fps=30, marca=MARCA
    )
    explicito = contrato_de_pieza(
        pieza, version="1.0.3", estilo="pms", ancho=1080, alto=1920, fps=30, marca=MARCA
    )
    assert por_default == explicito

    r_default = _pedir(por_default, tmp_path / "cache_a")
    r_explicito = _pedir(explicito, tmp_path / "cache_b")

    assert r_default.razon_fallo is None, f"{r_default.razon_fallo} {r_default.detalle}"
    assert r_explicito.razon_fallo is None, f"{r_explicito.razon_fallo} {r_explicito.detalle}"
    assert r_default.sha256 == r_explicito.sha256, (
        "el estilo por default no coincide byte a byte con 'pms' explicito"
    )
