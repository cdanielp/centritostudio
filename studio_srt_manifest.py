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

import unicodedata
from pathlib import Path, PureWindowsPath

import srt_types
from srt_types import SrtDiagnostic, SrtDocument

MANIFEST_VERSION = 1
_ALLOWED_SEVERITY = frozenset({"warning", "error"})
_HEX = frozenset("0123456789abcdef")

# Encodings que el parser (S36-A) puede emitir en `document.encoding`. Allowlist estricta.
_ALLOWED_ENCODINGS = frozenset({"utf-8", "windows-1252"})

# Extensiones de video validas (case-insensitive). Misma politica que resolver_video_input.
_ALLOWED_VIDEO_EXT = frozenset({".mp4", ".mov"})

# Codigos de diagnostico validos: todos los ERR_*/WARN_* declarados por S36-A (en sync).
_KNOWN_CODES = frozenset(
    value
    for name in dir(srt_types)
    if name.startswith(("ERR_", "WARN_")) and isinstance((value := getattr(srt_types, name)), str)
)


# ─── Helpers de seguridad ──────────────────────────────────────────────────────
def _has_control(text: str) -> bool:
    """True si text contiene algun caracter de control Unicode (categoria Cc).

    Cubre C0 (U+0000-U+001F), DEL (U+007F) y C1 (U+0080-U+009F). No rechaza letras
    acentuadas (Ll/Lu), emojis (So) ni espacios normales (Zs).
    """
    return any(unicodedata.category(c) == "Cc" for c in text)


def is_safe_basename(name: object) -> bool:
    """True solo si name es un basename puro: str no vacio, sin ruta y sin caracteres de control."""
    return (
        isinstance(name, str)
        and name != ""
        and not _has_control(name)
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


def _int_at_least(value: object, minimum: int) -> int:
    """Entero estricto con cota inferior semantica. Lanza ValueError si viola."""
    result = _as_int(value)
    if result < minimum:
        raise ValueError("entero fuera de rango")
    return result


def _opt_int_at_least(value: object, minimum: int) -> int | None:
    """None o entero estricto >= minimum."""
    if value is None:
        return None
    return _int_at_least(value, minimum)


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
    # Rango REAL del SRT: los cues pueden venir fuera de orden (warning time_not_monotonic no
    # aborta), asi que el primer/ultimo cue no marcan el rango. min/max sobre TODOS los cues
    # garantiza start <= end. El `else 0` es defensivo: parse_and_validate ya rechaza 0 cues,
    # pero build_manifest es puro y min([]) reventaria.
    start = min(c.start_ms for c in cues) if cues else 0
    end = max(c.end_ms for c in cues) if cues else 0
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
# INVARIANTE: las cotas semanticas de abajo (cue_index>=1, n_errors==0, start/end validos)
# se apoyan en que studio_srt.parse_and_validate ABORTA ante cualquier diagnostico `error`
# (indice<=0, start<0, end<=start, sin cues). Si esa politica se relajara, revisar estas cotas.
def _clean_diagnostic(d: object) -> dict:
    """Reconstruye un diagnostico con solo las 4 claves aprobadas. Lanza ValueError si viola.

    `code` debe ser uno de los codigos conocidos de S36-A; `severity` de la allowlist;
    `cue_position` (0-based) >= 0 o None; `cue_index` (indice SRT positivo) >= 1 o None.
    """
    if not isinstance(d, dict):
        raise ValueError("diagnostico no es objeto")
    code = d.get("code")
    severity = d.get("severity")
    if code not in _KNOWN_CODES or severity not in _ALLOWED_SEVERITY:
        raise ValueError("diagnostico invalido")
    return {
        "code": code,
        "severity": severity,
        "cue_position": _opt_int_at_least(d.get("cue_position"), 0),
        "cue_index": _opt_int_at_least(d.get("cue_index"), 1),
    }


def _clean_video(video: object, video_stem: str) -> dict:
    """Reconstruye el bloque video validado. Lanza ValueError si viola el contrato.

    `filename` debe ser un basename seguro (sin ruta ni control), con extension .mp4/.mov
    (case-insensitive) y stem identico al video real. `duration_ms` debe ser int estricto > 0
    (el endpoint solo asocia tras determinar una duracion real valida; nunca None ni 0).
    """
    if not isinstance(video, dict) or video.get("name") != video_stem:
        raise ValueError("video no coincide")
    filename = video.get("filename")
    if not is_safe_basename(filename):
        raise ValueError("filename invalido")
    name_path = Path(filename)
    if name_path.suffix.lower() not in _ALLOWED_VIDEO_EXT:
        raise ValueError("extension de video invalida")
    if name_path.stem != video_stem:
        raise ValueError("filename no corresponde al video")
    return {
        "name": video_stem,
        "filename": filename,
        "duration_ms": _int_at_least(video.get("duration_ms"), 1),
    }


def _clean_selection(selection: object) -> dict:
    """Reconstruye el bloque selection validado. Lanza ValueError si viola el contrato.

    `encoding` debe pertenecer a la allowlist de encodings que el parser puede emitir.
    """
    if not isinstance(selection, dict) or selection.get("selected") is not True:
        raise ValueError("seleccion invalida")
    source_name = selection.get("source_name")
    managed_file = selection.get("managed_file")
    source_sha256 = selection.get("source_sha256")
    encoding = selection.get("encoding")
    if not is_sha256(source_sha256):
        raise ValueError("sha256 invalido")
    # El archivo administrado se nombra SIEMPRE por su hash completo: no se acepta ningun
    # otro basename aunque sea seguro. `{sha}.srt` con sha 64-hex ya es un basename puro.
    if managed_file != f"{source_sha256}.srt":
        raise ValueError("managed_file no coincide con el sha")
    if source_name is not None and not is_safe_basename(source_name):
        raise ValueError("source_name inseguro")
    if encoding not in _ALLOWED_ENCODINGS:
        raise ValueError("encoding no permitido")
    return {
        "selected": True,
        "source_name": source_name,
        "managed_file": managed_file,
        "source_sha256": source_sha256,
        "encoding": encoding,
    }


def _clean_summary(summary: object) -> dict:
    """Valida los numeros del summary con semantica: no negativos, end>start, sin errores.

    Un manifiesto `ready` siempre tiene n_errors == 0 (los errores abortan la asociacion).
    """
    if not isinstance(summary, dict):
        raise ValueError("summary invalido")
    n_cues = _int_at_least(summary.get("n_cues"), 1)
    start_ms = _int_at_least(summary.get("start_ms"), 0)
    end_ms = _int_at_least(summary.get("end_ms"), start_ms + 1)  # rango real: end > start
    n_errors = _int_at_least(summary.get("n_errors"), 0)
    n_warnings = _int_at_least(summary.get("n_warnings"), 0)
    if n_errors != 0:
        raise ValueError("un manifiesto ready no puede tener errores")
    return {
        "n_cues": n_cues,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "n_errors": n_errors,
        "n_warnings": n_warnings,
    }


def sanitize_manifest(raw: object, video_stem: str) -> dict:
    """Reconstruye el manifiesto publico por whitelist y valida el contrato v1.

    Nunca devuelve campos extra del archivo. Si algo viola el contrato (version, status,
    nombre de video, basenames, sha256, encoding, codigos, numeros semanticos), lanza
    ValueError sin filtrar contenido.
    """
    try:
        if not isinstance(raw, dict) or raw.get("version") != MANIFEST_VERSION:
            raise ValueError("version invalida")
        if raw.get("status") != "ready":
            raise ValueError("status invalido")
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
