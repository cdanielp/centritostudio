"""HF-4: el eje `estilo` del contrato de lower_third (CLARO/MINIMO/RUDO + PMS de fabrica).

Nada de esto renderiza: fija la resolucion (funcion, estilo) -> plantilla, la caida a "pms"
cuando no existe variante, que el estilo entra al esquema (y por tanto a `calcular_hash`) y
que el planificador de posiciones sigue sin tocarse. El canario de influencia real (D50.5) y
la prueba de cache cruzada entre estilos viven en test_hf4_estilo_real.py (hf_real).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import motion_capa as mc
import motion_plan as mp
from auto_config import AutoConfig, AutoConfigError
from hyperframes.contrato import ESTILOS_VALIDOS, validar_contrato

RAIZ = Path(__file__).resolve().parents[1]


def _pieza(nombre="lower_third", t0=0, dur=4500, texto=None):
    return mp.Pieza(nombre, t0, t0 + dur, texto or {"nombre": "N", "rol": "R"})


VERSIONES = {
    "lower_third": "1.0.3",
    "lower_third_claro": "1.0.0",
    "lower_third_minimo": "1.0.0",
    "lower_third_rudo": "1.0.0",
    "hook": "1.0.4",
}


# ── resolver_estilo ─────────────────────────────────────────────────────────


def test_estilo_pms_resuelve_a_la_funcion_a_secas():
    nombre, version, cayo = mc.resolver_estilo("lower_third", "pms", VERSIONES)
    assert (nombre, version, cayo) == ("lower_third", "1.0.3", False)


@pytest.mark.parametrize("estilo", ["claro", "minimo", "rudo"])
def test_lower_third_tiene_las_tres_variantes_de_estilo(estilo):
    nombre, version, cayo = mc.resolver_estilo("lower_third", estilo, VERSIONES)
    assert nombre == f"lower_third_{estilo}"
    assert version == VERSIONES[nombre]
    assert cayo is False


@pytest.mark.parametrize("estilo", ["claro", "minimo", "rudo"])
def test_una_funcion_sin_variante_cae_a_pms_y_lo_marca(estilo):
    """Hoy solo lower_third tiene los cuatro estilos; las otras cuatro funciones caen
    SIEMPRE, y eso es lo esperado, no un error (letra explicita del brief)."""
    nombre, version, cayo = mc.resolver_estilo("hook", estilo, VERSIONES)
    assert (nombre, version) == ("hook", "1.0.4")
    assert cayo is True


def test_resolver_estilo_nunca_lanza_con_version_desconocida():
    nombre, version, cayo = mc.resolver_estilo("fantasma", "rudo", VERSIONES)
    assert nombre == "fantasma"
    assert version == ""
    assert cayo is True


# ── contrato_de_pieza: estilo y compatibilidad con el default historico ─────


def test_contrato_de_pieza_sin_estilo_es_pms_e_identico_al_historico():
    """Invariante nueva (Paso 5b): la capa encendida con estilo pms (o sin pedir estilo, que
    es lo que hacia todo el codigo antes de HF-4) resuelve exactamente igual que hoy."""
    dato = mc.contrato_de_pieza(
        _pieza(), version="1.0.3", ancho=1080, alto=1920, fps=30, marca=mc.MARCA
    )
    assert dato["estilo"] == "pms"
    assert dato["plantilla"] == {"nombre": "lower_third", "version": "1.0.3"}
    assert dato["marca"] == mc.marca_de("lower_third", mc.MARCA)
    validar_contrato(dato)


def test_contrato_de_pieza_con_nombre_resuelto_usa_el_acento_de_la_variante():
    dato = mc.contrato_de_pieza(
        _pieza(),
        version="1.0.0",
        nombre_plantilla="lower_third_rudo",
        estilo="rudo",
        ancho=1080,
        alto=1920,
        fps=30,
        marca=mc.MARCA,
    )
    assert dato["plantilla"] == {"nombre": "lower_third_rudo", "version": "1.0.0"}
    assert dato["estilo"] == "rudo"
    assert dato["marca"]["primario"] == mc.ACENTO_PRINCIPAL
    validar_contrato(dato)


def test_estilo_invalido_lo_rechaza_el_esquema():
    dato = mc.contrato_de_pieza(
        _pieza(), version="1.0.3", estilo="ridiculo", ancho=1080, alto=1920, fps=30, marca=mc.MARCA
    )
    with pytest.raises(Exception, match="estilo"):
        validar_contrato(dato)


def test_estilos_validos_tiene_pms_primero():
    """ESTILO_DEFAULT se deriva de ESTILOS_VALIDOS[0]; si el orden cambia sin querer, esto
    lo dice antes de que el default silencioso se convierta en otra cosa."""
    assert ESTILOS_VALIDOS[0] == "pms"
    assert mc.ESTILO_DEFAULT == "pms"


# ── estilo entra al hash de cache (via ESQUEMA, sin tocar calcular_hash) ────


def test_estilo_distinto_cambia_el_hash_de_cache():
    from hyperframes import calcular_hash

    entorno = {"hyperframes": "0.7.90", "node": "x", "chromium": "y", "ffmpeg": "z"}
    a = mc.contrato_de_pieza(
        _pieza(), version="1.0.3", estilo="pms", ancho=1080, alto=1920, fps=30, marca=mc.MARCA
    )
    b = mc.contrato_de_pieza(
        _pieza(),
        version="1.0.0",
        nombre_plantilla="lower_third_rudo",
        estilo="rudo",
        ancho=1080,
        alto=1920,
        fps=30,
        marca=mc.MARCA,
    )
    assert calcular_hash(a, entorno) != calcular_hash(b, entorno)


# ── estilo entra a la huella del plan sellado ───────────────────────────────


def test_estilo_distinto_cambia_la_huella_de_entrada():
    """Sin esto, cambiar de estilo con el mismo clip reutilizaria el plan sellado del render
    anterior y el sello quedaria describiendo el estilo viejo (Paso 3)."""
    comunes = dict(
        duracion_ms=9000,
        orientacion="vertical",
        textos=mp.TextosMarca(titulo="T", kicker="K", nombre="N", rol="R", cta="C"),
        tramos=[],
        tray_csv=None,
        catalogo={"lower_third"},
        textos_llm=False,
    )
    a = mc.huella_de_entrada(**comunes, estilo="pms")
    b = mc.huella_de_entrada(**comunes, estilo="rudo")
    assert a != b


def test_huella_de_entrada_sin_estilo_sigue_siendo_pms_por_default():
    comunes = dict(
        duracion_ms=9000,
        orientacion="vertical",
        textos=mp.TextosMarca(titulo="T", kicker="K", nombre="N", rol="R", cta="C"),
        tramos=[],
        tray_csv=None,
        catalogo={"lower_third"},
        textos_llm=False,
    )
    assert mc.huella_de_entrada(**comunes) == mc.huella_de_entrada(**comunes, estilo="pms")


# ── el planificador de posiciones no se toco ────────────────────────────────


def test_resolver_plan_no_le_pasa_estilo_al_planificador(monkeypatch, tmp_path):
    """`estilo` viaja hasta la huella; `mp.planificar` no debe recibirlo ni verlo."""
    capturado = {}
    original = mp.planificar

    def espia(**kwargs):
        capturado.update(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(mp, "planificar", espia)
    mc.resolver_plan(
        clip_mp4=None,
        duracion_ms=9000,
        orientacion="vertical",
        textos=mp.TextosMarca(titulo="T", kicker="", nombre="", rol="", cta=""),
        tramos=[],
        tray_csv=None,
        catalogo={"hook", "cierre"},
        estilo="rudo",
    )
    assert "estilo" not in capturado


# ── informe: incidencia de caida a pms ──────────────────────────────────────
# El extremo a extremo (clips_de_motion con la capa ENCENDIDA de verdad) renderiza con
# HyperFrames si npx esta disponible; por eso vive en test_hf4_estilo_real.py (hf_real) y no
# aqui. Aqui se fija solo la logica pura que decide la caida, sin tocar disco ni red.


def test_mensaje_de_caida_nombra_la_funcion_y_el_estilo_pedido():
    nombre, version, cayo = mc.resolver_estilo("hook", "rudo", VERSIONES)
    assert cayo is True
    mensaje = f"estilo 'rudo' no existe para 'hook', se uso '{mc.ESTILO_DEFAULT}'"
    assert "hook" in mensaje and "rudo" in mensaje and "pms" in mensaje


# ── AutoConfig: motion_estilo, validacion y fingerprint ─────────────────────


def test_auto_config_default_de_estilo_es_pms():
    assert AutoConfig(mode="v2").motion_estilo == "pms"


@pytest.mark.parametrize("estilo", ["claro", "minimo", "rudo"])
def test_auto_config_acepta_los_tres_estilos_nuevos(estilo):
    cfg = AutoConfig(mode="v2", motion_enabled=True, motion_estilo=estilo)
    assert cfg.motion_estilo == estilo


def test_auto_config_rechaza_estilo_invalido():
    with pytest.raises(AutoConfigError, match="motion_estilo"):
        AutoConfig(mode="v2", motion_estilo="feo")


def test_auto_config_estilo_no_influye_con_la_capa_apagada():
    """Misma regla que motion_cta: apagada, el campo no entra al fingerprint ni a to_dict."""
    base = AutoConfig(mode="v2")
    otro = AutoConfig(mode="v2", motion_estilo="rudo")
    assert base.fingerprint() == otro.fingerprint()
    assert "motion_estilo" not in base.to_dict()


def test_auto_config_estilo_encendido_cambia_el_fingerprint():
    on_pms = AutoConfig(mode="v2", motion_enabled=True, motion_estilo="pms")
    on_rudo = AutoConfig(mode="v2", motion_enabled=True, motion_estilo="rudo")
    assert on_pms.fingerprint() != on_rudo.fingerprint()
