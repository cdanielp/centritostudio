"""Regenera `motion/versiones.lock.json` con el sello de contenido de cada plantilla.

Se corre A MANO despues de tocar `motion/` Y de subir la version de la plantilla tocada. El
test del CI (`tests/test_hf3_sello_motion.py`) compara este lock con lo que hay en disco y
falla si el contenido cambio sin que la version subiera, que es el fallo que la clave de cache
no puede detectar por si sola.

Uso, desde la raiz del repo:

    venv\\Scripts\\python revision\\hf-3\\sellar_versiones.py
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))


def main() -> None:
    import motion_sello as ms

    motion = RAIZ / "motion"
    catalogo = ms.leer_catalogo(motion / "catalogo.json")
    lock_path = motion / ms.NOMBRE_LOCK
    antes = ms.leer_lock(lock_path)
    ahora = ms.sellar(motion, catalogo)

    for nombre in sorted(ahora):
        previo = antes.get(nombre)
        estado = "nuevo"
        if previo is not None:
            cambio_sello = previo["sello"] != ahora[nombre]["sello"]
            cambio_version = previo["version"] != ahora[nombre]["version"]
            estado = (
                "contenido y version"
                if cambio_sello and cambio_version
                else "solo contenido"
                if cambio_sello
                else "solo version"
                if cambio_version
                else "sin cambios"
            )
        print(f"  {nombre:<16} {ahora[nombre]['version']:<8} {ahora[nombre]['sello'][:16]}  {estado}")

    ms.escribir_lock(lock_path, ahora)
    print(f"\nlock escrito -> {lock_path.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
