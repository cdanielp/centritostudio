"""jobs_registry.py - Registro de jobs en memoria del Studio.

Extraido de jobs.py (patron core_ass_fx de s29: primitivas fuera, consumidor <400 lineas).
jobs.py re-exporta new_job/update_job/get_job: los consumidores no cambian.
"""

from __future__ import annotations

import threading
import uuid

_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()


def new_job(description: str) -> str:
    """Crea un job nuevo y devuelve su ID."""
    jid = str(uuid.uuid4())[:8]
    with _JOBS_LOCK:
        _JOBS[jid] = {
            "status": "pending",
            "progress": 0,
            "message": description,
            "result": None,
            "error": None,
        }
    return jid


def update_job(jid: str, **kwargs) -> None:
    """Actualiza campos de un job."""
    with _JOBS_LOCK:
        _JOBS[jid].update(kwargs)


def get_job(jid: str) -> dict | None:
    """Devuelve el job o None si no existe."""
    with _JOBS_LOCK:
        return _JOBS.get(jid)
