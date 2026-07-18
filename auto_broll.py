"""auto_broll.py — Resolucion automatica de b-roll para el Modo Automatico v2 (S37-B, #47).

Consume el `BrollPlan` (S37-A) y lo convierte en Popups/ClipOverlays REALES usando los
fetchers existentes (broll_cutaway / broll_video_stock, con SU cache: #47f). Reglas #47:

- 47a: ningun video se loopea; si ningun candidato cubre la duracion pedida -> fallback a
  imagen (`video_no_cover_fallback_image`). Fallos operativos de video -> fallback a imagen.
- 47b: el sidecar manual GANA por conflicto temporal ([start, end), tocar borde no bloquea);
  la ventana auto bloqueada se omite ANTES de descargar (`manual_precedence`).
- 47c: fuentes separadas — el manual jamas se toca; lo automatico se materializa en
  `{stem}_popups.auto.json` (compatible con el formato manual) + `{stem}_broll_resolved.json`
  (auditoria); el render combina EN MEMORIA.

Los resolvers reales viven en funciones module-level monkeypatcheables (tests sin red);
las APIs publicas usan esos defaults. Errores OPERATIVOS de Pexels -> decision auditable y
se continua; ValueError de contrato y bugs se PROPAGAN (D31).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import auto_broll_io

# Reexport de la capa de materializacion (API publica de este modulo; split por lineas)
from auto_broll_io import (  # noqa: F401
    CACHE_POLICY,
    RESOLVED_VERSION,
    entradas_popups_auto,
    escribir_json_atomico,
)

PER_PAGE_VIDEO = 15

# Codigos estables de decision (#47)
COD_RESOLVED_IMAGE = "resolved_image"
COD_RESOLVED_VIDEO = "resolved_video"
COD_MANUAL_PRECEDENCE = "manual_precedence"
COD_MANUAL_VIDEO_SLOT = "manual_video_occupies_slot"
COD_VIDEO_NO_COVER = "video_no_cover_fallback_image"
COD_VIDEO_SEARCH_FB = "video_search_fallback_image"
COD_VIDEO_DOWNLOAD_FB = "video_download_fallback_image"
COD_IMAGE_SEARCH_OMIT = "image_search_omitted"
COD_IMAGE_DOWNLOAD_OMIT = "image_download_omitted"
COD_FALLBACK_FAILED = "fallback_image_failed"
COD_BROLL_DISABLED = "broll_disabled"
COD_PLANNER_EMPTY = "planner_empty"

# Codigos de imagen del puente que corresponden al paso de DESCARGA (no busqueda).
_CODIGOS_DESCARGA_IMAGEN = frozenset({"descarga", "sin_variante"})


@dataclass(frozen=True)
class ResolucionBroll:
    """Resultado de resolver el plan: overlays reales + decision auditable por ventana."""

    auto_popups: tuple
    auto_clips: tuple
    decisiones: tuple[dict, ...]


# ─────────────────────────────────────────────────────────────────────────────
# Sidecar manual (fuente intocable) + intervalos ocupados
# ─────────────────────────────────────────────────────────────────────────────


def cargar_manual(
    stem: str, transcripts_dir: Path, video_w: int, video_h: int
) -> tuple[list, list]:
    """(manual_popups, manual_clips) del sidecar `{stem}_popups.json`. JAMAS lo modifica.

    Reusa las capas existentes: cve_popups.cargar_popups_manual (PNG/pexels imagen) y
    cve_clips.cargar_clips_manual (pexels_video). NO usa resolver_popups: los disparos por
    keyword de biblioteca son automatismo, no intencion manual. Fail-open operativo interno.
    """
    from cve_clips import cargar_clips_manual  # noqa: PLC0415 (lazy: classic no toca esta capa)
    from cve_popups import cargar_popups_manual, indexar_biblioteca  # noqa: PLC0415

    path = Path(transcripts_dir) / f"{stem}_popups.json"
    biblioteca = indexar_biblioteca()
    popups = cargar_popups_manual(path, biblioteca, video_w, video_h)
    clips = cargar_clips_manual(path, video_w, video_h)
    return popups, clips


def intervalos_manual(popups: list, clips: list) -> list[tuple[float, float]]:
    """Intervalos [t0, t1) ocupados por TODO elemento manual resuelto (popup o clip)."""
    out = [(float(p.t0), float(p.t1)) for p in popups]
    out += [(float(c.t0), float(c.t1)) for c in clips]
    return sorted(out)


def _overlap(a0: float, a1: float, b0: float, b1: float) -> bool:
    """[start, end): tocar borde NO es traslape."""
    return a0 < b1 and b0 < a1


def _bloqueada(w, ocupados: list[tuple[float, float]]) -> bool:
    return any(_overlap(w.start_s, w.end_s, b0, b1) for b0, b1 in ocupados)


# ─────────────────────────────────────────────────────────────────────────────
# Resolvers default (module-level: los tests los monkeypatchean; sin red aqui)
# ─────────────────────────────────────────────────────────────────────────────


def _resolve_image(query: str, t0: float, t1: float, video_w: int, video_h: int):
    """Default real: puente de imagen existente (cover, pantalla completa, behind_text)."""
    import broll_cutaway  # noqa: PLC0415 (lazy: sin ventana image no se importa Pexels)

    orientation, _ = broll_cutaway.orientacion_para_video(video_w, video_h)
    return broll_cutaway.resolver_cutaway_pexels(
        query, t0, t1, orientation=orientation, fit="cover", size_pct=1.0, behind_text=True
    )


def _search_videos(query: str, video_w: int, video_h: int):
    """Default real: busqueda fail-open del fetcher de videos (orden determinista)."""
    import broll_cutaway  # noqa: PLC0415
    import broll_video_stock  # noqa: PLC0415

    orientation, _ = broll_cutaway.orientacion_para_video(video_w, video_h)
    return broll_video_stock.buscar_video_broll_seguro(
        query, orientation=orientation, per_page=PER_PAGE_VIDEO
    )


def _download_video(asset, video_w: int, video_h: int):
    """Default real: descarga con cache del fetcher (#47f). PexelsVideoError se propaga aqui."""
    import broll_cutaway  # noqa: PLC0415
    import broll_video_stock  # noqa: PLC0415

    _, destino = broll_cutaway.orientacion_para_video(video_w, video_h)
    return broll_video_stock.descargar_video_asset(
        asset, destino=destino, target_width=video_w, target_height=video_h
    )


def _meta_imagen(asset) -> dict:
    """Metadata SEGURA del asset de imagen: sin URL, sin key, sin ruta absoluta."""
    return {
        "provider": asset.provider,
        "asset_id": asset.asset_id,
        "author": asset.author,
        "width": asset.width,
        "height": asset.height,
        "local_basename": asset.local_path.name if asset.local_path else None,
    }


def _meta_video(asset) -> dict:
    """Metadata SEGURA del asset de video (incluye duracion remota y variante)."""
    return {
        "provider": asset.provider,
        "asset_id": asset.asset_id,
        "author": asset.author,
        "width": asset.width,
        "height": asset.height,
        "duration_s": asset.duration,
        "file_id": asset.selected_file_id,
        "local_basename": asset.local_path.name if asset.local_path else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Resolucion del plan
# ─────────────────────────────────────────────────────────────────────────────


def _decision(w, final, status, code, message, asset=None, steps=None) -> dict:
    return {
        "window_id": w.window_id,
        "requested_media_type": w.media_type,
        "final_media_type": final,
        "query": w.query,
        "start_s": w.start_s,
        "end_s": w.end_s,
        "status": status,
        "code": code,
        "message": message,
        "asset": asset,
        "steps": list(steps or []),
    }


def _resolver_imagen(w, video_w, video_h, resolve_image_fn, steps):
    """Ventana -> Popup de imagen o decision de omision. ValueError de contrato PROPAGA."""
    res = resolve_image_fn(w.query, w.start_s, w.end_s, video_w, video_h)
    if res.popup is not None:
        code = steps[-1] if steps else COD_RESOLVED_IMAGE
        status = "fallback" if steps else "resolved"
        return res.popup, _decision(
            w, "image", status, code, res.mensaje, _meta_imagen(res.asset), steps
        )
    fallo = (
        COD_IMAGE_DOWNLOAD_OMIT if res.codigo in _CODIGOS_DESCARGA_IMAGEN else COD_IMAGE_SEARCH_OMIT
    )
    if steps:  # la imagen era el fallback de un video que ya fallo -> ambos pasos registrados
        return None, _decision(
            w, None, "omitted", COD_FALLBACK_FAILED, res.mensaje, None, [*steps, fallo]
        )
    return None, _decision(w, None, "omitted", fallo, res.mensaje, None, [res.codigo])


def _resolver_video(w, video_w, video_h, fns):
    """Ventana video -> (ClipOverlay, decision) o fallback a imagen (#47a). Sin loop."""
    from broll_video_stock import PexelsVideoError  # noqa: PLC0415

    resolve_image_fn, search_fn, download_fn = fns
    resultado = search_fn(w.query, video_w, video_h)
    if resultado.error is not None:
        return None, *_fallback_imagen(w, video_w, video_h, resolve_image_fn, COD_VIDEO_SEARCH_FB)
    candidato = next((a for a in resultado.assets if a.duration >= w.duration_s), None)
    if candidato is None:
        return None, *_fallback_imagen(w, video_w, video_h, resolve_image_fn, COD_VIDEO_NO_COVER)
    try:
        descargado = download_fn(candidato, video_w, video_h)
    except PexelsVideoError:
        return None, *_fallback_imagen(w, video_w, video_h, resolve_image_fn, COD_VIDEO_DOWNLOAD_FB)
    from clip_overlay import ClipOverlay  # noqa: PLC0415

    clip = ClipOverlay(
        clip=descargado.local_path,
        t0=w.start_s,
        t1=w.end_s,
        source_start=0.0,
        loop=False,  # #47a: NUNCA loop automatico en V1
        cutaway=True,
        fit="cover",
        size_pct=1.0,
        behind_text=True,
        mute=True,
    )
    dec = _decision(
        w,
        "video",
        "resolved",
        COD_RESOLVED_VIDEO,
        "video cubre la ventana",
        _meta_video(descargado),
    )
    return clip, None, dec


def _fallback_imagen(w, video_w, video_h, resolve_image_fn, paso_video):
    """El video no se pudo usar -> intenta imagen registrando el paso previo."""
    popup, dec = _resolver_imagen(w, video_w, video_h, resolve_image_fn, [paso_video])
    return popup, dec


def resolver_plan(
    plan,
    manual_popups: list,
    manual_clips: list,
    video_w: int,
    video_h: int,
    *,
    broll_enabled: bool = True,
    resolve_image_fn=None,
    search_video_fn=None,
    download_video_fn=None,
) -> ResolucionBroll:
    """Resuelve las ventanas del BrollPlan a overlays reales aplicando #47a/b.

    Orden determinista (ventanas del plan, ya ordenadas por inicio). Manual gana por
    conflicto SIN descargar el asset bloqueado. Slot de video: si hay clip manual o ya se
    resolvio un video automatico, la ventana video se degrada a imagen.
    """
    resolve_image_fn = resolve_image_fn or _resolve_image
    search_video_fn = search_video_fn or _search_videos
    download_video_fn = download_video_fn or _download_video

    if not broll_enabled:
        dec = {
            "window_id": None,
            "status": "disabled",
            "code": COD_BROLL_DISABLED,
            "message": "b-roll automatico desactivado por config",
        }
        return ResolucionBroll((), (), (dec,))
    if not plan.windows:
        dec = {
            "window_id": None,
            "status": "empty",
            "code": COD_PLANNER_EMPTY,
            "message": "el planner no produjo ventanas",
        }
        return ResolucionBroll((), (), (dec,))

    ocupados = intervalos_manual(manual_popups, manual_clips)
    slot_video_ocupado = bool(manual_clips)
    popups: list = []
    clips: list = []
    decisiones: list[dict] = []

    for w in plan.windows:
        if _bloqueada(w, ocupados):
            decisiones.append(
                _decision(
                    w,
                    None,
                    "blocked",
                    COD_MANUAL_PRECEDENCE,
                    "ventana en conflicto con elemento manual (manual gana, no se descarga)",
                )
            )
            continue
        if w.media_type == "video" and slot_video_ocupado:
            popup, dec = _resolver_imagen(
                w, video_w, video_h, resolve_image_fn, [COD_MANUAL_VIDEO_SLOT]
            )
            if popup is not None:
                popups.append(popup)
            decisiones.append(dec)
            continue
        if w.media_type == "video":
            clip, popup_fb, dec = _resolver_video(
                w, video_w, video_h, (resolve_image_fn, search_video_fn, download_video_fn)
            )
            if clip is not None:
                clips.append(clip)
                slot_video_ocupado = True
            elif popup_fb is not None:
                popups.append(popup_fb)
            decisiones.append(dec)
            continue
        popup, dec = _resolver_imagen(w, video_w, video_h, resolve_image_fn, [])
        if popup is not None:
            popups.append(popup)
        decisiones.append(dec)

    return ResolucionBroll(tuple(popups), tuple(clips), tuple(decisiones))


# ─────────────────────────────────────────────────────────────────────────────
# Materializacion (#47c): delega en auto_broll_io (split por limite de lineas)
# ─────────────────────────────────────────────────────────────────────────────


def construir_resolved(
    plan_dict: dict,
    resolucion: ResolucionBroll,
    manual_popups: list,
    manual_clips: list,
    clip_meta: dict,
    fingerprint: str,
) -> dict:
    """Auditoria versionada de la resolucion (#47c). Ensambla en auto_broll_io."""
    return auto_broll_io.construir_resolved(
        plan_dict,
        resolucion.decisiones,
        intervalos_manual(manual_popups, manual_clips),
        len(manual_popups),
        len(manual_clips),
        clip_meta,
        fingerprint,
    )


__all__ = [
    "CACHE_POLICY",
    "RESOLVED_VERSION",
    "ResolucionBroll",
    "cargar_manual",
    "intervalos_manual",
    "resolver_plan",
    "entradas_popups_auto",
    "construir_resolved",
    "escribir_json_atomico",
]
