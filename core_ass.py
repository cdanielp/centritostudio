"""
core_ass.py — Generacion ASS, aplicacion de brain y quemado con FFmpeg.
Importado via core.py (re-exportado); tambien importable directamente en tests.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pysubs2

from core_ass_fx import _KW_SCALE_DEFAULT as _KW_BASE

# Primitivas de texto ASS + extensiones F6/CVE (punch_scale, glow) — re-export
# para compatibilidad: tests y consumidores siguen usando core_ass._kw_scale etc.
from core_ass_fx import (  # noqa: F401
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


# Timing del rebote (ms). Derivados del brief D19: sube en ~70ms, asienta hasta ~200ms.
_OVERSHOOT_FACTOR = 1.12  # cuanto se pasa del reposo antes de asentar
_OVERSHOOT_RISE_MS = 70
_OVERSHOOT_SETTLE_MS = 200
_POP_SIMPLE_RISE_MS = 90  # sin rebote: crece y se queda en el reposo


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
    """
    pop = getattr(style_cfg, "pop_scale", 1.0)
    if pop <= 1.0:
        return f"{{\\c{active_color}{kw_sc}}}{esc}{{\\r}}"

    base = kw_base if is_kw else 100
    rest = int(round(base * pop))  # tamaño de reposo del enfasis mientras la palabra activa
    if getattr(style_cfg, "overshoot", False):
        peak = int(round(rest * _OVERSHOOT_FACTOR))
        anim = (
            f"\\t(0,{_OVERSHOOT_RISE_MS},\\fscx{peak}\\fscy{peak})"
            f"\\t({_OVERSHOOT_RISE_MS},{_OVERSHOOT_SETTLE_MS},\\fscx{rest}\\fscy{rest})"
        )
    else:
        anim = f"\\t(0,{_POP_SIMPLE_RISE_MS},\\fscx{rest}\\fscy{rest})"
    return f"{{{anim}\\c{active_color}}}{esc}{{\\r}}"


def _word_event_text(group_words: list[dict], active_idx: int, style_cfg: StyleConfig) -> str:
    """Construye texto ASS con animacion word-by-word y keyword_color persistente al 122%."""
    parts: list[str] = []
    prev_line = None
    hl = style_cfg.highlight_color
    kw = style_cfg.keyword_color
    anim = style_cfg.animation_type

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
        else:
            parts.append(esc)

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
    subs.styles["Default"] = base


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
    """
    glow_on = getattr(style_cfg, "kw_glow", False)
    subs = pysubs2.SSAFile()
    _make_ass_style(subs, video_width, video_height, style_cfg)
    for group in groups:
        gw = group["words"]
        con_glow = glow_on and any(w.get("is_keyword", False) for w in gw)
        glow_text = _glow_event_text(gw, style_cfg) if con_glow else None
        for idx, word in enumerate(gw):
            ev_end = gw[idx + 1]["start"] if idx < len(gw) - 1 else group["end"]
            ev_end = max(ev_end, word["start"] + 0.05)
            start = pysubs2.make_time(s=word["start"])
            end = pysubs2.make_time(s=ev_end)
            if con_glow:
                subs.events.append(pysubs2.SSAEvent(start=start, end=end, text=glow_text, layer=0))
            subs.events.append(
                pysubs2.SSAEvent(
                    start=start,
                    end=end,
                    text=_word_event_text(gw, idx, style_cfg),
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
) -> float:
    """Quema ASS + overlays PNG RGBA en un solo pase FFmpeg.

    emoji_overlays: lista de (png_path, t_start_s, t_end_s).
    Posicion: centrado horizontal, arriba del bloque de captions (via style_cfg).
    Entrada/salida con fade de EMOJI_FADE_S. Lista vacia delega en burn_video.
    """
    if not emoji_overlays:
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

    ass_esc = _ffmpeg_ass_path(ass_path)

    # Inputs: video primero; cada PNG como stream en loop con duracion fija
    # (necesario para poder aplicar fade con timeline propio)
    cmd: list[str] = ["ffmpeg", "-y", "-i", str(input_video)]
    for png, t_start, t_end in emoji_overlays:
        dur = max(t_end - t_start, 0.1)
        cmd += ["-loop", "1", "-t", f"{dur:.3f}", "-i", str(png)]

    # filter_complex: ASS -> escalar+fade cada PNG -> overlay centrado en cadena
    fc_parts: list[str] = [f"[0:v]ass={ass_esc}[vcap]"]
    fade = EMOJI_FADE_S
    for i, (_png, t_start, t_end) in enumerate(emoji_overlays):
        dur = max(t_end - t_start, 0.1)
        fade_out_st = max(dur - fade, 0.0)
        fc_parts.append(
            f"[{i + 1}:v]format=rgba,scale={size_px}:-2,"
            f"fade=t=in:st=0:d={fade:.3f}:alpha=1,"
            f"fade=t=out:st={fade_out_st:.3f}:d={fade:.3f}:alpha=1,"
            f"setpts=PTS-STARTPTS+{t_start:.3f}/TB[ovs{i}]"
        )

    current = "[vcap]"
    for i, (_png, t_start, t_end) in enumerate(emoji_overlays):
        next_label = f"[vo{i}]"
        enable = f"between(t,{t_start:.3f},{t_end:.3f})"
        fc_parts.append(
            f"{current}[ovs{i}]overlay=x=(W-w)/2:y={y_px}:"
            f"eof_action=pass:enable='{enable}'{next_label}"
        )
        current = next_label

    cmd += ["-filter_complex", ";".join(fc_parts)]
    cmd += ["-map", current, "-map", "0:a"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "copy"]
    cmd.append(str(output_video))

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
