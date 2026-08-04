"""motion_sello.py — Sello de contenido de las plantillas de `motion/` (HF-3, punto 5.3).

La clave de cache de una pieza es CIEGA al contenido de la plantilla: hashea el contrato y el
entorno, no el HTML. Editar una propiedad de CSS produce un MOV distinto y deja la clave
identica, asi que un hit de cache devolveria la pieza vieja. Hoy lo unico que lo tapa es la
regla D51.1 (subir la version de la plantilla es lo que invalida), y esa regla depende de que
nadie se olvide.

Este modulo convierte esa regla en un gate: sella el contenido de cada carpeta de `motion/` en
un lock, y el CI compara. Si el contenido cambio y la version no subio, el test falla y dice
exactamente que carpeta y que version toca poner.

PURO: solo lee archivos y calcula sha256. Sin red, sin reloj, sin subprocess.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

NOMBRE_LOCK = "versiones.lock.json"
# Lo que NO entra al sello: artefactos que no cambian lo que se pinta.
IGNORADOS = ("__pycache__", ".DS_Store", "Thumbs.db")
# Extensiones de TEXTO, cuyos finales de linea se normalizan antes de hashear. Git los convierte
# a CRLF al hacer checkout en Windows y los deja en LF en Linux, asi que hashear los bytes tal
# cual daba un sello distinto en cada plataforma y el gate reventaba en el CI aunque nadie
# hubiera tocado una plantilla. Un cambio de CRLF a LF no cambia lo que HyperFrames renderiza.
EXTENSIONES_TEXTO = (".html", ".js", ".json", ".css", ".txt", ".md", ".svg")


def _archivos_de(carpeta: Path) -> list[Path]:
    """Todos los archivos de la plantilla, en orden estable y con el gemelo dentro."""
    return sorted(
        p
        for p in carpeta.rglob("*")
        if p.is_file() and not any(parte in IGNORADOS for parte in p.parts)
    )


def _bytes_normalizados(archivo: Path) -> bytes:
    """Bytes del archivo, con los finales de linea normalizados si es texto.

    Los binarios (las fuentes) van tal cual: ahi una secuencia CR LF es un dato, no un salto.
    """
    crudo = archivo.read_bytes()
    if archivo.suffix.lower() in EXTENSIONES_TEXTO:
        return crudo.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return crudo


def sello_de_carpeta(carpeta: Path) -> str:
    """sha256 del CONTENIDO de una plantilla: rutas relativas + bytes de cada archivo.

    La ruta entra al hash ademas de los bytes: sin ella, renombrar `index.html` a `otro.html`
    daria el mismo sello, y eso si cambia lo que renderiza HyperFrames.

    Los finales de linea de los archivos de texto se normalizan: el sello tiene que valer lo
    mismo en Windows y en el runner del CI, y Git cambia CRLF por LF entre los dos.
    """
    carpeta = Path(carpeta)
    h = hashlib.sha256()
    for archivo in _archivos_de(carpeta):
        h.update(archivo.relative_to(carpeta).as_posix().encode("utf-8"))
        h.update(b"\0")
        h.update(_bytes_normalizados(archivo))
        h.update(b"\0")
    return h.hexdigest()


def sellar(raiz_motion: Path, catalogo: list[dict]) -> dict:
    """{plantilla: {version, sello}} para el catalogo dado. Puro."""
    raiz_motion = Path(raiz_motion)
    return {
        str(d["nombre"]): {
            "version": str(d["version"]),
            "sello": sello_de_carpeta(raiz_motion / str(d["nombre"])),
        }
        for d in catalogo
    }


def leer_catalogo(ruta: Path) -> list[dict]:
    return json.loads(Path(ruta).read_text(encoding="utf-8"))


def leer_lock(ruta: Path) -> dict:
    ruta = Path(ruta)
    if not ruta.is_file():
        return {}
    return json.loads(ruta.read_text(encoding="utf-8"))


def escribir_lock(ruta: Path, sellos: dict) -> None:
    Path(ruta).write_text(
        json.dumps(sellos, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )


def comparar(actual: dict, lock: dict) -> list[str]:
    """Problemas encontrados, uno por linea. Lista vacia = todo cuadra.

    El caso que importa es el tercero: contenido distinto con la MISMA version declarada. Ese
    es exactamente el fallo silencioso que la cache no puede ver.
    """
    problemas: list[str] = []
    for nombre in sorted(set(actual) | set(lock)):
        hoy, antes = actual.get(nombre), lock.get(nombre)
        if antes is None:
            problemas.append(
                f"'{nombre}': plantilla nueva sin sellar. Corre "
                f"`venv\\Scripts\\python revision/hf-3/sellar_versiones.py` y commitea el lock."
            )
            continue
        if hoy is None:
            problemas.append(
                f"'{nombre}': esta en el lock pero ya no esta en el catalogo. Si la quitaste a "
                f"proposito, vuelve a sellar."
            )
            continue
        if hoy["sello"] == antes["sello"] and hoy["version"] == antes["version"]:
            continue
        if hoy["sello"] != antes["sello"] and hoy["version"] == antes["version"]:
            problemas.append(
                f"'{nombre}': el CONTENIDO de motion/{nombre}/ cambio y la version sigue en "
                f"{hoy['version']}. La clave de cache no mira el contenido de la plantilla, asi "
                f"que las piezas ya renderizadas seguirian sirviendose VIEJAS desde cache. Sube "
                f"la version en motion/catalogo.json y en motion/ejemplos/{nombre}.json, y "
                f"vuelve a sellar."
            )
            continue
        problemas.append(
            f"'{nombre}': version {antes['version']} -> {hoy['version']}. Vuelve a sellar con "
            f"`venv\\Scripts\\python revision/hf-3/sellar_versiones.py`."
        )
    return problemas


__all__ = [
    "EXTENSIONES_TEXTO",
    "NOMBRE_LOCK",
    "comparar",
    "escribir_lock",
    "leer_catalogo",
    "leer_lock",
    "sellar",
    "sello_de_carpeta",
]
