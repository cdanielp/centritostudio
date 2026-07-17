"""broll_cutaway.py - Puente entre el fetcher Pexels y un Popup cutaway (feat/broll-pexels-cutaway).

Contrato publico pequeno y auditable que convierte una entrada explicita de b-roll Pexels en
un `Popup(cutaway=True)` listo para el plan de overlays:

    query -> buscar_broll_seguro() -> primer candidato -> descargar_asset() -> Popup(cutaway=True)

Reutiliza COMPLETAMENTE el fetcher (`broll_stock`): no hay HTTP, ni cache, ni sidecar, ni la
API key aqui. La geometria del cutaway (centrado, fit, size_pct) es la ya implementada en
`core_overlays.Popup` / `_preparar_cutaway`; este modulo no la duplica.

Fail-open acotado (regla #16, mismo criterio que el fetcher): los errores OPERATIVOS conocidos
(familia `PexelsError`: sin key, 429, auth, timeout, HTTP, JSON invalido, sin variante, descarga)
se traducen a un `ResultadoCutawayPexels` SIN popup y con codigo/mensaje auditable -> el render
omite ese b-roll y sigue. Cero resultados NO es excepcion: devuelve codigo "sin_resultados".
Los errores de PROGRAMACION (RuntimeError/TypeError/AssertionError) y de ENTRADA (ValueError por
query vacia, t1<=t0, fit/size_pct/orientation invalidos) se PROPAGAN: no se ocultan bugs ni se
confunde un contrato roto con un fallo de red.

Seguridad (regla #9): jamas se imprime ni serializa la PEXELS_API_KEY (el fetcher ya la protege;
aqui solo pasan mensajes ya saneados por `buscar_broll_seguro`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from broll_stock import (
    PexelsAuthError,
    PexelsDescargaError,
    PexelsDeshabilitado,
    PexelsError,
    PexelsHTTPError,
    PexelsRateLimit,
    PexelsRespuestaInvalida,
    PexelsSinVariante,
    PexelsTimeout,
    StockAsset,
    buscar_broll_seguro,
    descargar_asset,
)
from core_overlays import CUTAWAY_FIT, Popup

# Cuantos candidatos pedimos para tener de donde elegir. V1: se elige SIEMPRE el primero.
PER_PAGE = 15
SIZE_PCT_MIN = 0.05  # piso de cordura: un cutaway mas pequeno no tiene sentido como b-roll
SIZE_PCT_MAX = 1.0  # 1.0 = pantalla completa; el maximo admitido por el cutaway

# Orientaciones validas de Pexels (las que acepta la API en el parametro `orientation`).
ORIENTACIONES_PEXELS = frozenset({"portrait", "landscape", "square"})

# Error operativo de descarga -> codigo estable (mismos codigos que expone el fetcher). La
# busqueda ya viene con su codigo via `buscar_broll_seguro`; esto cubre solo el paso descargar.
_CODIGO_DESCARGA = {
    PexelsRateLimit: "rate_limit",
    PexelsAuthError: "auth",
    PexelsTimeout: "timeout",
    PexelsHTTPError: "http",
    PexelsRespuestaInvalida: "respuesta_invalida",
    PexelsSinVariante: "sin_variante",
    PexelsDescargaError: "descarga",
    PexelsDeshabilitado: "deshabilitado",
}


@dataclass(frozen=True)
class ResultadoCutawayPexels:
    """Resultado del puente: un Popup listo (`ok`) o una omision auditable (sin popup).

    `codigo` == "ok" -> `popup` presente y `asset` es el StockAsset descargado (metadata segura
    para evidencia: id, autor, dimensiones, variante, rutas). Cualquier otro codigo -> `popup` es
    None y `mensaje` explica por que se omitio (sin secretos). Nunca finge exito.
    """

    popup: Popup | None
    codigo: str
    mensaje: str
    asset: StockAsset | None = None


def orientacion_para_video(video_w: int, video_h: int) -> tuple[str, str]:
    """Mapea el aspecto del video a (orientation_pexels, destino) SIN hardcodear vertical.

    - vertical (h > w, p.ej. 9:16)  -> ("portrait", "vertical")
    - horizontal o cuadrado (w >= h) -> ("landscape", "horizontal")
    `destino` es lo que consume `descargar_asset` para ordenar las variantes de cover.
    """
    if video_h > video_w:
        return "portrait", "vertical"
    return "landscape", "horizontal"


def _destino_de_orientacion(orientation: str) -> str:
    """Destino para `descargar_asset` (orden de variantes cover). square -> horizontal."""
    return "vertical" if orientation == "portrait" else "horizontal"


def _validar_entrada(query: str, t0: float, t1: float, orientation: str, fit: str, size_pct: float):
    """Valida el CONTRATO de entrada. Errores de contrato -> ValueError (se propaga, no es red)."""
    if not (query or "").strip():
        raise ValueError("query vacia: se requiere un termino de busqueda para el b-roll Pexels")
    if t0 < 0:
        raise ValueError(f"t0 invalido: {t0!r} (debe ser >= 0)")
    if t1 <= t0:
        raise ValueError(f"ventana invalida: t1 ({t1}) debe ser > t0 ({t0})")
    if fit not in CUTAWAY_FIT:
        raise ValueError(f"fit invalido: {fit!r} (usa {sorted(CUTAWAY_FIT)})")
    if not (SIZE_PCT_MIN <= size_pct <= SIZE_PCT_MAX):
        raise ValueError(f"size_pct fuera de rango: {size_pct!r} (permitido [{SIZE_PCT_MIN}, 1.0])")
    if orientation not in ORIENTACIONES_PEXELS:
        raise ValueError(
            f"orientation invalida: {orientation!r} (usa {sorted(ORIENTACIONES_PEXELS)})"
        )


def resolver_cutaway_pexels(
    query: str,
    t0: float,
    t1: float,
    *,
    orientation: str,
    fit: str = "cover",
    size_pct: float = 1.0,
    behind_text: bool = True,
    cache_dir: Path | None = None,
) -> ResultadoCutawayPexels:
    """Resuelve una entrada explicita de b-roll Pexels a un Popup cutaway (o una omision).

    La duracion y posicion en el tiempo vienen de la ENTRADA (t0/t1); Pexels no decide timestamps.
    Seleccion determinista: el PRIMER candidato devuelto por el fetcher. Fail-open para
    `PexelsError`; ValueError de contrato y errores de programacion se propagan (ver docstring).
    """
    _validar_entrada(query, t0, t1, orientation, fit, size_pct)

    resultado = buscar_broll_seguro(query, orientation=orientation, per_page=PER_PAGE)
    if resultado.error is not None:
        return ResultadoCutawayPexels(None, resultado.error.code, resultado.error.message)
    if not resultado.assets:
        return ResultadoCutawayPexels(
            None, "sin_resultados", f"Pexels no devolvio imagenes para {query!r}"
        )

    candidato = resultado.assets[0]  # V1: primer candidato valido, determinista
    destino = _destino_de_orientacion(orientation)
    try:
        descargado = descargar_asset(candidato, cache_dir=cache_dir, destino=destino, fit=fit)
    except PexelsError as e:
        codigo = _CODIGO_DESCARGA.get(type(e), "error")
        return ResultadoCutawayPexels(None, codigo, str(e))

    popup = Popup(
        png=descargado.local_path,
        t0=t0,
        t1=t1,
        pos="center",
        size_pct=size_pct,
        behind_text=behind_text,
        cutaway=True,
        fit=fit,
    )
    return ResultadoCutawayPexels(popup, "ok", "b-roll cutaway Pexels listo", asset=descargado)
