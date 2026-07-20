"""cve_sidecar.py — Sidecar de transparencia del CVE (D21).

Registro de que keywords automaticas lleva un render y por que (palabra, timestamp,
grupo/frase, regla R1-R7 | brain | manual, fuente, preset y densidad usados).
Consumido via cve.py (re-export): CLI y Studio comparten la misma fuente.
"""

from __future__ import annotations

import json
from pathlib import Path


def _fuente_de_regla(regla: str) -> str:
    if regla == "brain":
        return "brain"
    if regla.startswith("manual"):
        return "manual"
    return "regla"


def construir_seleccion(groups: list[dict], plan) -> dict:
    """Registro puro de la seleccion de keywords de un render (plan = RenderPlan)."""
    keywords = []
    for g_idx, g in enumerate(groups):
        for w in g.get("words", []):
            if not (w.get("is_keyword") and w.get("kw_regla")):
                continue
            regla = str(w["kw_regla"])
            keywords.append(
                {
                    "palabra": w.get("text", ""),
                    "timestamp": w.get("start"),
                    "grupo": g_idx,
                    "frase": g.get("text", ""),
                    "regla": regla,
                    "fuente": _fuente_de_regla(regla),
                }
            )
    # Transparencia F6: posicion resuelta por grupo (avoid_faces / [center]); solo los
    # grupos que difieren del default bottom. Saneado: sin rutas ni datos del detector.
    posiciones = [
        {"grupo": g_idx, "posicion": g["caption_pos"]}
        for g_idx, g in enumerate(groups)
        if g.get("caption_pos") and g["caption_pos"] != "bottom"
    ]
    return {
        "preset": plan.preset,
        "densidad": plan.kw_densidad,
        "punch_scale": plan.kw_punch_scale,
        "keywords": keywords,
        # Transparencia D22: palabras que el filtro anti-debil rechazo (brain stopwords/cortas).
        "descartadas": list(getattr(plan, "kw_descartadas", []) or []),
        "posiciones": posiciones,
    }


def escribir_sidecar_seleccion(groups: list[dict], plan, out_video: Path) -> Path | None:
    """Escribe {render}.keyword_selection.json si el preset selecciono keywords automatico.

    OBLIGATORIO en todo render con seleccion automatica (D21). Fail-open: un fallo del
    sidecar jamas afecta al render (solo log). keywords off -> no aplica -> None.
    """
    if plan is None or plan.keywords_mode == "off":
        return None
    try:
        data = construir_seleccion(groups, plan)
        path = Path(out_video).with_suffix(".keyword_selection.json")
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[cve] sidecar de seleccion: {path.name} ({len(data['keywords'])} keyword(s))")
        return path
    except Exception as e:
        print(f"[cve] sidecar de seleccion fallo ({e}) - render no afectado")
        return None
