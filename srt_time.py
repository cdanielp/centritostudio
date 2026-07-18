"""srt_time.py — Primitivas de timestamp SRT (compartidas por parser y serializador).

Contrato canonico: 'HH:MM:SS,mmm'. Tiempos en milisegundos enteros, sin floats.
"""

from __future__ import annotations

import re

from srt_types import SrtParseError

_TS_RE = re.compile(r"^(\d{2,}):([0-5][0-9]):([0-5][0-9])[.,](\d{3})$")


def parse_timestamp(value: str) -> int:
    """Convierte 'HH:MM:SS,mmm' (o '.' tolerado) a milisegundos enteros. No acepta basura."""
    m = _TS_RE.match(value.strip())
    if not m:
        raise SrtParseError(f"timestamp ilegible: {value.strip()[:40]!r}")
    h, mm, ss, ms = (int(g) for g in m.groups())
    return ((h * 60 + mm) * 60 + ss) * 1000 + ms


def format_timestamp(milliseconds: int) -> str:
    """Serializa ms enteros a 'HH:MM:SS,mmm' (coma canonica). Rechaza negativos."""
    if milliseconds < 0:
        raise SrtParseError(f"milisegundos negativos: {milliseconds}")
    ms = milliseconds % 1000
    total_s = milliseconds // 1000
    s, total_m = total_s % 60, total_s // 60
    mm, h = total_m % 60, total_m // 60
    return f"{h:02d}:{mm:02d}:{s:02d},{ms:03d}"
