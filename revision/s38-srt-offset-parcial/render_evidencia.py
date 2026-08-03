"""render_evidencia.py — Render real para el gate visual de K (S38, v2).

Genera DOS tramos en `output/revision-srt-parcial-v2/`:

  A. el MISMO tramo que juzgo K (`--t0`, default 1137.75 s), para comparar 1:1 contra el
     render anterior;
  B. un tramo elegido por el script en una zona de cobertura BAJA (bloque 15-25 min), que es
     donde el reparto tiene que sostenerse con pocas anclas.

Cada tramo se audita con `auditar_ass.py` sobre el .ass realmente emitido.

PRIVACIDAD: las rutas se pasan por CLI y NO se escriben aqui — el nombre de un archivo privado
tampoco se versiona. El SRT no se copia, no se versiona y su texto no se imprime. El sidecar
que se deja en `output/` va SIN el campo `text`.

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

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import auditar_ass  # noqa: E402
import core  # noqa: E402
import srt_caption  # noqa: E402
import srt_offset  # noqa: E402
import styles  # noqa: E402
from srt_import import load_srt  # noqa: E402

OUT = ROOT / "output" / "revision-srt-parcial-v2"
DUR_S = 75
MIN_COVERAGE = 0.5
T0_DE_K = 1137.75  # tramo del render que K rechazo: se repite para comparar 1:1
ZONA_BAJA = (900.0, 1500.0)  # bloque 15-25 min


def _recorte(groups: list[dict], t0: float, t1: float) -> list[dict]:
    """Groups CONTENIDOS en [t0, t1) rebasados a t=0. No inventa nada: solo desplaza.

    Un cue que cruza el borde se DESCARTA, no se recorta: rebasarlo daria tiempos negativos
    que pysubs2 acota a 0, y eso fabrica eventos de duracion cero y duplicados que no existen
    en el material (artefacto del recorte, no del reparto).
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


def _tramo_cobertura_baja(groups: list[dict], cues) -> float:
    """Inicio del tramo de menor cobertura dentro de la zona 15-25 min."""
    lo, hi = ZONA_BAJA
    candidatos = [g["start"] for g in groups if lo <= g["start"] <= hi - DUR_S]
    if not candidatos:
        return lo
    cov = {c.cue_index: c.coverage for c in cues}
    por_id = {g["id"]: g for g in groups}
    mejor, mejor_cov = candidatos[0], 2.0
    for t0 in candidatos:
        dentro = [g for g in groups if t0 <= g["start"] < t0 + DUR_S]
        if len(dentro) < 10:
            continue
        m = sum(cov.get(por_id[g["id"]]["id"] + 1, 0.0) for g in dentro) / len(dentro)
        if m < mejor_cov:
            mejor, mejor_cov = t0, m
    return mejor


def _ffmpeg(cmd: list[str], etiqueta: str) -> None:
    r = subprocess.run(cmd, cwd=str(OUT), capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"[X] {etiqueta} fallo\n{r.stderr[-1500:]}")


def _burn(ass: Path, t0: float, destino: Path, video: Path) -> None:
    _ffmpeg(
        [
            "ffmpeg", "-y", "-ss", f"{t0:.3f}", "-t", str(DUR_S), "-i", str(video),
            "-vf", f"ass={ass.name}", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k", destino.name,
        ],  # fmt: skip
        "burn",
    )


def _contact_sheet(mp4: Path, destino: Path) -> None:
    _ffmpeg(
        [
            "ffmpeg", "-y", "-i", mp4.name,
            "-vf", f"fps=9/{DUR_S},scale=480:-1,tile=3x3", "-frames:v", "1", destino.name,
        ],  # fmt: skip
        "contact sheet",
    )


def _tramo(groups, t0, etiqueta, video, w, h) -> bool:
    """Construye ass + mp4 + sheet de un tramo y audita sus invariantes."""
    rec = _recorte(groups, t0, t0 + DUR_S)
    modos: dict = {}
    for g in rec:
        modos[g.get("timing_mode")] = modos.get(g.get("timing_mode"), 0) + 1
    print(f"\n[tramo {etiqueta}] t0={t0:.2f}s | {len(rec)} cues | {modos}")

    ass = OUT / f"{etiqueta}.ass"
    core.build_ass(rec, w, h, styles.get_style("hormozi"), ass)
    mp4 = OUT / f"{etiqueta}.mp4"
    _burn(ass, t0, mp4, video)
    _contact_sheet(mp4, OUT / f"{etiqueta}_contact_sheet.png")
    return auditar_ass.imprimir(auditar_ass.auditar(rec, ass), f"({etiqueta})")


def main() -> int:
    ap = argparse.ArgumentParser(description="Render de evidencia del alineado parcial")
    ap.add_argument("--srt", required=True, help="SRT corregido (no se versiona ni se imprime)")
    ap.add_argument("--video", required=True, help="video fuente")
    ap.add_argument("--words", required=True, help="{stem}_words.json del transcript")
    ap.add_argument("--t0", type=float, default=T0_DE_K, help="tramo A (el que juzgo K)")
    a = ap.parse_args()
    # Absolutas: ffmpeg corre con cwd=OUT para que el filtro `ass=` reciba un basename (el
    # escape de rutas Windows en ese filtro es traicionero, gotcha conocido).
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

    ok_a = _tramo(groups, a.t0, "A_mismo_tramo_que_K", video, w, h)
    t0b = _tramo_cobertura_baja(groups, result.cues)
    ok_b = _tramo(groups, t0b, "B_cobertura_baja", video, w, h)

    limpio = json.loads(json.dumps(payload))
    for c in limpio.get("cues", []):
        c.pop("text", None)
    limpio["_nota_auditoria"] = "campo text removido (SRT fuente privado)"
    limpio["_tramos"] = {"A": a.t0, "B": t0b, "dur_s": DUR_S}
    srt_caption.escribir_sidecar(limpio, OUT / "alignment_sin_texto.json")

    print(f"\n[ok] carpeta: {OUT}")
    return 0 if (ok_a and ok_b) else 1


if __name__ == "__main__":
    raise SystemExit(main())
