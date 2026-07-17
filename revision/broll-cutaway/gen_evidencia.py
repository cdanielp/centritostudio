"""Genera evidencia visual del b-roll cutaway usando el codigo real (construir_comando).

Reproducible: crea extractos cortos + un PNG de b-roll ancho (aspecto distinto al cuadro),
quema un CAPTION real de dos lineas con el pipeline existente (core_ass.build_ass + estilo
hormozi) y renderiza cutaway en vertical (cover full-frame, contain 0.85) y horizontal
(cover full-frame). El cutaway va behind_text=True -> el overlay se compone ANTES del ass,
asi el caption queda ENCIMA. Extrae un frame durante la ventana activa del cutaway.
Sin red ni assets externos. Solo ASCII en print().
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import core  # noqa: E402
import core_ass  # noqa: E402
import core_overlays as co  # noqa: E402
import styles  # noqa: E402

OUT = Path(__file__).resolve().parent
CLIP_V = ROOT / "output" / "clips" / "mariosoto_clip1_corto_9x16.mp4"

# Caption de prueba: dos lineas visibles durante la ventana del cutaway (0.3-2.7s).
CAPTION_LINEAS = ["B-ROLL DE PRUEBA", "LOS CAPTIONS DEBEN QUEDAR ENCIMA"]


def run(cmd: list[str], cwd: str | None = None) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if r.returncode != 0:
        raise SystemExit(f"[X] fallo: {' '.join(cmd[:4])}...\n{r.stderr[-600:]}")


def caption_ass(dst: Path, w: int, h: int) -> None:
    """Quema un .ass real de 2 lineas con el pipeline existente (estilo hormozi)."""
    words = []
    t = 0.4
    for li, linea in enumerate(CAPTION_LINEAS):
        for tok in linea.split():
            words.append(
                {"text": tok, "start": round(t, 3), "end": round(t + 0.22, 3), "line_idx": li}
            )
            t += 0.22
    grupo = {"id": 0, "start": 0.4, "end": 2.6, "text": " ".join(CAPTION_LINEAS), "words": words}
    core_ass.build_ass([grupo], w, h, styles.get_style("hormozi"), dst)


def extracto(src: Path, dst: Path, w: int, h: int, dur: int = 3) -> None:
    run([
        "ffmpeg", "-y", "-i", str(src), "-t", str(dur),
        "-vf", f"scale={w}:{h}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", str(dst),
    ])


def broll_png(dst: Path, w: int, h: int) -> None:
    # testsrc ancho: aspecto muy distinto al cuadro para distinguir contain (letterbox)
    # de cover (recorte). Se guarda como PNG con alpha para la capa de overlays.
    run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=size={w}x{h}:duration=1",
        "-frames:v", "1", "-pix_fmt", "rgba", str(dst),
    ])


def render_cutaway(src: Path, png: Path, dst: Path, w: int, h: int, fit: str, pct: float) -> None:
    ass = OUT / "_caption.ass"
    caption_ass(ass, w, h)  # caption real (no vacio) para validar overlay-detras-de-ass
    p = co.Popup(png=png, t0=0.3, t1=2.7, cutaway=True, size_pct=pct, fit=fit, behind_text=True)
    cmd = co.construir_comando(
        src, core_ass._ffmpeg_ass_path(ass), dst, [], 216, int(h * 0.6), 0.12, w, h, [p]
    )
    run(cmd, cwd=str(ROOT))
    info = core.get_video_info(dst)
    print(f"[ok] {dst.name}: {info['width']}x{info['height']} dur={info['duration']:.2f}s")


def frame(src: Path, dst: Path, at: float = 1.5) -> None:
    run(["ffmpeg", "-y", "-ss", str(at), "-i", str(src), "-frames:v", "1", str(dst)])


def main() -> None:
    if not CLIP_V.exists():
        raise SystemExit(f"[X] falta {CLIP_V}")
    src_v = OUT / "_src_vertical.mp4"
    src_h = OUT / "_src_horizontal.mp4"
    extracto(CLIP_V, src_v, 1080, 1920)
    extracto(CLIP_V, src_h, 1920, 1080)  # reencuadre solo para tener una fuente horizontal
    png = OUT / "_broll_wide.png"
    broll_png(png, 1600, 500)

    casos = [
        (src_v, 1080, 1920, "cover", 1.0, "cutaway_vertical_cover_fullframe.mp4"),
        (src_v, 1080, 1920, "contain", 0.85, "cutaway_vertical_contain_85.mp4"),
        (src_h, 1920, 1080, "cover", 1.0, "cutaway_horizontal_cover_fullframe.mp4"),
    ]
    for src, w, h, fit, pct, nombre in casos:
        dst = OUT / nombre
        render_cutaway(src, png, dst, w, h, fit, pct)
        frame(dst, OUT / nombre.replace(".mp4", ".png"))

    # limpieza de temporales pesados; conservar frames + videos de evidencia
    for tmp in (src_v, src_h, OUT / "_caption.ass"):
        tmp.unlink(missing_ok=True)
    print("[done] evidencia en revision/broll-cutaway/")


if __name__ == "__main__":
    main()
