"""Genera el CSV de trayectoria que falta para los clips 9:16 ya existentes.

Sin este CSV el planificador no sabe donde esta la cara, trata el carril vertical como ocupado
y omite TODAS las piezas: la medicion mediria la ausencia del dato en vez de la regla. Los
clips 9:16 del proyecto se reencuadraron antes de que Auto pidiera la trayectoria, asi que no
lo tienen.

NO DESTRUCTIVO: el MP4 reencuadrado se escribe en una carpeta temporal y se descarta; lo unico
que queda es `trayectoria_<stem>_9x16.csv` junto a los clips, que es lo que el resto del
pipeline ya sabe leer.

Uso, desde la raiz del repo:

    venv\\Scripts\\python revision\\hf-3\\generar_trayectorias.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

CLIPS_DIR = RAIZ / "output" / "clips"
SUFIJO = "_9x16"


def pares() -> list[tuple[Path, str]]:
    """(fuente 16:9, stem del 9:16) de cada clip vertical al que le falte la trayectoria."""
    salida: list[tuple[Path, str]] = []
    for vertical in sorted(CLIPS_DIR.glob(f"*{SUFIJO}.mp4")):
        if vertical.name.startswith("_"):
            continue
        stem = vertical.stem
        if (CLIPS_DIR / f"trayectoria_{stem}.csv").exists():
            continue
        fuente = CLIPS_DIR / f"{stem[: -len(SUFIJO)]}.mp4"
        if fuente.exists():
            salida.append((fuente, stem))
    return salida


def main() -> None:
    import reframe

    faltan = pares()
    print(f"clips 9:16 sin trayectoria y con fuente 16:9 disponible: {len(faltan)}")
    temporal = Path(tempfile.mkdtemp(prefix="hf3_tray_"))
    try:
        for i, (fuente, stem) in enumerate(faltan, 1):
            destino = temporal / f"{stem}.mp4"
            t = time.perf_counter()
            try:
                reframe.reframe_clip(
                    fuente, destino, tracker="escenas", tray_dir=CLIPS_DIR
                )
            except Exception as exc:  # noqa: BLE001 - un clip ilegible no para la medicion
                print(f"  [{i}/{len(faltan)}] {stem}: FALLO {type(exc).__name__}: {exc}")
                continue
            csv = CLIPS_DIR / f"trayectoria_{stem}.csv"
            print(f"  [{i}/{len(faltan)}] {stem}: {time.perf_counter() - t:.1f}s "
                  f"-> {csv.name} {'ok' if csv.exists() else 'NO ESCRITO'}")
            destino.unlink(missing_ok=True)
    finally:
        shutil.rmtree(temporal, ignore_errors=True)


if __name__ == "__main__":
    main()
