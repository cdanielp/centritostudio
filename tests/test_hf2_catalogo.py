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

# Las cinco piezas de HF-2 y el rango de duracion natural (ms) que fija el brief, mas las tres
# variantes de estilo de lower_third (HF-4): mismos slots y el mismo rango natural, porque son
# la misma funcion con otra piel.
PIEZAS_ESPERADAS = {
    "hook": (2000, 3000),
    "lower_third": (4000, 5000),
    "lower_third_claro": (4000, 5000),
    "lower_third_minimo": (4000, 5000),
    "lower_third_rudo": (4000, 5000),
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


def test_catalogo_declara_exactamente_las_ocho_piezas():
    nombres = {p.nombre for p in _plantillas()}
    assert nombres == set(PIEZAS_ESPERADAS), f"catalogo con piezas inesperadas: {sorted(nombres)}"
    assert len(_catalogo()) == 8


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


def test_sin_nombres_de_plataformas_externas_en_el_catalogo():
    """Regla del proyecto: el nombre de la plataforma de la comunidad no aparece en
    ningun output ni copy. Se construye sin el literal para que este test no sea el
    unico sitio del repo donde figura."""
    prohibida = "".join(("s", "k", "o", "o", "l"))
    rutas = [
        r for r in (RAIZ / "motion").rglob("*") if r.suffix in (".json", ".html", ".md", ".txt")
    ]
    assert len(rutas) >= 16, "el barrido de motion/ quedo vacio; el test ya no protege nada"
    con_nombre = [r.name for r in rutas if prohibida in r.read_text(encoding="utf-8").lower()]
    assert not con_nombre, f"nombre de plataforma externa prohibido en: {con_nombre}"


def test_sin_em_dashes_en_catalogo_ejemplos_y_plantillas():
    rutas = [RUTA_CATALOGO, *RUTA_EJEMPLOS.glob("*.json")]
    rutas += [RAIZ / p.proyecto / "index.html" for p in _plantillas()]
    con_em_dash = [r.name for r in rutas if "—" in r.read_text(encoding="utf-8")]
    assert not con_em_dash, f"em dashes prohibidos por el brief en: {con_em_dash}"


# Variable del contrato -> custom property CSS que actua de fallback en :root.
COLORES_MARCA = {
    "marca_primario": "--primario",
    "marca_secundario": "--secundario",
    "marca_texto": "--texto",
}


@pytest.mark.parametrize("nombre", sorted(PIEZAS_ESPERADAS))
def test_defaults_de_color_css_y_variables_coinciden(nombre):
    """El default declarado y el fallback CSS viven duplicados a proposito (el JS
    siempre pisa el CSS); este test impide que un rebrand los deje divergir en silencio."""
    plantilla = next(p for p in _plantillas() if p.nombre == nombre)
    html = (RAIZ / plantilla.proyecto / "index.html").read_text(encoding="utf-8")
    crudo = re.search(r"data-composition-variables='(\[.*?\])'", html, re.DOTALL)
    assert crudo, f"{nombre}: el proyecto no declara data-composition-variables"
    declarados = {v["id"]: v["default"] for v in json.loads(crudo.group(1))}
    raiz_css = re.search(r":root\s*\{(.*?)\}", html, re.DOTALL)
    assert raiz_css, f"{nombre}: falta el bloque :root con los fallbacks"
    for var_id, css_var in COLORES_MARCA.items():
        fallback = re.search(rf"{css_var}:\s*(#[0-9A-Fa-f]{{6}})", raiz_css.group(1))
        assert fallback, f"{nombre}: falta el fallback CSS de {css_var} en :root"
        assert fallback.group(1).upper() == str(declarados[var_id]).upper(), (
            f"{nombre}: {var_id} divergio entre el default declarado "
            f"({declarados[var_id]}) y el fallback CSS ({fallback.group(1)})"
        )


def gemelo_horizontal(texto: str) -> str:
    """Deriva el gemelo 16:9 del primario 9:16: CUATRO reemplazos y NADA mas.

    HyperFrames 0.7.90 fija el lienzo con los data-width/height ESTATICOS del HTML
    (medido en HF-2: un script que los reescribe desde las variables es ignorado y
    hasta el flag --width de la CLI avisa que no puede cambiarlos). Un proyecto es
    un solo tamano, asi que cada pieza versiona un gemelo horizontal que comparte
    fuente y gsap por ruta relativa al padre.

    El CUARTO reemplazo (HF-3 bloque 2.2) son los defaults de `tamano_ancho` y
    `tamano_alto` del bloque de variables, que en los cinco gemelos declaraban
    1080x1920 dentro de un proyecto 1920x1080. La derivacion de HF-2 solo miraba
    tres sitios y por eso la contradiccion nunca truena: son DEFAULTS, y el contrato
    de pieza siempre manda los valores buenos. Pero es exactamente la forma del
    fallo silencioso que ya costo una sesion aqui (un lienzo que se declara en dos
    sitios y no coincide), y quien abriera el gemelo a mano leeria 1080x1920.
    """
    t = texto.replace(
        'data-width="1080" data-height="1920"', 'data-width="1920" data-height="1080"'
    )
    t = t.replace('src="gsap.min.js"', 'src="../gsap.min.js"')
    t = t.replace('url("fonts/InterVariable.woff2")', 'url("../fonts/InterVariable.woff2")')
    return t.replace(
        '{"id":"tamano_ancho","type":"number","label":"Ancho","default":1080},\n'
        '  {"id":"tamano_alto","type":"number","label":"Alto","default":1920},',
        '{"id":"tamano_ancho","type":"number","label":"Ancho","default":1920},\n'
        '  {"id":"tamano_alto","type":"number","label":"Alto","default":1080},',
    )


@pytest.mark.parametrize("nombre", sorted(PIEZAS_ESPERADAS))
def test_gemelo_horizontal_es_derivacion_pura_del_primario(nombre):
    """Si el primario cambia y el gemelo no, este test truena: no pueden divergir."""
    plantilla = next(p for p in _plantillas() if p.nombre == nombre)
    primario = (RAIZ / plantilla.proyecto / "index.html").read_text(encoding="utf-8")
    gemelo = (RAIZ / plantilla.proyecto / "horizontal" / "index.html").read_text(encoding="utf-8")
    assert 'data-width="1080" data-height="1920"' in primario, "el primario es 9:16"
    assert gemelo == gemelo_horizontal(primario), (
        f"{nombre}: el gemelo horizontal divergio del primario; regenera con la "
        "derivacion pura (solo cambian el lienzo, sus defaults y las dos rutas de assets)"
    )


@pytest.mark.parametrize("nombre", sorted(PIEZAS_ESPERADAS))
def test_el_gemelo_declara_su_lienzo_igual_en_los_dos_sitios(nombre):
    """El lienzo se declara dos veces (root estatico y defaults de variables) y deben coincidir.

    Es la comprobacion directa de la deuda 2.2, independiente de la derivacion: aunque alguien
    regenerara el gemelo con otra herramienta, esto sigue exigiendo que no se contradiga.
    """
    plantilla = next(p for p in _plantillas() if p.nombre == nombre)
    gemelo = (RAIZ / plantilla.proyecto / "horizontal" / "index.html").read_text(encoding="utf-8")
    assert 'data-width="1920" data-height="1080"' in gemelo
    assert '{"id":"tamano_ancho","type":"number","label":"Ancho","default":1920}' in gemelo
    assert '{"id":"tamano_alto","type":"number","label":"Alto","default":1080}' in gemelo
    assert 'data-width="1080" data-height="1920"' not in gemelo
