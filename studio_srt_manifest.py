r"""studio_srt_manifest.py — Manifiesto v1 del contrato SRT de Studio (S36-C1, D37).

Capa PURA de construccion y SANEAMIENTO del manifiesto de asociacion video<->SRT.
Separada de `studio_srt` para mantener cada modulo bajo el limite de tamano del proyecto.

- `build_manifest` arma el manifiesto v1 saneado a partir del documento validado.
- `sanitize_manifest` reconstruye por WHITELIST cualquier manifiesto leido de disco y valida
  el contrato v1; nunca devuelve campos extra del archivo. Ante cualquier violacion lanza
  `ValueError` (el llamador lo traduce a un error de almacenamiento sin filtrar contenido).
- Helpers de seguridad de basename / sha256 / entero estricto, reutilizados por el dominio.

Nunca incluye texto de cues, rutas absolutas ni tracebacks. Tiempos en ms enteros.
"""

from __future__ import annotations

from pathlib import Path, PureWindowsPath

from srt_types import SrtDiagnostic, SrtDocument

MANIFEST_VERSION = 1
_ALLOWED_SEVERITY = frozenset({"warning", "error"})
_HEX = frozenset("0123456789abcdef")


# ─── Helpers de seguridad ──────────────────────────────────────────────────────
def is_safe_basename(name: object) -> bool:
    """True solo si name es un basename puro (sin ruta, sin NUL, no vacio)."""
    return (
        isinstance(name, str)
        and name != ""
        and "\x00" not in name
        and Path(name).name == name
        and PureWindowsPath(name).name == name
    )


def is_sha256(value: object) -> bool:
    """True solo si value es exactamente 64 caracteres hex minusculos."""
    return isinstance(value, str) and len(value) == 64 and all(c in _HEX for c in value)


def _as_int(value: object) -> int:
    """Entero estricto (rechaza bool, float y str). Lanza ValueError si no es int limpio."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("se esperaba un entero")
    return value


def _basename(name: str | None) -> str | None:
    if not name:
        return None
    return PureWindowsPath(name).name


# ─── Construccion del manifiesto v1 ────────────────────────────────────────────
def build_manifest(
    *,
    video_stem: str,
    video_filename: str,
    video_duration_ms: int | None,
    document: SrtDocument,
    diagnostics: tuple[SrtDiagnostic, ...],
    managed_name: str,
) -> dict:
    """Manifiesto v1 saneado: sin texto de cues, sin rutas, sin `message` de diagnosticos."""
    cues = document.cues
    start = cues[0].start_ms if cues else 0
    end = cues[-1].end_ms if cues else 0
    return {
        "version": MANIFEST_VERSION,
        "video": {
            "name": video_stem,
            "filename": video_filename,
            "duration_ms": int(video_duration_ms) if video_duration_ms is not None else None,
        },
        "selection": {
            "selected": True,
            "source_name": _basename(document.source_name),
            "managed_file": managed_name,
            "source_sha256": document.source_sha256,
            "encoding": document.encoding,
        },
        "summary": {
            "n_cues": len(cues),
            "start_ms": start,
            "end_ms": end,
            "n_errors": sum(1 for d in diagnostics if d.severity == "error"),
            "n_warnings": sum(1 for d in diagnostics if d.severity == "warning"),
        },
        "diagnostics": [
            {
                "code": d.code,
                "severity": d.severity,
                "cue_position": d.cue_position,
                "cue_index": d.cue_index,
            }
            for d in diagnostics
        ],
        "status": "ready",
    }


def empty_selection(video_stem: str) -> dict:
    """Respuesta publica cuando no hay SRT seleccionado para el video."""
    return {
        "version": MANIFEST_VERSION,
        "video": {"name": video_stem},
        "selection": {"selected": False},
        "status": "none",
    }


# ─── Saneamiento por whitelist (reconstruccion + validacion del contrato v1) ───
def _clean_diagnostic(d: object) -> dict:
    """Reconstruye un diagnostico con solo las 4 claves aprobadas. Lanza ValueError si viola."""
    if not isinstance(d, dict):
        raise ValueError("diagnostico no es objeto")
    code = d.get("code")
    severity = d.get("severity")
    cue_position = d.get("cue_position")
    cue_index = d.get("cue_index")
    if not isinstance(code, str) or severity not in _ALLOWED_SEVERITY:
        raise ValueError("diagnostico invalido")
    for pos in (cue_position, cue_index):
        if pos is not None and (isinstance(pos, bool) or not isinstance(pos, int)):
            raise ValueError("posicion de cue invalida")
    return {
        "code": code,
        "severity": severity,
        "cue_position": cue_position,
        "cue_index": cue_index,
    }


def _clean_video(video: object, video_stem: str) -> dict:
    """Reconstruye el bloque video validado. Lanza ValueError si viola el contrato."""
    if not isinstance(video, dict) or video.get("name") != video_stem:
        raise ValueError("video no coincide")
    filename = video.get("filename")
    if not isinstance(filename, str) or not filename:
        raise ValueError("filename invalido")
    duration_ms = video.get("duration_ms")
    if duration_ms is not None:
        duration_ms = _as_int(duration_ms)
    return {"name": video_stem, "filename": filename, "duration_ms": duration_ms}


def _clean_selection(selection: object) -> dict:
    """Reconstruye el bloque selection validado. Lanza ValueError si viola el contrato."""
    if not isinstance(selection, dict) or selection.get("selected") is not True:
        raise ValueError("seleccion invalida")
    source_name = selection.get("source_name")
    managed_file = selection.get("managed_file")
    source_sha256 = selection.get("source_sha256")
    encoding = selection.get("encoding")
    if not is_safe_basename(managed_file):
        raise ValueError("managed_file inseguro")
    if source_name is not None and not is_safe_basename(source_name):
        raise ValueError("source_name inseguro")
    if not is_sha256(source_sha256):
        raise ValueError("sha256 invalido")
    if not isinstance(encoding, str) or not encoding:
        raise ValueError("encoding invalido")
    return {
        "selected": True,
        "source_name": source_name,
        "managed_file": managed_file,
        "source_sha256": source_sha256,
        "encoding": encoding,
    }


def _clean_summary(summary: object) -> dict:
    if not isinstance(summary, dict):
        raise ValueError("summary invalido")
    return {
        key: _as_int(summary.get(key))
        for key in ("n_cues", "start_ms", "end_ms", "n_errors", "n_warnings")
    }


def sanitize_manifest(raw: object, video_stem: str) -> dict:
    """Reconstruye el manifiesto publico por whitelist y valida el contrato v1.

    Nunca devuelve campos extra del archivo. Si algo viola el contrato (version, nombre de
    video, basenames, sha256, tipos), lanza ValueError sin filtrar contenido.
    """
    try:
        if not isinstance(raw, dict) or raw.get("version") != MANIFEST_VERSION:
            raise ValueError("version invalida")
        diagnostics = raw["diagnostics"]
        if not isinstance(diagnostics, list):
            raise ValueError("diagnostics invalido")
        return {
            "version": MANIFEST_VERSION,
            "video": _clean_video(raw["video"], video_stem),
            "selection": _clean_selection(raw["selection"]),
            "summary": _clean_summary(raw["summary"]),
            "diagnostics": [_clean_diagnostic(d) for d in diagnostics],
            "status": "ready",
        }
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ValueError("manifiesto SRT invalido") from None
