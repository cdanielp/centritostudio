"""gen_fixture.py — Genera el video sintetico del smoke S36-C2A1 (sin red, sin GPU).

Crea un MP4 vertical 1080x1920 de 4s con audio (tono) via FFmpeg lavfi. El SRT y las words
sinteticas viven versionados en fixtures/ (texto sintetico, jamas el SRT privado del usuario).
El MP4 NO se versiona (*.mp4 gitignored).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def generar_video(destino: Path, *, dur: float = 4.0) -> Path:
    """Video vertical 1080x1920 con audio sintetico. Determinista (color+tono fijos)."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=0x101820:s=1080x1920:r=30:d={dur}",
        "-f", "lavfi", "-i", f"sine=frequency=220:duration={dur}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest",
        str(destino),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return destino


if __name__ == "__main__":
    out = generar_video(Path("output/revision-s36-c2a1/demo.mp4"))
    print(f"[gen] video sintetico -> {out.name}")
    print(f"[gen] SRT fixture      -> {(FIXTURES / 'demo.srt').name}")
    print(f"[gen] words fixture    -> {(FIXTURES / 'demo_words.json').name}")
