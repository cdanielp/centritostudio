"""Runner del subconjunto PORTABLE de tests para el gate remoto ligero (H5).

Lee el manifiesto ``ci/pytest-light.txt`` (una ruta por linea, relativa a la raiz del
repo), valida cada entrada y ejecuta pytest con el MISMO interprete, con la red
bloqueada (pytest-socket) y SIN shell. Portable Windows/Linux.

Contrato de validacion (falla con exit 2 antes de tocar pytest):
    * manifiesto ausente o vacio;
    * ruta duplicada;
    * ruta fuera de ``tests/`` (o que escape via ``..``);
    * test inexistente.

No imprime variables de entorno ni abre el contenido de archivos privados: solo
resuelve rutas de tests versionados. Propaga el exit code de pytest; un skip/xfail
inesperado tambien pone el gate en ROJO (ver ``_pytest_light_plugin``).

Uso:
    python ci/run_pytest_light.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CI_DIR = ROOT / "ci"
MANIFEST = CI_DIR / "pytest-light.txt"
TESTS_DIR = (ROOT / "tests").resolve()


def _fail(mensaje: str) -> None:
    """Aborta la validacion con exit 2 (categoria de error, sin datos sensibles)."""
    print(f"ERROR: {mensaje}")
    raise SystemExit(2)


def _leer_manifiesto() -> list[str]:
    if not MANIFEST.is_file():
        _fail("manifiesto ausente: ci/pytest-light.txt")
    entradas: list[str] = []
    for cruda in MANIFEST.read_text(encoding="utf-8").splitlines():
        linea = cruda.strip()
        if not linea or linea.startswith("#"):
            continue
        entradas.append(linea)
    if not entradas:
        _fail("manifiesto vacio")
    return entradas


def _validar(entradas: list[str]) -> list[str]:
    """Devuelve rutas POSIX relativas, unicas, existentes y confinadas a tests/."""
    vistas: set[str] = set()
    relativas: list[str] = []
    for entrada in entradas:
        norm = entrada.replace("\\", "/")
        if norm in vistas:
            _fail(f"entrada duplicada: {norm}")
        vistas.add(norm)
        if not norm.startswith("tests/"):
            _fail(f"ruta fuera de tests/: {norm}")
        resuelta = (ROOT / norm).resolve()
        if resuelta != TESTS_DIR and TESTS_DIR not in resuelta.parents:
            _fail(f"ruta escapa de tests/: {norm}")
        if not resuelta.is_file():
            _fail(f"test inexistente: {norm}")
        relativas.append(resuelta.relative_to(ROOT).as_posix())
    return relativas


def _entorno() -> dict[str, str]:
    """Copia del entorno con ci/ en PYTHONPATH para cargar el plugin de cero-skips."""
    env = dict(os.environ)
    previo = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(CI_DIR) + (os.pathsep + previo if previo else "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def main() -> int:
    relativas = _validar(_leer_manifiesto())
    print(f"archivos-seleccionados={len(relativas)}")
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--disable-socket",
        "-p",
        "no:cacheprovider",
        "-p",
        "_pytest_light_plugin",
        *relativas,
    ]
    completado = subprocess.run(cmd, cwd=str(ROOT), env=_entorno(), check=False)
    return completado.returncode


if __name__ == "__main__":
    raise SystemExit(main())
