"""clip_overlay.py - Cutaway de CLIP DE VIDEO como overlay temporal (PR B, video-cutaway).

Tipo explicito `ClipOverlay` (NO se fuerza un video dentro de `core_overlays.Popup`, que es de
imagen) + constructores PUROS del filtro FFmpeg del clip: recorte desde `source_start`, loop
opcional, normalizacion (fps/SAR/pixel format/timestamps), encaje `cover` (escala conservando
aspecto + crop, nunca deforma), fade con alpha y ventana temporal [t0, t1]. Sin I/O de video ni
subprocess: aqui solo se construyen strings; `core_overlays.construir_comando` los teje con el ass
y `core_ass` ejecuta FFmpeg en un solo pase.

Reglas del clip (regla #19, la mas importante): el AUDIO del clip NUNCA se mapea ni se mezcla; el
render mapea solo el audio original (`0:a`). Aqui no se construye ningun filtro de audio. V1: solo
`fit="cover"`, `mute=True`, un unico clip por render.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

FIT_VALIDOS = frozenset({"cover"})  # V1: solo cover (contain DIFERIDO, ver DECISIONES D31)
CLIP_FADE_S = 0.20  # mismo fade largo del cutaway de imagen (elemento grande)
SIZE_PCT_MIN = 0.05
SIZE_PCT_MAX = 1.0


@dataclass(frozen=True)
class ClipOverlay:
    """Un clip de video usado como cutaway temporal. Semantico: sin pixeles todavia.

    `clip` es la ruta local (ya descargada por el fetcher o local). `t0/t1` los decide la ENTRADA,
    no Pexels. `source_start` recorta desde ese punto del clip. `loop=True` repite el clip corto
    hasta cubrir la ventana; `loop=False` no congela el ultimo frame (vuelve al video original).
    `mute=True` SIEMPRE en V1: el audio del clip jamas entra al render.
    """

    clip: Path
    t0: float
    t1: float
    source_start: float = 0.0
    loop: bool = True
    cutaway: bool = True
    fit: str = "cover"
    size_pct: float = 1.0
    behind_text: bool = True
    fade: bool = True
    mute: bool = True


def validar_clip_overlay(
    *,
    t0: float,
    t1: float,
    source_start: float,
    fit: str,
    size_pct: float,
    loop: object,
    mute: object,
) -> None:
    """Valida el CONTRATO de un clip cutaway. Errores de contrato -> ValueError (se propaga; el
    adaptador de JSON manual los captura y omite solo esa entrada, ver DECISIONES D31)."""
    if t0 < 0:
        raise ValueError(f"t0 invalido: {t0!r} (debe ser >= 0)")
    if t1 <= t0:
        raise ValueError(f"ventana invalida: t1 ({t1}) debe ser > t0 ({t0})")
    if source_start < 0:
        raise ValueError(f"source_start invalido: {source_start!r} (debe ser >= 0)")
    if fit not in FIT_VALIDOS:
        raise ValueError(f"fit invalido: {fit!r} (V1 solo admite 'cover')")
    if not (SIZE_PCT_MIN <= size_pct <= SIZE_PCT_MAX):
        raise ValueError(f"size_pct fuera de rango: {size_pct!r} (permitido [{SIZE_PCT_MIN}, 1.0])")
    if not isinstance(loop, bool):
        raise ValueError(f"loop debe ser booleano, no {type(loop).__name__}")
    if not isinstance(mute, bool) or mute is not True:
        raise ValueError("mute=True es obligatorio para b-roll de video Pexels en V1")


def preparar_clip(c: ClipOverlay, video_w: int, video_h: int, fps: float) -> dict | None:
    """ClipOverlay semantico -> pixeles concretos. None = clip desactivado (archivo faltante, rango
    invalido o fit no soportado): se omite con log y el render sigue (fail-open del render)."""
    nombre = Path(c.clip).name
    if not Path(c.clip).exists():
        print(f"[clip] video no encontrado, clip omitido: {c.clip}")
        return None
    if c.t1 <= c.t0:
        print(f"[clip] rango invalido ({c.t0:.2f}-{c.t1:.2f}), clip omitido: {nombre}")
        return None
    if c.fit not in FIT_VALIDOS:
        print(f"[clip] fit '{c.fit}' no soportado (V1 solo cover), clip omitido: {nombre}")
        return None
    pct = min(max(c.size_pct, SIZE_PCT_MIN), SIZE_PCT_MAX)
    box_w = max(int(video_w * pct) - int(video_w * pct) % 2, 2)  # par para libx264
    box_h = max(int(video_h * pct) - int(video_h * pct) % 2, 2)
    return {
        "clip": c.clip,
        "t0": c.t0,
        "t1": c.t1,
        "source_start": max(c.source_start, 0.0),
        "loop": bool(c.loop),
        "window": max(c.t1 - c.t0, 0.1),
        "box_w": box_w,
        "box_h": box_h,
        "fps": fps if fps and fps > 0 else 30.0,
        "fade_s": CLIP_FADE_S if c.fade else 0.0,
        "behind": bool(c.behind_text),
    }


def input_args_clip(prep: dict) -> list[str]:
    """Args de INPUT del clip. loop=True -> `-stream_loop -1` (repite el clip corto hasta cubrir la
    ventana); el `trim` del filtro acota la duracion. loop=False -> input simple (una pasada)."""
    args: list[str] = []
    if prep["loop"]:
        args += ["-stream_loop", "-1"]
    args += ["-i", str(prep["clip"])]
    return args


def filtro_clip(idx: int, prep: dict, label: str) -> str:
    """Cadena del clip: recorte desde source_start + duracion de ventana -> normaliza (rebase de
    timestamps, fps de la base, SAR 1, pixel format) -> cover (escala 'increase' + crop, sin
    deformar) -> fade alpha opcional -> desplaza a t0. El audio del clip NUNCA se toca aqui."""
    w, h = prep["box_w"], prep["box_h"]
    window, ss, fade_s = prep["window"], prep["source_start"], prep["fade_s"]
    cover = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    fades = ""
    if fade_s > 0:
        out_st = max(window - fade_s, 0.0)
        fades = (
            f"fade=t=in:st=0:d={fade_s:.3f}:alpha=1,"
            f"fade=t=out:st={out_st:.3f}:d={fade_s:.3f}:alpha=1,"
        )
    return (
        f"[{idx}:v]trim=start={ss:.3f}:duration={window:.3f},setpts=PTS-STARTPTS,"
        f"fps={prep['fps']:.3f},{cover},setsar=1,format=yuva420p,{fades}"
        f"setpts=PTS-STARTPTS+{prep['t0']:.3f}/TB[{label}]"
    )


def overlay_clip(src: str, ovl: str, prep: dict, dest: str) -> str:
    """Overlay del clip centrado con ventana temporal. `eof_action=pass` + `repeatlast=0`: si el
    clip (loop=False) termina antes de t1, NO congela el ultimo frame -> vuelve al original."""
    enable = f"between(t,{prep['t0']:.3f},{prep['t1']:.3f})"
    return (
        f"[{src}][{ovl}]overlay=x=(W-w)/2:y=(H-h)/2:"
        f"eof_action=pass:repeatlast=0:enable='{enable}'[{dest}]"
    )
