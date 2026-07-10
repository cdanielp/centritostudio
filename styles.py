"""
Estilos de captions animados — Prompt Models Studio
Cada estilo define la apariencia visual y el tipo de animación word-by-word.
Formato de colores ASS: &HAABBGGRR (alpha, blue, green, red — NO es RGB directo)

Capa de configuración externa (fail-safe, reversible):
- `styles.json` en la raíz (OPCIONAL) puede sobrescribir campos de cualquier estilo,
  o definir estilos nuevos. Se valida CAMPO POR CAMPO: un campo ausente o inválido cae
  al valor built-in del estilo; un JSON roto o ausente deja los estilos built-in intactos.
- `assets/marca/marca.json` (OPCIONAL) sobrescribe el estilo `pms` con los colores/fuente
  de la marca cuando K aporte M2/M3. Mientras no exista, `pms` usa un placeholder documentado
  (no bloqueante).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path

# ╔══════════════════════════════════════════════════════════════════════╗
# ║  CONFIGURACIÓN DEL ESTILO PMS — Edita aquí para personalizar        ║
# ║  (placeholder mientras no exista assets/marca/marca.json — M2/M3 de K) ║
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

# Intensidad del "pop" de la palabra activa (escala del scale-pop word-by-word).
# 1.0 = sin pop (solo cambio de color); >1.0 = scale-pop con \t sobre el ASS existente.
POP_LEVELS: dict[str, float] = {"off": 1.0, "suave": 1.08, "fuerte": 1.15}


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
    pop_scale: float = 1.0  # Intensidad del scale-pop de la palabra activa (1.0 = off)


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

_BUILTIN: dict[str, StyleConfig] = {
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
        pop_scale=1.08,  # pop suave por default (override con --pop fuerte/off)
    ),
    "clean": StyleConfig(
        name="clean",
        font_name="Arial",
        font_size=80,
        primary_color="&H00FFFFFF",  # Blanco sobrio
        highlight_color="&H0000D7FF",  # Dorado suave para la palabra activa
        outline_color="&H00000000",
        outline_size=1.0,  # Sin caja: contorno minimo
        shadow_color="&H66000000",  # Sombra suave semi-transparente
        shadow_depth=2.5,
        bold=False,  # Font-weight sobrio
        uppercase=False,
        animation_type="highlight",
        keyword_color="&H0000D7FF",  # Mismo dorado (sobrio, sin verde chillon)
        max_chars_per_line=24,
        margin_pct=0.12,
        pop_scale=1.0,  # Sin scale-pop: solo realce de color (sobrio)
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
        pop_scale=1.08,  # pop suave por default
    ),
}

# Base para estilos NUEVOS definidos solo en styles.json (fallback por-campo).
_DEFAULT_BASE = _BUILTIN["clean"]

# ─────────────────────────────────────────────────────────────────────────────
# Capa de configuración externa fail-safe (styles.json + assets/marca/marca.json)
# ─────────────────────────────────────────────────────────────────────────────

_STYLES_JSON = Path(__file__).parent / "styles.json"
_MARCA_JSON = Path(__file__).parent / "assets" / "marca" / "marca.json"
_COLOR_RE = re.compile(r"^&H[0-9A-Fa-f]{8}$")


def _is_color(v: object) -> bool:
    return isinstance(v, str) and bool(_COLOR_RE.match(v))


def _is_pos_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


def _is_pos_num(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0


def _is_nonneg_num(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0


def _is_bool(v: object) -> bool:
    return isinstance(v, bool)


def _is_nonempty_str(v: object) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _is_anim(v: object) -> bool:
    return v in {"highlight", "karaoke", "bounce", "scale"}


def _is_margin(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and 0.0 < v < 0.5


def _is_pop(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and 1.0 <= v <= 2.0


# Campo -> validador. Solo estos campos son sobrescribibles desde JSON; el resto se ignora.
_FIELD_VALIDATORS = {
    "font_name": _is_nonempty_str,
    "font_size": _is_pos_int,
    "primary_color": _is_color,
    "highlight_color": _is_color,
    "outline_color": _is_color,
    "outline_size": _is_nonneg_num,
    "shadow_color": _is_color,
    "shadow_depth": _is_nonneg_num,
    "bold": _is_bool,
    "uppercase": _is_bool,
    "animation_type": _is_anim,
    "keyword_color": _is_color,
    "max_chars_per_line": _is_pos_int,
    "max_lines": _is_pos_int,
    "margin_pct": _is_margin,
    "pop_scale": _is_pop,
}


def _merge_style(base: StyleConfig, overrides: dict) -> StyleConfig:
    """Aplica overrides válidos CAMPO POR CAMPO sobre base. Inválidos/ausentes -> base."""
    kwargs = {
        field: overrides[field]
        for field, validator in _FIELD_VALIDATORS.items()
        if field in overrides and validator(overrides[field])
    }
    return replace(base, **kwargs) if kwargs else base


def _load_overrides(path: Path) -> dict:
    """Lee un JSON de overrides de estilos. Cualquier fallo -> {} (fail-safe silencioso)."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    # Admite {"styles": {...}} o el dict de estilos directo.
    section = data.get("styles", data)
    return section if isinstance(section, dict) else {}


def _build_styles() -> dict[str, StyleConfig]:
    """Compone STYLES: built-in + marca (sobre pms) + styles.json, todo fail-safe por campo."""
    result: dict[str, StyleConfig] = dict(_BUILTIN)

    # Marca (M2/M3 de K): sobrescribe pms si assets/marca/marca.json existe y es válido.
    marca = _load_overrides(_MARCA_JSON)
    if marca:
        # marca.json puede ser {"pms": {...}} o los campos de pms directo.
        pms_over = marca.get("pms", marca)
        if isinstance(pms_over, dict):
            result["pms"] = _merge_style(result["pms"], pms_over)

    # styles.json: overrides por-campo de estilos existentes + estilos nuevos.
    for name, ov in _load_overrides(_STYLES_JSON).items():
        if not isinstance(ov, dict):
            continue
        key = name.lower().strip()
        if not key:
            continue
        base = result.get(key) or replace(_DEFAULT_BASE, name=key)
        result[key] = _merge_style(base, ov)

    return result


STYLES: dict[str, StyleConfig] = _build_styles()


# ─────────────────────────────────────────────────────────────────────────────
# API pública
# ─────────────────────────────────────────────────────────────────────────────


def _resolve_pop(pop: str | float | None) -> float | None:
    """Traduce la intensidad de pop a escala. None o inválido -> None (usa la del estilo)."""
    if pop is None or isinstance(pop, bool):
        return None
    if isinstance(pop, (int, float)):
        return float(pop) if 1.0 <= pop <= 2.0 else None
    if isinstance(pop, str):
        return POP_LEVELS.get(pop.lower().strip())
    return None


def get_style(name: str, pop: str | float | None = None) -> StyleConfig:
    """Devuelve el estilo por nombre. `pop` (suave|fuerte|off|float) sobrescribe pop_scale.

    Un `pop` inválido/desconocido es fail-safe: se ignora y se usa el pop_scale del estilo.
    """
    key = name.lower().strip()
    if key not in STYLES:
        available = ", ".join(sorted(STYLES))
        raise ValueError(f"Estilo '{name}' no disponible. Opciones: {available}")
    cfg = STYLES[key]
    pv = _resolve_pop(pop)
    if pv is not None:
        cfg = replace(cfg, pop_scale=pv)
    return cfg


def list_styles() -> list[str]:
    return sorted(STYLES.keys())
