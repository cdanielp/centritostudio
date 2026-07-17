"""broll_video_stock_base.py - Tipos, errores y cache/IO del fetcher de VIDEOS de b-roll Pexels.

Capa base sin red ni API key: define los tipos publicos (VideoStockAsset, VideoFileCandidate,
SeleccionVideo, RateLimitInfo re-exportado, BrollVideoError, VideoBrollResult), los errores
tipados (familia PexelsVideoError) y los helpers de cache de busqueda + escritura atomica +
sidecar. `broll_video_stock.py` la consume y re-exporta el contrato publico. Split por la regla
anti-spaghetti (archivo <= 400 lineas); mismo patron que broll_stock_base (ver DECISIONES.md D28).

Reutiliza de `broll_stock_base` (fetcher de IMAGENES, ya mergeado) la escritura atomica, el reloj
UTC, la normalizacion de query y el tipo RateLimitInfo: son primitivas puras sin estado ni red, y
`broll_stock_base` no importa este modulo (no hay ciclo). No se refactoriza el fetcher de imagenes.

Seguridad (regla #9): nada aqui imprime, serializa ni recibe la PEXELS_API_KEY. El sidecar guarda
atribucion/licencia del video, jamas la key.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

# Reuso de primitivas puras del fetcher de imagenes (sin ciclo: base de imagenes no nos importa).
from broll_stock_base import (
    RateLimitInfo,  # re-export: mismo contrato de rate limit para imagen y video
    _escribir_atomico,
    _escribir_json_atomico,
    _normalizar_query,
    _utc_now_iso,
)

__all__ = [
    "RateLimitInfo",
    "_escribir_atomico",
    "_escribir_json_atomico",
    "_normalizar_query",
    "_utc_now_iso",
]

ROOT = Path(__file__).parent

PROVIDER = "pexels"
PROVIDER_URL = "https://www.pexels.com"
SIDECAR_VERSION = 1

# Cache propia de VIDEOS (separada de la de imagenes para no mezclar identidades). Gitignored
# por la regla `assets/broll/cache/` de .gitignore: ningun MP4 ni sidecar entra al repo.
CACHE_ROOT = ROOT / "assets" / "broll" / "cache" / "pexels_video"
SEARCH_CACHE_DIR = CACHE_ROOT / "_search"
SEARCH_CACHE_VERSION = 1
SEARCH_CACHE_TTL_S = 24 * 3600  # 24 horas

MP4_FILE_TYPE = "video/mp4"  # unico file_type de video directo aceptado (no HLS)


# ── Errores tipados (familia PexelsVideoError) ────────────────────────────────
# Todos heredan de PexelsVideoError: los errores OPERATIVOS conocidos del fetcher de video.
# Los errores de PROGRAMACION (RuntimeError/TypeError/ValueError/AssertionError) NO heredan de
# aqui y por tanto se PROPAGAN (buscar_video_broll_seguro solo atrapa PexelsVideoError).


class PexelsVideoError(Exception):
    """Base de los errores operativos conocidos del fetcher de videos Pexels."""


class PexelsVideoDeshabilitado(PexelsVideoError):
    """PEXELS_API_KEY ausente: el fetcher esta deshabilitado."""


class PexelsVideoRateLimit(PexelsVideoError):
    """HTTP 429. Conserva Retry-After si vino (dato opcional). NO se reintenta en V1."""

    def __init__(self, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class PexelsVideoAuthError(PexelsVideoError):
    """HTTP 401/403: la key fue rechazada."""


class PexelsVideoHTTPError(PexelsVideoError):
    """Otro status HTTP no exitoso."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class PexelsVideoTimeout(PexelsVideoError):
    """La API o el CDN no respondieron dentro del timeout."""


class PexelsVideoRespuestaInvalida(PexelsVideoError):
    """Respuesta no-JSON o sin la estructura esperada."""


class PexelsVideoSinVariante(PexelsVideoError):
    """Ningun video_file MP4 directo valido esta disponible."""


class PexelsVideoDescargaError(PexelsVideoError):
    """La descarga fallo, quedo vacia o el contenido no es un MP4 reconocible."""


# ── Tipos ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class VideoFileCandidate:
    """Una variante descargable (video_file) de un Video de Pexels."""

    file_id: str
    quality: str
    file_type: str
    width: int
    height: int
    link: str


@dataclass(frozen=True)
class SeleccionVideo:
    """Resultado determinista de elegir un video_file para un destino (target_w x target_h)."""

    file_id: str
    quality: str
    width: int
    height: int
    file_type: str
    url: str
    motivo: str


@dataclass(frozen=True)
class VideoStockAsset:
    """Un candidato de VIDEO. Antes de descargar, local_path/metadata_path y los campos
    selected_* son None. `video_files` conserva las variantes para `seleccionar_variante_video`;
    se excluye de igualdad/hash y del repr por ruido."""

    provider: str
    asset_id: str
    query: str
    width: int
    height: int
    duration: int
    orientation: str
    source_url: str
    author: str
    author_url: str
    preview_url: str
    media_type: str = "video"
    video_files: tuple[VideoFileCandidate, ...] = field(
        default_factory=tuple, compare=False, repr=False
    )
    # Poblados al seleccionar/descargar (parte de la identidad de cache y del sidecar).
    selected_file_id: str | None = None
    selected_quality: str | None = None
    selected_width: int | None = None
    selected_height: int | None = None
    selected_file_type: str | None = None
    download_url: str | None = None
    selection_reason: str | None = None
    local_path: Path | None = None
    metadata_path: Path | None = None


@dataclass(frozen=True)
class BrollVideoError:
    """Error saneado para el contrato fail-open. Nunca contiene la key ni Authorization."""

    code: str
    message: str
    retry_after: int | None = None


@dataclass(frozen=True)
class VideoBrollResult:
    """Resultado fail-open: assets O un error tipado; jamas finge exito."""

    assets: tuple[VideoStockAsset, ...] = ()
    error: BrollVideoError | None = None
    rate_limit: RateLimitInfo | None = None


# ── Utilidades puras ──────────────────────────────────────────────────────────


def orientacion_de(width: int, height: int) -> str:
    """Orientacion por dimensiones: portrait (alto>ancho), landscape, square, unknown."""
    if width <= 0 or height <= 0:
        return "unknown"
    if height > width:
        return "portrait"
    if width > height:
        return "landscape"
    return "square"


# ── Cache de busqueda (JSON, 24h, deshabilitable) ─────────────────────────────


def _clave_cache_busqueda(
    query: str,
    orientation: str | None,
    size: str | None,
    locale: str | None,
    per_page: int,
    page: int,
) -> str:
    """Clave determinista. Incluye media_type=video para NO colisionar con la cache de imagenes."""
    q = _normalizar_query(query).lower()
    base = f"video|{q}|{orientation or ''}|{size or ''}|{locale or ''}|{per_page}|{page}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


def _search_cache_path(clave: str) -> Path:
    return SEARCH_CACHE_DIR / f"{clave}.json"


def _leer_cache_busqueda(
    clave: str, ttl_s: int = SEARCH_CACHE_TTL_S, ahora_epoch: float | None = None
) -> list | None:
    """Videos cacheados si el archivo es valido y no vencio; si no, None (se ignora y renueva)."""
    path = _search_cache_path(clave)
    if not path.exists():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    if not isinstance(obj, dict) or obj.get("schema_version") != SEARCH_CACHE_VERSION:
        return None
    ts = obj.get("cached_utc_epoch")
    videos = obj.get("videos")
    if not isinstance(ts, (int, float)) or not isinstance(videos, list):
        return None
    ahora = ahora_epoch if ahora_epoch is not None else time.time()
    if ahora - ts > ttl_s:
        return None
    return videos


def _escribir_cache_busqueda(
    clave: str, videos: list, ahora_epoch: float | None = None, ahora_iso: str | None = None
) -> None:
    """Escribe la cache de busqueda atomicamente. No contiene la API key (videos de Pexels)."""
    SEARCH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    obj = {
        "schema_version": SEARCH_CACHE_VERSION,
        "cached_utc": ahora_iso or _utc_now_iso(),
        "cached_utc_epoch": ahora_epoch if ahora_epoch is not None else time.time(),
        "videos": videos,
    }
    _escribir_json_atomico(_search_cache_path(clave), obj)


# ── Cache de archivo (MP4) + firma + sidecar ──────────────────────────────────


def _stem_cache(video_id: str, file_id: str) -> str:
    """Identidad de cache que INCLUYE el file_id: dos variantes del mismo video no colisionan."""
    return f"{PROVIDER}_{video_id}_{file_id}"


def _video_cacheado(cache_dir: Path, stem: str) -> Path | None:
    """El MP4 ya cacheado (con contenido) o None."""
    p = cache_dir / f"{stem}.mp4"
    if p.exists() and p.stat().st_size > 0:
        return p
    return None


def _firma_mp4(datos: bytes) -> bool:
    """True si los bytes tienen la firma ISO Base Media/MP4: un box 'ftyp' al inicio."""
    return len(datos) >= 12 and datos[4:8] == b"ftyp"


def _mp4_valido(path: Path) -> bool:
    """El contenido en disco sigue teniendo firma MP4 (ftyp)."""
    try:
        with path.open("rb") as fh:
            cabecera = fh.read(12)
    except OSError:
        return False
    return _firma_mp4(cabecera)


def verificar_mp4_ffprobe(path: Path) -> bool:
    """Validacion REAL opcional con ffprobe: True si el archivo tiene stream de video. Si ffprobe
    no esta disponible, devuelve True (no bloquea; la firma ftyp ya valido el contenedor). La usan
    el smoke y la evidencia real, no los unit tests (que usan MP4 sinteticos de solo ftyp)."""
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "csv=p=0",
                str(path),
            ],  # fmt: skip
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, OSError):
        return True
    return r.returncode == 0 and "video" in r.stdout


def _cache_hit_valido(sidecar_path: Path, asset: VideoStockAsset) -> bool:
    """Cache hit solo si el sidecar existe, es valido y coincide con la seleccion actual.

    Exige provider, asset_id, video_file_id y download_url del sidecar concordando con `asset`
    (ya enriquecido con la seleccion). Cualquier desajuste -> re-descarga.
    """
    if not sidecar_path.exists():
        return False
    try:
        obj = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return False
    if not isinstance(obj, dict) or "sidecar_version" not in obj:
        return False
    return (
        obj.get("provider") == asset.provider
        and str(obj.get("asset_id")) == str(asset.asset_id)
        and str(obj.get("video_file_id")) == str(asset.selected_file_id)
        and obj.get("download_url") == asset.download_url
    )


def _sidecar_dict(asset: VideoStockAsset, video_path: Path, ahora_utc: str) -> dict:
    """Sidecar de atribucion/licencia + identidad de cache del video. JAMAS incluye la key."""
    return {
        "sidecar_version": SIDECAR_VERSION,
        "provider": asset.provider,
        "provider_url": PROVIDER_URL,
        "asset_id": asset.asset_id,
        "media_type": asset.media_type,
        "video_file_id": asset.selected_file_id,
        "query": asset.query,
        "author": asset.author,
        "author_url": asset.author_url,
        "attribution_text": f"Video by {asset.author} on Pexels",
        "source_url": asset.source_url,
        "preview_url": asset.preview_url,
        "duration": asset.duration,
        "width": asset.width,
        "height": asset.height,
        "orientation": asset.orientation,
        "selected_width": asset.selected_width,
        "selected_height": asset.selected_height,
        "selected_quality": asset.selected_quality,
        "selected_file_type": asset.selected_file_type,
        "download_url": asset.download_url,
        "selection_reason": asset.selection_reason,
        "local_file": video_path.name,
        "downloaded_utc": ahora_utc,
        "last_used_utc": ahora_utc,
        "licencia": {
            "uso_comercial": True,
            "redistribucion_como_stock": False,
            "uso_en_datasets_o_entrenamiento_ia": False,
            "nota": "Centrito lo usa como material integrado en una edicion de video.",
        },
    }


def _refrescar_sidecar(sidecar_path: Path, asset: VideoStockAsset, ahora_utc: str) -> None:
    """En cache hit: reescribe el sidecar (atomico) actualizando SOLO query, selection_reason y
    last_used_utc. Preserva downloaded_utc. Best-effort: sidecar ilegible -> no toca nada."""
    try:
        obj = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return
    if not isinstance(obj, dict):
        return
    obj["query"] = asset.query
    obj["selection_reason"] = asset.selection_reason
    obj["last_used_utc"] = ahora_utc
    _escribir_json_atomico(sidecar_path, obj)
