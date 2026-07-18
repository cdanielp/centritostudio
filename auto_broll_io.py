"""auto_broll_io.py — Materializacion de la resolucion de b-roll v2 (S37-B, #47c).

Split de auto_broll.py (limite <=400 lineas): aqui vive la escritura de los sidecars
AUTOMATICOS — `{stem}_popups.auto.json` (lista compatible con el formato manual, solo
lo que realmente llego al render) y `{stem}_broll_resolved.json` (auditoria versionada).
El sidecar MANUAL `{stem}_popups.json` jamas se escribe desde aqui.

Escritura atomica con temporal UNICO (tempfile.mkstemp en el mismo directorio): seguro
ante escrituras concurrentes. Sin URLs, sin API keys, sin rutas absolutas en los JSON.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

RESOLVED_VERSION = 1
CACHE_POLICY = "existing_fetcher_cache"  # #47f: cache de los fetchers, sin cache paralela


def escribir_json_atomico(path: Path, payload: dict | list) -> Path:
    """Escritura atomica con temporal UNICO en el mismo directorio (seguro concurrente)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    texto = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(texto)
        os.replace(tmp, path)
    except OSError:
        if tmp.exists():
            tmp.unlink()
        raise
    return path


def entradas_popups_auto(decisiones: tuple[dict, ...]) -> list[dict]:
    """Lista compatible con el formato manual: SOLO lo que realmente llego al render.

    El tipo `source` refleja el media FINAL real (un fallback video->imagen sale como
    imagen). Sin URLs, sin keys, sin rutas (la query permite re-resolver en reanudacion).
    """
    out: list[dict] = []
    for d in decisiones:
        final = d.get("final_media_type")
        if final not in ("image", "video"):
            continue
        base = {
            "t": d["start_s"],
            "dur": round(d["end_s"] - d["start_s"], 3),
            "query": d["query"],
            "fit": "cover",
            "size_pct": 1.0,
            "behind_text": True,
            "planner_window_id": d["window_id"],
        }
        if final == "video":
            base.update(
                {"source": "pexels_video", "source_start": 0.0, "loop": False, "mute": True}
            )
        else:
            base["source"] = "pexels"
        out.append(base)
    return out


def construir_resolved(
    plan_dict: dict,
    decisiones: tuple[dict, ...],
    occupied_intervals: list[tuple[float, float]],
    n_manual_popups: int,
    n_manual_clips: int,
    clip_meta: dict,
    fingerprint: str,
) -> dict:
    """Auditoria versionada de la resolucion (#47c). Sin secretos/URLs/rutas absolutas."""
    finales = [d for d in decisiones if d.get("final_media_type") in ("image", "video")]
    coverage_s = round(sum(d["end_s"] - d["start_s"] for d in finales), 3)
    dur = float(clip_meta.get("duration_s") or 0.0)
    return {
        "version": RESOLVED_VERSION,
        "planner_version": plan_dict.get("version"),
        "mode": "v2",
        "config_fingerprint": fingerprint,
        "clip": clip_meta,
        "cache_policy": CACHE_POLICY,
        "manual": {
            "popups": n_manual_popups,
            "clips": n_manual_clips,
            "occupied_intervals": [list(i) for i in occupied_intervals],
        },
        "requested_windows": len(plan_dict.get("windows", [])),
        "resolved": sum(1 for d in decisiones if d.get("status") == "resolved"),
        "fallbacks": sum(1 for d in decisiones if d.get("status") == "fallback"),
        "blocked": sum(1 for d in decisiones if d.get("status") == "blocked"),
        "omitted": sum(1 for d in decisiones if d.get("status") == "omitted"),
        "final": {
            "images": sum(1 for d in finales if d["final_media_type"] == "image"),
            "videos": sum(1 for d in finales if d["final_media_type"] == "video"),
            "coverage_s": coverage_s,
            "coverage_pct": round(coverage_s / dur, 3) if dur > 0 else 0.0,
        },
        "decisions": list(decisiones),
    }


__all__ = [
    "RESOLVED_VERSION",
    "CACHE_POLICY",
    "escribir_json_atomico",
    "entradas_popups_auto",
    "construir_resolved",
]
