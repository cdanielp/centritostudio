"""render_evidencia.py — Render real de 75 s para el gate visual de K (S38, tarea 3.5).

Lo que K tiene que juzgar: un cue PARCIALMENTE animado (unas palabras con timing real, el
resto interpolado en el hueco) se ve bien o se ve roto.

PRIVACIDAD: las rutas se pasan por CLI y NO se escriben aqui — el nombre de un archivo privado
tampoco se versiona. El SRT no se copia, no se versiona y su texto no se imprime. El .ass y el
MP4 quedan en `output/revision-srt-parcial/` (gitignored). El sidecar va SIN el campo `text`.

Uso:
    venv\\Scripts\\python revision\\s38-srt-offset-parcial\\render_evidencia.py ^
        --srt input\\<tu_srt>.srt --video input\\<tu_video>.mp4 ^
        --words transcripts\\<tu_video>_words.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import core  # noqa: E402
import srt_caption  # noqa: E402
import srt_offset  # noqa: E402
import styles  # noqa: E402
from srt_import import load_srt  # noqa: E402

OUT = ROOT / "output" / "revision-srt-parcial"

# Tramo elegido por densidad de cues parciales (se calcula abajo, no se fija a mano).
DUR_S = 75
MIN_COVERAGE = 0.5


def _recorte(groups: list[dict], t0: float, t1: float) -> list[dict]:
    """Groups del tramo [t0, t1) rebasados a t=0. No inventa nada: solo desplaza."""
    fuera = []
    for g in groups:
        if g["end"] <= t0 or g["start"] >= t1:
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


def _mejor_tramo(groups: list[dict], dur: float) -> float:
    """Inicio del tramo con MAS cues parciales: es lo que K tiene que poder juzgar."""
    parciales = [g["start"] for g in groups if g.get("timing_mode") == "word_partial"]
    if not parciales:
        return 0.0
    mejor, mejor_n = 0.0, -1
    for t0 in parciales:
        n = sum(1 for s in parciales if t0 <= s < t0 + dur)
        if n > mejor_n:
            mejor, mejor_n = t0, n
    return max(0.0, mejor - 1.0)


def _burn(ass: Path, t0: float, destino: Path, video: Path) -> None:
    cmd = [
        "ffmpeg", "-y", "-ss", f"{t0:.3f}", "-t", str(DUR_S), "-i", str(video),
        "-vf", f"ass={ass.name}", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k", destino.name,
    ]  # fmt: skip
    r = subprocess.run(cmd, cwd=str(OUT), capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"[X] ffmpeg fallo\n{r.stderr[-1500:]}")


def _contact_sheet(mp4: Path, destino: Path) -> None:
    """3x3 de frames repartidos: se ve la evolucion de la animacion de un vistazo."""
    cmd = [
        "ffmpeg", "-y", "-i", mp4.name,
        "-vf", f"fps=9/{DUR_S},scale=480:-1,tile=3x3", "-frames:v", "1", destino.name,
    ]  # fmt: skip
    r = subprocess.run(cmd, cwd=str(OUT), capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"[X] contact sheet fallo\n{r.stderr[-1500:]}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Render de evidencia del alineado parcial")
    ap.add_argument("--srt", required=True, help="SRT corregido (no se versiona ni se imprime)")
    ap.add_argument("--video", required=True, help="video fuente")
    ap.add_argument("--words", required=True, help="{stem}_words.json del transcript")
    ap.add_argument("--stem", default="evidencia", help="prefijo de los archivos de salida")
    a = ap.parse_args()
    # Absolutas: `_burn`/`_contact_sheet` corren con cwd=OUT para que el filtro `ass=` reciba
    # un basename (el escape de rutas Windows en ese filtro es traicionero, gotcha conocido).
    srt_path, video, words_path = (Path(x).resolve() for x in (a.srt, a.video, a.words))
    for p in (srt_path, video, words_path):
        if not p.is_file():
            print("[X] Falta material: revisa --srt, --video y --words")
            return 1
    OUT.mkdir(parents=True, exist_ok=True)
    words = json.loads(words_path.read_text(encoding="utf-8"))["words"]

    est = srt_offset.estimar_offset(load_srt(srt_path), words)
    print(f"[offset] propuesta={est.offset_ms} ms anclas={est.n_anclas} conf={est.confianza}")
    if not est.aplicable:
        print("[X] la propuesta no es aplicable; no se renderiza a ciegas")
        return 1

    info = core.get_video_info(video)
    w, h = info["width"], info["height"]
    groups, result, payload = srt_caption.preparar_desde_srt(
        srt_path,
        words,
        video_duration_ms=int(info["duration"] * 1000),
        words_file=words_path.name,
        offset_ms=est.offset_ms,
        modo_parcial=True,
        min_coverage=MIN_COVERAGE,
    )
    print(
        f"[align] {result.n_cues} cues | {result.word_aligned} animados | "
        f"{result.word_partial} parciales | {result.cue_fallback} estaticos"
    )

    t0 = _mejor_tramo(groups, DUR_S)
    tramo = _recorte(groups, t0, t0 + DUR_S)
    modos = {}
    for g in tramo:
        modos[g.get("timing_mode")] = modos.get(g.get("timing_mode"), 0) + 1
    print(f"[tramo] t0={t0:.1f}s dur={DUR_S}s | {len(tramo)} cues | {modos}")

    ass = OUT / f"{a.stem}_srt_parcial.ass"
    core.build_ass(tramo, w, h, styles.get_style("hormozi"), ass)
    mp4 = OUT / f"{a.stem}_srt_parcial.mp4"
    _burn(ass, t0, mp4, video)
    sheet = OUT / "contact_sheet.png"
    _contact_sheet(mp4, sheet)

    limpio = json.loads(json.dumps(payload))
    for c in limpio.get("cues", []):
        c.pop("text", None)
    limpio["_nota_auditoria"] = "campo text removido (SRT fuente privado)"
    limpio["_tramo_render"] = {"t0_s": t0, "dur_s": DUR_S, "modos": modos}
    srt_caption.escribir_sidecar(limpio, OUT / "alignment_sin_texto.json")

    print(f"\n[ok] video  : {mp4}")
    print(f"[ok] sheet  : {sheet}")
    print(f"[ok] sidecar: {OUT / 'alignment_sin_texto.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
