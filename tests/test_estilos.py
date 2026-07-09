"""Tests de styles.py — corren desde hoy, sin GPU."""

import re

import pytest

import styles

COLOR_ASS = re.compile(r"^&H[0-9A-Fa-f]{8}$")
ESTILOS_MINIMOS = {"hormozi", "karaoke", "bounce", "pms"}


def test_estilos_minimos_existen():
    assert ESTILOS_MINIMOS.issubset(set(styles.list_styles()))


@pytest.mark.parametrize("nombre", sorted(ESTILOS_MINIMOS))
def test_campos_y_colores_validos(nombre):
    cfg = styles.get_style(nombre)
    campos_color = (
        "primary_color",
        "highlight_color",
        "outline_color",
        "shadow_color",
        "keyword_color",
    )
    for campo in campos_color:
        valor = getattr(cfg, campo)
        assert COLOR_ASS.match(valor), f"{nombre}.{campo}={valor} no es &HAABBGGRR"
    assert cfg.font_size > 0
    assert 0.0 < cfg.margin_pct < 0.5
    assert cfg.max_chars_per_line >= 8
    assert cfg.animation_type in {"highlight", "karaoke", "bounce", "scale"}


def test_estilo_inexistente_lanza_error():
    with pytest.raises(ValueError):
        styles.get_style("no_existe_xyz")


def test_get_style_es_case_insensitive():
    assert styles.get_style("HORMOZI").name == "hormozi"
