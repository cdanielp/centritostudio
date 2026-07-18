"""gen_fixture.py — Crea el fixture SINTETICO del round-trip SRT (S36-B).

Sin GPU, sin red, sin Whisper real, sin DeepSeek. Genera:
  1. un video vertical 9:16 sintetico (FFmpeg lavfi, con tono de audio),
  2. un transcript de palabras sintetico MAS RECIENTE que el video (evita transcribir),
  3. (el SRT corregido sintetico ya vive versionado en fixtures/corregido_sintetico.srt).

Los artefactos generados (mp4/json/srt derivados) viven en work/ y NUNCA se versionan.
El transcript se escribe en transcripts/ (gitignored) con el stem del video para que
caption.py lo reutilice.

Uso:
    python revision/s36-b-srt-caption-roundtrip/gen_fixture.py --create
    python revision/s36-b-srt-caption-roundtrip/gen_fixture.py --clean
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORK = HERE / "work"
TRANSCRIPTS = ROOT / "transcripts"
STEM = "s36b_fixture"
VIDEO = WORK / f"{STEM}.mp4"
WORDS_JSON = TRANSCRIPTS / f"{STEM}_words.json"

# Transcript SINTETICO tipo Whisper: incluye un error ("prueva") para probar substitution,
# y NO contiene el texto del cue 4 (fuerza cue_fallback honesto). Tiempos en segundos.
SYNTH_WORDS = [
    {"w": "hola", "s": 0.00, "e": 0.40, "prob": 0.98},
    {"w": "mundo", "s": 0.50, "e": 0.95, "prob": 0.97},
    {"w": "esto", "s": 1.20, "e": 1.45, "prob": 0.96},
    {"w": "es", "s": 1.55, "e": 1.70, "prob": 0.95},
    {"w": "una", "s": 1.80, "e": 2.00, "prob": 0.95},
    {"w": "prueva", "s": 2.10, "e": 2.55, "prob": 0.60},  # mal transcrito -> substitution
    {"w": "el", "s": 3.00, "e": 3.20, "prob": 0.97},
    {"w": "cafe", "s": 3.30, "e": 3.65, "prob": 0.96},
    {"w": "esta", "s": 3.75, "e": 4.05, "prob": 0.96},
    {"w": "listo", "s": 4.15, "e": 4.55, "prob": 0.97},
    # (cue 4 "Texto anadido sin audio" no tiene palabras -> fallback)
]


def _run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"[gen_fixture] fallo: {' '.join(cmd[:3])}...\n{r.stderr[-800:]}")


def create() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    TRANSCRIPTS.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x101018:size=1080x1920:rate=30:duration=6",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=220:duration=6",
            "-c:v",
            "libx264",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(VIDEO),
        ]
    )
    # El transcript se escribe DESPUES del video -> mtime mayor -> caption.py lo reutiliza.
    WORDS_JSON.write_text(
        json.dumps({"words": SYNTH_WORDS, "language": "es"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[gen_fixture] video:      {VIDEO.relative_to(ROOT)}")
    print(f"[gen_fixture] transcript: {WORDS_JSON.relative_to(ROOT)} ({len(SYNTH_WORDS)} palabras)")
    print("[gen_fixture] srt fuente: fixtures/corregido_sintetico.srt (versionado)")
    print("[gen_fixture] listo. Ahora corre smoke_srt_roundtrip.py")


def clean() -> None:
    removed = 0
    if WORK.exists():
        for p in WORK.iterdir():
            p.unlink()
            removed += 1
        WORK.rmdir()
    for p in TRANSCRIPTS.glob(f"{STEM}*"):
        p.unlink()
        removed += 1
    for p in (ROOT / "output").glob(f"{STEM}*"):
        p.unlink()
        removed += 1
    print(f"[gen_fixture] limpiados {removed} artefactos generados (nada versionado tocado)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Fixture sintetico del round-trip SRT (S36-B)")
    ap.add_argument("--create", action="store_true", help="genera video + transcript sintetico")
    ap.add_argument("--clean", action="store_true", help="borra los artefactos generados")
    args = ap.parse_args()
    if args.clean:
        clean()
    elif args.create:
        create()
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
