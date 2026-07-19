"""studio_srt_routes.py — Router HTTP del contrato SRT de Studio (S36-C1, D37).

Capa HTTP delgada: traduce errores tipados de `studio_srt` a status HTTP, recibe el
UploadFile y delega TODA la logica de validacion/almacenamiento/asociacion al modulo
de dominio. No duplica parser ni validador. No inicia jobs, ni render, ni Whisper, ni
Auto. El almacenamiento privado (transcripts/studio_srt/) NUNCA se monta ni se sirve.

Los directorios son globals del modulo para que los tests los reapunten a tmp_path.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

import studio_srt

ROOT = Path(__file__).parent
INPUT_DIR = ROOT / "input"
TRANSCRIPTS = ROOT / "transcripts"
STUDIO_SRT_DIR = TRANSCRIPTS / "studio_srt"

router = APIRouter()

# Mapa de error tipado -> status HTTP. 500 se reserva para fallo de almacenamiento.
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
    video = studio_srt.resolver_video_input(name, INPUT_DIR)
    if video is None:
        raise HTTPException(404, f"Video {name} no encontrado en input/")
    return video


def _duracion_ms(video_path: Path, name: str) -> int:
    """Duracion real del video en ms. Usa el info.json cacheado; si falta, ffprobe via core."""
    info_file = TRANSCRIPTS / f"{name}_info.json"
    info: dict = {}
    if info_file.is_file():
        try:
            info = json.loads(info_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            info = {}
    if not info:
        import core  # noqa: PLC0415  (import diferido: evita costo de ffprobe en tests offline)

        info = core.get_video_info(video_path)
    return int(round(float(info.get("duration", 0.0)) * 1000))


@router.get("/api/srt/capabilities")
def srt_capabilities() -> dict:
    """Capacidades seguras del contrato SRT; solo estado local, sin red ni modelos."""
    return studio_srt.capabilities()


@router.get("/api/videos/{name}/srt")
def get_video_srt(name: str) -> dict:
    """Estado de la seleccion SRT del video (manifiesto publico saneado o estado `none`)."""
    _resolver_video(name)
    return studio_srt.read_selection(name, TRANSCRIPTS)


@router.post("/api/videos/{name}/srt")
async def post_video_srt(name: str, file: UploadFile = File(...)):
    """Asocia un SRT validado al video. 200 si es idempotente, 201 si es nueva seleccion."""
    video = _resolver_video(name)
    try:
        studio_srt.validate_srt_filename(file.filename)
        # Rechazo temprano por tamano si el cliente declara file.size, para no leer el cuerpo
        # completo en memoria; parse_and_validate reaplica el mismo limite duro sobre los bytes.
        if file.size is not None and file.size > studio_srt.MAX_SRT_BYTES:
            raise studio_srt.StudioSrtTooLarge("el SRT excede el limite de bytes")
        data = await file.read()
        duration_ms = _duracion_ms(video, name)
        document, diagnostics = studio_srt.parse_and_validate(
            data, source_name=file.filename, video_duration_ms=duration_ms
        )
        manifest, created = studio_srt.store_and_associate(
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
