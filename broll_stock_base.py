"""broll_stock_base.py - Tipos, errores y capa de cache/IO del fetcher de b-roll Pexels.

Capa base sin dependencias de red ni de la API key: define los tipos publicos
(StockAsset, SeleccionVariante, RateLimitInfo, BrollError, BrollResult), los errores
tipados, y los helpers de cache de busqueda + escritura atomica + sidecar. `broll_stock.py`
la consume y re-exporta el contrato publico. Split por la regla anti-spaghetti (archivo
<= 400 lineas, skill centrito-dev); ver DECISIONES.md D28.

Seguridad (regla #9): nada aqui imprime, serializa ni recibe la PEXELS_API_KEY. El sidecar
guarda atribucion/licencia, jamas la key.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).parent

PROVIDER = "pexels"
PROVIDER_URL = "https://www.pexels.com"
SIDECAR_VERSION = 1

# Cache de archivos descargados + cache de respuestas de busqueda (gitignored).
CACHE_ROOT = ROOT / "assets" / "broll" / "cache" / "pexels"
SEARCH_CACHE_DIR = CACHE_ROOT / "_search"
SEARCH_CACHE_VERSION = 1
SEARCH_CACHE_TTL_S = 24 * 3600  # 24 horas

_FIRMAS_IMAGEN = ("jpg", "png", "webp")  # unicos formatos aceptados


# ── Errores tipados (capa honesta: no oculta errores de programacion) ─────────
# Todos heredan de PexelsError: la familia de errores OPERATIVOS conocidos. Los errores
# de programacion (RuntimeError/TypeError/ValueError/AssertionError) NO heredan de aqui y
# por tanto se propagan (buscar_broll_seguro solo atrapa PexelsError).


class PexelsError(Exception):
    """Base de los errores operativos conocidos del fetcher de Pexels."""


class PexelsDeshabilitado(PexelsError):
    """PEXELS_API_KEY ausente: el fetcher esta deshabilitado."""


class PexelsRateLimit(PexelsError):
    """HTTP 429. Conserva Retry-After si vino (dato opcional). NO se reintenta en V1."""

    def __init__(self, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class PexelsAuthError(PexelsError):
    """HTTP 401/403: la key fue rechazada."""


class PexelsHTTPError(PexelsError):
    """Otro status HTTP no exitoso."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class PexelsTimeout(PexelsError):
    """La API o el CDN no respondieron dentro del timeout."""


class PexelsRespuestaInvalida(PexelsError):
    """Respuesta no-JSON o sin la estructura esperada."""


class PexelsSinVariante(PexelsError):
    """Ninguna de las variantes admitidas esta disponible en `src`."""


class PexelsDescargaError(PexelsError):
    """La descarga fallo, quedo vacia o el contenido no es una imagen reconocible."""


# ── Tipos ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StockAsset:
    """Un candidato de imagen. Antes de descargar, local_path/metadata_path son None.

    `src` conserva el mapa de variantes de Pexels para `seleccionar_variante`; se excluye
    de igualdad/hash (dict no hashable) y del repr por ruido.
    """

    provider: str
    asset_id: str
    query: str
    width: int
    height: int
    orientation: str
    download_url: str
    source_url: str
    author: str
    author_url: str
    alt: str
    media_type: str = "image"
    src: dict = field(default_factory=dict, compare=False, repr=False)
    # Poblados al descargar: qué variante se eligió y por qué (parte de la identidad de cache).
    selected_variant: str | None = None
    selection_reason: str | None = None
    local_path: Path | None = None
    metadata_path: Path | None = None


@dataclass(frozen=True)
class SeleccionVariante:
    """Resultado determinista de elegir una variante de `src`."""

    nombre: str
    url: str
    motivo: str


@dataclass(frozen=True)
class RateLimitInfo:
    """Headers de rate limit de Pexels (solo garantizados en respuestas 2xx)."""

    limit: int | None = None
    remaining: int | None = None
    reset: int | None = None


@dataclass(frozen=True)
class BrollError:
    """Error saneado para el contrato fail-open. Nunca contiene la key ni Authorization."""

    code: str
    message: str
    retry_after: int | None = None


@dataclass(frozen=True)
class BrollResult:
    """Resultado fail-open: assets O un error tipado; jamas finge exito."""

    assets: tuple[StockAsset, ...] = ()
    error: BrollError | None = None
    rate_limit: RateLimitInfo | None = None


# ── Utilidades puras ──────────────────────────────────────────────────────────


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalizar_query(query: str) -> str:
    """strip + colapsa espacios internos. NO cambia el texto enviado a la API salvo esto."""
    return " ".join((query or "").split())


# ── Cache de busqueda (JSON, 24h, deshabilitable) ─────────────────────────────


def _clave_cache_busqueda(query: str, orientation: str | None, per_page: int, page: int) -> str:
    """Clave determinista: query normalizada+lowercase, orientation, per_page, page."""
    q = _normalizar_query(query).lower()
    base = f"{q}|{orientation or ''}|{per_page}|{page}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


def _search_cache_path(clave: str) -> Path:
    return SEARCH_CACHE_DIR / f"{clave}.json"


def _leer_cache_busqueda(
    clave: str, ttl_s: int = SEARCH_CACHE_TTL_S, ahora_epoch: float | None = None
) -> list | None:
    """Devuelve las fotos cacheadas si el archivo es valido y no vencio; si no, None.

    Corrupta, de otro esquema o vencida -> None (se ignora y renueva). Nunca finge exito.
    """
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
    fotos = obj.get("photos")
    if not isinstance(ts, (int, float)) or not isinstance(fotos, list):
        return None
    ahora = ahora_epoch if ahora_epoch is not None else time.time()
    if ahora - ts > ttl_s:
        return None
    return fotos


def _escribir_cache_busqueda(
    clave: str, fotos: list, ahora_epoch: float | None = None, ahora_iso: str | None = None
) -> None:
    """Escribe la cache de busqueda atomicamente. No contiene la API key (photos de Pexels)."""
    SEARCH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    obj = {
        "schema_version": SEARCH_CACHE_VERSION,
        "cached_utc": ahora_iso or _utc_now_iso(),
        "cached_utc_epoch": ahora_epoch if ahora_epoch is not None else time.time(),
        "photos": fotos,
    }
    _escribir_json_atomico(_search_cache_path(clave), obj)


# ── Escritura atomica + firma de bytes ────────────────────────────────────────


def _escribir_atomico(path: Path, datos: bytes) -> None:
    """Escribe bytes a un temporal y reemplaza atomicamente (os.replace)."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(datos)
    os.replace(tmp, path)


def _escribir_json_atomico(path: Path, obj: dict) -> None:
    """Escribe JSON utf-8 (ensure_ascii=False) a un temporal y reemplaza atomicamente."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _firma_imagen(datos: bytes) -> str | None:
    """Detecta el formato por firma de bytes: jpg, png o webp. None si no es imagen conocida."""
    if datos[:3] == b"\xff\xd8\xff":
        return "jpg"
    if datos[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if datos[:4] == b"RIFF" and datos[8:12] == b"WEBP":
        return "webp"
    return None


# ── Cache de archivo + sidecar ────────────────────────────────────────────────


def _variante_segura(nombre: str) -> str:
    """Normaliza el nombre de variante para usarlo en un filename (Windows-safe)."""
    return re.sub(r"[^a-z0-9_-]", "", (nombre or "").lower()) or "sin_variante"


def _stem_cache(asset: StockAsset, variante: str) -> str:
    """Nombre estable que INCLUYE la variante: dos variantes del mismo id no colisionan."""
    return f"{asset.provider}_{asset.asset_id}_{_variante_segura(variante)}"


def _imagen_cacheada(cache_dir: Path, stem: str) -> Path | None:
    """Devuelve la imagen ya cacheada (glob por extension de imagen), o None si no existe."""
    for ext in _FIRMAS_IMAGEN:
        p = cache_dir / f"{stem}.{ext}"
        if p.exists() and p.stat().st_size > 0:
            return p
    return None


def _imagen_valida(path: Path) -> bool:
    """El contenido en disco sigue siendo una imagen jpg/png/webp (firma de bytes)."""
    try:
        with path.open("rb") as fh:
            cabecera = fh.read(12)
    except OSError:
        return False
    return _firma_imagen(cabecera) is not None


def _cache_hit_valido(sidecar_path: Path, asset: StockAsset) -> bool:
    """Cache hit solo si el sidecar existe, es valido y coincide con la seleccion actual.

    Exige que provider, asset_id, selected_variant y download_url del sidecar concuerden
    con `asset` (ya enriquecido con la seleccion resuelta). Cualquier desajuste -> re-descarga.
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
        and obj.get("selected_variant") == asset.selected_variant
        and obj.get("download_url") == asset.download_url
    )


def _sidecar_dict(asset: StockAsset, img_path: Path, ahora_utc: str) -> dict:
    """Construye el sidecar de atribucion/licencia + identidad de cache. JAMAS incluye la key."""
    return {
        "sidecar_version": SIDECAR_VERSION,
        "provider": asset.provider,
        "provider_url": PROVIDER_URL,
        "asset_id": asset.asset_id,
        "media_type": asset.media_type,
        "query": asset.query,
        "width": asset.width,
        "height": asset.height,
        "orientation": asset.orientation,
        "selected_variant": asset.selected_variant,
        "selection_reason": asset.selection_reason,
        "download_url": asset.download_url,
        "source_url": asset.source_url,
        "author": asset.author,
        "author_url": asset.author_url,
        "attribution_text": f"Photo by {asset.author} on Pexels",
        "alt": asset.alt,
        "local_file": img_path.name,
        "downloaded_utc": ahora_utc,
        "last_used_utc": ahora_utc,
        "licencia": {
            "uso_comercial": True,
            "redistribucion_como_stock": False,
            "uso_en_datasets_o_entrenamiento_ia": False,
            "nota": "Centrito lo usa como material integrado en una edicion de video.",
        },
    }


def _refrescar_sidecar(sidecar_path: Path, asset: StockAsset, ahora_utc: str) -> None:
    """En cache hit: reescribe el sidecar (atomico) actualizando SOLO query, selection_reason
    y last_used_utc. Preserva downloaded_utc (nunca se reinicia). Best-effort: si el sidecar
    no se puede leer, no toca nada (el hit igual devuelve la imagen cacheada)."""
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
