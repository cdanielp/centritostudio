"""render_evidencia.py — A/B del resalte de conectores sobre los MISMOS tramos de S39 (S40).

K juzgó el gate de ancla real sobre dos tramos concretos y midió, sobre esos mismos `.ass`,
que el resalte caía en palabra vacía cerca de la mitad de las veces. Este script rinde
exactamente esos dos tramos otra vez, en dos versiones:

  A_con_resalte   `resaltar_conectores=True` — el render histórico, byte por byte.
  B_sin_resalte   el default nuevo: "que", "un", "de"... llegan a su turno sin resaltarse.

y publica el % de resaltes que caen en conector ANTES y DESPUÉS, medido con `medir_resalte.py`
sobre el `.ass` realmente emitido.

PRIVACIDAD: rutas por CLI, nunca versionadas. El SRT no se copia ni se imprime; los renders
viven en `output/`, que está en `.gitignore`.

Uso:
    venv\\Scripts\\python revision\\s40-sin-resalte-conectores\\render_evidencia.py ^
        --srt input\\<srt>.srt --video output\\<video>.mp4 --words transcripts\\<video>_words.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import core  # noqa: E402
import cve  # noqa: E402
import medir_resalte  # noqa: E402
import media_provenance  # noqa: E402
import srt_caption  # noqa: E402
import srt_offset  # noqa: E402
import srt_render  # noqa: E402
from srt_import import load_srt  # noqa: E402

OUT = ROOT / "output" / "revision-sin-resalte"
DUR_S = 75
MIN_COVERAGE = 0.5
PRESET = "keyword_punch"
DENSIDAD = "alta"  # mismo ajuste que S39: con el default `baja` no hay keywords que ver
# Los DOS tramos exactos que juzgó K en S39 (mismo material, mismo offset propuesto).
TRAMOS = {"tramo2": 313.05, "tramo3": 374.15}


def _recorte(groups: list[dict], t0: float, t1: float) -> list[dict]:
    """Groups CONTENIDOS en [t0, t1) rebasados a t=0. Mismo criterio que S38/S39.

    Un cue que cruza el borde se DESCARTA, no se recorta: rebasarlo daría tiempos negativos
    que pysubs2 acota a 0, fabricando eventos de duración cero que no existen en el material.
    """
    fuera = []
    for g in groups:
        if g["start"] < t0 or g["end"] > t1:
            continue
        ng = json.loads(json.dumps(g))
        ng["start"] = round(g["start"] - t0, 3)
        ng["end"] = round(g["end"] - t0, 3)
        for w in ng["words"]:
            w["start"] = round(w["start"] - t0, 3)
            w["end"] = round(w["end"] - t0, 3)
        fuera.append(ng)
    for i, g in enumerate(fuera):
        g["id"] = i
    return fuera


def _ffmpeg(cmd: list[str], etiqueta: str) -> None:
    r = subprocess.run(cmd, cwd=str(OUT), capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"[X] {etiqueta} fallo\n{r.stderr[-1500:]}")


def _render(rec, etiqueta, video, w, h, style_cfg, t0) -> dict:
    ass = OUT / f"{etiqueta}.ass"
    core.build_ass(rec, w, h, style_cfg, ass)
    _ffmpeg(
        [
            "ffmpeg", "-y", "-ss", f"{t0:.3f}", "-t", str(DUR_S), "-i", str(video),
            "-vf", f"ass={ass.name}", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k", f"{etiqueta}.mp4",
        ],  # fmt: skip
        f"burn {etiqueta}",
    )
    _ffmpeg(
        [
            "ffmpeg", "-y", "-i", f"{etiqueta}.mp4",
            "-vf", f"fps=9/{DUR_S},scale=480:-1,tile=3x3", "-frames:v", "1",
            f"{etiqueta}_contact_sheet.png",
        ],  # fmt: skip
        f"sheet {etiqueta}",
    )
    return medir_resalte.medir(ass)


def main() -> int:
    ap = argparse.ArgumentParser(description="A/B del resalte de conectores (S40)")
    ap.add_argument("--srt", required=True)
    ap.add_argument("--video", required=True)
    ap.add_argument("--words", required=True)
    a = ap.parse_args()

    srt_path, video, words_path = (Path(x).resolve() for x in (a.srt, a.video, a.words))
    for p in (srt_path, video, words_path):
        if not p.is_file():
            print("[X] Falta material: revisa --srt, --video y --words")
            return 1
    OUT.mkdir(parents=True, exist_ok=True)

    words = json.loads(words_path.read_text(encoding="utf-8"))["words"]
    est = srt_offset.estimar_offset(load_srt(srt_path), words)
    if not est.aplicable:
        print("[X] la propuesta de offset no es aplicable; no se renderiza a ciegas")
        return 1
    print(f"[offset] {est.offset_ms} ms (anclas={est.n_anclas}, conf={est.confianza})")

    info = core.get_video_info(video)
    w, h = info["width"], info["height"]
    try:  # D46: timings de otro video desincronizan en silencio
        media_provenance.verificar_transcript_contra_video(
            {"words": words}, video, video_duration_s=info["duration"],
            words_path=words_path, root=ROOT,
        )  # fmt: skip
    except media_provenance.ProcedenciaError as exc:
        print(f"[X] procedencia: {exc}")
        return 1

    groups, result, _payload = srt_caption.preparar_desde_srt(
        srt_path, words, video_duration_ms=int(info["duration"] * 1000),
        words_file=words_path.name, offset_ms=est.offset_ms,
        modo_parcial=True, min_coverage=MIN_COVERAGE,
    )  # fmt: skip
    print(
        f"[align] {result.n_cues} cues | {result.word_aligned} completos | "
        f"{result.word_partial} parciales | {result.cue_fallback} estaticos"
    )

    # El gate de anclas reales (S39, ya en main) se aplica igual en A y en B: la UNICA
    # diferencia entre las dos versiones es `resaltar_conectores`.
    plan = cve.resolve_preset(PRESET, densidad=DENSIDAD)
    marcados, plan, _aviso = srt_render.apply_preset_to_srt_groups(
        groups, plan, brain_path=ROOT / "transcripts" / "no.brain.json", width=w, height=h
    )

    filas = []
    for nombre, t0 in TRAMOS.items():
        rec = _recorte(marcados, t0, t0 + DUR_S)
        for etiqueta, cfg in (
            (f"{nombre}_A_con_resalte", replace(plan.style_cfg, resaltar_conectores=True)),
            (f"{nombre}_B_sin_resalte", plan.style_cfg),
        ):
            r = _render(rec, etiqueta, video, w, h, cfg, t0)
            filas.append(r)
            print(
                f"[{etiqueta}] t0={t0:.2f}s | {len(rec)} cues | {r['resaltes']} resaltes | "
                f"en conector {r['pct_conectores']:.1f}% (ampliada {r['pct_ampliada']:.1f}%)"
            )

    print(f"\n{'archivo':<34} {'resaltes':>8} {'conect.':>8} {'%conector':>10} {'%ampliada':>10}")
    for r in filas:
        print(
            f"{r['archivo']:<34} {r['resaltes']:>8} {r['conectores']:>8} "
            f"{r['pct_conectores']:>9.1f}% {r['pct_ampliada']:>9.1f}%"
        )
    (OUT / "medicion.json").write_text(
        json.dumps({"tramos": TRAMOS, "densidad": DENSIDAD, "filas": filas}, ensure_ascii=False,
                   indent=2),
        encoding="utf-8",
    )  # fmt: skip
    print(f"\n[ok] carpeta: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
