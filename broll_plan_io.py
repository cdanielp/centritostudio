"""broll_plan_io.py — Serializacion (contrato JSON v1) y escritura del sidecar (S37-A).

Separado del nucleo del planner: `broll_planner.plan_broll` es PURO y no toca disco;
aqui vive la conversion a dict serializable, la escritura ATOMICA de
`{stem}_broll_plan.json` y la carga de fixtures. Sin rutas absolutas, sin bytes, sin
secretos ni datos de Pexels en la salida. `ensure_ascii=False` preserva acentos/enie.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from broll_plan_types import (
    PLANNER_NAME,
    SIGNAL_SOURCE,
    TIME_EPS,
    BrollConfig,
    BrollInputError,
    BrollPlan,
    BrollSignal,
    BrollWindow,
    round_time,
)


def _signal_to_dict(sig: BrollSignal) -> dict:
    return {
        "group_id": sig.group_id,
        "group_position": sig.group_position,
        "keyword_index": sig.keyword_index,
        "keyword": sig.keyword,
        "kw_ts": round_time(sig.kw_ts),
        "group_text": sig.group_text,
    }


def _window_to_dict(w: BrollWindow) -> dict:
    return {
        "id": w.window_id,
        "start_s": w.start_s,
        "end_s": w.end_s,
        "duration_s": w.duration_s,
        "media_type": w.media_type,
        "query": w.query,
        "reason": w.reason,
        "signal": _signal_to_dict(w.signal),
        "trace": {
            "motion_terms": list(w.signal.motion_terms),
            "query_terms": list(w.query_terms),
            "source": SIGNAL_SOURCE,
        },
    }


def _summary(plan: BrollPlan) -> dict:
    coverage_s = round_time(sum(w.duration_s for w in plan.windows))
    pct = round_time(coverage_s / plan.clip_duration_s) if plan.clip_duration_s > 0 else 0.0
    n_video = sum(1 for w in plan.windows if w.media_type == "video")
    return {
        "signals_total": plan.signals_total,
        "candidates_valid": plan.candidates_valid,
        "windows_planned": len(plan.windows),
        "image_windows": len(plan.windows) - n_video,
        "video_windows": n_video,
        "coverage_s": coverage_s,
        "coverage_pct": pct,
        "target_coverage_pct": plan.config.target_coverage_pct,
        "max_coverage_pct": plan.config.max_coverage_pct,
        "target_reached": pct >= plan.config.target_coverage_pct - TIME_EPS
        and len(plan.windows) > 0,
    }


def _config_to_dict(cfg: BrollConfig) -> dict:
    return {
        "enabled": cfg.enabled,
        "target_coverage_pct": cfg.target_coverage_pct,
        "max_coverage_pct": cfg.max_coverage_pct,
        "hook_protected_s": cfg.hook_protected_s,
        "image_duration_s": {
            "min": cfg.image_min_s,
            "preferred": cfg.image_preferred_s,
            "max": cfg.image_max_s,
        },
        "video_duration_s": {
            "min": cfg.video_min_s,
            "preferred": cfg.video_preferred_s,
            "max": cfg.video_max_s,
        },
        "max_video_windows": cfg.max_video_windows,
        "fx_preset": cfg.fx_preset,
        "premium_outro_s": cfg.premium_outro_s,
        "lead_in_s": cfg.lead_in_s,
        "max_query_terms": cfg.max_query_terms,
    }


def broll_plan_to_dict(plan: BrollPlan) -> dict:
    """Serializa el plan al contrato JSON v1 (sin rutas, sin bytes; ensure_ascii=False amigable)."""
    return {
        "version": plan.version,
        "planner": PLANNER_NAME,
        "clip": {"duration_s": plan.clip_duration_s},
        "config": _config_to_dict(plan.config),
        "protected_zones": [
            {"kind": z.kind, "start_s": z.start_s, "end_s": z.end_s, "reason": z.reason}
            for z in plan.protected_zones
        ],
        "summary": _summary(plan),
        "windows": [_window_to_dict(w) for w in plan.windows],
        "rejected": [
            {
                "code": r.code,
                "reason": r.reason,
                "signal": _signal_to_dict(r.signal) if r.signal is not None else None,
            }
            for r in plan.rejected
        ],
        "warnings": list(plan.warnings),
    }


def write_broll_plan(plan: BrollPlan, destination: Path, *, overwrite: bool = False) -> Path:
    """Escribe el sidecar {stem}_broll_plan.json de forma atomica. No sobreescribe por default."""
    destination = Path(destination)
    if destination.suffix.lower() != ".json":
        raise BrollInputError(f"el destino debe terminar en .json: {destination.name}")
    if destination.is_dir():
        raise BrollInputError(f"el destino es un directorio: {destination}")
    if destination.exists() and not overwrite:
        raise BrollInputError(f"el destino ya existe (usa overwrite=True): {destination.name}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(broll_plan_to_dict(plan), ensure_ascii=False, indent=2) + "\n"
    tmp = destination.with_name(destination.name + ".tmp")
    try:
        tmp.write_text(payload, encoding="utf-8", newline="")
        os.replace(tmp, destination)
    except OSError:
        if tmp.exists():
            tmp.unlink()
        raise
    return destination


def load_broll_inputs(groups_path: Path, brain_path: Path) -> tuple[list, dict]:
    """Carga groups.json y brain.json desde disco. Separado de plan_broll (que es puro)."""
    groups = json.loads(Path(groups_path).read_text(encoding="utf-8"))
    brain = json.loads(Path(brain_path).read_text(encoding="utf-8"))
    if not isinstance(groups, list):
        raise BrollInputError("groups.json debe contener una lista")
    if not isinstance(brain, dict):
        raise BrollInputError("brain.json debe contener un objeto")
    return groups, brain


__all__ = [
    "broll_plan_to_dict",
    "write_broll_plan",
    "load_broll_inputs",
]
