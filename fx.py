"""fx.py — Capa local OPCIONAL de efectos visuales sobre FFmpeg (S36-FX).

Capa PURA: construye un plan de efectos y los strings de filtros FFmpeg que van
ANTES del quemado ASS (para no deformar los captions). No transcribe, no llama al
LLM, no toca captions ni brain. core_ass la invoca; core_overlays ensambla el comando.

Efectos: punch-in (zoom con easing), flash blanco, scanner rojo y logo/outro (PNG).
Todo apagado por default: con fx_preset=None el render historico sigue byte-identico.

Presets:
  express -> punch-in ligero + logo (watermark).
  pro     -> punch-in + flash + scanner.
  premium -> pro + outro (logo al final).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import core_overlays  # Popup: el logo/outro se materializa con la capa de overlays ya testeada

# ─────────────────────────────────────────────────────────────────────────────
# Limites visuales (reglas S36-FX; no saturar)
# ─────────────────────────────────────────────────────────────────────────────

PUNCH_MIN_GAP_S = 4.0  # separacion minima entre punch-ins
PUNCH_FALLBACK_GAP_S = 5.5  # cadencia sin brain (rango 4-7s)
PUNCH_DUR_S = 0.9  # duracion (rango 0.6-1.2)
PUNCH_DUR_LIGERO_S = 0.7  # express: mas corto
PUNCH_ZOOM = 1.10  # zoom (rango 1.08-1.12)
PUNCH_ZOOM_LIGERO = 1.08  # express: mas sutil

FLASH_DUR_S = 0.14  # rango 0.10-0.18
FLASH_ALPHA = 0.50  # default aprobado por K (S36-FX-B): flash soft (guia advisory 0.55-0.85)
FLASH_MIN_GAP_S = 3.0

SCANNER_DUR_S = 0.6  # rango 0.5-0.8
SCANNER_FALLBACK_GAP_S = 11.0  # cadencia sin datos (rango 8-15s)
SCANNER_MIN_GAP_S = 8.0
SCANNER_ALPHA = 0.7
SCANNER_STEPS = 8  # el barrido se hace con N barras estaticas encadenadas (drawbox no anima y)

SEG_GAP_S = 2.0  # gap entre kw_ts que sugiere frontera de segmento (para flash)
OUTRO_S = 2.5  # duracion del outro (logo al final, premium)

# preset -> que efectos lleva. logo: None | "watermark" | "outro".
PRESETS: dict[str, dict] = {
    "express": {
        "punch": True,
        "flash": False,
        "scanner": False,
        "logo": "watermark",
        "zoom": PUNCH_ZOOM_LIGERO,
        "dur": PUNCH_DUR_LIGERO_S,
    },
    "pro": {
        "punch": True,
        "flash": True,
        "scanner": True,
        "logo": None,
        "zoom": PUNCH_ZOOM,
        "dur": PUNCH_DUR_S,
    },
    "premium": {
        "punch": True,
        "flash": True,
        "scanner": True,
        "logo": "outro",
        "zoom": PUNCH_ZOOM,
        "dur": PUNCH_DUR_S,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Dataclasses del plan
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PunchIn:
    t0: float
    t1: float
    zoom: float


@dataclass(frozen=True)
class Flash:
    t0: float
    dur: float
    alpha: float


@dataclass(frozen=True)
class Scanner:
    t0: float
    t1: float


@dataclass(frozen=True)
class LogoOutro:
    start: float
    end: float
    png: str
    width: float = 0.20  # fraccion del ancho del video
    y_margin: float = 0.04
    pos: str = "top_right"


@dataclass(frozen=True)
class FXPlan:
    punch_ins: list[PunchIn] = field(default_factory=list)
    flashes: list[Flash] = field(default_factory=list)
    scanners: list[Scanner] = field(default_factory=list)
    logo: LogoOutro | None = None
    preset: str | None = None

    def vacio(self) -> bool:
        return not (self.punch_ins or self.flashes or self.scanners or self.logo)


# ─────────────────────────────────────────────────────────────────────────────
# Carga de datos (brain.json) — fail-open
# ─────────────────────────────────────────────────────────────────────────────


def _espaciar(tiempos: list[float], gap: float) -> list[float]:
    """Selecciona timestamps respetando una separacion minima (greedy)."""
    elegidos: list[float] = []
    for t in sorted(tiempos):
        if not elegidos or t - elegidos[-1] >= gap:
            elegidos.append(t)
    return elegidos


def _bounds_por_gap(kw_ts: list[float], gap: float) -> list[float]:
    """Fronteras de segmento: un salto grande entre keywords sugiere nuevo segmento."""
    return [kw_ts[i] for i in range(1, len(kw_ts)) if kw_ts[i] - kw_ts[i - 1] >= gap]


def cargar_brain_fx(path: str | Path) -> dict | None:
    """Extrae del brain.json las senales que alimentan el plan FX.

    Devuelve {"kw_ts", "segment_bounds", "emphasis_ts"} o None si no hay brain util.
    Fail-open: ausente, JSON roto o sin kw_ts -> None (se usara el fallback por intervalos).
    """
    p = Path(path)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    groups = data.get("groups") or []
    kw_ts = sorted({round(float(g["kw_ts"]), 3) for g in groups if g.get("kw_ts") is not None})
    if not kw_ts:
        return None
    return {
        "kw_ts": kw_ts,
        "segment_bounds": _bounds_por_gap(kw_ts, SEG_GAP_S),
        "emphasis_ts": _espaciar(kw_ts, SCANNER_MIN_GAP_S),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Generacion del plan
# ─────────────────────────────────────────────────────────────────────────────


def _punch(tiempos: list[float], duration: float, cfg: dict) -> list[PunchIn]:
    dur, zoom = cfg["dur"], cfg["zoom"]
    fuera: list[PunchIn] = []
    for t in _espaciar(tiempos, PUNCH_MIN_GAP_S):
        t0 = max(0.0, t)
        t1 = min(t0 + dur, duration)
        if t1 - t0 >= 0.3:
            fuera.append(PunchIn(round(t0, 3), round(t1, 3), zoom))
    return fuera


def _flash(bounds: list[float], duration: float) -> list[Flash]:
    fuera: list[Flash] = []
    for t in _espaciar(bounds, FLASH_MIN_GAP_S):
        if 0.2 <= t <= duration - FLASH_DUR_S:
            fuera.append(Flash(round(t, 3), FLASH_DUR_S, FLASH_ALPHA))
    return fuera


def _scanner(tiempos: list[float], duration: float) -> list[Scanner]:
    fuera: list[Scanner] = []
    for t in _espaciar(tiempos, SCANNER_MIN_GAP_S):
        t1 = min(t + SCANNER_DUR_S, duration)
        if t1 - t >= 0.3:
            fuera.append(Scanner(round(t, 3), round(t1, 3)))
    return fuera


def _logo_del_preset(cfg: dict, duration: float, logo_png: str | Path | None) -> LogoOutro | None:
    kind = cfg["logo"]
    if not kind or not logo_png:
        return None
    png = str(logo_png)
    if kind == "outro":
        return LogoOutro(max(0.0, duration - OUTRO_S), duration, png, width=0.42, pos="center")
    return LogoOutro(0.5, duration, png, width=0.20, y_margin=0.04, pos="top_right")


def generar_plan_fx_fallback(
    duration: float, preset: str | None, logo_png: str | Path | None = None
) -> FXPlan:
    """Plan por intervalos regulares cuando no hay brain. Pocos efectos, dentro de limites.

    Sin datos NO hay flash (no hay fronteras de segmento -> no saturar).
    """
    cfg = PRESETS.get(preset or "")
    if cfg is None or duration <= 0:
        return FXPlan(preset=preset)
    punch = (
        _punch(_intervalos(duration, PUNCH_FALLBACK_GAP_S), duration, cfg) if cfg["punch"] else []
    )
    scan = (
        _scanner(_intervalos(duration, SCANNER_FALLBACK_GAP_S), duration) if cfg["scanner"] else []
    )
    return FXPlan(punch, [], scan, _logo_del_preset(cfg, duration, logo_png), preset)


def _intervalos(duration: float, gap: float) -> list[float]:
    """Timestamps cada `gap` segundos, empezando en gap (no en 0)."""
    t, out = gap, []
    while t < duration - 0.3:
        out.append(round(t, 3))
        t += gap
    return out


def generar_plan_fx(
    duration: float,
    preset: str | None,
    brain_data: dict | None = None,
    logo_png: str | Path | None = None,
) -> FXPlan:
    """Construye el FXPlan. Con brain: punch desde kw_ts, flash en fronteras, scanner en enfasis.
    Sin brain: delega en el fallback por intervalos. Preset desconocido -> plan vacio.
    """
    cfg = PRESETS.get(preset or "")
    if cfg is None or duration <= 0:
        return FXPlan(preset=preset)
    if not (brain_data and brain_data.get("kw_ts")):
        return generar_plan_fx_fallback(duration, preset, logo_png)
    punch = _punch(brain_data["kw_ts"], duration, cfg) if cfg["punch"] else []
    flash = _flash(brain_data.get("segment_bounds") or [], duration) if cfg["flash"] else []
    scan = _scanner(brain_data.get("emphasis_ts") or [], duration) if cfg["scanner"] else []
    return FXPlan(punch, flash, scan, _logo_del_preset(cfg, duration, logo_png), preset)


# ─────────────────────────────────────────────────────────────────────────────
# Construccion de filtros FFmpeg (strings puros)
# ─────────────────────────────────────────────────────────────────────────────


def _z_expr(punch_ins: list[PunchIn]) -> str:
    """Zoom Z(it) para zoompan: 1.0 en reposo; pulso sin() (easing, no lineal) por ventana.

    `it` = in_time de zoompan (tiempo del frame de entrada, en segundos).
    """
    expr = "1"
    for p in reversed(punch_ins):
        dur = max(p.t1 - p.t0, 0.001)
        ease = f"sin(PI*(it-{p.t0:.3f})/{dur:.3f})"  # 0 -> 1 -> 0 (sube y baja suave)
        val = f"1+{p.zoom - 1:.4f}*{ease}"
        expr = f"if(between(it,{p.t0:.3f},{p.t1:.3f}),{val},{expr})"
    return expr


def _flash_filtro(fl: Flash) -> str:
    """drawbox blanco a pantalla completa, visible solo en la ventana temporal del flash."""
    t1 = fl.t0 + fl.dur
    return (
        f"drawbox=x=0:y=0:w=iw:h=ih:color=white@{fl.alpha:.2f}:t=fill:"
        f"enable='between(t,{fl.t0:.3f},{t1:.3f})'"
    )


def _scanner_filtro(sc: Scanner, video_h: int, bar: int) -> list[str]:
    """Barra roja que barre de arriba a abajo: N barras estaticas encadenadas en el tiempo.

    drawbox NO evalua `y` por frame (no tiene eval=frame en FFmpeg 8.0), asi que el
    barrido se compone con SCANNER_STEPS barras estaticas, cada una en su sub-ventana.
    """
    dur = max(sc.t1 - sc.t0, 0.001)
    paso = dur / SCANNER_STEPS
    filtros: list[str] = []
    for k in range(SCANNER_STEPS):
        st = sc.t0 + k * paso
        en = sc.t0 + (k + 1) * paso
        y = int(round((video_h - bar) * k / max(SCANNER_STEPS - 1, 1)))
        filtros.append(
            f"drawbox=x=0:y={y}:w=iw:h={bar}:color=red@{SCANNER_ALPHA:.2f}:t=fill:"
            f"enable='between(t,{st:.3f},{en:.3f})'"
        )
    return filtros


def construir_filtro_video_fx(
    base_label: str,
    plan: FXPlan,
    video_w: int,
    video_h: int,
    fps: float = 30.0,
    out_label: str = "vfx",
) -> tuple[str, str]:
    """Cadena de filtros de video (punch/flash/scanner) que consume [base] y produce [out].

    Va ANTES del filtro ass (los captions se queman despues -> no se deforman). El logo
    NO va aqui: es un overlay PNG (ver logo_a_popup). Sin efectos: devuelve ("", base_label).

    Punch-in via zoompan (zoom animado por frame): `fps` DEBE ser el de la fuente para no
    desincronizar el audio (zoompan re-temporiza). d=1 = un frame de salida por frame de
    entrada; el zoom se centra con x/y.
    """
    filtros: list[str] = []
    if plan.punch_ins:
        z = _z_expr(plan.punch_ins)
        filtros.append(
            f"zoompan=z='{z}':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"s={video_w}x{video_h}:fps={fps:.4f}"
        )
    filtros += [_flash_filtro(fl) for fl in plan.flashes]
    if plan.scanners:
        bar = max(4, (video_h // 90) & ~1)  # alto de la barra, par (visible sin saturar)
        for sc in plan.scanners:
            filtros += _scanner_filtro(sc, video_h, bar)
    if not filtros:
        return "", base_label
    return f"[{base_label}]" + ",".join(filtros) + f"[{out_label}]", out_label


def logo_a_popup(plan: FXPlan) -> core_overlays.Popup | None:
    """Convierte el logo/outro del plan en un Popup (overlay PNG real, encima del ass)."""
    lg = plan.logo
    if lg is None:
        return None
    return core_overlays.Popup(
        png=Path(lg.png),
        t0=lg.start,
        t1=lg.end,
        pos=lg.pos,
        size_pct=lg.width,
        behind_text=False,
        fade=True,
    )
