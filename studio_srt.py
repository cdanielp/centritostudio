r"""studio_srt.py — Logica pura de asociacion video<->SRT para Studio (S36-C1, D37).

Capa de DOMINIO: sin FastAPI, sin HTML, sin render, sin Auto, sin jobs. Reutiliza
exclusivamente la fachada `srt_import` (S36-A) para parsear y validar; aqui solo se
confina el video, se almacena el SRT de forma privada y se administra la asociacion
(un SRT seleccionado por video) mediante un manifiesto v1 saneado.

Reglas duras:
- Tiempos SIEMPRE en milisegundos enteros.
- Escrituras atomicas: archivo temporal + fsync + os.replace; nunca queda `.tmp`.
- El manifiesto NUNCA incluye texto de cues, rutas absolutas ni tracebacks.
- `managed_file` es siempre un basename (sin `/` ni `\`).
- Los bytes originales del usuario se guardan tal cual; el sha256 es sobre esos bytes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path, PureWindowsPath

from srt_import import (
    SrtDecodeError,
    SrtError,
    SrtLimitError,
    parse_srt_bytes,
    validate_srt,
)
from srt_types import MAX_CUES, MAX_SRT_BYTES, SrtDiagnostic, SrtDocument

MANIFEST_VERSION = 1
MANAGED_SHA_LEN = 12
SELECTION_SUFFIX = "_srt_selection.json"


# ─── Errores tipados (errores de USUARIO/almacenamiento, no bugs) ──────────────
class StudioSrtError(Exception):
    """Base de errores del administrador de SRT de Studio."""


class StudioSrtNotFound(StudioSrtError):
    """El video referenciado no existe o no es un basename confinado en input/."""


class StudioSrtInvalid(StudioSrtError):
    """El SRT es invalido (malformado, sin cues utilizables o con errores estructurales)."""


class StudioSrtTooLarge(StudioSrtError):
    """El SRT excede el limite de bytes o de cues."""


class StudioSrtUnsupported(StudioSrtError):
    """Nombre de archivo vacio, con ruta o con extension distinta de .srt."""


class StudioSrtStorageError(StudioSrtError):
    """Fallo inesperado de almacenamiento; la seleccion previa permanece intacta."""


# ─── Confinamiento del video ───────────────────────────────────────────────────
def resolver_video_input(name: str, input_dir: Path) -> Path | None:
    """Basename confinado en input_dir (.mp4 primero, luego .mov). Sin traversal.

    Misma politica que el resolver historico de Studio: rechaza rutas POSIX y Windows,
    drive letters, UNC, `..` y cualquier candidato que escape de input/ tras resolve().
    """
    if not name or Path(name).name != name or PureWindowsPath(name).name != name:
        return None
    root = Path(input_dir).resolve()
    for ext in (".mp4", ".mov", ".MP4", ".MOV"):
        candidate = (root / f"{name}{ext}").resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        if candidate.is_file():
            return candidate
    return None


# ─── Validacion del nombre del SRT subido ──────────────────────────────────────
def validate_srt_filename(filename: str | None) -> None:
    """Exige un basename .srt (case-insensitive). La extension y el parser son la autoridad."""
    if not filename:
        raise StudioSrtUnsupported("nombre de archivo vacio")
    if Path(filename).name != filename or PureWindowsPath(filename).name != filename:
        raise StudioSrtUnsupported("el nombre debe ser un basename sin ruta")
    if not filename.lower().endswith(".srt"):
        raise StudioSrtUnsupported("extension no soportada (se espera .srt)")


# ─── Parseo + validacion contra el video ───────────────────────────────────────
def parse_and_validate(
    data: bytes, *, source_name: str, video_duration_ms: int | None
) -> tuple[SrtDocument, tuple[SrtDiagnostic, ...]]:
    """Parsea (tolerante) y valida contra la duracion real. Warnings no abortan; errors si.

    Devuelve (documento, diagnosticos_combinados). Combina los diagnosticos del parser
    (decode, bloques descartados) con los de la revalidacion independiente (cross-cue y
    contra el video). Aborta con error tipado si hay errores o no quedan cues utilizables.
    """
    if len(data) > MAX_SRT_BYTES:
        raise StudioSrtTooLarge(f"el SRT excede el limite de {MAX_SRT_BYTES} bytes")
    try:
        document = parse_srt_bytes(data, source_name=source_name, encoding="auto", strict=False)
    except SrtLimitError:
        raise StudioSrtTooLarge("el SRT excede los limites de tamano/cues") from None
    except SrtDecodeError:
        raise StudioSrtInvalid("no se pudo decodificar el SRT") from None
    except SrtError:
        raise StudioSrtInvalid("SRT malformado") from None

    validation = validate_srt(document, video_duration_ms=video_duration_ms)
    diagnostics = tuple(document.diagnostics) + tuple(validation)
    if not document.cues:
        raise StudioSrtInvalid("el SRT no contiene cues utilizables")
    if any(d.severity == "error" for d in diagnostics):
        raise StudioSrtInvalid("el SRT contiene errores estructurales")
    return document, diagnostics


# ─── Manifiesto v1 (saneado; sirve tanto para almacenar como para responder) ───
def _basename(name: str | None) -> str | None:
    if not name:
        return None
    return PureWindowsPath(name).name


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


# ─── Escritura atomica ─────────────────────────────────────────────────────────
def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path = Path(path)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def _atomic_write_json(path: Path, obj: dict) -> None:
    path = Path(path)
    payload = json.dumps(obj, ensure_ascii=False, indent=2)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def _read_manifest(path: Path) -> dict | None:
    path = Path(path)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _manifest_path(manifest_dir: Path, video_stem: str) -> Path:
    return Path(manifest_dir) / f"{video_stem}{SELECTION_SUFFIX}"


# ─── Asociacion (un SRT seleccionado por video) ────────────────────────────────
def store_and_associate(
    document: SrtDocument,
    diagnostics: tuple[SrtDiagnostic, ...],
    *,
    video_stem: str,
    video_filename: str,
    video_duration_ms: int | None,
    data: bytes,
    storage_root: Path,
    manifest_dir: Path,
) -> tuple[dict, bool]:
    """Almacena el SRT por hash y actualiza la asociacion. Devuelve (manifiesto, creado).

    Idempotente: mismo video + mismo sha256 ya seleccionado -> no reescribe, creado=False.
    Reemplazo: nuevo sha -> escribe el nuevo archivo administrado y solo entonces promueve
    el manifiesto; la seleccion previa nunca se borra. Orden: archivo administrado primero,
    manifiesto al final, para que un fallo tardio conserve la seleccion previa.
    """
    sha = document.source_sha256
    managed_name = f"{sha[:MANAGED_SHA_LEN]}.srt"
    manifest_path = _manifest_path(manifest_dir, video_stem)

    existing = _read_manifest(manifest_path)
    if (
        existing
        and existing.get("selection", {}).get("selected")
        and existing.get("selection", {}).get("source_sha256") == sha
    ):
        return existing, False

    manifest = build_manifest(
        video_stem=video_stem,
        video_filename=video_filename,
        video_duration_ms=video_duration_ms,
        document=document,
        diagnostics=diagnostics,
        managed_name=managed_name,
    )
    video_dir = Path(storage_root) / video_stem
    managed_path = video_dir / managed_name
    try:
        video_dir.mkdir(parents=True, exist_ok=True)
        if not managed_path.is_file():
            _atomic_write_bytes(managed_path, data)
        _atomic_write_json(manifest_path, manifest)
    except OSError:
        raise StudioSrtStorageError("no se pudo almacenar la seleccion SRT") from None
    return manifest, True


def read_selection(video_stem: str, manifest_dir: Path) -> dict:
    """Manifiesto publico saneado del video, o estado `none` si no hay seleccion activa."""
    data = _read_manifest(_manifest_path(manifest_dir, video_stem))
    if not data or not data.get("selection", {}).get("selected"):
        return empty_selection(video_stem)
    return data


def disassociate(video_stem: str, manifest_dir: Path) -> dict:
    """Desasocia la seleccion (idempotente). No borra archivos administrados ni el original."""
    manifest_path = _manifest_path(manifest_dir, video_stem)
    try:
        manifest_path.unlink(missing_ok=True)
    except OSError:
        raise StudioSrtStorageError("no se pudo desasociar la seleccion SRT") from None
    # Contrato DELETE: respuesta minima sin `version` (a diferencia del GET sin seleccion).
    return {"video": {"name": video_stem}, "selection": {"selected": False}, "status": "none"}


# ─── Capacidades (estatico; sin red, sin modelos, sin paths) ───────────────────
def capabilities() -> dict:
    """Capacidades seguras del contrato SRT de Studio para S36-C1."""
    return {
        "version": MANIFEST_VERSION,
        "extensions": [".srt"],
        "max_bytes": MAX_SRT_BYTES,
        "max_cues": MAX_CUES,
        "association": "one_selected_per_video",
        "batch": False,
        "auto_v2": False,
        "render": False,
        "editing": False,
    }
