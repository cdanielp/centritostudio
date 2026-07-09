"""
core_ass.py — Generacion ASS, aplicacion de brain y quemado con FFmpeg.
Importado via core.py (re-exportado); tambien importable directamente en tests.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pysubs2

from styles import StyleConfig

# ─────────────────────────────────────────────────────────────────────────────
# Helpers internos de ASS
# ─────────────────────────────────────────────────────────────────────────────


def _ass_to_pysubs2(ass_color: str) -> pysubs2.Color:
    h = ass_color.replace("&H", "").replace("&", "").zfill(8)
    a, b, g, r = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16)
    return pysubs2.Color(r, g, b, a)


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
        # Keyword siempre usa keyword_color; no-keyword usa highlight al estar activa
        active_color = kw if is_kw else hl
        kw_sc = "\\fscx122\\fscy122" if is_kw else ""

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
                sc = 122 if is_kw else 115
                tag = f"{{\\fscx{sc}\\fscy{sc}\\c{active_color}}}{esc}{{\\r}}"
            else:
                tag = f"{{\\c{active_color}{kw_sc}}}{esc}{{\\r}}"
            parts.append(tag)
        elif is_kw:
            # Persistente: keyword_color + 122% durante toda la duracion del grupo
            parts.append(f"{{\\c{kw}\\fscx122\\fscy122}}{esc}{{\\r}}")
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
    base.fontsize = max(int(style_cfg.font_size * dim_scale), 20)
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
    """Genera el .ass con captions animados word-by-word, escalado relativo a PlayResY."""
    subs = pysubs2.SSAFile()
    _make_ass_style(subs, video_width, video_height, style_cfg)
    for group in groups:
        gw = group["words"]
        for idx, word in enumerate(gw):
            ev_end = gw[idx + 1]["start"] if idx < len(gw) - 1 else group["end"]
            ev_end = max(ev_end, word["start"] + 0.05)
            subs.events.append(
                pysubs2.SSAEvent(
                    start=pysubs2.make_time(s=word["start"]),
                    end=pysubs2.make_time(s=ev_end),
                    text=_word_event_text(gw, idx, style_cfg),
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
