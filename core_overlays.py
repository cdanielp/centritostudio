"""core_overlays.py — Constructor puro del comando FFmpeg de overlays (emojis + popups).

Extraido de core_ass.burn_video_with_emojis (F6 S31): la cadena de emojis se genera
byte-identica a la historica; los popups de imagen (cve_popups) entran como capa
opcional con 9 anclas, auto_safe y behind_text. Sin I/O de video ni subprocess:
aqui solo se construyen strings de filtros y el comando; core_ass ejecuta FFmpeg.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import clip_overlay  # cutaway de CLIP de video (PR B): tipo + filtros puros, capa aditiva

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

# Cutaway (b-roll de imagen grande): salta la zona util, se centra y ocupa gran parte
# o todo el cuadro. Encaje EXPLICITO sin deformar: contain (imagen entera) | cover
# (llena y recorta). El tamano default 0.85 lo aplica la capa de declaracion (cve_popups).
CUTAWAY_FIT = frozenset({"contain", "cover"})
CUTAWAY_SIZE_PCT = 0.85  # fraccion del cuadro en ambos ejes; 1.0 = pantalla completa
CUTAWAY_FADE_S = 0.20  # fade un poco mas largo por ser un elemento grande


@dataclass(frozen=True)
class Popup:
    """Popup de imagen resuelto por cve_popups: semantico, sin pixeles todavia.

    size_pct default de construccion = None: se resuelve en __post_init__ al default que
    corresponde -POPUP_SIZE_PCT (popup pequeno) o CUTAWAY_SIZE_PCT (cutaway)-. Un valor
    explicito, INCLUIDO 0.20, se conserva (distingue omitido de 0.20 explicito). Tras
    construir, size_pct es SIEMPRE un float; el resto del codigo puede leerlo sin chequear None.
    """

    png: Path
    t0: float
    t1: float
    pos: str = "auto_safe"
    size_pct: float | None = None
    behind_text: bool = False
    fade: bool = True
    cutaway: bool = False  # True: b-roll grande centrado (salta zona util, usa fit)
    fit: str = "contain"  # solo cutaway: 'contain' (entera) | 'cover' (llena+recorta)

    def __post_init__(self) -> None:
        if self.size_pct is None:  # frozen -> object.__setattr__ para normalizar en sitio
            default = CUTAWAY_SIZE_PCT if self.cutaway else POPUP_SIZE_PCT
            object.__setattr__(self, "size_pct", default)


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
    if p.cutaway:
        return _preparar_cutaway(p, video_w, video_h, nombre)
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


def _preparar_cutaway(p: Popup, video_w: int, video_h: int, nombre: str) -> dict | None:
    """Cutaway grande: caja centrada de size_pct del cuadro, encaje por fit SIN deformar.

    No se confina a la zona util (por diseno ocupa gran parte o todo el cuadro). fit
    invalido -> 'contain' con log (fail-open, decision documentada). El centrado usa las
    expresiones (W-w)/2 y (H-h)/2: FFmpeg centra en runtime para cualquier aspecto de la
    imagen. size_pct fuera de rango se recorta a (0, 1.0]; <=0 desactiva (fail-open).
    """
    fit = p.fit
    if fit not in CUTAWAY_FIT:
        print(f"[popups] fit '{fit}' desconocido - se usa 'contain'")
        fit = "contain"
    if p.size_pct <= 0.0:
        print(f"[popups] '{nombre}' cutaway con size_pct<=0: popup desactivado")
        return None
    pct = min(p.size_pct, 1.0)
    if p.size_pct > 1.0:
        print(f"[popups] '{nombre}' cutaway size_pct>1.0 - se usa 1.0 (pantalla completa)")
    box_w = int(video_w * pct)
    box_h = int(video_h * pct)
    box_w = max(box_w - box_w % 2, 2)  # par para libx264
    box_h = max(box_h - box_h % 2, 2)
    return {
        "png": p.png,
        "t0": p.t0,
        "t1": p.t1,
        "cutaway": True,
        "box_w": box_w,
        "box_h": box_h,
        "fit": fit,
        "x": "(W-w)/2",  # centrado exacto en runtime, cualquier aspecto
        "y": "(H-h)/2",
        "fade_s": CUTAWAY_FADE_S if p.fade else 0.0,
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


def _filtro_png_cutaway(
    idx: int, box_w: int, box_h: int, fit: str, t0: float, t1: float, fade_s: float, label: str
) -> str:
    """Filtro de un PNG cutaway: encaje contain/cover en una caja box_w x box_h SIN deformar.

    contain: scale ...:decrease -> imagen entera dentro de la caja (sin recorte).
    cover:   scale ...:increase + crop -> llena la caja recortando el excedente.
    Ambos preservan el aspecto original (force_original_aspect_ratio). Fade y reloj propio
    identicos a la capa historica.
    """
    dur = max(t1 - t0, 0.1)
    if fit == "cover":
        encaje = f"scale={box_w}:{box_h}:force_original_aspect_ratio=increase,crop={box_w}:{box_h}"
    else:
        encaje = f"scale={box_w}:{box_h}:force_original_aspect_ratio=decrease"
    fades = ""
    if fade_s > 0:
        out_st = max(dur - fade_s, 0.0)
        fades = (
            f"fade=t=in:st=0:d={fade_s:.3f}:alpha=1,"
            f"fade=t=out:st={out_st:.3f}:d={fade_s:.3f}:alpha=1,"
        )
    return f"[{idx}:v]format=rgba,{encaje},{fades}setpts=PTS-STARTPTS+{t0:.3f}/TB[{label}]"


def _png_filter_for(p: dict, idx: int, label: str) -> str:
    """Filtro de preparacion del PNG segun sea popup normal (ancho) o cutaway (caja+fit)."""
    if p.get("cutaway"):
        return _filtro_png_cutaway(
            idx, p["box_w"], p["box_h"], p["fit"], p["t0"], p["t1"], p["fade_s"], label
        )
    return _filtro_png(idx, p["size"], p["t0"], p["t1"], p["fade_s"], label)


def _filtro_overlay(
    src: str, ovl: str, x: int | str, y: int | str, t0: float, t1: float, dest: str
) -> str:
    """Filtro overlay con ventana temporal (labels sin corchetes)."""
    enable = f"between(t,{t0:.3f},{t1:.3f})"
    return f"[{src}][{ovl}]overlay=x={x}:y={y}:eof_action=pass:enable='{enable}'[{dest}]"


def _tejer_clips(fc: list[str], clips_prep: list[dict], base: str, idx0: int, pref: str) -> str:
    """Compone clips de video sobre `base` (labels {pref}N / v{pref}N). Devuelve el nuevo base.

    El clip se prepara (recorte/loop/cover/fade) y se superpone; el audio del clip NUNCA entra
    (solo se teje el plano de video). Vacio -> no toca `fc` (byte-identico sin clips)."""
    for i, c in enumerate(clips_prep):
        etiqueta, salida = f"{pref}{i}", f"v{pref}{i}"
        fc.append(clip_overlay.filtro_clip(idx0 + i, c, etiqueta))
        fc.append(clip_overlay.overlay_clip(base, etiqueta, c, salida))
        base = salida
    return base


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
    fx_prefilter: str | None = None,
    clips: list[clip_overlay.ClipOverlay] | None = None,
    fps: float = 30.0,
    video_args: list[str] | None = None,
) -> list[str]:
    """Comando FFmpeg completo: FX + ass + emojis (cadena historica) + popups + clips opcionales.

    Sin popups NI fx NI clips el comando es BYTE-IDENTICO al historico (test de contrato lo fija).
    behind_text (popups y clips): se componen ANTES del filtro ass, asi los captions quedan encima.
    Los clips de VIDEO entran como inputs `-i` propios (loop via `-stream_loop`); su AUDIO jamas se
    mapea (solo `0:a`). fx_prefilter (S36-FX): cadena `[0:v]...[vfx]` ANTES del ass; base -> `vfx`.
    """
    prep = [_preparar_popup(p, video_w, video_h, emoji_y_px) for p in (popups or [])]
    activos = [p for p in prep if p]
    behind = [p for p in activos if p["behind"]]
    front = [p for p in activos if not p["behind"]]
    clips_prep = [clip_overlay.preparar_clip(c, video_w, video_h, fps) for c in (clips or [])]
    clips_act = [c for c in clips_prep if c]
    clips_behind = [c for c in clips_act if c["behind"]]
    clips_front = [c for c in clips_act if not c["behind"]]

    cmd: list[str] = ["ffmpeg", "-y", "-i", str(input_video)]
    for png, t0, t1 in emoji_overlays:
        cmd += ["-loop", "1", "-t", f"{max(t1 - t0, 0.1):.3f}", "-i", str(png)]
    for p in behind + front:
        cmd += ["-loop", "1", "-t", f"{max(p['t1'] - p['t0'], 0.1):.3f}", "-i", str(p["png"])]
    for c in clips_behind + clips_front:
        cmd += clip_overlay.input_args_clip(c)  # clip como input propio (audio nunca se mapea)

    fc: list[str] = []
    idx0 = 1 + len(emoji_overlays)  # primer input de popups
    idxc = idx0 + len(behind) + len(front)  # primer input de clips
    base = "0:v"
    if fx_prefilter:
        fc.append(fx_prefilter)  # [0:v] FX [vfx]  — el FX no anade inputs
        base = "vfx"
    for i, p in enumerate(behind):
        fc.append(_png_filter_for(p, idx0 + i, f"pb{i}"))
        fc.append(_filtro_overlay(base, f"pb{i}", p["x"], p["y"], p["t0"], p["t1"], f"vb{i}"))
        base = f"vb{i}"
    base = _tejer_clips(fc, clips_behind, base, idxc, "cb")  # clips behind: captions encima
    fc.append(f"[{base}]ass={ass_esc}[vcap]")
    for i, (_png, t0, t1) in enumerate(emoji_overlays):
        fc.append(_filtro_png(i + 1, emoji_size_px, t0, t1, emoji_fade_s, f"ovs{i}"))
    current = "vcap"
    for i, (_png, t0, t1) in enumerate(emoji_overlays):
        fc.append(_filtro_overlay(current, f"ovs{i}", "(W-w)/2", emoji_y_px, t0, t1, f"vo{i}"))
        current = f"vo{i}"
    for j, p in enumerate(front):
        k = idx0 + len(behind) + j
        fc.append(_png_filter_for(p, k, f"pf{j}"))
        fc.append(_filtro_overlay(current, f"pf{j}", p["x"], p["y"], p["t0"], p["t1"], f"vp{j}"))
        current = f"vp{j}"
    current = _tejer_clips(fc, clips_front, current, idxc + len(clips_behind), "cf")

    cmd += ["-filter_complex", ";".join(fc)]
    cmd += ["-map", f"[{current}]", "-map", "0:a"]  # SOLO 0:a: el audio del clip nunca se mapea
    # video_args=None conserva el encoder CPU historico BYTE-IDENTICO (test de contrato lo fija);
    # produccion inyecta la seleccion NVENC/CPU resuelta. El audio (-c:a copy) nunca cambia.
    encoder_args = (
        video_args
        if video_args is not None
        else ["-c:v", "libx264", "-preset", "medium", "-crf", "18"]
    )
    cmd += [*encoder_args, "-c:a", "copy"]
    cmd.append(str(output_video))
    return cmd
