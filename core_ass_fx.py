"""core_ass_fx.py — Primitivas de texto ASS + extensiones F6/CVE del motor de captions.

Vive separado de core_ass.py para que el motor no crezca (limite 400 lineas,
centrito-dev). Todo lo de F6 es aditivo y default-off: sin punch_scale por palabra
y sin kw_glow en el estilo, core_ass produce exactamente el ASS de siempre.
"""

from __future__ import annotations

from styles import StyleConfig

# ─────────────────────────────────────────────────────────────────────────────
# Primitivas compartidas de texto ASS (usadas por core_ass y por el glow)
# ─────────────────────────────────────────────────────────────────────────────


def _escape_ass(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")


def _join_parts(parts: list[str]) -> str:
    """Une partes de texto ASS respetando saltos de linea."""
    result: list[str] = []
    for p in parts:
        if p == "\\N":
            if result and result[-1] == " ":
                result.pop()
            result.append("\\N")
        else:
            if result and result[-1] != "\\N":
                result.append(" ")
            result.append(p)
    return "".join(result)


# ─────────────────────────────────────────────────────────────────────────────
# F6/CVE: escala por-palabra del keyword + glow aprox (default off)
# ─────────────────────────────────────────────────────────────────────────────

# Escala del keyword: 122 es el comportamiento historico; el engine CVE puede
# sobrescribirla POR PALABRA via w["punch_scale"] (F6). Fuera de rango -> 122.
_KW_SCALE_DEFAULT = 122
_KW_SCALE_MIN, _KW_SCALE_MAX = 100, 250

# Glow aprox del keyword (kw_glow, F6/CVE): capa 0 detras del texto (capa 1).
_GLOW_BORD = 7
_GLOW_BLUR = 5


def _kw_scale(w: dict) -> int:
    """Escala persistente del keyword: punch_scale de la palabra si es valida, si no 122."""
    v = w.get("punch_scale")
    if isinstance(v, int) and not isinstance(v, bool) and _KW_SCALE_MIN <= v <= _KW_SCALE_MAX:
        return v
    return _KW_SCALE_DEFAULT


def _color_sin_alpha(ass_color: str) -> str:
    """&HAABBGGRR -> &HBBGGRR& (formato de los tags \\3c/\\c inline)."""
    h = ass_color.replace("&H", "").replace("&", "").zfill(8)
    return f"&H{h[2:]}&"


def _glow_event_text(group_words: list[dict], style_cfg: StyleConfig) -> str:
    """Texto del evento gemelo de glow (capa 0): todo invisible salvo el halo del keyword.

    El keyword lleva relleno/sombra transparentes + borde grueso del color de acento +
    blur -> halo detras de la palabra visible de la capa 1. Mismas metricas de texto.
    """
    accent = _color_sin_alpha(style_cfg.keyword_color)
    parts: list[str] = []
    prev_line = None
    for w in group_words:
        if prev_line is not None and w["line_idx"] != prev_line:
            if parts and parts[-1] != "\\N":
                parts.append("\\N")
        disp = w["text"].upper() if style_cfg.uppercase else w["text"]
        esc = _escape_ass(disp)
        if w.get("is_keyword", False):
            sc = _kw_scale(w)
            parts.append(
                f"{{\\1a&HFF&\\4a&HFF&\\bord{_GLOW_BORD}\\blur{_GLOW_BLUR}"
                f"\\3c{accent}\\fscx{sc}\\fscy{sc}}}{esc}{{\\r}}"
            )
        else:
            parts.append(f"{{\\alpha&HFF&}}{esc}{{\\r}}")
        prev_line = w["line_idx"]
    return _join_parts(parts)
