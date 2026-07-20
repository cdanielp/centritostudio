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

# Timing del rebote (ms). Derivados del brief D19: sube en ~70ms, asienta hasta ~200ms.
# Viven aqui (no en core_ass) para que el glow y la palabra activa compartan la MISMA
# envolvente de escala sin dependencia circular.
_OVERSHOOT_FACTOR = 1.12  # cuanto se pasa del reposo antes de asentar
_OVERSHOOT_RISE_MS = 70
_OVERSHOOT_SETTLE_MS = 200
_POP_SIMPLE_RISE_MS = 90  # sin rebote: crece y se queda en el reposo


def _kw_scale(w: dict) -> int:
    """Escala persistente del keyword: punch_scale de la palabra si es valida, si no 122."""
    v = w.get("punch_scale")
    if isinstance(v, int) and not isinstance(v, bool) and _KW_SCALE_MIN <= v <= _KW_SCALE_MAX:
        return v
    return _KW_SCALE_DEFAULT


def _active_scale_anim(style_cfg: StyleConfig, is_kw: bool, sc_kw: int) -> str:
    """SOLO la parte de escala/animacion (`\\fscx..\\fscy..` o `\\t(...)`) de la palabra activa.

    Sin color ni glow: es la envolvente de ESCALA que define el ancho de avance del texto.
    La comparte la capa de texto (`_word_event_text`) y la capa de glow (`_glow_event_text`)
    para que ambas tengan METRICAS IDENTICAS por frame — mismo wrap, mismo centrado, cero
    desalineacion (fix duplicacion phrase spans). Debe reflejar EXACTAMENTE la escala que
    `_word_event_text` aplica a la palabra activa segun `animation_type`. `sc_kw` = escala
    persistente del keyword (int).
    """
    anim = style_cfg.animation_type
    if anim == "bounce":
        hi, lo = (128, 122) if is_kw else (122, 100)
        return f"\\t(0,80,\\fscx{hi}\\fscy{hi})\\t(80,160,\\fscx{lo}\\fscy{lo})"
    if anim == "scale":
        sc = sc_kw if is_kw else 115
        return f"\\fscx{sc}\\fscy{sc}"
    if anim == "karaoke":
        return f"\\fscx{sc_kw}\\fscy{sc_kw}" if is_kw else ""
    # highlight (default): color + scale-pop con reposo (s28C) y rebote opcional.
    pop = getattr(style_cfg, "pop_scale", 1.0)
    if pop <= 1.0:
        return f"\\fscx{sc_kw}\\fscy{sc_kw}" if is_kw else ""
    base = sc_kw if is_kw else 100
    rest = int(round(base * pop))
    if getattr(style_cfg, "overshoot", False):
        peak = int(round(rest * _OVERSHOOT_FACTOR))
        return (
            f"\\t(0,{_OVERSHOOT_RISE_MS},\\fscx{peak}\\fscy{peak})"
            f"\\t({_OVERSHOOT_RISE_MS},{_OVERSHOOT_SETTLE_MS},\\fscx{rest}\\fscy{rest})"
        )
    return f"\\t(0,{_POP_SIMPLE_RISE_MS},\\fscx{rest}\\fscy{rest})"


def _color_sin_alpha(ass_color: str) -> str:
    """&HAABBGGRR -> &HBBGGRR& (formato de los tags \\3c/\\c inline)."""
    h = ass_color.replace("&H", "").replace("&", "").zfill(8)
    return f"&H{h[2:]}&"


def _glow_event_text(group_words: list[dict], active_idx: int, style_cfg: StyleConfig) -> str:
    """Texto del evento gemelo de glow (capa 0): todo invisible salvo el halo del keyword.

    El keyword lleva relleno/sombra transparentes + borde grueso del color de acento +
    blur -> halo detras de la palabra visible de la capa 1. CADA palabra recibe la MISMA
    escala que en `_word_event_text` (incluida la animacion de la palabra activa `active_idx`)
    para que ambas capas compartan layout exacto: mismo wrap y centrado, sin desalineacion
    (fix duplicacion de phrase spans — el glow estatico se descuadraba con la palabra que
    hace pop). Las no-keyword quedan invisibles pero conservan su ancho para no desplazar.
    """
    accent = _color_sin_alpha(style_cfg.keyword_color)
    parts: list[str] = []
    prev_line = None
    for i, w in enumerate(group_words):
        if prev_line is not None and w["line_idx"] != prev_line:
            if parts and parts[-1] != "\\N":
                parts.append("\\N")
        disp = w["text"].upper() if style_cfg.uppercase else w["text"]
        esc = _escape_ass(disp)
        is_kw = w.get("is_keyword", False)
        sc = _kw_scale(w)
        # Escala IDENTICA a la capa de texto: activa -> misma animacion; keyword no activa
        # -> escala persistente; no-keyword -> base (100%). Layout compartido por frame.
        if i == active_idx:
            scale = _active_scale_anim(style_cfg, is_kw, sc)
        elif is_kw:
            scale = f"\\fscx{sc}\\fscy{sc}"
        else:
            scale = ""
        if is_kw:
            parts.append(
                f"{{\\1a&HFF&\\4a&HFF&\\bord{_GLOW_BORD}\\blur{_GLOW_BLUR}"
                f"\\3c{accent}{scale}}}{esc}{{\\r}}"
            )
        else:
            parts.append(f"{{\\alpha&HFF&{scale}}}{esc}{{\\r}}")
        prev_line = w["line_idx"]
    return _join_parts(parts)
