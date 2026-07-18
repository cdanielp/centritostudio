"""broll_planner.py — Planner PURO, determinista y auditable de b-roll (S37-A, DECISIONES D34).

brain senala, el planner DECIDE, auto orquesta (PR B), los resolvers descargan, el render
compone. Este modulo cubre solo el segundo eslabon: recibe groups + brain + duracion + config
y produce un BrollPlan v1 con ventanas, zonas protegidas, rechazos trazables y cobertura.

`plan_broll` es PURO: no lee red, reloj, random, entorno ni filesystem, y JAMAS muta sus
entradas. La E/S (leer fixtures, escribir el sidecar) vive en funciones aparte. No hay Pexels,
LLM, FFmpeg ni descargas: el planner solicita INTENCION (ventana + tipo + query), no assets.
"""

from __future__ import annotations

from broll_plan_io import broll_plan_to_dict, load_broll_inputs, write_broll_plan
from broll_plan_place import hook_end, place_signals
from broll_plan_query import clean_token, detect_motion
from broll_plan_types import (
    PLAN_VERSION,
    REJ_BRAIN_ITEM_NOT_OBJECT,
    REJ_GROUP_NOT_FOUND,
    REJ_GROUP_WORDS_INVALID,
    REJ_KEYWORD_EMPTY,
    REJ_KEYWORD_INDEX_INVALID,
    REJ_KEYWORD_NOT_SELECTED,
    REJ_KW_TS_INVALID,
    REJ_KW_TS_MISSING,
    REJ_KW_TS_OUT_OF_RANGE,
    TIME_EPS,
    WARN_BRAIN_MISSING_GROUPS,
    WARN_DISABLED_BY_CONFIG,
    ZONE_HOOK,
    ZONE_OUTRO,
    BrollConfig,
    BrollInputError,
    BrollPlan,
    BrollRejected,
    BrollSignal,
    ProtectedZone,
    _is_real,
    round_time,
)


# ----------------------------------------------------------------------------- #
# API publica                                                                   #
# ----------------------------------------------------------------------------- #
def plan_broll(
    groups: list[dict],
    brain_data: dict,
    clip_duration_s: float,
    config: BrollConfig | None = None,
) -> BrollPlan:
    """Construye un BrollPlan determinista a partir de senales del brain. PURO: no toca E/S."""
    cfg = config if config is not None else BrollConfig()
    if not _is_real(clip_duration_s) or clip_duration_s <= 0.0:
        raise BrollInputError("clip_duration_s debe ser un numero real finito > 0")
    if not isinstance(groups, list):
        raise BrollInputError("groups debe ser una lista")
    if not isinstance(brain_data, dict):
        raise BrollInputError("brain_data debe ser un dict")

    clip = float(clip_duration_s)
    zones = _protected_zones(clip, cfg)
    brain_groups, warnings = _brain_groups(brain_data)
    signals_total = len(brain_groups)

    if not cfg.enabled:
        return BrollPlan(
            version=PLAN_VERSION,
            clip_duration_s=round_time(clip),
            config=cfg,
            protected_zones=zones,
            windows=(),
            rejected=(),
            warnings=(WARN_DISABLED_BY_CONFIG, *warnings),
            signals_total=signals_total,
            candidates_valid=0,
        )

    candidates, struct_rejected = _extract_candidates(groups, brain_groups, clip)
    windows, place_rejected, place_warnings = place_signals(candidates, clip, cfg)
    return BrollPlan(
        version=PLAN_VERSION,
        clip_duration_s=round_time(clip),
        config=cfg,
        protected_zones=zones,
        windows=windows,
        rejected=tuple(struct_rejected) + tuple(place_rejected),
        warnings=tuple(warnings) + tuple(place_warnings),
        signals_total=signals_total,
        candidates_valid=len(candidates),
    )


# --- Zonas protegidas (la geometria hook/outro vive en broll_plan_place) ---
def _protected_zones(clip: float, cfg: BrollConfig) -> tuple[ProtectedZone, ...]:
    """Declara hook (siempre que sea > 0) y outro (solo preset premium con duracion util)."""
    zones: list[ProtectedZone] = []
    h_end = hook_end(clip, cfg)
    if h_end > TIME_EPS:
        zones.append(ProtectedZone("hook", 0.0, round_time(h_end), ZONE_HOOK))
    if cfg.reserves_outro:
        start = max(0.0, clip - cfg.premium_outro_s)
        if clip - start > TIME_EPS:
            zones.append(ProtectedZone("outro", round_time(start), round_time(clip), ZONE_OUTRO))
    return tuple(zones)


# ----------------------------------------------------------------------------- #
# Extraccion de senales                                                         #
# ----------------------------------------------------------------------------- #
def _brain_groups(brain_data: dict) -> tuple[list, list[str]]:
    """Lista de items del brain + warnings. Falta de 'groups' => vacio con warning razonable."""
    raw = brain_data.get("groups")
    if not isinstance(raw, list):
        return [], [WARN_BRAIN_MISSING_GROUPS]
    return raw, []


def _group_index(groups: list) -> dict[int, tuple[dict, int]]:
    """Mapa id -> (grupo, posicion). id duplicado: gana el primero (determinista)."""
    index: dict[int, tuple[dict, int]] = {}
    for pos, g in enumerate(groups):
        if not isinstance(g, dict):
            continue
        gid = g.get("id")
        if isinstance(gid, bool) or not isinstance(gid, int):
            continue
        if gid not in index:
            index[gid] = (g, pos)
    return index


def _group_text(group: dict, words: list) -> str:
    """Texto fuente del grupo: campo 'text' o reconstruccion desde words."""
    text = str(group.get("text", "") or "")
    if text.strip():
        return text
    return " ".join(str(w.get("text", "")) for w in words if isinstance(w, dict))


def _extract_candidates(
    groups: list, brain_groups: list, clip: float
) -> tuple[list[BrollSignal], list[BrollRejected]]:
    """Convierte items de brain en senales validas. Un item invalido no borra los validos."""
    index = _group_index(groups)
    candidates: list[BrollSignal] = []
    rejected: list[BrollRejected] = []
    for item in brain_groups:
        sig, rej = _candidate_from_item(item, index, clip)
        if sig is not None:
            candidates.append(sig)
        elif rej is not None:
            rejected.append(rej)
    return candidates, rejected


def _candidate_from_item(
    item: object, index: dict[int, tuple[dict, int]], clip: float
) -> tuple[BrollSignal | None, BrollRejected | None]:
    """Valida UN item de brain -> (senal, None) o (None, rechazo). kw=None no es error ruidoso."""
    if not isinstance(item, dict):
        return None, BrollRejected(REJ_BRAIN_ITEM_NOT_OBJECT, "item de brain no es objeto")
    gid = item.get("g")
    if isinstance(gid, bool) or not isinstance(gid, int) or gid not in index:
        return None, BrollRejected(REJ_GROUP_NOT_FOUND, f"grupo g={gid!r} inexistente")
    group, pos = index[gid]
    words = group.get("words")
    if not isinstance(words, list):
        return None, BrollRejected(REJ_GROUP_WORDS_INVALID, f"grupo {gid} sin words validas")
    kw = item.get("kw")
    if kw is None:
        return None, BrollRejected(REJ_KEYWORD_NOT_SELECTED, f"grupo {gid} sin keyword elegida")
    if isinstance(kw, bool) or not isinstance(kw, int) or not (0 <= kw < len(words)):
        return None, BrollRejected(REJ_KEYWORD_INDEX_INVALID, f"grupo {gid} kw={kw!r} invalido")
    word = words[kw]

    keyword = clean_token(str(word.get("text", "") or "")) if isinstance(word, dict) else ""
    if not keyword:
        return None, BrollRejected(REJ_KEYWORD_EMPTY, f"grupo {gid} keyword vacia")
    kw_ts = item.get("kw_ts")
    if kw_ts is None:
        return None, BrollRejected(REJ_KW_TS_MISSING, f"grupo {gid} sin kw_ts")
    if not _is_real(kw_ts):
        return None, BrollRejected(REJ_KW_TS_INVALID, f"grupo {gid} kw_ts no numerico")
    if kw_ts < 0.0 or kw_ts >= clip:
        return None, BrollRejected(REJ_KW_TS_OUT_OF_RANGE, f"grupo {gid} kw_ts fuera de [0, clip)")
    group_text = _group_text(group, words)
    motion = detect_motion(keyword, group_text)
    signal = BrollSignal(gid, pos, kw, keyword, round_time(kw_ts), group_text, motion)
    return signal, None


# La colocacion temporal + greedy de cobertura vive en broll_plan_place; la serializacion
# (contrato JSON v1) y la E/S del sidecar viven en broll_plan_io para
# mantener este modulo enfocado en el algoritmo puro. Se reexportan como API publica.
__all__ = [
    "plan_broll",
    "broll_plan_to_dict",
    "write_broll_plan",
    "load_broll_inputs",
]
