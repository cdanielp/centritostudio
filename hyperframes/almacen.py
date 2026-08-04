"""Cache de piezas en disco: layout, sidecar, integridad y lock (HF-1).

Layout:  <raiz>/<2 primeros del hash>/<hash>/pieza.mov + pieza.json

Sigue el MISMO contrato de publicacion atomica que `media_integrity` (temporal en subdir
privado del mismo volumen, verificacion, `os.replace`, borrado del temporal ante fallo) pero
con temporal `.mov`: `media_integrity.ruta_temporal` fuerza `.mp4` y HyperFrames elige el
muxer por la extension, asi que reutilizarla produciria un MP4 sin alfa. El sidecar SI se
escribe con `atomic_io.atomic_write_json`, que es la fuente unica del repo.

El sha256 del MOV es un detector de INTEGRIDAD de la cache (que el archivo no se corrompio
en disco), nunca una asercion de que el render sea visualmente correcto: HF-0 documento que
la salida deriva entre versiones de Chrome y ffmpeg.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from atomic_io import atomic_write_json

from .razones import Razon

NOMBRE_MOV = "pieza.mov"
NOMBRE_SIDECAR = "pieza.json"
TEMP_DIRNAME = ".hf_tmp"
LOCK_DIRNAME = ".lock"
LOCK_RANCIO_S = 900  # un lock mas viejo que esto quedo de un proceso muerto
_SONDEO_PASO_S = 0.05


@dataclass(frozen=True)
class Hit:
    """Resultado de consultar la cache."""

    encontrado: bool
    ruta: Path | None = None
    sidecar: dict = field(default_factory=dict)
    razon: Razon | None = None


def _directorio(raiz: Path, hash_: str) -> Path:
    return Path(raiz) / hash_[:2] / hash_


def ruta_pieza(raiz: Path, hash_: str) -> Path:
    """Ruta del MOV de la pieza."""
    return _directorio(raiz, hash_) / NOMBRE_MOV


def ruta_sidecar(raiz: Path, hash_: str) -> Path:
    """Ruta del sidecar JSON de la pieza."""
    return _directorio(raiz, hash_) / NOMBRE_SIDECAR


def sha256_de(ruta: Path) -> str:
    """sha256 del archivo, leido por bloques (un MOV ProRes pesa decenas de MB)."""
    digest = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(bloque)
    return digest.hexdigest()


@contextlib.contextmanager
def temporal(raiz: Path, hash_: str):
    """Ruta temporal `.mov` UNICA, fuera del directorio final. Se borra siempre al salir.

    Vive en un subdir privado del MISMO volumen para que `os.replace` siga siendo atomico, y
    fuera del directorio final para que un render abortado no deje una pieza a medias donde
    `buscar` la encontraria.
    """
    tmp_dir = Path(raiz) / TEMP_DIRNAME
    tmp_dir.mkdir(parents=True, exist_ok=True)
    ruta = tmp_dir / f"{hash_[:8]}-{uuid.uuid4().hex}.mov"
    try:
        yield ruta
    finally:
        with contextlib.suppress(OSError):
            ruta.unlink()


def publicar(
    raiz: Path,
    hash_: str,
    origen: Path,
    *,
    contrato: dict,
    entorno: dict,
    sondeo: dict,
    segundos_render: float,
) -> Path:
    """Mueve `origen` a su lugar en la cache y escribe el sidecar. Devuelve la ruta del MOV."""
    destino = ruta_pieza(raiz, hash_)
    destino.parent.mkdir(parents=True, exist_ok=True)
    digest = sha256_de(origen)
    os.replace(origen, destino)
    atomic_write_json(
        ruta_sidecar(raiz, hash_),
        {
            "hash": hash_,
            "contrato": contrato,
            "entorno": entorno,
            "duracion_ms": sondeo.get("duracion_ms"),
            "fps": sondeo.get("fps"),
            "pix_fmt": sondeo.get("pix_fmt"),
            "sha256": digest,
            "segundos_render": round(float(segundos_render), 3),
            "fecha": datetime.now().isoformat(timespec="seconds"),
        },
    )
    return destino


def buscar(raiz: Path, hash_: str) -> Hit:
    """Consulta la cache. Un hit exige MOV + sidecar + sha256 que cuadre.

    Un MOV sin sidecar (o al reves) es un miss limpio: la publicacion quedo a medias y no hay
    nada que reportar. Un sha256 que no cuadra SI es `cache_corrupta`: el archivo estaba y se
    degrado, y eso el llamador tiene que saberlo aunque el re-render lo arregle.
    """
    mov, side = ruta_pieza(raiz, hash_), ruta_sidecar(raiz, hash_)
    if not mov.is_file() or not side.is_file():
        return Hit(encontrado=False)
    try:
        sidecar = json.loads(side.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Hit(encontrado=False, razon=Razon.CACHE_CORRUPTA)
    if not isinstance(sidecar, dict) or not sidecar.get("sha256"):
        return Hit(encontrado=False, razon=Razon.CACHE_CORRUPTA)
    try:
        if mov.stat().st_size == 0 or sha256_de(mov) != sidecar["sha256"]:
            return Hit(encontrado=False, razon=Razon.CACHE_CORRUPTA)
    except OSError:
        return Hit(encontrado=False, razon=Razon.CACHE_CORRUPTA)
    return Hit(encontrado=True, ruta=mov, sidecar=sidecar)


def _rancio(lock_dir: Path, rancio_s: float) -> bool:
    """True si el lock quedo abandonado (mas viejo que `rancio_s`)."""
    try:
        return (time.time() - lock_dir.stat().st_mtime) > rancio_s
    except OSError:
        return False


@contextlib.contextmanager
def lock(raiz: Path, hash_: str, *, espera_s: float = 0.0, rancio_s: float = LOCK_RANCIO_S):
    """Lock por hash via `mkdir` atomico. Cede True si lo tomo, False si sigue ocupado.

    Un lock mas viejo que `rancio_s` se reclama: sin eso, un hard-kill dejaria esa pieza
    bloqueada para siempre y ninguna corrida futura podria regenerarla.
    """
    lock_dir = _directorio(raiz, hash_) / LOCK_DIRNAME
    lock_dir.parent.mkdir(parents=True, exist_ok=True)
    limite = time.monotonic() + max(espera_s, 0.0)
    tomado = False
    while True:
        try:
            lock_dir.mkdir()
            tomado = True
            break
        except FileExistsError:
            if _rancio(lock_dir, rancio_s):
                with contextlib.suppress(OSError):
                    lock_dir.rmdir()
                continue
            if time.monotonic() >= limite:
                break
            time.sleep(_SONDEO_PASO_S)
    try:
        yield tomado
    finally:
        if tomado:
            with contextlib.suppress(OSError):
                lock_dir.rmdir()


def tamano_ocupado(raiz: Path) -> int:
    """Bytes ocupados por la cache. HF-1 solo REPORTA: no hay GC ni limite de tamano."""
    raiz = Path(raiz)
    if not raiz.is_dir():
        return 0
    total = 0
    for hijo in raiz.rglob("*"):
        try:
            if hijo.is_file():
                total += hijo.stat().st_size
        except OSError:
            continue
    return total


__all__ = [
    "LOCK_RANCIO_S",
    "Hit",
    "buscar",
    "lock",
    "publicar",
    "ruta_pieza",
    "ruta_sidecar",
    "sha256_de",
    "tamano_ocupado",
    "temporal",
]
