"""HF-3 bloque 1: la capa de letreros, su freno de solapamiento y su exposicion.

Nada de esto renderiza: se fija el CONTRATO de pieza, el comando conceptual y la forma del
resultado, nunca pixeles (invariante I5).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import motion_capa as mc
import motion_plan as mp
from auto_config import AutoConfig, AutoConfigError

RAIZ = Path(__file__).resolve().parents[1]


def _pieza(nombre="hook", t0=0, dur=2500, texto=None):
    return mp.Pieza(nombre, t0, t0 + dur, texto or {"kicker": "", "titulo": "T"})


# ── La capa apagada no existe ────────────────────────────────────────────────


def test_apagada_devuelve_cero_clips_sin_tocar_nada(tmp_path):
    r = mc.clips_de_motion(
        opciones=mc.OpcionesMotion(),
        ancho=1080,
        alto=1920,
        fps=30,
        duracion_s=30.0,
        raiz_cache=tmp_path / "no_deberia_crearse",
        root=RAIZ,
    )
    assert r.clips == ()
    assert r.informe == {"enabled": False}
    assert not (tmp_path / "no_deberia_crearse").exists()


def test_apagada_no_importa_hyperframes(monkeypatch, tmp_path):
    """Si la capa apagada importara el Motor B, un entorno sin el romperia la ruta historica."""

    def explota(*a, **kw):
        raise AssertionError("la capa apagada no debe tocar hyperframes")

    monkeypatch.setattr(mc, "_clips_de_motion", explota)
    assert (
        mc.clips_de_motion(
            opciones=mc.OpcionesMotion(),
            ancho=1080,
            alto=1920,
            fps=30,
            duracion_s=10.0,
            raiz_cache=tmp_path,
            root=RAIZ,
        ).clips
        == ()
    )


def test_encendida_es_fail_open_ante_cualquier_fallo(monkeypatch, tmp_path):
    def explota(**kw):
        raise RuntimeError("npx desapareceio")

    monkeypatch.setattr(mc, "_clips_de_motion", explota)
    r = mc.clips_de_motion(
        opciones=mc.OpcionesMotion(enabled=True, titulo="T"),
        ancho=1080,
        alto=1920,
        fps=30,
        duracion_s=30.0,
        raiz_cache=tmp_path,
        root=RAIZ,
    )
    assert r.clips == ()
    assert "npx desapareceio" in r.informe["error"]


# ── Solapamiento en 9:16 ─────────────────────────────────────────────────────


def test_solapamiento_vertical_es_error_explicito():
    piezas = [_pieza("hook", 0, 2500), _pieza("cierre", 2000, 3500)]
    with pytest.raises(mc.SolapamientoDePiezas) as exc:
        mc.validar_sin_solape(piezas, "vertical")
    mensaje = str(exc.value)
    assert "hook" in mensaje and "cierre" in mensaje
    assert "500" in mensaje  # nombra la interseccion medida, no solo que hay una


def test_piezas_pegadas_sin_cruce_no_son_solapamiento():
    mc.validar_sin_solape([_pieza("hook", 0, 2500), _pieza("cierre", 2500, 3500)], "vertical")


def test_en_16_9_el_cruce_se_tolera_porque_las_bandas_son_disjuntas():
    mc.validar_sin_solape([_pieza("hook", 0, 2500), _pieza("cierre", 1000, 3500)], "horizontal")


# ── Contrato de pieza ────────────────────────────────────────────────────────


def test_contrato_de_pieza_es_valido_para_el_esquema_de_hf1():
    from hyperframes import validar_contrato
    from hyperframes.capacidad import verificar_capacidad

    dato = mc.contrato_de_pieza(
        _pieza(), version="1.0.3", ancho=1080, alto=1920, fps=30, marca=mc.MARCA
    )
    validar_contrato(dato)
    verificar_capacidad(dato, (1080, 1920))


def test_el_fps_del_contrato_es_el_del_destino_no_un_default():
    """La cadena de clips fuerza el fps de la base: una pieza a 30 sobre 24 pierde frames."""
    dato = mc.contrato_de_pieza(
        _pieza(), version="1.0.3", ancho=1920, alto=1080, fps=24, marca=mc.MARCA
    )
    assert dato["fps"] == 24


def test_la_version_del_contrato_sale_del_catalogo_no_de_un_literal():
    versiones = mc.versiones_del_catalogo(RAIZ / "motion" / "catalogo.json")
    catalogo = json.loads((RAIZ / "motion" / "catalogo.json").read_text(encoding="utf-8"))
    assert versiones == {d["nombre"]: d["version"] for d in catalogo}


def test_orientacion_se_deduce_del_tamano():
    assert mc.orientacion_de(1080, 1920) == "vertical"
    assert mc.orientacion_de(1920, 1080) == "horizontal"
    assert mc.orientacion_de(1080, 1080) == "horizontal"  # cuadrado usa el lienzo 1920x1080


# ── Las piezas viven DENTRO del paquete ──────────────────────────────────────


def test_la_cache_de_piezas_cuelga_del_paquete(tmp_path):
    """Fuente unica para las dos rutas de paquete: asi un resume las encuentra donde las dejo."""
    assert mc.raiz_cache_de_paquete(tmp_path / "demo_v2_x") == tmp_path / "demo_v2_x" / "piezas"


def test_las_dos_rutas_de_paquete_derivan_la_misma_carpeta_de_piezas(tmp_path):
    """`_paquete_dir` y `_paquete_dir_v2` eligen carpeta por caminos distintos; el nombre de la
    subcarpeta de piezas lo decide un solo helper para que no puedan divergir."""
    classic = tmp_path / "demo_20260804-120000"
    v2 = tmp_path / "demo_v2_202608041200"
    assert mc.raiz_cache_de_paquete(classic) == classic / mc.NOMBRE_CACHE
    assert mc.raiz_cache_de_paquete(v2) == v2 / mc.NOMBRE_CACHE


# ── Tramos ───────────────────────────────────────────────────────────────────


def test_tramos_de_groups_convierte_a_ms_y_salta_los_grupos_sin_tiempos():
    groups = [
        {"start": 0.0, "end": 1.25, "text": "hola"},
        {"start": None, "end": 2.0, "text": "roto"},
        {"start": 2.0, "end": 3.0, "text": "adios"},
    ]
    assert mc.tramos_de_groups(groups) == [
        mp.Tramo(0, 1250, "hola"),
        mp.Tramo(2000, 3000, "adios"),
    ]


# ── El flag ──────────────────────────────────────────────────────────────────


def test_default_off_en_autoconfig():
    assert AutoConfig().motion_enabled is False
    assert AutoConfig(mode="v2").motion_enabled is False


def test_apagada_el_fingerprint_es_el_historico():
    """Un campo nuevo en to_dict habria invalidado TODOS los paquetes v2 ya existentes."""
    base = AutoConfig(mode="v2")
    assert base.fingerprint() == AutoConfig(mode="v2", motion_cta="otra cosa").fingerprint()
    assert "motion_enabled" not in base.to_dict()


def test_encendida_el_fingerprint_cambia_y_los_textos_entran():
    base = AutoConfig(mode="v2")
    on = AutoConfig(mode="v2", motion_enabled=True)
    assert on.fingerprint() != base.fingerprint()
    assert (
        on.fingerprint() != AutoConfig(mode="v2", motion_enabled=True, motion_cta="x").fingerprint()
    )


def test_motion_en_classic_es_error_de_contrato():
    with pytest.raises(AutoConfigError, match="mode='v2'"):
        AutoConfig(mode="classic", motion_enabled=True)


@pytest.mark.parametrize("campo", ["motion_nombre", "motion_rol", "motion_cta"])
def test_los_textos_de_marca_estan_acotados(campo):
    with pytest.raises(AutoConfigError):
        AutoConfig(mode="v2", **{campo: "x" * 200})
    with pytest.raises(AutoConfigError):
        AutoConfig(mode="v2", **{campo: "dos\nlineas"})


# ── El naming ────────────────────────────────────────────────────────────────


def test_el_tag_de_variante_no_cambia_con_la_capa_apagada():
    import cve

    historico = cve.tag_variante("keyword_punch", "viral", "media")
    assert cve.tag_variante("keyword_punch", "viral", "media", motion=None) == historico
    assert cve.tag_variante("keyword_punch", "viral", "media", motion=False) == historico


def test_el_tag_de_variante_marca_la_capa_encendida():
    import cve

    assert cve.tag_variante("keyword_punch", "viral", motion=True).endswith(cve.TOKEN_MOTION)


def test_el_nombre_srt_usa_el_mismo_token():
    import cve
    import srt_render

    historico = srt_render.nombre_base_srt("v", "_hormozi", False, False, None)
    assert srt_render.nombre_base_srt("v", "_hormozi", False, False, None, False) == historico
    con = srt_render.nombre_base_srt("v", "_hormozi", False, False, None, True)
    assert con == historico + cve.TOKEN_MOTION


# ── La CLI ───────────────────────────────────────────────────────────────────


def test_la_cli_trae_el_flag_apagado_por_default():
    from caption_args import build_parser, motion_opts_de_args

    args = build_parser().parse_args(["input/x.mp4"])
    assert args.motion is False
    assert motion_opts_de_args(args).enabled is False


def test_la_cli_construye_las_opciones_con_el_flag():
    from caption_args import build_parser, motion_opts_de_args

    args = build_parser().parse_args(
        ["input/x.mp4", "--motion", "--motion-titulo", "T", "--motion-cta", "C"]
    )
    opts = motion_opts_de_args(args)
    assert (opts.enabled, opts.titulo, opts.cta) == (True, "T", "C")


def test_un_texto_de_motion_sin_el_flag_es_error_no_silencio():
    from caption_args import build_parser, motion_opts_de_args

    args = build_parser().parse_args(["input/x.mp4", "--motion-titulo", "T"])
    with pytest.raises(SystemExit, match="--motion-titulo"):
        motion_opts_de_args(args)
