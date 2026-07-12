"""render_ab.py — A/B visual de intensidades FX (S36-FX-B). EVIDENCIA, no shipped.

NO cambia defaults ni fx.py: construye las 3 variantes desde el MISMO plan base
(mismos timings) variando solo intensidad, y renderiza con el builder real
`core_overlays.construir_comando`. Los efectos de intensidad son por-instancia
(zoom del PunchIn, alpha del Flash) o via los helpers de fx (scanner: alpha/pasos/grosor).

Uso: venv\\Scripts\\python revision\\s36-fx-ab\\render_ab.py
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import core
import core_ass
import core_overlays
import fx
from assets_comfy import EMOJI_FADE_S, EMOJI_SIZE_PCT
from styles import get_style

VIDEO = Path("output/clips/mariosoto_clip1_corto_9x16.mp4")
BRAIN = Path("transcripts/mariosoto_clip1_corto_9x16.brain.json")
WORDS = Path("transcripts/mariosoto_clip1_corto_9x16_words.json")
OUT = Path("revision/s36-fx-ab")
LOGO = Path("assets/marca/logo.png")

# Mismo plan (timings), solo cambia intensidad. bar = alto de la barra del scanner.
VARIANTS = {
    "1_soft": dict(zoom=1.07, flash=0.50, bar_div=150, scan_alpha=0.48, steps=12),
    "2_current": dict(zoom=1.10, flash=0.70, bar_div=90, scan_alpha=0.70, steps=8),
    "3_strong": dict(zoom=1.12, flash=0.83, bar_div=55, scan_alpha=0.85, steps=6),
}


def _prefilter(plan: fx.FXPlan, w: int, h: int, fps: float, v: dict) -> str:
    """Cadena [0:v]...[vfx] con la intensidad de la variante (usa helpers reales de fx)."""
    fx.SCANNER_ALPHA = v["scan_alpha"]  # helpers leen estos globals (throwaway)
    fx.SCANNER_STEPS = v["steps"]
    bar = max(4, (h // v["bar_div"]) & ~1)
    filtros: list[str] = []
    if plan.punch_ins:
        z = fx._z_expr(plan.punch_ins)
        filtros.append(
            f"zoompan=z='{z}':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"s={w}x{h}:fps={fps:.4f}"
        )
    filtros += [fx._flash_filtro(fl) for fl in plan.flashes]
    for sc in plan.scanners:
        filtros += fx._scanner_filtro(sc, h, bar)
    return f"[0:v]{','.join(filtros)}[vfx]"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    info = core.get_video_info(VIDEO)
    w, h, fps, dur = info["width"], info["height"], info["fps"], info["duration"]
    print(f"[ab] {VIDEO.name} {w}x{h} {fps:.3f}fps {dur:.2f}s")

    # Captions compartidos (hormozi, mismos para las 3 variantes)
    import json  # noqa: PLC0415

    raw = json.loads(WORDS.read_text(encoding="utf-8"))
    groups = core.group_words(raw["words"])
    style_cfg = get_style("hormozi", None, None)
    ass_path = OUT / "ab.ass"
    core.build_ass(groups, w, h, style_cfg, ass_path)
    ass_esc = core_ass._ffmpeg_ass_path(ass_path)

    size_px = max(int(w * EMOJI_SIZE_PCT), 2)
    size_px -= size_px % 2
    y_px = core_ass._emoji_y_sobre_captions(w, h, size_px, style_cfg)

    brain_data = fx.cargar_brain_fx(BRAIN)
    base = fx.generar_plan_fx(dur, "premium", brain_data, LOGO if LOGO.exists() else None)
    print(
        f"[ab] plan base: {len(base.punch_ins)} punch, {len(base.flashes)} flash, "
        f"{len(base.scanners)} scanner, logo={'si' if base.logo else 'no'}"
    )

    for name, v in VARIANTS.items():
        plan = fx.FXPlan(
            punch_ins=[fx.PunchIn(p.t0, p.t1, v["zoom"]) for p in base.punch_ins],
            flashes=[fx.Flash(fl.t0, fl.dur, v["flash"]) for fl in base.flashes],
            scanners=list(base.scanners),  # MISMAS ventanas: solo cambia intensidad
            logo=base.logo,
            preset=base.preset,
        )
        prefilter = _prefilter(plan, w, h, fps, v)
        popups = [p for p in [fx.logo_a_popup(plan)] if p]
        out_mp4 = OUT / f"ab_{name}.mp4"
        cmd = core_overlays.construir_comando(
            VIDEO, ass_esc, out_mp4, [], size_px, y_px, EMOJI_FADE_S, w, h, popups, prefilter
        )
        t0 = time.time()
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"FFmpeg error ({name}):\n{r.stderr[-1200:]}")
        print(f"[ab] {out_mp4.name} en {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
