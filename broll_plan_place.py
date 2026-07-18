"""broll_plan_place.py — Colocacion temporal + greedy de cobertura (S37-A).

Geometria PURA y determinista: dado el conjunto de senales validas (en orden de brain),
coloca cada una anclada en su kw_ts dentro del hueco libre que la contiene, respetando
hook, outro premium, solapes y densidad (target/max). Nada de red, reloj, random ni disco.

El algoritmo es un greedy explicito en orden de brain (documentado en DECISIONES D34):
para cada senal se calcula la ventana [start, end); una ventana que termina justo donde
empieza otra NO se considera solape ([start, end) semiabierto).
"""

from __future__ import annotations

from broll_plan_query import build_query, fold
from broll_plan_types import (
    REASON_IMAGE_DEFAULT,
    REASON_VIDEO_DOWNGRADED,
    REASON_VIDEO_MOTION,
    REJ_DUPLICATE_QUERY,
    REJ_DURATION_BELOW_MIN,
    REJ_MAX_COVERAGE_EXCEEDED,
    REJ_OVERLAP_UNRESOLVABLE,
    REJ_PROTECTED_HOOK,
    REJ_PROTECTED_OUTRO,
    REJ_QUERY_EMPTY,
    REJ_TARGET_COVERAGE_REACHED,
    REJ_VIDEO_LIMIT_FALLBACK,
    TIME_EPS,
    WARN_NO_USABLE_TIMELINE,
    BrollConfig,
    BrollRejected,
    BrollSignal,
    BrollWindow,
    round_time,
)


def hook_end(clip: float, cfg: BrollConfig) -> float:
    """Fin del hook protegido, acotado al clip."""
    return min(cfg.hook_protected_s, clip)


def usable_end(clip: float, cfg: BrollConfig) -> float:
    """Inicio del outro premium (fin util) o el fin del clip si no se reserva outro."""
    return clip - cfg.premium_outro_s if cfg.reserves_outro else clip


class _Placed:
    """Registro mutable interno de una ventana aceptada (floats sin redondear para la geometria)."""

    __slots__ = ("start", "end", "dur", "media", "query", "reason", "signal", "query_terms")

    def __init__(self, start, end, dur, media, query, reason, signal, query_terms):
        self.start = start
        self.end = end
        self.dur = dur
        self.media = media
        self.query = query
        self.reason = reason
        self.signal = signal
        self.query_terms = query_terms


def place_signals(
    candidates: list[BrollSignal], clip: float, cfg: BrollConfig
) -> tuple[tuple[BrollWindow, ...], list[BrollRejected], list[str]]:
    """Greedy en orden de brain: coloca cada senal respetando zonas, solapes y densidad."""
    lower = hook_end(clip, cfg)
    upper = usable_end(clip, cfg)
    rejected: list[BrollRejected] = []
    warnings: list[str] = []
    if upper - lower <= TIME_EPS:
        warnings.append(WARN_NO_USABLE_TIMELINE)
    accepted: list[_Placed] = []
    seen_queries: set[str] = set()
    state = {"coverage_s": 0.0, "video_used": 0}
    budgets = (cfg.target_coverage_pct * clip, cfg.max_coverage_pct * clip)

    for sig in candidates:
        placed, rej, degraded = _try_place(
            sig, cfg, lower, upper, accepted, seen_queries, state, budgets
        )
        if rej is not None:
            rejected.append(rej)
            continue
        accepted.append(placed)
        state["coverage_s"] += placed.dur
        seen_queries.add(fold(placed.query))
        if placed.media == "video":
            state["video_used"] += 1
        if degraded is not None:
            rejected.append(degraded)
    return _finalize_windows(accepted), rejected, warnings


def _try_place(sig, cfg, lower, upper, accepted, seen_queries, state, budgets):
    """Evalua una senal -> (_Placed, None, degrade|None) o (None, rechazo, None)."""
    target_budget, max_budget = budgets
    coverage_s = state["coverage_s"]
    query, qterms, _ = build_query(sig.keyword, sig.group_text, cfg.max_query_terms)
    if not query:
        return None, BrollRejected(REJ_QUERY_EMPTY, "query vacia", sig), None
    if sig.kw_ts < lower - TIME_EPS:
        return None, BrollRejected(REJ_PROTECTED_HOOK, "ancla dentro del hook", sig), None
    if cfg.reserves_outro and sig.kw_ts >= upper - TIME_EPS:
        return None, BrollRejected(REJ_PROTECTED_OUTRO, "ancla dentro del outro premium", sig), None
    if coverage_s >= target_budget - TIME_EPS:
        return None, BrollRejected(REJ_TARGET_COVERAGE_REACHED, "target alcanzado", sig), None
    if fold(query) in seen_queries:
        return None, BrollRejected(REJ_DUPLICATE_QUERY, f"query duplicada: {query}", sig), None
    media, dims, reason, degraded = _decide_media(sig, cfg, state["video_used"])
    placement, code = _place_one(sig.kw_ts, cfg.lead_in_s, dims, lower, upper, accepted)
    if placement is None:
        return None, BrollRejected(code, "no cabe sin violar zonas/solapes", sig), None
    start, end, dur = placement
    if coverage_s + dur > max_budget + TIME_EPS:
        return None, BrollRejected(REJ_MAX_COVERAGE_EXCEEDED, "excede cobertura maxima", sig), None
    return _Placed(start, end, dur, media, query, reason, sig, qterms), None, degraded


def _decide_media(sig, cfg, video_used):
    """Decide image/video. Video solo con senal de movimiento y cupo disponible; si no, degrada."""
    wants_video = bool(sig.motion_terms)
    if wants_video and video_used < cfg.max_video_windows:
        dims = (cfg.video_min_s, cfg.video_preferred_s, cfg.video_max_s)
        return "video", dims, REASON_VIDEO_MOTION, None
    dims = (cfg.image_min_s, cfg.image_preferred_s, cfg.image_max_s)
    if wants_video:
        note = BrollRejected(
            REJ_VIDEO_LIMIT_FALLBACK, "cupo de video usado: colocada como imagen", sig
        )
        return "image", dims, REASON_VIDEO_DOWNGRADED, note
    return "image", dims, REASON_IMAGE_DEFAULT, None


def _place_one(anchor, lead_in, dims, lower, upper, accepted):
    """Coloca una ventana anclada en kw_ts dentro del hueco libre que la contiene."""
    dmin, dpref, dmax = dims
    if upper - lower <= TIME_EPS:
        return None, REJ_DURATION_BELOW_MIN
    gap = _gap_containing(anchor, _free_gaps(lower, upper, accepted))
    if gap is None:
        return None, REJ_OVERLAP_UNRESOLVABLE
    glo, ghi = gap
    available = ghi - glo
    if available < dmin - TIME_EPS:
        bounded = glo > lower + TIME_EPS or ghi < upper - TIME_EPS
        return None, (REJ_OVERLAP_UNRESOLVABLE if bounded else REJ_DURATION_BELOW_MIN)
    dur = min(dpref, available, dmax)
    start = min(max(anchor - lead_in, glo), ghi - dur)
    if start < glo:
        start = glo
    return (start, start + dur, dur), None


def _free_gaps(lower, upper, accepted):
    """Huecos libres en [lower, upper) tras excluir las ventanas ya aceptadas (no solapadas)."""
    occ = sorted((a.start, a.end) for a in accepted)
    gaps: list[tuple[float, float]] = []
    cur = lower
    for s, e in occ:
        s = max(s, lower)
        e = min(e, upper)
        if s > cur + TIME_EPS:
            gaps.append((cur, s))
        cur = max(cur, e)
        if cur >= upper - TIME_EPS:
            break
    if cur < upper - TIME_EPS:
        gaps.append((cur, upper))
    return gaps


def _gap_containing(anchor, gaps):
    """Hueco [lo, hi) que contiene el ancla; None si cae dentro de una ventana aceptada."""
    for glo, ghi in gaps:
        if glo - TIME_EPS <= anchor < ghi - TIME_EPS:
            return (glo, ghi)
    return None


def _finalize_windows(accepted: list[_Placed]) -> tuple[BrollWindow, ...]:
    """Ordena por inicio y asigna IDs deterministas broll-0001.. (redondea a la salida)."""
    accepted.sort(key=lambda p: (p.start, p.end))
    windows: list[BrollWindow] = []
    for i, p in enumerate(accepted, start=1):
        start = round_time(p.start)
        end = round_time(p.end)
        windows.append(
            BrollWindow(
                window_id=f"broll-{i:04d}",
                start_s=start,
                end_s=end,
                duration_s=round_time(end - start),
                media_type=p.media,
                query=p.query,
                reason=p.reason,
                signal=p.signal,
                query_terms=p.query_terms,
            )
        )
    return tuple(windows)


__all__ = ["hook_end", "usable_end", "place_signals"]
