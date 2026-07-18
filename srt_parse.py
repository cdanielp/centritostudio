"""srt_parse.py — Decodificacion y parser de estado del importador SRT (S36-A).

Decodifica bytes (UTF-8 / BOM / cp1252) y parsea bloques separados por lineas en
blanco a un SrtDocument inmutable. El parser NUNCA muta ni corrige el texto del
usuario, no reordena cues y no inventa timing por palabra (ver DECISIONES D33).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from srt_time import parse_timestamp
from srt_types import (
    ERR_EMPTY_CUE_TEXT,
    ERR_END_LE_START,
    ERR_INDEX_NOT_INTEGER,
    ERR_MISSING_TIMESTAMP,
    ERR_NUL_CHARACTER,
    ERR_TIMESTAMP_UNREADABLE,
    ERR_TRUNCATED_BLOCK,
    MAX_CUES,
    MAX_SRT_BYTES,
    MAX_TOTAL_TEXT_CHARS,
    WARN_CP1252_FALLBACK,
    WARN_DECIMAL_DOT,
    WARN_WHITESPACE_NORMALIZED,
    SrtCue,
    SrtDecodeError,
    SrtDiagnostic,
    SrtDocument,
    SrtError,
    SrtLimitError,
    SrtParseError,
    diag,
)

_INT_RE = re.compile(r"^\d+$")


# --- Decodificacion (UTF-8 / BOM / cp1252) ---


def _decode_strict(data: bytes, codec: str) -> str:
    try:
        return data.decode(codec)
    except UnicodeDecodeError as e:
        raise SrtDecodeError(f"no decodificable como {codec} (offset {e.start})") from e


def _decode_auto(data: bytes) -> tuple[str, str, list[SrtDiagnostic]]:
    if data[:3] == b"\xef\xbb\xbf":
        return _decode_strict(data[3:], "utf-8"), "utf-8", []
    try:
        return data.decode("utf-8"), "utf-8", []
    except UnicodeDecodeError:
        pass
    text = _decode_strict(data, "cp1252")
    fb = diag(
        WARN_CP1252_FALLBACK,
        "warning",
        "los bytes no eran UTF-8 valido; se decodifico como Windows-1252",
    )
    return text, "windows-1252", [fb]


def _decode_bytes(data: bytes, encoding: str) -> tuple[str, str, list[SrtDiagnostic]]:
    enc = encoding.lower()
    if enc == "auto":
        return _decode_auto(data)
    if enc in ("utf-8", "utf8"):
        return _decode_strict(data, "utf-8"), "utf-8", []
    if enc in ("utf-8-sig", "utf_8_sig"):
        return _decode_strict(data, "utf-8-sig"), "utf-8", []
    if enc in ("cp1252", "windows-1252"):
        return _decode_strict(data, "cp1252"), "windows-1252", []
    raise SrtDecodeError(f"encoding no soportado: {encoding!r}")


# --- Parser de estado (bloques separados por lineas en blanco) ---


def _iter_blocks(text: str):
    """Agrupa lineas en bloques; source_position es el ordinal 0-based del bloque."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    block: list[str] = []
    pos = 0
    for raw in lines:
        if raw.strip() == "":
            if block:
                yield pos, block
                pos, block = pos + 1, []
        else:
            block.append(raw)
    if block:
        yield pos, block


def _parse_time_line(ts_line: str):
    """Devuelve (start_ms, end_ms, [codigos_warning]) o None si no hay flecha '-->'."""
    if "-->" not in ts_line:
        return None
    left, _, right = ts_line.partition("-->")
    left_t = left.strip()
    right_parts = right.split()
    right_t = right_parts[0] if right_parts else ""
    start, end = parse_timestamp(left_t), parse_timestamp(right_t)
    warnings = []
    if "." in left_t or "." in right_t:
        warnings.append(WARN_DECIMAL_DOT)
    if len(right_parts) > 1 or ts_line != f"{left_t} --> {right_t}":
        warnings.append(WARN_WHITESPACE_NORMALIZED)
    return start, end, warnings


def _parse_block(pos: int, lines: list[str]):
    """Parsea un bloque -> (SrtCue|None, [diagnosticos]). Nunca muta ni corrige texto."""
    idx_raw = lines[0].strip()
    if not _INT_RE.match(idx_raw):
        return None, [diag(ERR_INDEX_NOT_INTEGER, "error", f"indice no entero (bloque {pos})", pos)]
    index = int(idx_raw)
    if len(lines) < 2:
        return None, [diag(ERR_TRUNCATED_BLOCK, "error", f"bloque {pos} truncado", pos, index)]
    try:
        parsed = _parse_time_line(lines[1])
    except SrtParseError:
        return None, [
            diag(
                ERR_TIMESTAMP_UNREADABLE, "error", f"timestamp ilegible (bloque {pos})", pos, index
            )
        ]
    if parsed is None:
        return None, [
            diag(ERR_MISSING_TIMESTAMP, "error", f"falta linea temporal (bloque {pos})", pos, index)
        ]
    start, end, ts_warn = parsed
    text_lines = tuple(lines[2:])
    if not text_lines or all(ln.strip() == "" for ln in text_lines):
        return None, [
            diag(ERR_EMPTY_CUE_TEXT, "error", f"cue sin texto (bloque {pos})", pos, index)
        ]
    if any("\x00" in ln for ln in text_lines):
        return None, [diag(ERR_NUL_CHARACTER, "error", f"caracter NUL (bloque {pos})", pos, index)]
    if end <= start:
        return None, [diag(ERR_END_LE_START, "error", f"end<=start (bloque {pos})", pos, index)]
    diags = [
        diag(c, "warning", f"timestamp normalizado (bloque {pos})", pos, index) for c in ts_warn
    ]
    return SrtCue(index, start, end, text_lines, pos), diags


def _parse(text, source_name, strict, encoding, sha256, seed_diags) -> SrtDocument:
    if len(text) > MAX_TOTAL_TEXT_CHARS:
        raise SrtLimitError(f"texto excede MAX_TOTAL_TEXT_CHARS ({MAX_TOTAL_TEXT_CHARS})")
    diags = list(seed_diags)
    cues: list[SrtCue] = []
    for pos, lines in _iter_blocks(text):
        if len(cues) >= MAX_CUES:
            raise SrtLimitError(f"demasiados cues (> {MAX_CUES})")
        cue, block_diags = _parse_block(pos, lines)
        if cue is None:
            if strict:
                err = block_diags[0]
                raise SrtParseError(f"[{err.code}] {err.message}")
            diags.extend(block_diags)
            continue
        diags.extend(block_diags)
        cues.append(cue)
    return SrtDocument(tuple(cues), encoding, sha256, tuple(diags), source_name)


def parse_srt_text(
    text: str, *, source_name: str | None = None, strict: bool = False
) -> SrtDocument:
    """Parsea SRT ya decodificado. sha256 se calcula sobre el texto en UTF-8."""
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return _parse(text, source_name, strict, "utf-8", sha, [])


def parse_srt_bytes(
    data: bytes, *, source_name: str | None = None, encoding: str = "auto", strict: bool = False
) -> SrtDocument:
    """Decodifica bytes segun politica de encoding y parsea. sha256 sobre los bytes fuente."""
    if len(data) > MAX_SRT_BYTES:
        raise SrtLimitError(f"entrada excede MAX_SRT_BYTES ({MAX_SRT_BYTES})")
    text, enc, diags = _decode_bytes(data, encoding)
    sha = hashlib.sha256(data).hexdigest()
    return _parse(text, source_name, strict, enc, sha, diags)


def load_srt(
    path: Path, *, encoding: str = "auto", strict: bool = False, max_bytes: int = MAX_SRT_BYTES
) -> SrtDocument:
    """Carga un .srt desde disco con guardas de seguridad. No sigue directorios."""
    path = Path(path)
    if path.is_dir():
        raise SrtError(f"la ruta es un directorio, no un archivo: {path.name}")
    if not path.is_file():
        raise SrtError(f"archivo no encontrado: {path.name}")
    if path.suffix.lower() != ".srt":
        raise SrtError(f"extension no valida (se espera .srt): {path.name}")
    size = path.stat().st_size
    if size > max_bytes:
        raise SrtLimitError(f"archivo excede el limite ({size} > {max_bytes} bytes)")
    return parse_srt_bytes(
        path.read_bytes(), source_name=path.name, encoding=encoding, strict=strict
    )
