"""broll_video_stock.py - Fetcher de VIDEOS de stock (Pexels) para b-roll de clip (PR A).

Busca, descarga y cachea clips de Pexels. Modulo PURO respecto al pipeline: NO conecta con FFmpeg,
render, Popup/overlays, caption, cve_popups ni UI (eso es el PR B). Produce assets tipados
(`VideoStockAsset`) y archivos en cache. La seleccion determinista del video_file vive en
`broll_video_select`; los tipos/errores/cache/IO en `broll_video_stock_base` (split anti-spaghetti,
archivo <= 400 lineas). Este modulo re-exporta el contrato publico.

Endpoint oficial: GET https://api.pexels.com/v1/videos/search (verificado contra la doc de Pexels).
`size` (large|medium|small) es un FILTRO opcional; por defecto NO se envia (size=None) porque la
resolucion la decide el selector sobre los video_files, no el filtro de busqueda.

Seguridad (regla #9): PEXELS_API_KEY vive en el entorno y NUNCA se imprime, serializa ni aparece en
sidecars, errores o logs; el header Authorization jamas se logea. Cliente HTTP: `requests` (ya en
requirements.txt, mismo patron que broll_stock). Sin deps nuevas.
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import requests

import broll_video_stock_base as _base
from broll_video_select import seleccionar_variante_video  # re-export: seleccion determinista
from broll_video_stock_base import (  # re-export del contrato publico
    PROVIDER,
    BrollVideoError,
    PexelsVideoAuthError,
    PexelsVideoDescargaError,
    PexelsVideoDeshabilitado,
    PexelsVideoError,
    PexelsVideoHTTPError,
    PexelsVideoRateLimit,
    PexelsVideoRespuestaInvalida,
    PexelsVideoSinVariante,
    PexelsVideoTimeout,
    RateLimitInfo,
    SeleccionVideo,
    VideoBrollResult,
    VideoFileCandidate,
    VideoStockAsset,
    orientacion_de,
    verificar_mp4_ffprobe,
)

# re-exports del contrato publico usados por consumidores (smoke/evidencia/PR B)
__all__ = ["seleccionar_variante_video", "SeleccionVideo", "verificar_mp4_ffprobe"]

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

SEARCH_URL = "https://api.pexels.com/v1/videos/search"
TIMEOUT_S = 10  # timeout de busqueda
DOWNLOAD_TIMEOUT_S = 60  # timeout de descarga (los MP4 pesan mas que una imagen)
PER_PAGE_MIN = 1
PER_PAGE_MAX = 80  # tope admitido por la API de Pexels
CHUNK_BYTES = 1 << 16  # 64 KiB por chunk en el streaming de descarga
MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024  # tope de cordura: 100 MB por clip

ORIENTACIONES_VALIDAS = frozenset({"landscape", "portrait", "square"})
SIZES_VALIDOS = frozenset({"large", "medium", "small"})


# ── Configuracion / clave (nunca exponen el secreto) ──────────────────────────


def tiene_api_key() -> bool:
    """True si PEXELS_API_KEY esta configurada (sin revelar su valor)."""
    return bool(os.getenv("PEXELS_API_KEY", "").strip())


def _api_key() -> str:
    key = os.getenv("PEXELS_API_KEY", "").strip()
    if not key:
        raise PexelsVideoDeshabilitado(
            "PEXELS_API_KEY no configurada. Agregala a .env (ver .env.example) para usar b-roll."
        )
    return key


def _headers() -> dict:
    """Headers con Authorization. NUNCA logear este dict (contiene la key)."""
    return {"Authorization": _api_key()}


def estado_pexels_video() -> dict:
    """Estado del fetcher de video sin revelar secretos: {habilitado, motivo}."""
    if tiene_api_key():
        return {"habilitado": True, "motivo": "PEXELS_API_KEY presente"}
    return {"habilitado": False, "motivo": "PEXELS_API_KEY ausente"}


def _sanitizar(msg: str) -> str:
    """Red de seguridad: si el valor de la key se colara en un mensaje, se redacta a ***."""
    key = os.getenv("PEXELS_API_KEY", "").strip()
    if key and key in msg:
        msg = msg.replace(key, "***")
    return msg


# ── Parseo de la respuesta ─────────────────────────────────────────────────────


def _candidatos_de(video: dict) -> tuple[VideoFileCandidate, ...]:
    """Convierte video_files[] crudos en VideoFileCandidate (sin filtrar todavia)."""
    out: list[VideoFileCandidate] = []
    for vf in video.get("video_files") or []:
        if not isinstance(vf, dict):
            continue
        out.append(
            VideoFileCandidate(
                file_id=str(vf.get("id", "")),
                quality=str(vf.get("quality", "") or ""),
                file_type=str(vf.get("file_type", "") or ""),
                width=int(vf.get("width") or 0),
                height=int(vf.get("height") or 0),
                link=str(vf.get("link", "") or ""),
            )
        )
    return tuple(out)


def _asset_desde_video(video: dict, query: str) -> VideoStockAsset:
    """Convierte un objeto Video de Pexels en VideoStockAsset (candidato sin descargar)."""
    user = video.get("user")
    if not isinstance(user, dict):
        user = {}
    w = int(video.get("width") or 0)
    h = int(video.get("height") or 0)
    return VideoStockAsset(
        provider=PROVIDER,
        asset_id=str(video.get("id", "")),
        query=query,
        width=w,
        height=h,
        duration=int(video.get("duration") or 0),
        orientation=orientacion_de(w, h),
        source_url=str(video.get("url", "") or ""),
        author=str(user.get("name", "") or ""),
        author_url=str(user.get("url", "") or ""),
        preview_url=str(video.get("image", "") or ""),
        video_files=_candidatos_de(video),
    )


def _rate_limit_desde_headers(headers) -> RateLimitInfo | None:
    """Lee X-Ratelimit-* (solo en 2xx). None si no vino ninguno. Mismo formato que en imagenes."""

    def _int(nombre: str) -> int | None:
        val = headers.get(nombre)
        if val is not None and str(val).strip().lstrip("-").isdigit():
            return int(val)
        return None

    limit = _int("X-Ratelimit-Limit")
    remaining = _int("X-Ratelimit-Remaining")
    reset = _int("X-Ratelimit-Reset")
    if limit is None and remaining is None and reset is None:
        return None
    return RateLimitInfo(limit=limit, remaining=remaining, reset=reset)


# ── Busqueda ──────────────────────────────────────────────────────────────────


def _validar_params(query, orientation, size, locale, per_page, page):
    q = _base._normalizar_query(query)
    if not q:
        raise ValueError("query vacio: se requiere un termino de busqueda")
    if orientation is not None and orientation not in ORIENTACIONES_VALIDAS:
        raise ValueError(
            f"orientation invalida: {orientation!r} (usa landscape|portrait|square o None)"
        )
    if size is not None and size not in SIZES_VALIDOS:
        raise ValueError(f"size invalido: {size!r} (usa large|medium|small o None)")
    if locale is not None and not str(locale).strip():
        raise ValueError("locale vacio: usa un locale oficial (ej. es-ES) o None")
    per_page = max(PER_PAGE_MIN, min(PER_PAGE_MAX, int(per_page)))
    page = max(1, int(page))
    return q, per_page, page


def _http_buscar(q, orientation, size, locale, per_page, page):
    """Ejecuta el GET a Pexels y valida status/JSON. Devuelve (videos, rate)."""
    params = {"query": q, "per_page": per_page, "page": page}
    if orientation:
        params["orientation"] = orientation
    if size:  # por defecto size=None -> NO se envia; la resolucion la decide el selector
        params["size"] = size
    if locale:
        params["locale"] = locale
    try:
        resp = requests.get(SEARCH_URL, headers=_headers(), params=params, timeout=TIMEOUT_S)
    except requests.Timeout as e:
        raise PexelsVideoTimeout("Pexels no respondio a tiempo en la busqueda") from e
    except requests.RequestException as e:
        raise PexelsVideoRespuestaInvalida(f"error de red: {type(e).__name__}") from e

    if resp.status_code == 429:
        ra = resp.headers.get("Retry-After")
        retry_after = int(ra) if ra and str(ra).strip().isdigit() else None
        raise PexelsVideoRateLimit("Pexels rate limit (HTTP 429)", retry_after=retry_after)
    if resp.status_code in (401, 403):
        raise PexelsVideoAuthError(f"Pexels rechazo la key (HTTP {resp.status_code})")
    if not (200 <= resp.status_code < 300):
        raise PexelsVideoHTTPError(f"Pexels HTTP {resp.status_code}", status=resp.status_code)

    try:
        data = resp.json()
    except ValueError as e:
        raise PexelsVideoRespuestaInvalida("la respuesta de Pexels no es JSON valido") from e
    if not isinstance(data, dict) or not isinstance(data.get("videos"), list):
        raise PexelsVideoRespuestaInvalida("respuesta de Pexels sin lista 'videos'")

    videos = [v for v in data["videos"] if isinstance(v, dict)]
    return videos, _rate_limit_desde_headers(resp.headers)


def _buscar_con_rate(query, orientation, size, locale, per_page, page, usar_cache):
    q, per_page, page = _validar_params(query, orientation, size, locale, per_page, page)
    clave = _base._clave_cache_busqueda(q, orientation, size, locale, per_page, page)

    if usar_cache:
        cacheados = _base._leer_cache_busqueda(clave)
        if cacheados is not None:
            return [_asset_desde_video(v, q) for v in cacheados], None

    videos, rate = _http_buscar(q, orientation, size, locale, per_page, page)
    if usar_cache:
        _base._escribir_cache_busqueda(clave, videos)
    return [_asset_desde_video(v, q) for v in videos], rate


def buscar_videos_pexels(
    query: str,
    orientation: str | None = None,
    size: str | None = None,
    locale: str | None = "es-ES",
    per_page: int = 10,
    page: int = 1,
    usar_cache: bool = True,
) -> list[VideoStockAsset]:
    """Busca videos en Pexels. Capa HONESTA: lanza errores tipados (no fail-open).

    Por defecto size=None: la API no filtra por resolucion; la elige el selector. Cero resultados
    es exito valido (lista vacia). NO reintenta en 429. Fail-open: `buscar_video_broll_seguro`.
    """
    assets, _rate = _buscar_con_rate(query, orientation, size, locale, per_page, page, usar_cache)
    return assets


_CODIGO_ERROR = {
    PexelsVideoDeshabilitado: "deshabilitado",
    PexelsVideoRateLimit: "rate_limit",
    PexelsVideoAuthError: "auth",
    PexelsVideoTimeout: "timeout",
    PexelsVideoHTTPError: "http",
    PexelsVideoRespuestaInvalida: "respuesta_invalida",
    PexelsVideoSinVariante: "sin_variante",
    PexelsVideoDescargaError: "descarga",
}


def buscar_video_broll_seguro(
    query: str,
    orientation: str | None = None,
    size: str | None = None,
    locale: str | None = "es-ES",
    per_page: int = 10,
    page: int = 1,
    usar_cache: bool = True,
) -> VideoBrollResult:
    """Contrato FAIL-OPEN para ERRORES OPERATIVOS conocidos (la familia PexelsVideoError).

    Traduce cada error operativo a un BrollVideoError tipado (saneado, sin secretos) para que el
    pipeline omita el b-roll y continue. Errores de programacion (RuntimeError/TypeError/ValueError/
    AssertionError) se PROPAGAN para no ocultar bugs.
    """
    try:
        assets, rate = _buscar_con_rate(
            query, orientation, size, locale, per_page, page, usar_cache
        )
        return VideoBrollResult(assets=tuple(assets), error=None, rate_limit=rate)
    except PexelsVideoError as e:
        code = _CODIGO_ERROR.get(type(e), "error")
        retry_after = getattr(e, "retry_after", None)
        return VideoBrollResult(
            error=BrollVideoError(code, _sanitizar(str(e)), retry_after=retry_after)
        )


# ── Descarga + cache de archivo + sidecar ─────────────────────────────────────


def _descargar_mp4_bytes(url: str, max_bytes: int = MAX_DOWNLOAD_BYTES) -> bytes:
    """Descarga el MP4 por streaming. Valida status, Content-Type (si viene) y tope de tamano."""
    try:
        resp = requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT_S)
    except requests.Timeout as e:
        raise PexelsVideoTimeout("timeout al descargar el video") from e
    except requests.RequestException as e:
        raise PexelsVideoDescargaError(f"error de red al descargar: {type(e).__name__}") from e
    try:
        if not (200 <= resp.status_code < 300):
            raise PexelsVideoDescargaError(f"HTTP {resp.status_code} al descargar el video")
        ct = (resp.headers.get("Content-Type") or "").lower()
        if ct and not (ct.startswith("video/") or ct.startswith("application/octet-stream")):
            raise PexelsVideoDescargaError(f"Content-Type no es video: {ct}")
        buf = bytearray()
        for chunk in resp.iter_content(CHUNK_BYTES):
            if chunk:
                buf += chunk
            if len(buf) > max_bytes:
                raise PexelsVideoDescargaError(f"video excede el tope de {max_bytes} bytes")
        return bytes(buf)
    finally:
        resp.close()


def descargar_video_asset(
    asset: VideoStockAsset,
    *,
    destino: str,
    target_width: int,
    target_height: int,
    cache_dir: Path | None = None,
    ahora_utc: str | None = None,
) -> VideoStockAsset:
    """Descarga (o reutiliza de cache) el MP4 del asset y escribe su sidecar.

    La VARIANTE se resuelve ANTES de la ruta: la identidad de cache es provider+video_id+file_id
    (`pexels_{video_id}_{file_id}.mp4`), asi dos variantes del mismo video nunca colisionan. Cache
    hit solo si el MP4 existe y valido Y el sidecar coincide (provider, asset_id, video_file_id,
    download_url). Escritura atomica (tmp + os.replace); firma ISO/MP4 (ftyp) obligatoria (HTML
    renombrado se rechaza). Devuelve una instancia frozen con los selected_*, download_url,
    selection_reason, local_path y metadata_path.
    """
    seleccion = seleccionar_variante_video(
        asset.video_files, destino=destino, target_width=target_width, target_height=target_height
    )
    cache = Path(cache_dir) if cache_dir is not None else _base.CACHE_ROOT
    cache.mkdir(parents=True, exist_ok=True)
    stem = _base._stem_cache(asset.asset_id, seleccion.file_id)
    sidecar_path = cache / f"{stem}.json"
    video_path = cache / f"{stem}.mp4"
    ahora = ahora_utc or _base._utc_now_iso()
    elegido = replace(
        asset,
        selected_file_id=seleccion.file_id,
        selected_quality=seleccion.quality,
        selected_width=seleccion.width,
        selected_height=seleccion.height,
        selected_file_type=seleccion.file_type,
        download_url=seleccion.url,
        selection_reason=seleccion.motivo,
    )

    cacheado = _base._video_cacheado(cache, stem)
    if (
        cacheado is not None
        and _base._mp4_valido(cacheado)
        and _base._cache_hit_valido(sidecar_path, elegido)
    ):
        _base._refrescar_sidecar(sidecar_path, elegido, ahora)
        return replace(elegido, local_path=cacheado, metadata_path=sidecar_path)

    datos = _descargar_mp4_bytes(seleccion.url)
    if not datos:
        raise PexelsVideoDescargaError("la descarga quedo vacia (0 bytes)")
    if not _base._firma_mp4(datos):
        raise PexelsVideoDescargaError("el contenido descargado no es un MP4 (sin firma ftyp)")

    _base._escribir_atomico(video_path, datos)
    descargado = replace(elegido, local_path=video_path)
    _base._escribir_json_atomico(sidecar_path, _base._sidecar_dict(descargado, video_path, ahora))
    return replace(descargado, metadata_path=sidecar_path)
