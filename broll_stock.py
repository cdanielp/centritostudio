"""broll_stock.py - Fetcher de imagenes de stock (Pexels) para b-roll (feat/broll-pexels-images).

API PUBLICA del fetcher: busca, selecciona, descarga y cachea imagenes de Pexels para b-roll
cutaway. Modulo PURO respecto al pipeline: no conecta con brain, render, overlays/Popup, UI
ni auto.py (fuera de alcance por diseno). Solo produce assets tipados (`StockAsset`) y archivos
en cache que una integracion futura consumira.

Los tipos, errores y la capa de cache/IO viven en `broll_stock_base` (split por la regla
anti-spaghetti, archivo <= 400 lineas; ver DECISIONES.md D28). Este modulo re-exporta el
contrato publico, asi `from broll_stock import StockAsset, buscar_broll_seguro, ...` funciona.

Seguridad (regla #9): PEXELS_API_KEY vive en el entorno y NUNCA se imprime, serializa ni
aparece en sidecars, mensajes de error o logs. El header Authorization jamas se logea.
La licencia Pexels y la atribucion se guardan en cada sidecar (ver `_sidecar_dict` / D28).

Cliente HTTP: `requests` (ya en requirements.txt, mismo patron que submagic.py). Sin deps nuevas.
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import requests

import broll_stock_base as _base
from broll_stock_base import (  # re-export del contrato publico
    PROVIDER,
    BrollError,
    BrollResult,
    PexelsAuthError,
    PexelsDescargaError,
    PexelsDeshabilitado,
    PexelsError,
    PexelsHTTPError,
    PexelsRateLimit,
    PexelsRespuestaInvalida,
    PexelsSinVariante,
    PexelsTimeout,
    RateLimitInfo,
    SeleccionVariante,
    StockAsset,
)

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

SEARCH_URL = "https://api.pexels.com/v1/search"
TIMEOUT_S = 10  # timeout explicito por request (busqueda y descarga)
PER_PAGE_MIN = 1
PER_PAGE_MAX = 80  # tope admitido por la API de Pexels
ORIENTACIONES_VALIDAS = frozenset({"landscape", "portrait", "square"})


# ── Configuracion / clave (nunca exponen el secreto) ──────────────────────────


def tiene_api_key() -> bool:
    """True si PEXELS_API_KEY esta configurada (sin revelar su valor)."""
    return bool(os.getenv("PEXELS_API_KEY", "").strip())


def _api_key() -> str:
    key = os.getenv("PEXELS_API_KEY", "").strip()
    if not key:
        raise PexelsDeshabilitado(
            "PEXELS_API_KEY no configurada. Agregala a .env (ver .env.example) para usar b-roll."
        )
    return key


def _headers() -> dict:
    """Headers con Authorization. NUNCA logear este dict (contiene la key)."""
    return {"Authorization": _api_key()}


def estado_pexels() -> dict:
    """Estado del fetcher sin revelar secretos: {habilitado, motivo}."""
    if tiene_api_key():
        return {"habilitado": True, "motivo": "PEXELS_API_KEY presente"}
    return {"habilitado": False, "motivo": "PEXELS_API_KEY ausente"}


def _sanitizar(msg: str) -> str:
    """Red de seguridad: si el valor de la key se colara en un mensaje, se redacta a ***."""
    key = os.getenv("PEXELS_API_KEY", "").strip()
    if key and key in msg:
        msg = msg.replace(key, "***")
    return msg


# ── Busqueda ──────────────────────────────────────────────────────────────────


def _orientacion_de(width: int, height: int) -> str:
    if width <= 0 or height <= 0:
        return "unknown"
    if height > width:
        return "portrait"
    if width > height:
        return "landscape"
    return "square"


def _asset_desde_foto(foto: dict, query: str) -> StockAsset:
    """Convierte un objeto foto de Pexels en StockAsset (candidato sin descargar)."""
    src = foto.get("src")
    if not isinstance(src, dict):
        src = {}
    w = int(foto.get("width") or 0)
    h = int(foto.get("height") or 0)
    return StockAsset(
        provider=PROVIDER,
        asset_id=str(foto.get("id", "")),
        query=query,
        width=w,
        height=h,
        orientation=_orientacion_de(w, h),
        download_url=str(src.get("original", "")),
        source_url=str(foto.get("url", "")),
        author=str(foto.get("photographer", "")),
        author_url=str(foto.get("photographer_url", "")),
        alt=str(foto.get("alt") or ""),
        src=src,
    )


def _rate_limit_desde_headers(headers) -> RateLimitInfo | None:
    """Lee X-Ratelimit-* (solo en 2xx). None si no vino ninguno."""

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


def _validar_params(query: str, orientation: str | None, per_page: int, page: int):
    q = _base._normalizar_query(query)
    if not q:
        raise ValueError("query vacio: se requiere un termino de busqueda")
    if orientation is not None and orientation not in ORIENTACIONES_VALIDAS:
        raise ValueError(
            f"orientation invalida: {orientation!r} (usa landscape|portrait|square o None)"
        )
    per_page = max(PER_PAGE_MIN, min(PER_PAGE_MAX, int(per_page)))
    page = max(1, int(page))
    return q, per_page, page


def _http_buscar(q: str, orientation: str | None, per_page: int, page: int):
    """Ejecuta el GET a Pexels y valida status/JSON. Devuelve (fotos, rate)."""
    params = {"query": q, "per_page": per_page, "page": page}
    if orientation:
        params["orientation"] = orientation
    try:
        resp = requests.get(SEARCH_URL, headers=_headers(), params=params, timeout=TIMEOUT_S)
    except requests.Timeout as e:
        raise PexelsTimeout("Pexels no respondio a tiempo en la busqueda") from e
    except requests.RequestException as e:
        raise PexelsRespuestaInvalida(f"error de red: {type(e).__name__}") from e

    if resp.status_code == 429:
        # V1: NO reintentar, NO dormir. Conservar Retry-After solo como dato opcional.
        ra = resp.headers.get("Retry-After")
        retry_after = int(ra) if ra and str(ra).strip().isdigit() else None
        raise PexelsRateLimit("Pexels rate limit (HTTP 429)", retry_after=retry_after)
    if resp.status_code in (401, 403):
        raise PexelsAuthError(f"Pexels rechazo la key (HTTP {resp.status_code})")
    if not (200 <= resp.status_code < 300):
        raise PexelsHTTPError(f"Pexels HTTP {resp.status_code}", status=resp.status_code)

    try:
        data = resp.json()
    except ValueError as e:
        raise PexelsRespuestaInvalida("la respuesta de Pexels no es JSON valido") from e
    if not isinstance(data, dict) or not isinstance(data.get("photos"), list):
        raise PexelsRespuestaInvalida("respuesta de Pexels sin lista 'photos'")

    fotos = [f for f in data["photos"] if isinstance(f, dict)]
    return fotos, _rate_limit_desde_headers(resp.headers)


def _buscar_con_rate(
    query: str,
    orientation: str | None,
    per_page: int,
    page: int,
    usar_cache: bool,
) -> tuple[list[StockAsset], RateLimitInfo | None]:
    q, per_page, page = _validar_params(query, orientation, per_page, page)
    clave = _base._clave_cache_busqueda(q, orientation, per_page, page)

    if usar_cache:
        cacheadas = _base._leer_cache_busqueda(clave)
        if cacheadas is not None:
            return [_asset_desde_foto(f, q) for f in cacheadas], None

    fotos, rate = _http_buscar(q, orientation, per_page, page)
    if usar_cache:
        _base._escribir_cache_busqueda(clave, fotos)
    return [_asset_desde_foto(f, q) for f in fotos], rate


def buscar_imagenes_pexels(
    query: str,
    orientation: str | None = None,
    per_page: int = 10,
    page: int = 1,
    usar_cache: bool = True,
) -> list[StockAsset]:
    """Busca imagenes en Pexels. Capa HONESTA: lanza errores tipados (no fail-open).

    - Valida query no vacio y orientation en {landscape,portrait,square}.
    - Limita per_page a [1,80] y page a >=1.
    - Envia Authorization, timeout explicito, valida HTTP y JSON.
    - Cero resultados es un exito valido (lista vacia), no un error.
    - NO reintenta en 429 (lanza PexelsRateLimit).
    Usa `buscar_broll_seguro` si quieres el contrato fail-open para el pipeline.
    """
    assets, _rate = _buscar_con_rate(query, orientation, per_page, page, usar_cache)
    return assets


# Codigo tipado por cada error OPERATIVO conocido (subclase de PexelsError).
_CODIGO_ERROR = {
    PexelsDeshabilitado: "deshabilitado",
    PexelsRateLimit: "rate_limit",
    PexelsAuthError: "auth",
    PexelsTimeout: "timeout",
    PexelsHTTPError: "http",
    PexelsRespuestaInvalida: "respuesta_invalida",
    PexelsSinVariante: "sin_variante",
    PexelsDescargaError: "descarga",
}


def buscar_broll_seguro(
    query: str,
    orientation: str | None = None,
    per_page: int = 10,
    page: int = 1,
    usar_cache: bool = True,
) -> BrollResult:
    """Contrato FAIL-OPEN para ERRORES OPERATIVOS conocidos (la familia PexelsError).

    Traduce cada error operativo (key ausente, 429, 401/403, HTTP, timeout, JSON invalido...)
    a un BrollError tipado (mensaje saneado, sin secretos) para que el pipeline omita el b-roll
    y continue. Un exito trae assets (tupla, posible vacia) y rate_limit si la API lo reporto.
    NO atrapa errores de programacion (RuntimeError/TypeError/ValueError/AssertionError): esos
    se PROPAGAN para no ocultar bugs.
    """
    try:
        assets, rate = _buscar_con_rate(query, orientation, per_page, page, usar_cache)
        return BrollResult(assets=tuple(assets), error=None, rate_limit=rate)
    except PexelsError as e:
        code = _CODIGO_ERROR.get(type(e), "error")
        retry_after = getattr(e, "retry_after", None)
        return BrollResult(error=BrollError(code, _sanitizar(str(e)), retry_after=retry_after))


# ── Seleccion de variante (determinista, prioriza resolucion) ─────────────────

# La orientacion ya se resolvio en la busqueda (params orientation), asi que los candidatos
# ya tienen composicion compatible con el destino. Por eso NO priorizamos las variantes
# recortadas (portrait ~800x1200, landscape ~1200x627): se ven suaves al llenar Full HD.
# large2x (~1880px) conserva mejor detalle; original es el fallback de maxima calidad.
_ORDEN_CONTAIN = ("large2x", "original", "large")
_ORDEN_COVER_VERTICAL = ("large2x", "original", "portrait")
_ORDEN_COVER_HORIZONTAL = ("large2x", "original", "landscape")

_MOTIVO_VARIANTE = {
    "large2x": "large2x (~1880px): mejor resolucion conservando la composicion completa",
    "original": "original: fallback de maxima calidad cuando falta large2x",
    "large": "large: fallback cuando faltan large2x y original",
    "portrait": "portrait (~800x1200): ultimo fallback orientado vertical",
    "landscape": "landscape (~1200x627): ultimo fallback orientado horizontal",
}


def _orden_variantes(destino: str, fit: str) -> tuple[str, ...]:
    fit = (fit or "cover").lower()
    destino = (destino or "").lower()
    if fit == "contain":
        return _ORDEN_CONTAIN
    if fit != "cover":
        raise ValueError(f"fit invalido: {fit!r} (usa 'contain' o 'cover')")
    if destino == "vertical":
        return _ORDEN_COVER_VERTICAL
    if destino == "horizontal":
        return _ORDEN_COVER_HORIZONTAL
    raise ValueError(f"destino invalido: {destino!r} (usa 'vertical' u 'horizontal')")


def seleccionar_variante(src: dict, destino: str, fit: str = "cover") -> SeleccionVariante:
    """Elige la URL de imagen de forma DETERMINISTA (nunca aleatoria).

    Ordenes de fallback (documentados en DECISIONES.md D28):
      - contain:            large2x -> original -> large
      - cover + vertical:   large2x -> original -> portrait
      - cover + horizontal: large2x -> original -> landscape
    Sin ninguna variante admitida -> PexelsSinVariante.
    """
    if not isinstance(src, dict):
        raise ValueError("src debe ser un dict de variantes de Pexels")
    orden = _orden_variantes(destino, fit)
    for nombre in orden:
        url = src.get(nombre)
        if url:
            return SeleccionVariante(nombre=nombre, url=str(url), motivo=_MOTIVO_VARIANTE[nombre])
    raise PexelsSinVariante(f"ninguna variante admitida disponible (busque {orden})")


# ── Descarga + cache de archivo + sidecar ─────────────────────────────────────


def _descargar_bytes(url: str) -> bytes:
    """Descarga la imagen. Valida status y Content-Type (cuando esta disponible)."""
    try:
        resp = requests.get(url, timeout=TIMEOUT_S)
    except requests.Timeout as e:
        raise PexelsTimeout("timeout al descargar la imagen") from e
    except requests.RequestException as e:
        raise PexelsDescargaError(f"error de red al descargar: {type(e).__name__}") from e
    if not (200 <= resp.status_code < 300):
        raise PexelsDescargaError(f"HTTP {resp.status_code} al descargar la imagen")
    ct = (resp.headers.get("Content-Type") or "").lower()
    if ct and not ct.startswith("image/"):
        raise PexelsDescargaError(f"Content-Type no es imagen: {ct}")
    return resp.content


def descargar_asset(
    asset: StockAsset,
    cache_dir: Path | None = None,
    destino: str = "vertical",
    fit: str = "cover",
    ahora_utc: str | None = None,
) -> StockAsset:
    """Descarga (o reutiliza de cache) la imagen del asset y escribe su sidecar.

    La VARIANTE se resuelve ANTES de la ruta: la identidad del cache es provider+asset_id+
    variante (`pexels_{id}_{variante}.{ext}`), asi dos variantes del mismo id nunca colisionan;
    la extension viene de la FIRMA de bytes. Cache hit solo si la imagen existe y sigue siendo
    imagen valida Y el sidecar coincide en provider, asset_id, selected_variant y download_url
    con la seleccion actual; cualquier desajuste re-descarga. Escritura atomica (tmp+os.replace).
    Devuelve una instancia frozen con selected_variant, selection_reason, download_url, local_path
    y metadata_path.
    """
    seleccion = seleccionar_variante(asset.src, destino=destino, fit=fit)
    cache = Path(cache_dir) if cache_dir is not None else _base.CACHE_ROOT
    cache.mkdir(parents=True, exist_ok=True)
    stem = _base._stem_cache(asset, seleccion.nombre)
    sidecar_path = cache / f"{stem}.json"
    ahora = ahora_utc or _base._utc_now_iso()
    elegido = replace(
        asset,
        download_url=seleccion.url,
        selected_variant=seleccion.nombre,
        selection_reason=seleccion.motivo,
    )

    img_cacheada = _base._imagen_cacheada(cache, stem)
    if (
        img_cacheada is not None
        and _base._imagen_valida(img_cacheada)
        and _base._cache_hit_valido(sidecar_path, elegido)
    ):
        # Cache hit: refresca query/selection_reason/last_used_utc; downloaded_utc intacto.
        _base._refrescar_sidecar(sidecar_path, elegido, ahora)
        return replace(elegido, local_path=img_cacheada, metadata_path=sidecar_path)

    datos = _descargar_bytes(seleccion.url)
    if not datos:
        raise PexelsDescargaError("la descarga quedo vacia (0 bytes)")
    ext = _base._firma_imagen(datos)
    if ext is None:
        raise PexelsDescargaError("el contenido descargado no es una imagen jpg/png/webp")

    img_path = cache / f"{stem}.{ext}"
    _base._escribir_atomico(img_path, datos)
    descargado = replace(elegido, local_path=img_path)
    _base._escribir_json_atomico(sidecar_path, _base._sidecar_dict(descargado, img_path, ahora))
    return replace(descargado, metadata_path=sidecar_path)
