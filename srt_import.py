"""srt_import.py — Fachada publica del importador SRT (S36-A, ver DECISIONES D33).

Un SRT es un documento de CUES (frases con tiempo), NO un transcript por palabra;
el parser jamas inventa timing por palabra. Tiempos SIEMPRE en milisegundos enteros.
Esta capa es PURA y reusable: no toca captions, render, FFmpeg ni la UI del Studio.

Punto de entrada unico: importa siempre desde `srt_import`, no de los submodulos.
    from srt_import import load_srt, validate_srt, serialize_srt, srt_to_contract

Submodulos internos:
    srt_types      tipos, excepciones, limites y codigos de diagnostico
    srt_time       parse/format de timestamps (ms enteros)
    srt_parse      decodificacion (UTF-8/BOM/cp1252) y parser de estado
    srt_validate   validacion estructurada e independiente
    srt_serialize  serializacion SRT + contrato JSON v1
"""

from __future__ import annotations

from srt_parse import load_srt, parse_srt_bytes, parse_srt_text
from srt_serialize import serialize_srt, srt_to_contract, write_srt_contract
from srt_time import format_timestamp, parse_timestamp
from srt_types import (
    SrtCue,
    SrtDecodeError,
    SrtDiagnostic,
    SrtDocument,
    SrtError,
    SrtLimitError,
    SrtParseError,
)
from srt_validate import validate_srt

__all__ = [
    # Tipos y excepciones
    "SrtCue",
    "SrtDiagnostic",
    "SrtDocument",
    "SrtError",
    "SrtDecodeError",
    "SrtParseError",
    "SrtLimitError",
    # Timestamps
    "parse_timestamp",
    "format_timestamp",
    # Parseo / carga
    "parse_srt_text",
    "parse_srt_bytes",
    "load_srt",
    # Validacion
    "validate_srt",
    # Serializacion / contrato
    "serialize_srt",
    "srt_to_contract",
    "write_srt_contract",
]
