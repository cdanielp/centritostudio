r"""studio_srt.py — Logica pura de asociacion video<->SRT para Studio (S36-C1, D37).

Capa de DOMINIO: sin FastAPI, sin HTML, sin render, sin Auto, sin jobs. Reutiliza
exclusivamente la fachada `srt_import` (S36-A) para parsear y validar; aqui solo se
confina el video, se almacena el SRT de forma privada y se administra la asociacion
(un SRT seleccionado por video). La construccion/saneamiento del manifiesto v1 vive en
`studio_srt_manifest` (whitelist); este modulo orquesta storage, integridad y atomicidad.

Reglas duras (endurecidas en la 2a pasada de S36-C1):
- Tiempos SIEMPRE en milisegundos enteros.
- Escrituras atomicas: temporal UNICO por operacion (mkstemp en el mismo dir) + fsync +
  os.replace; nunca queda `.tmp` ni se comparte temporal entre threads.
- El archivo administrado se nombra por el SHA256 COMPLETO ({sha}.srt): sin colisiones de
  prefijo; su hash real SIEMPRE coincide con `source_sha256` del manifiesto.
- La idempotencia verifica el storage: mismo SHA solo evita reescribir si el archivo existe,
  es regular, esta dentro del dir del video y sus bytes coinciden; si no, se REPARA.
- El manifiesto se RECONSTRUYE por whitelist al leerse (studio_srt_manifest.sanitize_manifest).
- Los bytes originales del usuario se guardan tal cual; el sha256 es sobre esos bytes.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path, PureWindowsPath

import studio_srt_manifest as manifest_mod
from srt_import import (
    SrtDecodeError,
    SrtError,
    SrtLimitError,
    parse_srt_bytes,
    validate_srt,
)
from srt_types import MAX_CUES, MAX_SRT_BYTES, SrtDiagnostic, SrtDocument
from studio_srt_manifest import MANIFEST_VERSION, build_manifest, empty_selection

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
    """Fallo de almacenamiento/integridad; la seleccion previa permanece intacta."""


# ─── Confinamiento del video ───────────────────────────────────────────────────
def resolver_video_input(name: str, input_dir: Path) -> Path | None:
    """Basename confinado en input_dir (.mp4 primero, luego .mov). Sin traversal.

    Misma politica que el resolver historico de Studio: rechaza rutas POSIX y Windows,
    drive letters, UNC, NUL/control, `..` y cualquier candidato que escape de input/.
    """
    if not name or "\x00" in name or Path(name).name != name or PureWindowsPath(name).name != name:
        return None
    root = Path(input_dir).resolve()
    for ext in (".mp4", ".mov", ".MP4", ".MOV"):
        try:
            candidate = (root / f"{name}{ext}").resolve()
            candidate.relative_to(root)
            if candidate.is_file():
                return candidate
        except (OSError, ValueError):
            # ValueError: escape de root o caracter invalido en la ruta; OSError: stat fallido.
            continue
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


# ─── Escritura atomica con temporal UNICO por operacion ────────────────────────
def _replace_with_retry(tmp: Path, path: Path, attempts: int = 6) -> None:
    """os.replace con reintento acotado ante PermissionError transitorio de Windows.

    Bajo escritura concurrente al mismo destino, MoveFileEx puede fallar con WinError 5;
    el resultado sigue siendo last-writer-wins con archivos completos (nunca parciales).
    """
    for i in range(attempts):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(0.005 * (i + 1))


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path = Path(path)
    fd, tmpname = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmpname)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        _replace_with_retry(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def _atomic_write_json(path: Path, obj: dict) -> None:
    path = Path(path)
    payload = json.dumps(obj, ensure_ascii=False, indent=2)
    fd, tmpname = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmpname)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        _replace_with_retry(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def _read_manifest(path: Path) -> dict | None:
    """Lectura tolerante (para la ruta de escritura): None si falta o es JSON ilegible."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _manifest_path(manifest_dir: Path, video_stem: str) -> Path:
    return Path(manifest_dir) / f"{video_stem}{SELECTION_SUFFIX}"


# ─── Integridad del archivo administrado ───────────────────────────────────────
def _managed_file_ok(
    video_dir: Path, managed_name: object, expected_sha: str, expected_data: bytes
) -> bool:
    """True solo si el archivo administrado existe, es regular, esta confinado y su hash y
    bytes coinciden con lo validado. Un basename inseguro o cualquier discrepancia -> False."""
    if not manifest_mod.is_safe_basename(managed_name):
        return False
    video_dir = Path(video_dir)
    managed_path = video_dir / managed_name
    try:
        managed_path.resolve().relative_to(video_dir.resolve())
    except ValueError:
        return False
    if not managed_path.is_file():
        return False
    try:
        actual = managed_path.read_bytes()
    except OSError:
        return False
    if not actual or hashlib.sha256(actual).hexdigest() != expected_sha:
        return False
    return actual == expected_data


def _selection_matches(existing: dict, sha: str) -> bool:
    selection = existing.get("selection", {})
    return bool(selection.get("selected")) and selection.get("source_sha256") == sha


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
) -> tuple[dict, bool, bool]:
    """Almacena el SRT por hash completo y actualiza la asociacion.

    Devuelve (manifiesto, creado, reparado):
    - creado=True  -> nueva seleccion o reemplazo (HTTP 201).
    - creado=False, reparado=False -> idempotente: mismo SHA, storage integro (HTTP 200).
    - creado=False, reparado=True  -> mismo SHA pero storage roto/incompleto: se reconstruye
      atomicamente y se regenera el manifiesto (HTTP 200; el contenido seleccionado no cambio).

    El archivo administrado se escribe primero y el manifiesto al final, para que un fallo
    tardio conserve la seleccion previa. La seleccion anterior nunca se borra.
    """
    sha = document.source_sha256
    managed_name = f"{sha}.srt"
    manifest_path = _manifest_path(manifest_dir, video_stem)
    video_dir = Path(storage_root) / video_stem
    managed_path = video_dir / managed_name

    existing = _read_manifest(manifest_path)
    same_selection = bool(existing) and _selection_matches(existing, sha)
    if same_selection and _managed_file_ok(
        video_dir, existing.get("selection", {}).get("managed_file"), sha, data
    ):
        try:
            return manifest_mod.sanitize_manifest(existing, video_stem), False, False
        except ValueError:
            pass  # manifiesto viola el contrato -> reparar abajo (same_selection sigue True)

    repaired = same_selection
    new_manifest = build_manifest(
        video_stem=video_stem,
        video_filename=video_filename,
        video_duration_ms=video_duration_ms,
        document=document,
        diagnostics=diagnostics,
        managed_name=managed_name,
    )
    try:
        video_dir.mkdir(parents=True, exist_ok=True)
        if not _managed_file_ok(video_dir, managed_name, sha, data):
            _atomic_write_bytes(managed_path, data)
        _atomic_write_json(manifest_path, new_manifest)
    except OSError:
        raise StudioSrtStorageError("no se pudo almacenar la seleccion SRT") from None
    return new_manifest, (not repaired), repaired


def read_selection(video_stem: str, manifest_dir: Path) -> dict:
    """Manifiesto publico saneado del video, o estado `none` si no hay seleccion activa.

    Si el manifiesto existe y esta seleccionado pero es ilegible o viola el contrato v1,
    lanza StudioSrtStorageError (el router responde 500 generico, sin filtrar contenido).
    """
    path = _manifest_path(manifest_dir, video_stem)
    if not path.is_file():
        return empty_selection(video_stem)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise StudioSrtStorageError("manifiesto SRT ilegible") from None
    if not isinstance(raw, dict) or raw.get("selection", {}).get("selected") is not True:
        return empty_selection(video_stem)
    try:
        return manifest_mod.sanitize_manifest(raw, video_stem)
    except ValueError:
        raise StudioSrtStorageError("manifiesto SRT invalido") from None


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
