"""atomic_io.py — Escrituras ATOMICAS de estado de recuperacion (H2, P2-ATOM-STATE).

Fuente UNICA para escribir el texto/JSON que el resume del Modo Automatico LEE (checkpoints por
clip, markers de paquete, procedencia classic, words/groups, REPORTE.md, clips.json). Contrato:

  * temporal UNICO en el MISMO directorio del destino (mismo filesystem que `os.replace` exige),
    via `tempfile.mkstemp` -> dos writers concurrentes al mismo destino jamas colisionan el `.tmp`;
  * `flush()` + `os.fsync()` antes de publicar (durabilidad ante corte de luz / cierre de ventana);
  * `os.replace(tmp, final)` atomico -> el destino nunca queda medio escrito;
  * ante CUALQUIER error se borra el temporal y el `final` anterior queda INTACTO;
  * no deja `.tmp` visible tras un error.

PURO: sin red, sin FFmpeg, sin Auto. Unifica los helpers `.tmp` de sufijo fijo dispersos por el
repo SOLO en los puntos que controlan resume. NO se expande a `.ass`/keyword sidecars (P2 residual
documentado): esos archivos no gobiernan la reanudacion.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Escribe `text` de forma atomica y durable (temporal unico + fsync + os.replace)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def atomic_write_json(
    path: Path, obj: object, *, ensure_ascii: bool = False, indent: int | None = 2
) -> None:
    """Serializa `obj` a JSON y lo escribe atomicamente (mismo contrato que atomic_write_text)."""
    atomic_write_text(path, json.dumps(obj, ensure_ascii=ensure_ascii, indent=indent))


__all__ = ["atomic_write_text", "atomic_write_json"]
