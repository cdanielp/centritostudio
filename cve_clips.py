"""cve_clips.py - Resolucion de b-roll de VIDEO (source='pexels_video') -> ClipOverlay (PR B).

Hermana de `cve_popups` (que resuelve popups/cutaway de IMAGEN): lee el mismo sidecar manual
`{stem}_popups.json` y produce la lista de `clip_overlay.ClipOverlay` que compone
`core_ass.burn_video_with_emojis` via `core_overlays`. Se separa de `cve_popups` por la regla
anti-spaghetti (<=400 lineas) y porque el clip de video es un tipo/flujo distinto del Popup.

Contrato de errores POR CAPAS (DECISIONES D31): el puente `broll_video_cutaway` es HONESTO (propaga
el ValueError de contrato); este ADAPTADOR lo captura y omite SOLO esa entrada con log ASCII
accionable; los errores OPERATIVOS de Pexels ya vienen traducidos (clip=None + codigo); los bugs
(RuntimeError/TypeError/AssertionError) se PROPAGAN. V1: MAXIMO UN clip pexels_video por render.
"""

from __future__ import annotations

import json
from pathlib import Path

from cve_popups import TRANSCRIPTS_DIR, _leer_t_dur


def _entrada_pexels_video(i: int, entrada: dict, video_w: int | None, video_h: int | None):
    """Entrada explicita source='pexels_video' -> ClipOverlay cutaway via el puente de video.

    Captura el ValueError de contrato del puente (loop no booleano, fit!=cover, tiempos/size
    invalidos, mute!=True) y OMITE solo esta entrada con log; los bugs del puente se PROPAGAN
    (resolver_clips los contiene). Import LAZY: sin una entrada pexels_video no se toca la red.
    """
    if not video_w or not video_h:
        print(f"[clip] entrada #{i} pexels_video: faltan dimensiones de video, omitida")
        return None
    td = _leer_t_dur(i, entrada)
    if td is None:
        return None
    t0, dur = td
    query = str(entrada.get("query", "") or "").strip()
    fit = str(entrada.get("fit", "cover") or "cover").lower()
    behind = bool(entrada.get("behind_text", True))
    loop = entrada.get("loop", True)  # raw: el puente valida que sea booleano
    mute = entrada.get("mute", True)  # raw: V1 exige True (el clip va silenciado)
    try:
        source_start = float(entrada.get("source_start", 0.0))
        size_pct = float(entrada.get("size_pct", 1.0))
    except (TypeError, ValueError):
        print(f"[clip] entrada #{i} pexels_video: source_start/size_pct invalido, omitida")
        return None
    if mute is not True:
        print(
            f"[clip] entrada #{i} pexels_video: mute debe ser true en V1 (clip silenciado), omitida"
        )
        return None
    import broll_video_cutaway  # noqa: PLC0415  (lazy: sin entrada pexels_video no se toca la red)

    orientation, _destino = broll_video_cutaway.orientacion_para_video(video_w, video_h)
    try:
        res = broll_video_cutaway.resolver_cutaway_video_pexels(
            query, t0, t0 + dur, orientation=orientation, target_width=video_w,
            target_height=video_h, source_start=source_start, loop=loop, fit=fit,
            size_pct=size_pct, behind_text=behind,
        )  # fmt: skip
    except ValueError as e:
        print(f"[clip] entrada #{i} pexels_video invalida: {e}")
        return None
    if res.clip is None:
        print(f"[clip] entrada #{i} pexels_video omitida (code={res.codigo})")
        return None
    print(f"[clip] entrada #{i} pexels_video OK: id={res.asset.asset_id} -> {res.clip.clip.name}")
    return res.clip


def cargar_clips_manual(path: Path, video_w: int | None = None, video_h: int | None = None) -> list:
    """Lee {stem}_popups.json y extrae los clips de video (source='pexels_video').

    V1: MAXIMO UN clip por render -> se procesa la PRIMERA entrada pexels_video del JSON; las demas
    se omiten con log (las entradas PNG/imagen las procesa cve_popups.cargar_popups_manual, capa
    aparte). JSON invalido o no-lista -> [] con log, jamas rompe.
    """
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError) as e:
        print(f"[clip] {path.name} invalido ({e}) - clips omitidos")
        return []
    if not isinstance(data, list):
        print(f"[clip] {path.name} debe ser una lista JSON - clips omitidos")
        return []
    clips: list = []
    procesado = False
    for i, entrada in enumerate(data):
        if not isinstance(entrada, dict):
            continue
        if str(entrada.get("source", "") or "").strip().lower() != "pexels_video":
            continue
        if procesado:
            print(f"[clip] entrada #{i} pexels_video ignorada: V1 admite un solo clip por render")
            continue
        procesado = True
        c = _entrada_pexels_video(i, entrada, video_w, video_h)
        if c:
            clips.append(c)
    return clips


def resolver_clips(
    stem: str,
    transcripts_dir: Path | None = None,
    video_w: int | None = None,
    video_h: int | None = None,
) -> list:
    """Capa de clips de video (b-roll pexels_video) del sidecar manual {stem}_popups.json.

    Fail-open para lo OPERATIVO (JSON roto, fallo de Pexels ya traducido, entrada invalida) -> []
    con log. Los errores de PROGRAMACION (RuntimeError/TypeError/ValueError/AssertionError) se
    PROPAGAN a proposito (D31), igual que cve_popups.resolver_popups.
    """
    try:
        manual_path = (transcripts_dir or TRANSCRIPTS_DIR) / f"{stem}_popups.json"
        clips = cargar_clips_manual(manual_path, video_w, video_h)
        if clips:
            resumen = ", ".join(f"{c.clip.name}@{c.t0:.1f}s" for c in clips)
            print(f"[clip] {len(clips)} clip(s) de video: {resumen}")
        return clips
    except (RuntimeError, TypeError, ValueError, AssertionError):
        raise
    except Exception as e:
        print(f"[clip] resolucion de clips fallo ({e}) - capa de clips omitida")
        return []
