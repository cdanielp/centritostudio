"""srt_types.py — Tipos, excepciones, limites y codigos de diagnostico del importador SRT.

Base de datos PURA para S36-A (ver DECISIONES D33). No importa nada del pipeline
de captions/render; solo libreria estandar. Tiempos SIEMPRE en milisegundos enteros.
Estructuras inmutables (frozen dataclasses): nunca se mutan las entradas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Severity = Literal["warning", "error"]

# --- Limites de seguridad (defaults sensatos; ajustables con justificacion) ---
MAX_SRT_BYTES = 10 * 1024 * 1024
MAX_CUES = 100_000
MAX_LINES_PER_CUE = 20
MAX_CHARS_PER_LINE = 10_000
MAX_TOTAL_TEXT_CHARS = 5_000_000
MAX_CUE_DURATION_MS = 30 * 60 * 1000  # 30 min: duracion de cue "excesiva" (solo warning)
LAST_CUE_GAP_MS = 60_000  # ultimo cue muy lejos del fin del video (solo informativo)

# --- Codigos de diagnostico (estables para S36-B) ---
# Errores estructurales: en modo strict abortan; en tolerante se registran y se salta el bloque.
ERR_INDEX_NOT_INTEGER = "index_not_integer"
ERR_MISSING_TIMESTAMP = "missing_timestamp_line"
ERR_TIMESTAMP_UNREADABLE = "timestamp_unreadable"
ERR_END_LE_START = "end_le_start"
ERR_EMPTY_CUE_TEXT = "empty_cue_text"
ERR_NUL_CHARACTER = "nul_character"
ERR_TRUNCATED_BLOCK = "truncated_block"
ERR_INDEX_NON_POSITIVE = "index_non_positive"
ERR_NEGATIVE_START = "negative_start"
ERR_DOCUMENT_EMPTY = "document_empty"
# Advertencias: nunca abortan, solo informan.
WARN_INDEX_DUPLICATE = "index_duplicate"
WARN_INDEX_NOT_CONSECUTIVE = "index_not_consecutive"
WARN_TIME_NOT_MONOTONIC = "time_not_monotonic"
WARN_OVERLAP = "overlap"
WARN_DECIMAL_DOT = "decimal_dot_normalized"
WARN_CP1252_FALLBACK = "encoding_cp1252_fallback"
WARN_WHITESPACE_NORMALIZED = "structural_whitespace_normalized"
WARN_CUE_AFTER_VIDEO = "cue_after_video"
WARN_CUE_PARTIALLY_OUT = "cue_partially_out_of_video"
WARN_LAST_CUE_FAR = "last_cue_far_from_video_end"
WARN_CUE_DURATION_EXCESSIVE = "cue_duration_excessive"
WARN_TOO_MANY_LINES = "too_many_lines"
WARN_LINE_TOO_LONG = "line_too_long"
WARN_CONTROL_CHARACTERS = "control_characters"


class SrtError(Exception):
    """Base de errores del importador SRT (errores de USUARIO, no bugs)."""


class SrtDecodeError(SrtError):
    """Los bytes fuente no pudieron decodificarse con la politica de encoding."""


class SrtParseError(SrtError):
    """SRT malformado; en modo strict aborta al primer error estructural."""


class SrtLimitError(SrtError):
    """Se excedio un limite de seguridad (tamano, numero de cues, texto total)."""


@dataclass(frozen=True)
class SrtCue:
    """Un bloque SRT: indice original, tiempos en ms enteros y lineas de texto tal cual."""

    index: int
    start_ms: int
    end_ms: int
    lines: tuple[str, ...]
    source_position: int

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@dataclass(frozen=True)
class SrtDiagnostic:
    """Diagnostico estructurado y determinista (nunca texto privado completo)."""

    code: str
    severity: Severity
    message: str
    cue_position: int | None = None
    cue_index: int | None = None


def diag(
    code: str,
    severity: Severity,
    message: str,
    cue_position: int | None = None,
    cue_index: int | None = None,
) -> SrtDiagnostic:
    """Fabrica compartida de diagnosticos (evita repetir el constructor en cada modulo)."""
    return SrtDiagnostic(code, severity, message, cue_position, cue_index)


@dataclass(frozen=True)
class SrtDocument:
    """Documento SRT inmutable: cues en orden fuente + metadatos + diagnosticos."""

    cues: tuple[SrtCue, ...]
    encoding: str
    source_sha256: str
    diagnostics: tuple[SrtDiagnostic, ...] = field(default_factory=tuple)
    source_name: str | None = None


__all__ = [
    "Severity",
    "MAX_SRT_BYTES",
    "MAX_CUES",
    "MAX_LINES_PER_CUE",
    "MAX_CHARS_PER_LINE",
    "MAX_TOTAL_TEXT_CHARS",
    "MAX_CUE_DURATION_MS",
    "LAST_CUE_GAP_MS",
    "SrtError",
    "SrtDecodeError",
    "SrtParseError",
    "SrtLimitError",
    "SrtCue",
    "SrtDiagnostic",
    "SrtDocument",
]
