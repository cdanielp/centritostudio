"""studio_srt_routes.py — Router HTTP del contrato SRT de Studio (S36-C1, D37).

Capa HTTP delgada: traduce errores tipados de `studio_srt` a status HTTP, recibe el
UploadFile y delega TODA la logica de validacion/almacenamiento/asociacion al modulo
de dominio. No duplica parser ni validador. No inicia jobs, ni render, ni Whisper, ni
Auto. El almacenamiento privado (transcripts/studio_srt/) NUNCA se monta ni se sirve.

Endurecido (2a pasada): la subida se lee acotada por chunks (limite duro aun sin
file.size); la duracion solo reutiliza el cache si es reciente y numericamente valida;
los mensajes de error nunca reflejan el `name` del usuario.

Los directorios son globals del modulo para que los tests los reapunten a tmp_path.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

import studio_srt

ROOT = Path(__file__).parent
INPUT_DIR = ROOT / "input"
TRANSCRIPTS = ROOT / "transcripts"
STUDIO_SRT_DIR = TRANSCRIPTS / "studio_srt"

_UPLOAD_CHUNK = 1 << 16  # 64 KiB por lectura; no se lee el cuerpo completo de una sola vez

router = APIRouter()

# Mapa de error tipado -> status HTTP. 500 se reserva para fallo de almacenamiento/integridad.
_STATUS = {
    studio_srt.StudioSrtNotFound: 404,
    studio_srt.StudioSrtUnsupported: 415,
    studio_srt.StudioSrtTooLarge: 413,
    studio_srt.StudioSrtInvalid: 400,
    studio_srt.StudioSrtStorageError: 500,
}


def _http_from(exc: studio_srt.StudioSrtError) -> HTTPException:
    """Traduce un error de dominio a HTTPException saneada (sin rutas ni texto privado)."""
    return HTTPException(_STATUS.get(type(exc), 500), str(exc))


def _resolver_video(name: str) -> Path:
    """Resuelve el video confinado. El mensaje NO refleja `name` (puede traer traversal/control)."""
    video = studio_srt.resolver_video_input(name, INPUT_DIR)
    if video is None:
        raise HTTPException(404, "Video no encontrado en input.")
    return video


async def _read_upload_limited(file: UploadFile, max_bytes: int) -> bytes:
    """Lee el UploadFile por chunks con limite DURO. No confia en file.size (solo rechazo temprano).

    Acepta exactamente max_bytes; rechaza max_bytes+1 con StudioSrtTooLarge antes de parsear.
    """
    size = getattr(file, "size", None)
    if isinstance(size, int) and size > max_bytes:
        raise studio_srt.StudioSrtTooLarge("el SRT excede el limite de bytes")
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_UPLOAD_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise studio_srt.StudioSrtTooLarge("el SRT excede el limite de bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def _finite_positive(value: object) -> float | None:
    """Devuelve float>0 finito, o None (rechaza bool, no-numeros, NaN/Infinity y <=0)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return float(value)


def _cached_duration_s(video_path: Path, name: str) -> float | None:
    """Duracion (s) del cache {name}_info.json solo si es reciente (mtime>=video) y valida."""
    info_file = TRANSCRIPTS / f"{name}_info.json"
    try:
        if not info_file.is_file():
            return None
        if info_file.stat().st_mtime < Path(video_path).stat().st_mtime:
            return None  # cache anterior al video -> pertenece a otra version
        info = json.loads(info_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(info, dict):
        return None
    return _finite_positive(info.get("duration"))


def _duracion_ms(video_path: Path, name: str) -> int:
    """Duracion real del video en ms. Usa cache reciente/valido; si no, ffprobe via core.

    Nunca valida el SRT con duration=0: si no hay una duracion finita y positiva, lanza
    StudioSrtStorageError (el router responde 500 generico, sin filtrar rutas).
    """
    dur_s = _cached_duration_s(video_path, name)
    if dur_s is None:
        import core  # noqa: PLC0415  (import diferido: evita costo de ffprobe en tests offline)

        try:
            info = core.get_video_info(video_path)
        except Exception:  # noqa: BLE001  (fallo de ffprobe -> respuesta generica, sin ruta)
            raise studio_srt.StudioSrtStorageError(
                "no se pudo determinar la duracion del video"
            ) from None
        dur_s = _finite_positive(info.get("duration") if isinstance(info, dict) else None)
    if dur_s is None:
        raise studio_srt.StudioSrtStorageError("duracion de video no disponible")
    return int(round(dur_s * 1000))


@router.get("/api/srt/capabilities")
def srt_capabilities() -> dict:
    """Capacidades seguras del contrato SRT; solo estado local, sin red ni modelos."""
    return studio_srt.capabilities()


@router.get("/api/videos/{name}/srt")
def get_video_srt(name: str) -> dict:
    """Estado de la seleccion SRT del video (manifiesto publico saneado o estado `none`)."""
    _resolver_video(name)
    try:
        return studio_srt.read_selection(name, TRANSCRIPTS)
    except studio_srt.StudioSrtError as exc:
        raise _http_from(exc) from None


@router.post("/api/videos/{name}/srt")
async def post_video_srt(name: str, file: UploadFile = File(...)):
    """Asocia un SRT validado al video. 200 si es idempotente/reparado, 201 si es nuevo."""
    video = _resolver_video(name)
    try:
        studio_srt.validate_srt_filename(file.filename)
        data = await _read_upload_limited(file, studio_srt.MAX_SRT_BYTES)
        duration_ms = _duracion_ms(video, name)
        document, diagnostics = studio_srt.parse_and_validate(
            data, source_name=file.filename, video_duration_ms=duration_ms
        )
        manifest, created, _repaired = studio_srt.store_and_associate(
            document,
            diagnostics,
            video_stem=name,
            video_filename=video.name,
            video_duration_ms=duration_ms,
            data=data,
            storage_root=STUDIO_SRT_DIR,
            manifest_dir=TRANSCRIPTS,
        )
    except studio_srt.StudioSrtError as exc:
        raise _http_from(exc) from None
    return _json_response(manifest, 201 if created else 200)


@router.delete("/api/videos/{name}/srt")
def delete_video_srt(name: str) -> dict:
    """Desasocia la seleccion SRT (idempotente). No borra archivos administrados."""
    _resolver_video(name)
    try:
        return studio_srt.disassociate(name, TRANSCRIPTS)
    except studio_srt.StudioSrtError as exc:
        raise _http_from(exc) from None


def _json_response(payload: dict, status_code: int):
    from fastapi.responses import JSONResponse  # noqa: PLC0415

    return JSONResponse(content=payload, status_code=status_code)
