"""broll_video_cutaway.py - Puente fetcher de VIDEOS Pexels -> ClipOverlay cutaway (PR B).

Contrato publico pequeno y auditable que convierte una entrada explicita de b-roll de video Pexels
en un `ClipOverlay(cutaway=True)` listo para el render:

    query -> buscar_video_broll_seguro() -> primer candidato -> descargar_video_asset -> ClipOverlay

Reutiliza COMPLETAMENTE el fetcher (`broll_video_stock`): no hay HTTP, ni cache, ni sidecar, ni la
API key aqui. La orientacion/destino se derivan del video con `broll_cutaway.orientacion_para_video`
(reuso del puente de imagen; no se duplica). Los timestamps los decide la ENTRADA, no Pexels.

Contrato de errores POR CAPAS (DECISIONES D31, igual criterio que la integracion de imagen D29):
- Este puente es HONESTO: el ValueError de contrato (query vacia, t1<=t0, source_start<0, fit,
  size_pct/loop/mute invalidos, orientation invalida) se PROPAGA. El adaptador de JSON manual
  (`cve_popups`) lo captura y omite SOLO esa entrada, sin derribar el render.
- Los errores OPERATIVOS de Pexels (familia `PexelsVideoError`: sin key/429/auth/timeout/http/JSON/
  sin variante/descarga) -> `ResultadoCutawayVideoPexels` SIN clip + codigo/mensaje auditable (se
  omite ese b-roll y sigue). Cero resultados = codigo "sin_resultados" (no excepcion).
- RuntimeError/TypeError/AssertionError (bugs) se PROPAGAN.

Seguridad (regla #9): jamas se imprime ni serializa la PEXELS_API_KEY (el fetcher ya la protege;
aqui solo pasan mensajes saneados por `buscar_video_broll_seguro`).
"""

from __future__ import annotations

from dataclasses import dataclass

import clip_overlay
from broll_cutaway import (
    orientacion_para_video,  # reuso: aspecto del video -> (orientation, destino)
)
from broll_video_stock import (
    PexelsVideoAuthError,
    PexelsVideoDescargaError,
    PexelsVideoDeshabilitado,
    PexelsVideoError,
    PexelsVideoHTTPError,
    PexelsVideoRateLimit,
    PexelsVideoRespuestaInvalida,
    PexelsVideoSinVariante,
    PexelsVideoTimeout,
    VideoStockAsset,
    buscar_video_broll_seguro,
    descargar_video_asset,
)
from clip_overlay import ClipOverlay

__all__ = ["ResultadoCutawayVideoPexels", "resolver_cutaway_video_pexels", "orientacion_para_video"]

PER_PAGE = 15  # cuantos candidatos pedimos; V1: se elige SIEMPRE el primero (determinista)

ORIENTACIONES_PEXELS = frozenset({"portrait", "landscape", "square"})

# Error operativo de descarga -> codigo estable (mismos codigos que expone el fetcher).
_CODIGO_DESCARGA = {
    PexelsVideoRateLimit: "rate_limit",
    PexelsVideoAuthError: "auth",
    PexelsVideoTimeout: "timeout",
    PexelsVideoHTTPError: "http",
    PexelsVideoRespuestaInvalida: "respuesta_invalida",
    PexelsVideoSinVariante: "sin_variante",
    PexelsVideoDescargaError: "descarga",
    PexelsVideoDeshabilitado: "deshabilitado",
}


@dataclass(frozen=True)
class ResultadoCutawayVideoPexels:
    """Resultado del puente: un ClipOverlay listo (`ok`) o una omision auditable (sin clip).

    `codigo == "ok"` -> `clip` presente y `asset` es el VideoStockAsset descargado (metadata segura
    para evidencia: id, file_id, autor, duracion, dimensiones, rutas). Otro codigo -> `clip`
    None y `mensaje` explica por que se omitio (sin secretos). Nunca finge exito.
    """

    clip: ClipOverlay | None
    codigo: str
    mensaje: str
    asset: VideoStockAsset | None = None


def _destino_de_orientacion(orientation: str) -> str:
    """Destino para `descargar_video_asset` (prioridad de orientacion). square -> horizontal."""
    return "vertical" if orientation == "portrait" else "horizontal"


def _validar_entrada(query, t0, t1, source_start, orientation, fit, size_pct, loop):
    """Valida el CONTRATO. Errores de contrato -> ValueError (se propaga; el adaptador lo omite)."""
    if not (query or "").strip():
        raise ValueError("query vacia: se requiere un termino de busqueda para el b-roll de video")
    if orientation not in ORIENTACIONES_PEXELS:
        raise ValueError(
            f"orientation invalida: {orientation!r} (usa {sorted(ORIENTACIONES_PEXELS)})"
        )
    # mute=True obligatorio en V1 (el audio del clip nunca entra); el puente siempre lo fija a True.
    clip_overlay.validar_clip_overlay(
        t0=t0, t1=t1, source_start=source_start, fit=fit, size_pct=size_pct, loop=loop, mute=True
    )


def resolver_cutaway_video_pexels(
    query: str,
    t0: float,
    t1: float,
    *,
    orientation: str,
    target_width: int,
    target_height: int,
    source_start: float = 0.0,
    loop: bool = True,
    fit: str = "cover",
    size_pct: float = 1.0,
    behind_text: bool = True,
) -> ResultadoCutawayVideoPexels:
    """Resuelve una entrada de b-roll de video Pexels a un ClipOverlay cutaway (o una omision).

    La duracion/posicion vienen de la ENTRADA (t0/t1); Pexels no decide timestamps. Seleccion
    determinista: el PRIMER candidato del fetcher. Fail-open para `PexelsVideoError`; ValueError de
    contrato y errores de programacion se propagan (ver docstring del modulo).
    """
    _validar_entrada(query, t0, t1, source_start, orientation, fit, size_pct, loop)

    resultado = buscar_video_broll_seguro(query, orientation=orientation, per_page=PER_PAGE)
    if resultado.error is not None:
        return ResultadoCutawayVideoPexels(None, resultado.error.code, resultado.error.message)
    if not resultado.assets:
        return ResultadoCutawayVideoPexels(
            None, "sin_resultados", f"Pexels no devolvio videos para {query!r}"
        )

    candidato = resultado.assets[0]  # V1: primer candidato valido, determinista
    destino = _destino_de_orientacion(orientation)
    try:
        descargado = descargar_video_asset(
            candidato, destino=destino, target_width=target_width, target_height=target_height
        )
    except PexelsVideoError as e:
        codigo = _CODIGO_DESCARGA.get(type(e), "error")
        return ResultadoCutawayVideoPexels(None, codigo, str(e))

    clip = ClipOverlay(
        clip=descargado.local_path,
        t0=t0,
        t1=t1,
        source_start=source_start,
        loop=loop,
        cutaway=True,
        fit=fit,
        size_pct=size_pct,
        behind_text=behind_text,
        mute=True,
    )
    return ResultadoCutawayVideoPexels(
        clip, "ok", "b-roll cutaway de video Pexels listo", descargado
    )
