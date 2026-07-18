"""srt_serialize.py — Serializacion SRT y contrato JSON v1 (S36-A).

Round-trip SEMANTICO (no byte-identico: BOM y line endings pueden normalizarse).
El contrato JSON es la base estable que consumira S36-B: sin floats de tiempo,
sin rutas absolutas, sin bytes, sin texto fuente fuera de los cues.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from srt_time import format_timestamp
from srt_types import SrtDocument, SrtError


def serialize_srt(document: SrtDocument, *, reindex: bool = False, newline: str = "\n") -> str:
    """Serializa a texto SRT canonico (coma, indices y lineas preservados)."""
    blocks = []
    for pos, cue in enumerate(document.cues):
        idx = pos + 1 if reindex else cue.index
        head = f"{idx}\n{format_timestamp(cue.start_ms)} --> {format_timestamp(cue.end_ms)}"
        blocks.append(head + "\n" + "\n".join(cue.lines))
    text = "\n\n".join(blocks)
    if blocks:
        text += "\n"
    if newline != "\n":
        text = text.replace("\n", newline)
    return text


def _basename(name: str | None) -> str | None:
    if name is None:
        return None
    return name.replace("\\", "/").rsplit("/", 1)[-1]


def srt_to_contract(document: SrtDocument) -> dict:
    """Contrato JSON v1 (serializable, tiempos int, sin rutas absolutas). No muta."""
    start = document.cues[0].start_ms if document.cues else 0
    end = document.cues[-1].end_ms if document.cues else 0
    n_err = sum(1 for x in document.diagnostics if x.severity == "error")
    n_warn = sum(1 for x in document.diagnostics if x.severity == "warning")
    return {
        "version": 1,
        "source": {
            "format": "srt",
            "name": _basename(document.source_name),
            "encoding": document.encoding,
            "sha256": document.source_sha256,
        },
        "summary": {
            "n_cues": len(document.cues),
            "start_ms": start,
            "end_ms": end,
            "duration_ms": end - start,
            "n_errors": n_err,
            "n_warnings": n_warn,
        },
        "cues": [
            {
                "index": c.index,
                "source_position": c.source_position,
                "start_ms": c.start_ms,
                "end_ms": c.end_ms,
                "lines": list(c.lines),
                "text": c.text,
            }
            for c in document.cues
        ],
        "diagnostics": [
            {
                "code": x.code,
                "severity": x.severity,
                "message": x.message,
                "cue_position": x.cue_position,
                "cue_index": x.cue_index,
            }
            for x in document.diagnostics
        ],
    }


def _atomic_write_text(path: Path, text: str) -> None:
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="")
    os.replace(tmp, path)


def write_srt_contract(document: SrtDocument, destination: Path) -> None:
    """Escribe el contrato JSON de forma atomica. Se niega a sobreescribir un destino existente."""
    destination = Path(destination)
    if destination.exists():
        raise SrtError(f"el destino ya existe (elige otro nombre): {destination.name}")
    payload = json.dumps(srt_to_contract(document), ensure_ascii=False, indent=2)
    _atomic_write_text(destination, payload)
