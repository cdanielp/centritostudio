"""HF-4 Paso 2/3: `auto_formato.formatos_pedidos`/`ruta_final`, puros, sin I/O."""

from __future__ import annotations

from pathlib import Path

from auto_formato import (
    MOTIVO_SIN_REFRAME_HORIZONTAL,
    SalidaFormato,
    formatos_pedidos,
    ruta_final,
)

# Clip fuente horizontal tipico (lo que entrega el clipper, D11/F4.1): 1920x1080.
HORIZONTAL = {"src_ancho": 1920, "src_alto": 1080}
VERTICAL = {"src_ancho": 1080, "src_alto": 1920}


def test_9x16_pedido_sobre_fuente_horizontal_reencuadra():
    r = formatos_pedidos("9:16", **HORIZONTAL)
    assert r.salidas == (SalidaFormato("9:16", "9x16", necesita_reframe=True),)
    assert r.omitidos == ()


def test_16x9_pedido_sobre_fuente_horizontal_no_reencuadra():
    r = formatos_pedidos("16:9", **HORIZONTAL)
    assert r.salidas == (SalidaFormato("16:9", "16x9", necesita_reframe=False),)
    assert r.omitidos == ()


def test_ambos_pedido_sobre_fuente_horizontal_da_las_dos_salidas_9x16_primero():
    r = formatos_pedidos("ambos", **HORIZONTAL)
    assert r.salidas == (
        SalidaFormato("9:16", "9x16", necesita_reframe=True),
        SalidaFormato("16:9", "16x9", necesita_reframe=False),
    )
    assert r.omitidos == ()


def test_16x9_pedido_sobre_fuente_ya_vertical_se_omite_con_motivo():
    """reframe.py solo sabe encuadrar HACIA 9:16: no hay ruta de vertical a horizontal."""
    r = formatos_pedidos("16:9", **VERTICAL)
    assert r.salidas == ()
    assert r.omitidos == ({"formato": "16:9", "motivo": MOTIVO_SIN_REFRAME_HORIZONTAL},)


def test_ambos_pedido_sobre_fuente_vertical_solo_da_9x16_y_omite_16x9():
    r = formatos_pedidos("ambos", **VERTICAL)
    assert r.salidas == (SalidaFormato("9:16", "9x16", necesita_reframe=True),)
    assert r.omitidos == ({"formato": "16:9", "motivo": MOTIVO_SIN_REFRAME_HORIZONTAL},)


def test_9x16_pedido_sobre_fuente_vertical_reencuadra_igual():
    """El reframe siempre corre para "9:16", pase lo que pase con la fuente: es la ruta
    historica exacta, sin condicion nueva."""
    r = formatos_pedidos("9:16", **VERTICAL)
    assert r.salidas == (SalidaFormato("9:16", "9x16", necesita_reframe=True),)


def test_ruta_final_generaliza_el_sufijo():
    clip = {"archivo": "mariosoto_clip2_corto.mp4"}
    stem, ruta = ruta_final(clip, Path("/paquete"), "16x9", estilo="hormozi")
    assert stem == "mariosoto_clip2_corto_16x9"
    assert ruta == Path("/paquete/mariosoto_clip2_corto_16x9_hormozi.mp4")


def test_ruta_final_9x16_coincide_con_el_formato_historico_de_auto_final_path():
    """Mismo calculo que `auto._final_path`, solo que parametrizado por sufijo/estilo."""
    clip = {"archivo": "clip.mp4"}
    stem, ruta = ruta_final(clip, Path("/p"), "9x16", estilo="hormozi")
    assert stem == "clip_9x16"
    assert ruta == Path("/p/clip_9x16_hormozi.mp4")
