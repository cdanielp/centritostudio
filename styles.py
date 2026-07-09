"""
Estilos de captions animados — Prompt Models Studio
Cada estilo define la apariencia visual y el tipo de animación word-by-word.
Formato de colores ASS: &HAABBGGRR (alpha, blue, green, red — NO es RGB directo)
"""

from __future__ import annotations

from dataclasses import dataclass

# ╔══════════════════════════════════════════════════════════════════════╗
# ║  CONFIGURACIÓN DEL ESTILO PMS — Edita aquí para personalizar        ║
# ╚══════════════════════════════════════════════════════════════════════╝
PMS_FONT = "Arial"
PMS_FONT_SIZE = 85
PMS_UPPERCASE = True
PMS_PRIMARY_COLOR = "&H00FFFFFF"  # Blanco
PMS_HIGHLIGHT_COLOR = "&H00ED3A7C"  # Morado #7C3AED (BGR invertido)
PMS_KEYWORD_COLOR = "&H0000D7FF"  # Dorado (R=FF,G=D7,B=00 → BGR: 00,D7,FF)
PMS_OUTLINE_COLOR = "&H00000000"  # Negro
PMS_OUTLINE_SIZE = 3.5
PMS_SHADOW_COLOR = "&HAA000000"  # Negro semi-transparente
PMS_SHADOW_DEPTH = 2.5
PMS_MAX_CHARS = 20
PMS_MARGIN_PCT = 0.12  # Distancia desde abajo (fracción de alto)
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class StyleConfig:
    """Configuración completa de un estilo de captions."""

    name: str
    font_name: str
    font_size: int
    primary_color: str  # Color base del texto (formato ASS &HAABBGGRR)
    highlight_color: str  # Color de la palabra activa
    outline_color: str
    outline_size: float
    shadow_color: str
    shadow_depth: float
    bold: bool
    uppercase: bool
    animation_type: str  # "highlight" | "karaoke" | "bounce" | "scale"
    keyword_color: str  # Color persistente del keyword (distinto de highlight)
    max_chars_per_line: int = 18
    max_lines: int = 2
    margin_pct: float = 0.12  # Margen inferior como fracción del alto del video


# Notas de colores ASS: formato &HAABBGGRR
#   Blanco    : &H00FFFFFF
#   Negro     : &H00000000
#   Amarillo  : &H0000FFFF  (R=FF,G=FF,B=00 → BGR: 00,FF,FF)
#   Cian      : &H00FFFF00  (R=00,G=FF,B=FF → BGR: FF,FF,00)
#   Naranja   : &H000080FF  (R=FF,G=80,B=00 → BGR: 00,80,FF)
#   Morado    : &H00ED3A7C  (R=7C,G=3A,B=ED → BGR: ED,3A,7C)
#   Rojo      : &H000000FF
#   Verde-lima: &H0047FF00  (R=00,G=FF,B=47 → BGR: 47,FF,00) — hormozi keyword
#   Dorado    : &H0000D7FF  (R=FF,G=D7,B=00 → BGR: 00,D7,FF) — pms keyword

STYLES: dict[str, StyleConfig] = {
    "hormozi": StyleConfig(
        name="hormozi",
        font_name="Arial Black",
        font_size=90,
        primary_color="&H00FFFFFF",  # Blanco
        highlight_color="&H0000FFFF",  # Amarillo (estilo Alex Hormozi)
        outline_color="&H00000000",  # Contorno negro grueso
        outline_size=6.0,
        shadow_color="&H88000000",
        shadow_depth=2.0,
        bold=True,
        uppercase=True,
        animation_type="highlight",
        keyword_color="&H0047FF00",  # Verde-lima brillante
        max_chars_per_line=18,
        margin_pct=0.10,
    ),
    "karaoke": StyleConfig(
        name="karaoke",
        font_name="Arial",
        font_size=82,
        primary_color="&H99FFFFFF",  # Blanco semi-transparente (no activas)
        highlight_color="&H00FFFF00",  # Cian brillante para relleno progresivo
        outline_color="&H00000000",
        outline_size=4.5,
        shadow_color="&HBB000000",
        shadow_depth=3.0,
        bold=True,
        uppercase=False,
        animation_type="karaoke",
        keyword_color="&H0000FFFF",  # Amarillo
        max_chars_per_line=22,
        margin_pct=0.12,
    ),
    "bounce": StyleConfig(
        name="bounce",
        font_name="Arial Black",
        font_size=86,
        primary_color="&H00FFFFFF",
        highlight_color="&H000080FF",  # Naranja vibrante
        outline_color="&H00000000",
        outline_size=5.5,
        shadow_color="&H88000000",
        shadow_depth=2.0,
        bold=True,
        uppercase=True,
        animation_type="bounce",
        keyword_color="&H00FFFF00",  # Cian
        max_chars_per_line=18,
        margin_pct=0.10,
    ),
    "pms": StyleConfig(
        name="pms",
        font_name=PMS_FONT,
        font_size=PMS_FONT_SIZE,
        primary_color=PMS_PRIMARY_COLOR,
        highlight_color=PMS_HIGHLIGHT_COLOR,
        outline_color=PMS_OUTLINE_COLOR,
        outline_size=PMS_OUTLINE_SIZE,
        shadow_color=PMS_SHADOW_COLOR,
        shadow_depth=PMS_SHADOW_DEPTH,
        bold=True,
        uppercase=PMS_UPPERCASE,
        animation_type="highlight",
        keyword_color=PMS_KEYWORD_COLOR,  # Dorado
        max_chars_per_line=PMS_MAX_CHARS,
        margin_pct=PMS_MARGIN_PCT,
    ),
}


def get_style(name: str) -> StyleConfig:
    key = name.lower().strip()
    if key not in STYLES:
        available = ", ".join(sorted(STYLES))
        raise ValueError(f"Estilo '{name}' no disponible. Opciones: {available}")
    return STYLES[key]


def list_styles() -> list[str]:
    return sorted(STYLES.keys())
