"""studio_packages.py - Router HTTP del Editor de Paquete (S35, D32).

Capa HTTP SOLO-LECTURA sobre output/paquetes/. No reimplementa motores: delega la
agregacion pura a paquete_editor y el semaforo/recomendacion a auto_report. Aqui
vive el confinamiento del servido de binario: el .mp4 de un clip se entrega por un
endpoint validado (nunca por un mount estatico abierto) y solo si es un basename
seguro y existe; el REPORTE.md por su propio endpoint. Nunca se sirven paquete.json
ni sidecars por la ruta publica del video. Cero escritura, cero recalculo (regla #19).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

import paquete_editor as pe

ROOT = Path(__file__).parent
PAQUETES_DIR = ROOT / "output" / "paquetes"
TRANSCRIPTS = ROOT / "transcripts"

router = APIRouter()


def _leer_paquete_json(d: Path) -> dict | None:
    """paquete.json de un dir -> dict, o None si falta/ilegible. Solo lectura."""
    pj = d / "paquete.json"
    if not pj.exists():
        return None
    try:
        return json.loads(pj.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _dir_paquete(pkg: str) -> Path:
    """Dir de un paquete validando traversal (solo hijos directos). 404 si escapa."""
    d = pe.resolver_hijo_seguro(PAQUETES_DIR, pkg)
    if d is None or not d.is_dir():
        raise HTTPException(404, "Paquete no encontrado")
    return d


def _epoch_paquete(card: dict, d: Path) -> float:
    """Instante del paquete para ordenar (mas reciente primero). Determinista.

    `card['fecha']` ya viene resuelta por resumen_lista_paquete (meta.fecha o, si
    falta, el sufijo del id 'nombre_YYYYMMDD-HHMM'). La parseamos a epoch; solo si
    NINGUNA de las dos parsea caemos al mtime del directorio, para que un paquete
    real sin fecha no se hunda ni desordene la lista. No recalcula nada del paquete.
    """
    fecha = card.get("fecha") or ""
    try:
        return datetime.strptime(fecha, "%Y%m%d-%H%M").timestamp()
    except (ValueError, TypeError):
        try:
            return d.stat().st_mtime
        except OSError:
            return 0.0


@router.get("/api/paquetes")
def list_paquetes() -> list[dict]:
    """Lista los paquetes (mas recientes primero). Fail-open por paquete.

    Orden determinista por instante (meta.fecha, o mtime del dir si falta/invalida)
    descendente; ultimo desempate por `id`. No se recalcula nada.
    """
    entradas: list[tuple[Path, dict]] = []
    if not PAQUETES_DIR.exists():
        return []
    for d in PAQUETES_DIR.glob("*"):
        if not d.is_dir():
            continue
        data = _leer_paquete_json(d)
        if data is None:  # corrida a medias / json ilegible: no se lista
            continue
        entradas.append((d, pe.resumen_lista_paquete(d.name, data)))
    entradas.sort(key=lambda e: (_epoch_paquete(e[1], e[0]), e[1]["id"]), reverse=True)
    return [card for _d, card in entradas]


@router.get("/api/paquetes/{pkg}")
def get_paquete(pkg: str) -> dict:
    """Detalle de un paquete para el Editor. Valida traversal (solo hijos directos)."""
    d = _dir_paquete(pkg)
    data = _leer_paquete_json(d)
    if data is None:
        raise HTTPException(404, "Paquete sin paquete.json (corrida incompleta)")
    return pe.vista_paquete(data, d.name, d, TRANSCRIPTS)


@router.get("/api/paquetes/{pkg}/video/{archivo}")
def get_paquete_video(pkg: str, archivo: str) -> FileResponse:
    """Sirve el binario .mp4 de un clip. Confinado: solo .mp4 existente del paquete.

    Rechaza cualquier otra extension (paquete.json, REPORTE.md, sidecars) y todo
    nombre inseguro/traversal: la ruta publica del video NUNCA expone internos.
    """
    d = _dir_paquete(pkg)
    p = pe.resolver_archivo_paquete(d, archivo)
    if p is None or not p.is_file() or p.suffix.lower() != ".mp4":
        raise HTTPException(404, "Video no disponible")
    return FileResponse(str(p), media_type="video/mp4")


@router.get("/api/paquetes/{pkg}/reporte")
def get_paquete_reporte(pkg: str) -> FileResponse:
    """Sirve el REPORTE.md del paquete (solo ese archivo). 404 si no existe."""
    d = _dir_paquete(pkg)
    p = d / "REPORTE.md"
    if not p.is_file():
        raise HTTPException(404, "REPORTE.md no disponible")
    return FileResponse(str(p), media_type="text/markdown; charset=utf-8")
