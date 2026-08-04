"""HF-2: el catalogo real de plantillas carga, valida y no colisiona con las reservadas.

Estos tests NO renderizan: fijan el contenido del catalogo versionado en `motion/` contra
el contrato de HF-1 (esquema, slots exactos, capacidad de la ruta de clips) y contra las
reglas duras del brief de HF-2 (autocontencion sin red, fuente local, sin em dashes).
El render real y el canario de influencia de D50.5 viven en test_hf2_real.py (hf_real).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from hyperframes.capacidad import verificar_capacidad
from hyperframes.catalogo import Catalogo
from hyperframes.contrato import validar_contrato, validar_slots
from hyperframes.invocador import claves_reservadas

RAIZ = Path(__file__).resolve().parents[1]
RUTA_CATALOGO = RAIZ / "motion" / "catalogo.json"
RUTA_EJEMPLOS = RAIZ / "motion" / "ejemplos"

# Las cinco piezas de HF-2 y el rango de duracion natural (ms) que fija el brief.
PIEZAS_ESPERADAS = {
    "hook": (2000, 3000),
    "lower_third": (4000, 5000),
    "titulo_seccion": (2000, 2000),
    "dato_destacado": (3000, 3000),
    "cierre": (3000, 4000),
}
TAMANOS = ((1080, 1920), (1920, 1080))


def _catalogo() -> Catalogo:
    return Catalogo.desde_archivo(RUTA_CATALOGO)


def _plantillas() -> list:
    datos = json.loads(RUTA_CATALOGO.read_text(encoding="utf-8"))
    cat = _catalogo()
    return [cat.exigir(d["nombre"], d["version"]) for d in datos]


def _ejemplo(nombre: str) -> dict:
    return json.loads((RUTA_EJEMPLOS / f"{nombre}.json").read_text(encoding="utf-8"))


def test_catalogo_declara_exactamente_las_cinco_piezas():
    nombres = {p.nombre for p in _plantillas()}
    assert nombres == set(PIEZAS_ESPERADAS), f"catalogo con piezas inesperadas: {sorted(nombres)}"
    assert len(_catalogo()) == 5


@pytest.mark.parametrize("nombre", sorted(PIEZAS_ESPERADAS))
def test_slots_declarados_no_colisionan_con_reservadas(nombre):
    plantilla = next(p for p in _plantillas() if p.nombre == nombre)
    assert plantilla.slots_texto, "una plantilla sin slots no puede pasar el canario de D50.5"
    choque = set(plantilla.slots_texto) & set(claves_reservadas())
    assert not choque, f"slots que el aplanado haria desaparecer en silencio: {sorted(choque)}"


@pytest.mark.parametrize("nombre", sorted(PIEZAS_ESPERADAS))
def test_proyecto_existe_y_es_autocontenido(nombre):
    plantilla = next(p for p in _plantillas() if p.nombre == nombre)
    proyecto = RAIZ / plantilla.proyecto
    html = (proyecto / "index.html").read_text(encoding="utf-8")
    assert (proyecto / "gsap.min.js").is_file(), "gsap debe ser archivo local, no CDN"
    assert (proyecto / "fonts" / "InterVariable.woff2").is_file(), "fuente embebida local"
    assert "@font-face" in html, "la fuente se declara con @font-face y ruta relativa"
    assert "http://" not in html and "https://" not in html, (
        "el render debe ser reproducible sin internet: cero cargas por red"
    )


@pytest.mark.parametrize("nombre", sorted(PIEZAS_ESPERADAS))
def test_contrato_de_ejemplo_valida_en_ambos_tamanos(nombre):
    plantilla = next(p for p in _plantillas() if p.nombre == nombre)
    for ancho, alto in TAMANOS:
        dato = dict(_ejemplo(nombre), tamano={"ancho": ancho, "alto": alto})
        validar_contrato(dato)
        validar_slots(dato, plantilla.slots_texto)
        verificar_capacidad(dato, (ancho, alto))


@pytest.mark.parametrize("nombre", sorted(PIEZAS_ESPERADAS))
def test_duracion_natural_dentro_del_rango_del_brief(nombre):
    minimo, maximo = PIEZAS_ESPERADAS[nombre]
    assert minimo <= _ejemplo(nombre)["duracion_ms"] <= maximo


@pytest.mark.parametrize("nombre", sorted(PIEZAS_ESPERADAS))
def test_variables_declaradas_cubren_slots_y_sistema(nombre):
    """El HTML declara EXACTAMENTE slots + claves del sistema: un id de mas o de menos
    es un texto que se pinta como default con returncode 0 (el fallo de D50.1)."""
    plantilla = next(p for p in _plantillas() if p.nombre == nombre)
    html = (RAIZ / plantilla.proyecto / "index.html").read_text(encoding="utf-8")
    crudo = re.search(r"data-composition-variables='(\[.*?\])'", html, re.DOTALL)
    assert crudo, "el proyecto no declara data-composition-variables"
    ids = {v["id"] for v in json.loads(crudo.group(1))}
    esperadas = set(plantilla.slots_texto) | set(claves_reservadas())
    assert ids == esperadas, f"faltan {sorted(esperadas - ids)}, sobran {sorted(ids - esperadas)}"


def test_sin_em_dashes_en_catalogo_ejemplos_y_plantillas():
    rutas = [RUTA_CATALOGO, *RUTA_EJEMPLOS.glob("*.json")]
    rutas += [RAIZ / p.proyecto / "index.html" for p in _plantillas()]
    con_em_dash = [r.name for r in rutas if "—" in r.read_text(encoding="utf-8")]
    assert not con_em_dash, f"em dashes prohibidos por el brief en: {con_em_dash}"


def gemelo_horizontal(texto: str) -> str:
    """Deriva el gemelo 16:9 del primario 9:16: tres reemplazos y NADA mas.

    HyperFrames 0.7.90 fija el lienzo con los data-width/height ESTATICOS del HTML
    (medido en HF-2: un script que los reescribe desde las variables es ignorado y
    hasta el flag --width de la CLI avisa que no puede cambiarlos). Un proyecto es
    un solo tamano, asi que cada pieza versiona un gemelo horizontal que comparte
    fuente y gsap por ruta relativa al padre.
    """
    t = texto.replace(
        'data-width="1080" data-height="1920"', 'data-width="1920" data-height="1080"'
    )
    t = t.replace('src="gsap.min.js"', 'src="../gsap.min.js"')
    return t.replace('url("fonts/InterVariable.woff2")', 'url("../fonts/InterVariable.woff2")')


@pytest.mark.parametrize("nombre", sorted(PIEZAS_ESPERADAS))
def test_gemelo_horizontal_es_derivacion_pura_del_primario(nombre):
    """Si el primario cambia y el gemelo no, este test truena: no pueden divergir."""
    plantilla = next(p for p in _plantillas() if p.nombre == nombre)
    primario = (RAIZ / plantilla.proyecto / "index.html").read_text(encoding="utf-8")
    gemelo = (RAIZ / plantilla.proyecto / "horizontal" / "index.html").read_text(encoding="utf-8")
    assert 'data-width="1080" data-height="1920"' in primario, "el primario es 9:16"
    assert gemelo == gemelo_horizontal(primario), (
        f"{nombre}: el gemelo horizontal divergio del primario; regenera con la "
        "derivacion pura (solo cambian el lienzo y las dos rutas de assets)"
    )
