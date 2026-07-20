"""
core_ass.py — Generacion ASS, aplicacion de brain y quemado con FFmpeg.
Importado via core.py (re-exportado); tambien importable directamente en tests.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pysubs2

import core_overlays  # constructor puro del comando de overlays (F6 S31)
from core_ass_fx import _KW_SCALE_DEFAULT as _KW_BASE

# Primitivas de texto ASS + extensiones F6/CVE (punch_scale, glow) — re-export
# para compatibilidad: tests y consumidores siguen usando core_ass._kw_scale etc.
from core_ass_fx import (  # noqa: F401
    _OVERSHOOT_FACTOR,
    _OVERSHOOT_RISE_MS,
    _OVERSHOOT_SETTLE_MS,
    _POP_SIMPLE_RISE_MS,
    _active_scale_anim,
    _escape_ass,
    _glow_event_text,
    _join_parts,
    _kw_scale,
)
from styles import StyleConfig

# ─────────────────────────────────────────────────────────────────────────────
# Helpers internos de ASS
# ─────────────────────────────────────────────────────────────────────────────


def _ass_to_pysubs2(ass_color: str) -> pysubs2.Color:
    h = ass_color.replace("&H", "").replace("&", "").zfill(8)
    a, b, g, r = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16)
    return pysubs2.Color(r, g, b, a)


def _active_highlight_tag(
    style_cfg: StyleConfig,
    is_kw: bool,
    active_color: str,
    kw_sc: str,
    esc: str,
    kw_base: int = _KW_BASE,
) -> str:
    """Tag ASS de la palabra activa en modo highlight.

    pop_scale<=1.0: solo color (byte-identico al caption estatico). >1.0: scale-pop con
    reposo del enfasis en `rest` (mas grande que los vecinos). Con overshoot, rebota al pico.
    La escala sale de `_active_scale_anim` (fuente unica compartida con el glow): mismo
    ancho de avance -> el gemelo de glow queda perfectamente alineado.
    """
    pop = getattr(style_cfg, "pop_scale", 1.0)
    if pop <= 1.0:
        return f"{{\\c{active_color}{kw_sc}}}{esc}{{\\r}}"
    anim = _active_scale_anim(style_cfg, is_kw, kw_base)
    return f"{{{anim}\\c{active_color}}}{esc}{{\\r}}"


def _word_event_text(group_words: list[dict], active_idx: int, style_cfg: StyleConfig) -> str:
    """Construye texto ASS con animacion word-by-word y keyword_color persistente al 122%."""
    parts: list[str] = []
    prev_line = None
    hl = style_cfg.highlight_color
    kw = style_cfg.keyword_color
    anim = style_cfg.animation_type
    # Karaoke moderno (F6/CVE): palabras ya dichas quedan marcadas. None = ruta histórica.
    past = getattr(style_cfg, "karaoke_past_color", None)

    for i, w in enumerate(group_words):
        if prev_line is not None and w["line_idx"] != prev_line:
            if parts and parts[-1] != "\\N":
                parts.append("\\N")

        disp = w["text"].upper() if style_cfg.uppercase else w["text"]
        esc = _escape_ass(disp)
        is_kw = w.get("is_keyword", False)
        sc_kw = _kw_scale(w)  # 122 salvo punch_scale del engine (F6)
        # Keyword siempre usa keyword_color; no-keyword usa highlight al estar activa
        active_color = kw if is_kw else hl
        kw_sc = f"\\fscx{sc_kw}\\fscy{sc_kw}" if is_kw else ""

        if i == active_idx:
            if anim == "karaoke":
                dur_cs = max(int((w["end"] - w["start"]) * 100), 5)
                tag = f"{{\\kf{dur_cs}\\c{active_color}{kw_sc}}}{esc}{{\\r}}"
            elif anim == "bounce":
                hi, lo = (128, 122) if is_kw else (122, 100)
                tag = (
                    f"{{\\t(0,80,\\fscx{hi}\\fscy{hi})"
                    f"\\t(80,160,\\fscx{lo}\\fscy{lo})\\c{active_color}}}{esc}{{\\r}}"
                )
            elif anim == "scale":
                sc = sc_kw if is_kw else 115
                tag = f"{{\\fscx{sc}\\fscy{sc}\\c{active_color}}}{esc}{{\\r}}"
            else:
                # highlight: color + scale-pop con reposo (s28C) y rebote opcional.
                # El reposo del keyword parte de sc_kw (punch_scale del engine o 122).
                tag = _active_highlight_tag(style_cfg, is_kw, active_color, kw_sc, esc, sc_kw)
            parts.append(tag)
        elif is_kw:
            # Persistente: keyword_color + escala kw durante toda la duracion del grupo
            parts.append(f"{{\\c{kw}\\fscx{sc_kw}\\fscy{sc_kw}}}{esc}{{\\r}}")
        elif anim == "karaoke" and past and i < active_idx:
            # Ya dicha: queda marcada con el color pasado (karaoke_highlight, F6/CVE)
            parts.append(f"{{\\c{past}}}{esc}{{\\r}}")
        else:
            parts.append(esc)

        prev_line = w["line_idx"]

    return _join_parts(parts)


def _static_cue_text(group_words: list[dict], style_cfg: StyleConfig) -> str:
    """Texto ASS estatico de un cue de fallback SRT (S36-B, D36B-3): sin word-by-word.

    Preserva el texto y los saltos de linea (via line_idx). Sin tags de color inline:
    se pinta con el color primario del estilo -> caption estatico honesto, no karaoke
    falso. Aditivo: solo se usa cuando el group trae timing_mode="cue_fallback".
    """
    parts: list[str] = []
    prev_line = None
    for w in group_words:
        if prev_line is not None and w["line_idx"] != prev_line:
            if parts and parts[-1] != "\\N":
                parts.append("\\N")
        disp = w["text"].upper() if style_cfg.uppercase else w["text"]
        parts.append(_escape_ass(disp))
        prev_line = w["line_idx"]
    return _join_parts(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Cerebro editorial — aplicacion de brain.json
# ─────────────────────────────────────────────────────────────────────────────


def apply_brain(groups: list[dict], brain_data: dict) -> list[dict]:
    """Enriquece grupos con is_keyword y brain_emoji. Re-grouping-safe via kw_ts."""
    if not brain_data or not brain_data.get("groups"):
        return groups

    # Map: kw_ts (redondeado a 3 dec) → emoji (puede ser None)
    kw_ts_map: dict[float, str | None] = {}
    for item in brain_data["groups"]:
        kw_ts = item.get("kw_ts")
        if kw_ts is not None:
            kw_ts_map[round(float(kw_ts), 3)] = item.get("emoji")

    result = []
    for g in groups:
        words = [dict(w) for w in g["words"]]
        brain_emoji = None
        for i, w in enumerate(words):
            w_ts = round(float(w.get("start", -999)), 3)
            if w_ts in kw_ts_map:
                words[i]["is_keyword"] = True
                if kw_ts_map[w_ts]:
                    brain_emoji = kw_ts_map[w_ts]
        result.append({**g, "words": words, "brain_emoji": brain_emoji})
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Generacion de archivo .ass
# ─────────────────────────────────────────────────────────────────────────────


def _scaled_fontsize(video_width: int, video_height: int, style_cfg: StyleConfig) -> int:
    """Fontsize del ASS escalado a la resolucion (fuente unica de la formula)."""
    ref_h = 1920 if video_height >= video_width else 1080
    dim_scale = max(video_height / ref_h, 0.40)
    return max(int(style_cfg.font_size * dim_scale), 20)


def _make_ass_style(
    subs: pysubs2.SSAFile, video_width: int, video_height: int, style_cfg: StyleConfig
) -> None:
    """Configura PlayRes, ScaledBorderAndShadow y el estilo Default."""
    ref_h = 1920 if video_height >= video_width else 1080
    dim_scale = max(video_height / ref_h, 0.40)
    subs.info.update(
        {
            "WrapStyle": "3",
            "ScaledBorderAndShadow": "yes",
            "PlayResX": str(video_width),
            "PlayResY": str(video_height),
            "ScriptType": "v4.00+",
        }
    )
    base = pysubs2.SSAStyle()
    base.fontname = style_cfg.font_name
    base.fontsize = _scaled_fontsize(video_width, video_height, style_cfg)
    base.primarycolor = _ass_to_pysubs2(style_cfg.primary_color)
    base.bold = style_cfg.bold
    base.outline = round(style_cfg.outline_size * dim_scale, 1)
    base.outlinecolor = _ass_to_pysubs2(style_cfg.outline_color)
    base.shadow = round(style_cfg.shadow_depth * dim_scale, 1)
    base.shadowcolor = _ass_to_pysubs2(style_cfg.shadow_color)
    base.alignment = pysubs2.Alignment.BOTTOM_CENTER
    base.marginl = int(50 * dim_scale)
    base.marginr = int(50 * dim_scale)
    base.marginv = int(video_height * style_cfg.margin_pct)
    if getattr(style_cfg, "karaoke_past_color", None):
        # Con \kf en la linea, libass pinta el texto posterior como "silaba futura"
        # usando SecondaryColour (default pysubs2: ROJO). El karaoke moderno exige
        # las siguientes EN BASE -> secundario = primario. Solo con past color ON:
        # el estilo karaoke clasico (aprobado) queda byte-identico.
        base.secondarycolor = _ass_to_pysubs2(style_cfg.primary_color)
    subs.styles["Default"] = base


def _pos_tag(group: dict) -> str:
    """Override de alineacion inline por grupo (F6 avoid_faces/[center]).

    'top' -> \\an8 (arriba-centro), 'center' -> \\an5 (centro). 'bottom'/ausente ->
    sin override: la ruta historica (BOTTOM_CENTER del estilo) queda byte-identica.
    """
    p = group.get("caption_pos")
    if p == "top":
        return "{\\an8}"
    if p == "center":
        return "{\\an5}"
    return ""


def build_ass(
    groups: list[dict],
    video_width: int,
    video_height: int,
    style_cfg: StyleConfig,
    output_path: Path,
) -> None:
    """Genera el .ass con captions animados word-by-word, escalado relativo a PlayResY.

    Con kw_glow (F6/CVE) los grupos con keyword emiten su texto en capa 1 y un evento
    gemelo de glow en capa 0. Default off: eventos sin capa, ruta identica a la actual.
    Con caption_pos (F6) el grupo lleva un override \\an; bottom/ausente = byte-identico.
    """
    glow_on = getattr(style_cfg, "kw_glow", False)
    subs = pysubs2.SSAFile()
    _make_ass_style(subs, video_width, video_height, style_cfg)
    for group in groups:
        pos = _pos_tag(group)
        # S36-B: cue de fallback SRT -> UN evento estatico con el texto exacto del cue
        # (sin animacion word-by-word). Aditivo: los groups historicos no traen la clave.
        if group.get("timing_mode") == "cue_fallback":
            subs.events.append(
                pysubs2.SSAEvent(
                    start=pysubs2.make_time(s=group["start"]),
                    end=pysubs2.make_time(s=max(group["end"], group["start"] + 0.05)),
                    text=pos + _static_cue_text(group["words"], style_cfg),
                    layer=0,
                )
            )
            continue
        gw = group["words"]
        con_glow = glow_on and any(w.get("is_keyword", False) for w in gw)
        for idx, word in enumerate(gw):
            ev_end = gw[idx + 1]["start"] if idx < len(gw) - 1 else group["end"]
            ev_end = max(ev_end, word["start"] + 0.05)
            start = pysubs2.make_time(s=word["start"])
            end = pysubs2.make_time(s=ev_end)
            if con_glow:
                # Glow gemelo POR palabra activa: misma escala/animacion que la capa de
                # texto -> layout identico, sin la duplicacion del glow estatico anterior.
                subs.events.append(
                    pysubs2.SSAEvent(
                        start=start,
                        end=end,
                        text=pos + _glow_event_text(gw, idx, style_cfg),
                        layer=0,
                    )
                )
            subs.events.append(
                pysubs2.SSAEvent(
                    start=start,
                    end=end,
                    text=pos + _word_event_text(gw, idx, style_cfg),
                    layer=1 if con_glow else 0,
                )
            )
    subs.save(str(output_path))


# ─────────────────────────────────────────────────────────────────────────────
# Quemado y miniaturas
# ─────────────────────────────────────────────────────────────────────────────


def _ffmpeg_ass_path(ass_path: Path) -> str:
    """Convierte ruta a formato compatible con filtro ass en Windows."""
    try:
        rel = ass_path.resolve().relative_to(Path.cwd())
        return str(rel).replace("\\", "/")
    except ValueError:
        pass
    s = str(ass_path.resolve()).replace("\\", "/")
    if len(s) >= 2 and s[1] == ":":
        s = s[0] + "\\:" + s[2:]
    return s


def burn_video(input_video: Path, ass_path: Path, output_video: Path) -> float:
    """Quema el .ass sobre el video. Devuelve el tiempo de proceso en segundos."""
    t0 = time.time()
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_video),
        "-vf",
        f"ass={_ffmpeg_ass_path(ass_path)}",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-c:a",
        "copy",
        str(output_video),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"FFmpeg error:\n{r.stderr[-1500:]}")
    return round(time.time() - t0, 2)


def _emoji_y_sobre_captions(
    video_w: int, video_h: int, size_px: int, style_cfg: StyleConfig | None
) -> int:
    """Calcula la y del emoji: centrado justo ARRIBA del bloque de captions.

    Deriva la posicion del ASS: marginv = H * margin_pct (anclado abajo),
    bloque de captions ~2 lineas a fontsize escalado. Fallback sin estilo:
    35% desde abajo.
    """
    if style_cfg is None:
        return max(0, video_h - int(0.35 * video_h) - size_px)
    fontsize = _scaled_fontsize(video_w, video_h, style_cfg)
    marginv = int(video_h * style_cfg.margin_pct)
    # 2 lineas con interlineado + outline ~ 2.6x fontsize
    caption_top = video_h - marginv - int(2.6 * fontsize)
    gap = int(0.015 * video_h)
    return max(0, caption_top - size_px - gap)


def burn_video_with_emojis(
    input_video: Path,
    ass_path: Path,
    output_video: Path,
    emoji_overlays: list[tuple[Path, float, float]],
    style_cfg: StyleConfig | None = None,
    popups: list | None = None,
    fx_plan=None,
    clips: list | None = None,
) -> float:
    """Quema FX + ASS + overlays PNG RGBA (emojis y popups) + clips de video en un solo pase FFmpeg.

    emoji_overlays: lista de (png_path, t_start_s, t_end_s) — capa historica intacta.
    popups: lista opcional de core_overlays.Popup (F6 S31); None/vacia = flujo anterior
    byte-identico. fx_plan: fx.FXPlan opcional (S36-FX); sus punch/flash/scanner van ANTES
    del ass y su logo/outro entra como popup. clips: lista opcional de clip_overlay.ClipOverlay
    (PR B, b-roll de video); su audio NUNCA se mapea (solo 0:a). Sin nada delega en burn_video.
    """
    if not emoji_overlays and not popups and fx_plan is None and not clips:
        return burn_video(input_video, ass_path, output_video)

    # Dimensiones calculadas en Python (NO en expresiones FFmpeg) para evitar
    # que `iw` en el filtro scale referencie el PNG y no el video principal.
    import core  # noqa: PLC0415
    from assets_comfy import EMOJI_FADE_S, EMOJI_SIZE_PCT  # noqa: PLC0415

    info = core.get_video_info(input_video)
    video_w, video_h = info["width"], info["height"]
    size_px = max(int(video_w * EMOJI_SIZE_PCT), 2)
    size_px -= size_px % 2  # forzar par para evitar errores libx264
    y_px = _emoji_y_sobre_captions(video_w, video_h, size_px, style_cfg)

    fx_prefilter = None
    popups = list(popups or [])
    if fx_plan is not None and not fx_plan.vacio():
        import fx as fxmod  # noqa: PLC0415

        chain, _out = fxmod.construir_filtro_video_fx(
            "0:v", fx_plan, video_w, video_h, info.get("fps", 30.0)
        )
        fx_prefilter = chain or None
        logo_popup = fxmod.logo_a_popup(fx_plan)
        if logo_popup is not None:
            popups.append(logo_popup)  # logo/outro = overlay PNG real, encima del ass

    cmd = core_overlays.construir_comando(
        input_video,
        _ffmpeg_ass_path(ass_path),
        output_video,
        emoji_overlays,
        size_px,
        y_px,
        EMOJI_FADE_S,
        video_w,
        video_h,
        popups,
        fx_prefilter,
        clips=clips,
        fps=info.get("fps", 30.0),
    )

    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"FFmpeg error:\n{r.stderr[-1500:]}")
    return round(time.time() - t0, 2)


def extract_thumb(video_path: Path, output_path: Path, at_sec: float = 1.0) -> None:
    """Extrae un frame del video como miniatura."""
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            str(at_sec),
            "-i",
            str(video_path),
            "-vframes",
            "1",
            "-vf",
            "scale=200:-1",
            str(output_path),
        ],
        capture_output=True,
    )
