"""setup_models.py — Instalador CLI de los modelos de deteccion facial (H3).

Descarga reproducible y VERIFICADA por SHA256 de YuNet y BlazeFace desde sus URLs oficiales.
NO se ejecuta al arrancar el Studio: es un paso explicito.

Uso:
    venv\\Scripts\\python.exe scripts\\setup_models.py            # instala los que falten
    venv\\Scripts\\python.exe scripts\\setup_models.py --model yunet
    venv\\Scripts\\python.exe scripts\\setup_models.py --force     # reinstala aunque existan
    venv\\Scripts\\python.exe scripts\\setup_models.py --list      # lista modelos y estado

La logica vive en model_setup.py (pura y testeable). Este archivo es solo el punto de entrada.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import model_assets  # noqa: E402
import model_setup  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Instala los modelos de deteccion facial.")
    parser.add_argument(
        "--model",
        action="append",
        choices=[m.id for m in model_assets.MODELS],
        help="Modelo(s) a instalar (por defecto: todos los usados).",
    )
    parser.add_argument("--force", action="store_true", help="Reinstala aunque ya existan.")
    parser.add_argument("--list", action="store_true", help="Lista modelos y estado; no descarga.")
    args = parser.parse_args(argv)

    if args.list:
        for m in model_assets.MODELS:
            estado = "presente" if model_assets.model_present(m) else "ausente"
            print(f"  {m.id:12s} [{estado:8s}] {m.rel_path}")
            print(f"               URL: {m.url}")
        return 0

    print("Instalando modelos (descarga oficial + verificacion SHA256)...")
    resultados = model_setup.install_all(args.model, force=args.force)
    hubo_error = False
    for mid, res in resultados:
        marca = "[OK]" if res in ("ok", "ya-presente") else "[X]"
        if res.startswith("error"):
            hubo_error = True
        print(f"  {marca} {mid}: {res}")
    if hubo_error:
        print(
            "\n[X] Algun modelo no se pudo instalar. Ver docs\\ENTORNO.md para instalacion manual."
        )
        return 1
    print("\n[OK] Modelos listos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
