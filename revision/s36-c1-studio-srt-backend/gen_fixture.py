"""gen_fixture.py — Fixture sintetico para el smoke de S36-C1.

Solo genera/limpia material SINTETICO local. Nunca versiona MP4, manifests ni SRT
privados; el unico artefacto versionado es fixtures/demo.srt (ya en el repo).

Uso:
    python revision/s36-c1-studio-srt-backend/gen_fixture.py --create
    python revision/s36-c1-studio-srt-backend/gen_fixture.py --clean
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
SCRATCH = HERE / "_scratch"

_DEMO_SRT = (
    "1\n00:00:00,000 --> 00:00:02,000\nHola desde Centrito Studio\n\n"
    "2\n00:00:02,000 --> 00:00:04,500\nEste es un SRT sintetico de prueba\n\n"
    "3\n00:00:04,500 --> 00:00:07,000\nSolo para el smoke de S36-C1\n"
)


def create() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    demo = FIXTURES / "demo.srt"
    demo.write_text(_DEMO_SRT, encoding="utf-8", newline="")
    print(f"[create] fixture SRT sintetico listo: {demo.relative_to(HERE)} ({demo.stat().st_size} B)")
    print("[create] el MP4 sintetico lo crea smoke_api.py en un tempdir efimero.")


def clean() -> None:
    if SCRATCH.exists():
        shutil.rmtree(SCRATCH, ignore_errors=True)
        print(f"[clean] eliminado {SCRATCH.name}/")
    else:
        print("[clean] nada que limpiar (sin _scratch).")


def main() -> None:
    ap = argparse.ArgumentParser(description="Fixture sintetico S36-C1")
    ap.add_argument("--create", action="store_true", help="genera el fixture SRT sintetico")
    ap.add_argument("--clean", action="store_true", help="elimina material de scratch")
    args = ap.parse_args()
    if args.clean:
        clean()
    if args.create:
        create()
    if not (args.create or args.clean):
        ap.print_help()


if __name__ == "__main__":
    main()
