"""core_overlays.py — Constructor puro del comando FFmpeg de overlays (emojis + popups).

Extraido de core_ass.burn_video_with_emojis (F6 S31): la cadena de emojis se genera
byte-identica a la historica; los popups de imagen (cve_popups) entran como capa
opcional con 9 anclas, auto_safe y behind_text. Sin I/O de video ni subprocess:
aqui solo se construyen strings de filtros y el comando; core_ass ejecuta FFmpeg.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Safe zones 9:16 (DISENO_CVE.md §5.1) — fuente unica; cve.py las re-exporta.
SAFE_TOP_PCT = 0.10  # username / sonido
SAFE_BOTTOM_PCT = 0.18  # descripcion / barra de progreso
SAFE_RIGHT_PCT = 0.14  # columna de acciones (like/comment/share)
SAFE_LEFT_PCT = 0.05  # respiro simetrico minimo

# 9 anclas del spec de K (§5.1); auto_safe = arriba del bloque de captions, centrado
ANCLAS = frozenset(
    {
        "top_left",
        "top",
        "top_right",
        "left",
        "center",
        "right",
        "bottom_left",
        "bottom",
        "bottom_right",
    }
)

POPUP_SIZE_PCT = 0.20  # ancho del popup respecto al ancho del video
POPUP_MIN_SIZE_PCT = 0.12  # piso de la cadena REDUCIR (§5.3)
POPUP_FADE_S = 0.12  # mismo fade probado de la capa de emojis


@dataclass(frozen=True)
class Popup:
    """Popup de imagen resuelto por cve_popups: semantico, sin pixeles todavia."""

    png: Path
    t0: float
    t1: float
    pos: str = "auto_safe"
    size_pct: float = POPUP_SIZE_PCT
    behind_text: bool = False
    fade: bool = True


def zona_util(video_w: int, video_h: int) -> tuple[int, int, int, int]:
    """(x0, y0, x1, y1) de la zona libre de UI de TikTok/Reels/Shorts."""
    return (
        int(video_w * SAFE_LEFT_PCT),
        int(video_h * SAFE_TOP_PCT),
        int(video_w * (1.0 - SAFE_RIGHT_PCT)),
        int(video_h * (1.0 - SAFE_BOTTOM_PCT)),
    )


def calcular_xy(pos: str, video_w: int, video_h: int, size_px: int, y_auto: int) -> tuple[int, int]:
    """(x, y) en pixeles del ancla, siempre DENTRO de la zona util (paso MOVER, §5.3).

    El alto del PNG se aproxima con size_px (misma aproximacion que la capa de
    emojis: escala por ancho). auto_safe = centrado arriba del bloque de captions
    (y_auto), recortado a la zona util. Posicion desconocida cae a auto_safe.
    """
    x0, y0, x1, y1 = zona_util(video_w, video_h)
    if pos != "auto_safe" and pos not in ANCLAS:
        print(f"[popups] posicion '{pos}' desconocida - se usa auto_safe")
        pos = "auto_safe"
    cx = (video_w - size_px) // 2
    cy = (video_h - size_px) // 2
    if pos == "auto_safe":
        x, y = cx, y_auto
    else:
        hor = "left" if "left" in pos else ("right" if "right" in pos else "center")
        ver = (
            "top" if pos.startswith("top") else ("bottom" if pos.startswith("bottom") else "center")
        )
        x = {"left": x0, "center": cx, "right": x1 - size_px}[hor]
        y = {"top": y0, "center": cy, "bottom": y1 - size_px}[ver]
    x = max(x0, min(x, x1 - size_px))
    y = max(y0, min(y, y1 - size_px))
    return x, y


def _preparar_popup(p: Popup, video_w: int, video_h: int, y_auto: int) -> dict | None:
    """Popup semantico -> pixeles concretos. Cadena §5.3: REDUCIR -> MOVER -> DESACTIVAR.

    None = popup desactivado (imagen faltante, rango invalido o no cabe): se omite
    con log y el render sigue — desactivar quita el adorno, nunca rompe el video.
    """
    nombre = Path(p.png).name
    if not Path(p.png).exists():
        print(f"[popups] imagen no encontrada, popup omitido: {p.png}")
        return None
    if p.t1 <= p.t0:
        print(f"[popups] rango invalido ({p.t0:.2f}-{p.t1:.2f}), popup omitido: {nombre}")
        return None
    x0, _y0, x1, _y1 = zona_util(video_w, video_h)
    ancho_util = x1 - x0
    size = int(video_w * p.size_pct)
    if size > ancho_util:  # REDUCIR: baja hasta el ancho util (piso POPUP_MIN_SIZE_PCT)
        reducido = max(int(video_w * POPUP_MIN_SIZE_PCT), min(size, ancho_util))
        print(f"[popups] '{nombre}' reducido {size}px -> {reducido}px (zona util)")
        size = reducido
    if size > ancho_util:  # ni reducido cabe -> DESACTIVAR
        print(f"[popups] '{nombre}' no cabe ni reducido: popup desactivado")
        return None
    size = max(size - size % 2, 2)  # par para libx264
    x, y = calcular_xy(p.pos, video_w, video_h, size, y_auto)  # MOVER via clamp
    return {
        "png": p.png,
        "t0": p.t0,
        "t1": p.t1,
        "size": size,
        "x": x,
        "y": y,
        "fade_s": POPUP_FADE_S if p.fade else 0.0,
        "behind": p.behind_text,
    }


def _filtro_png(idx: int, size_px: int, t0: float, t1: float, fade_s: float, label: str) -> str:
    """Filtro de preparacion de un PNG: rgba + escala + fade opcional + reloj propio."""
    dur = max(t1 - t0, 0.1)
    fades = ""
    if fade_s > 0:
        out_st = max(dur - fade_s, 0.0)
        fades = (
            f"fade=t=in:st=0:d={fade_s:.3f}:alpha=1,"
            f"fade=t=out:st={out_st:.3f}:d={fade_s:.3f}:alpha=1,"
        )
    return (
        f"[{idx}:v]format=rgba,scale={size_px}:-2,{fades}setpts=PTS-STARTPTS+{t0:.3f}/TB[{label}]"
    )


def _filtro_overlay(
    src: str, ovl: str, x: int | str, y: int, t0: float, t1: float, dest: str
) -> str:
    """Filtro overlay con ventana temporal (labels sin corchetes)."""
    enable = f"between(t,{t0:.3f},{t1:.3f})"
    return f"[{src}][{ovl}]overlay=x={x}:y={y}:eof_action=pass:enable='{enable}'[{dest}]"


def construir_comando(
    input_video: Path,
    ass_esc: str,
    output_video: Path,
    emoji_overlays: list[tuple[Path, float, float]],
    emoji_size_px: int,
    emoji_y_px: int,
    emoji_fade_s: float,
    video_w: int,
    video_h: int,
    popups: list[Popup] | None = None,
) -> list[str]:
    """Comando FFmpeg completo: ass + emojis (cadena historica) + popups opcionales.

    Sin popups el comando es BYTE-IDENTICO al historico de burn_video_with_emojis
    (test de contrato lo fija). behind_text: esos popups se componen ANTES del
    filtro ass, asi los captions quedan encima.
    """
    prep = [_preparar_popup(p, video_w, video_h, emoji_y_px) for p in (popups or [])]
    activos = [p for p in prep if p]
    behind = [p for p in activos if p["behind"]]
    front = [p for p in activos if not p["behind"]]

    cmd: list[str] = ["ffmpeg", "-y", "-i", str(input_video)]
    for png, t0, t1 in emoji_overlays:
        cmd += ["-loop", "1", "-t", f"{max(t1 - t0, 0.1):.3f}", "-i", str(png)]
    for p in behind + front:
        cmd += ["-loop", "1", "-t", f"{max(p['t1'] - p['t0'], 0.1):.3f}", "-i", str(p["png"])]

    fc: list[str] = []
    idx0 = 1 + len(emoji_overlays)  # primer input de popups
    base = "0:v"
    for i, p in enumerate(behind):
        fc.append(_filtro_png(idx0 + i, p["size"], p["t0"], p["t1"], p["fade_s"], f"pb{i}"))
        fc.append(_filtro_overlay(base, f"pb{i}", p["x"], p["y"], p["t0"], p["t1"], f"vb{i}"))
        base = f"vb{i}"
    fc.append(f"[{base}]ass={ass_esc}[vcap]")
    for i, (_png, t0, t1) in enumerate(emoji_overlays):
        fc.append(_filtro_png(i + 1, emoji_size_px, t0, t1, emoji_fade_s, f"ovs{i}"))
    current = "vcap"
    for i, (_png, t0, t1) in enumerate(emoji_overlays):
        fc.append(_filtro_overlay(current, f"ovs{i}", "(W-w)/2", emoji_y_px, t0, t1, f"vo{i}"))
        current = f"vo{i}"
    for j, p in enumerate(front):
        k = idx0 + len(behind) + j
        fc.append(_filtro_png(k, p["size"], p["t0"], p["t1"], p["fade_s"], f"pf{j}"))
        fc.append(_filtro_overlay(current, f"pf{j}", p["x"], p["y"], p["t0"], p["t1"], f"vp{j}"))
        current = f"vp{j}"

    cmd += ["-filter_complex", ";".join(fc)]
    cmd += ["-map", f"[{current}]", "-map", "0:a"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "copy"]
    cmd.append(str(output_video))
    return cmd
