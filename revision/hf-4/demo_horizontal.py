"""Demo HORIZONTAL 16:9 con el carril nuevo (Paso 1 de HF-4): captions + b-roll de Pexels +
letreros, SIN reencuadrar.

No hay orquestador de produccion para "horizontal + Pexels + letreros" en un solo paso: el
Modo Automatico (v1 y v2) SIEMPRE reencuadra a 9:16 (`auto.py`/`auto_v2.py`, `reframe_clip`
incondicional) y el render manual del Studio (`jobs_render.py`) no tiene Pexels, solo el
sistema de popups CVE mas antiguo. Este script llama a los MISMOS motores reales que usa
`auto_v2.procesar_clip_v2` (planner de b-roll + `auto_broll.resolver_plan` con los fetchers
reales de Pexels, y `motion_capa.clips_de_motion`) pero sobre el clip horizontal TAL CUAL,
sin el paso de reencuadre: es exactamente la combinacion que el Paso 1 arreglo (sin dato de
cara, el letrero sube a la banda superior en vez de caer en el carril nativo del 9:16).

Uso, desde la raiz del repo (necesita PEXELS_API_KEY y npx/Chrome headless):

    venv\\Scripts\\python revision\\hf-4\\demo_horizontal.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

CLIP = RAIZ / "output" / "clips" / "mariosoto_clip2_corto.mp4"  # 1920x1080, 20.5s
STEM = CLIP.stem
SALIDA_DIR = Path(__file__).resolve().parent / "evidencia_horizontal"
TIMEOUT_S = 300


def main() -> None:
    import os

    from dotenv import load_dotenv

    load_dotenv()
    if not os.environ.get("PEXELS_API_KEY"):
        print("falta PEXELS_API_KEY en el entorno; el b-roll no se podria resolver")
        return

    import auto_broll
    import core
    import motion_capa as mc
    from auto import _brain_fail_open
    from auto_report import STYLE_AUTO
    from broll_plan_types import BrollConfig
    from broll_planner import plan_broll
    from styles import get_style

    if not CLIP.is_file():
        print(f"no existe el clip de prueba: {CLIP.name}")
        return
    groups_path = RAIZ / "transcripts" / f"{STEM}_groups.json"
    if not groups_path.is_file():
        print(f"no hay transcript para {STEM}")
        return
    groups = json.loads(groups_path.read_text(encoding="utf-8"))

    info = core.get_video_info(CLIP)
    w, h, dur = info["width"], info["height"], float(info["duration"])
    orientacion = mc.orientacion_de(w, h)
    print(f"clip: {CLIP.name}  {w}x{h}  orientacion: {orientacion}  dur: {dur:.1f}s")

    SALIDA_DIR.mkdir(parents=True, exist_ok=True)

    # brain: MISMO analisis IA fail-open que usa auto_v2 (S37-A necesita sus keywords para
    # abrir ventanas de b-roll; sin esto el planner no tiene de donde sacar que buscar).
    brain_data = _brain_fail_open(groups, STEM) or {}

    # b-roll: MISMO planner y MISMOS fetchers reales que auto_v2 (Pexels de verdad).
    plan = plan_broll(groups, brain_data, dur, BrollConfig())
    resol = auto_broll.resolver_plan(plan, [], [], w, h, broll_enabled=True)
    final_popups = sorted(resol.auto_popups, key=lambda p: p.t0)
    final_clips_broll = sorted(resol.auto_clips, key=lambda c: c.t0)
    print(f"b-roll resuelto: {len(final_popups)} imagen(es), {len(final_clips_broll)} video(s)")

    # letreros: MISMA capa que auto_v2, sin trayectoria (un horizontal no pasa por el reframe,
    # que es justo el escenario que el Paso 1 de HF-4 corrige).
    opciones = mc.OpcionesMotion(
        enabled=True,
        titulo="El carril nuevo del letrero horizontal, sin pisar el carril del 9:16",
        nombre="Carlos Daniel Penagos",
        rol="Prompt Models Studio",
        cta="Sigue para más",
        textos_llm=False,
        estilo="pms",
    )
    motion = mc.clips_de_motion(
        opciones=opciones,
        ancho=w,
        alto=h,
        fps=info.get("fps") or 30.0,
        duracion_s=dur,
        raiz_cache=SALIDA_DIR / ".piezas",
        root=RAIZ,
        tramos=mc.tramos_de_groups(groups),
        tray_csv=None,  # horizontal: nunca hay trayectoria de reframe
        clip_mp4=CLIP,
    )
    print(f"letreros: {json.dumps(motion.informe, ensure_ascii=False, default=str)}")

    final_clips = [*final_clips_broll, *motion.clips]
    style_cfg = get_style(STYLE_AUTO)
    ass_path = RAIZ / "output" / f"{STEM}_hf4demo_{STYLE_AUTO}.ass"
    salida = SALIDA_DIR / f"{STEM}_16x9_{STYLE_AUTO}.mp4"
    core.build_ass(groups, w, h, style_cfg, ass_path)
    core.burn_video_with_emojis(
        CLIP, ass_path, salida, [], style_cfg, popups=final_popups, clips=final_clips
    )

    resumen = {
        "clip": CLIP.name,
        "tamano": [w, h],
        "orientacion": orientacion,
        "broll_imagenes": [{"t0": p.t0, "t1": p.t1} for p in final_popups],
        "broll_videos": [{"t0": c.t0, "t1": c.t1} for c in final_clips_broll],
        "letreros": [
            {"plantilla": p["plantilla"], "t0_ms": p["t0_ms"], "t1_ms": p["t1_ms"], "banda": p["banda"]}
            for p in (motion.informe.get("plan") or {}).get("piezas", [])
        ],
        "salida": str(salida.relative_to(RAIZ)),
    }
    (SALIDA_DIR / "resumen.json").write_text(
        json.dumps(resumen, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(resumen, indent=2, ensure_ascii=False))
    print(f"\n-> {salida.relative_to(RAIZ)}" if salida.is_file() else "\nNO se genero el MP4 final")


if __name__ == "__main__":
    main()
