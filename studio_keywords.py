"""studio_keywords.py — sidecar de marcado manual {stem}_keywords.json desde Studio (F6).

Puro y saneado: la UI envia frases/palabras a destacar; aqui se validan y se persisten
en el MISMO formato que consume cve.candidatos_manuales (palabra|frase + intensidad big).
Sin rutas ni claves libres: solo un allowlist. Fail-safe: entrada malformada se ignora.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

_INTENSIDADES_OK = {"big", "grande"}
_MAX_ENTRADAS = 200  # cota dura anti-abuso


def sanitize_entries(data) -> list[dict]:
    """Normaliza la carga de la UI a entradas validas del sidecar (allowlist estricto).

    Acepta una lista o {"keywords": [...]}. Cada entrada valida es {palabra|frase[, intensidad]}.
    Multi-palabra -> `frase` (span, #34); una palabra -> `palabra`. intensidad solo 'big'.
    """
    if isinstance(data, dict):
        data = data.get("keywords", [])
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for e in data:
        if not isinstance(e, dict):
            continue
        texto = e.get("frase") or e.get("palabra")
        if not isinstance(texto, str) or not texto.strip():
            continue
        # Corchetes de marca cruda -> espacio (no pegar palabras); luego colapsa espacios.
        limpio = " ".join(texto.replace("[", " ").replace("]", " ").split())
        if not limpio:
            continue
        entrada: dict = {"frase": limpio} if len(limpio.split()) > 1 else {"palabra": limpio}
        if str(e.get("intensidad") or "").lower() in _INTENSIDADES_OK:
            entrada["intensidad"] = "big"
        out.append(entrada)
        if len(out) >= _MAX_ENTRADAS:
            break
    return out


def read_entries(path: Path) -> list[dict]:
    """Lee y sanea el sidecar existente para prellenar la UI. Ausente/roto -> []."""
    if not path or not Path(path).exists():
        return []
    try:
        return sanitize_entries(json.loads(Path(path).read_text(encoding="utf-8")))
    except (ValueError, OSError):
        return []


def write_entries(path: Path, entries: list[dict]) -> None:
    """Escribe el sidecar de forma atomica (tmp + os.replace). Lista vacia -> borra el sidecar."""
    path = Path(path)
    if not entries:
        if path.exists():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"keywords": entries}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
