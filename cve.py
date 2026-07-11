"""cve.py — caption_viral_engine: capa de orquestacion de presets sobre el motor existente.

El engine COMPONE y CONFIGURA; los motores RENDERIZAN (DISENO_CVE.md §0). No hay logica
de render aqui: resuelve un preset a un RenderPlan (StyleConfig + modos) y marca los
grupos (keywords/marcas/fit) para que core_ass haga lo de siempre.
Fallback total: cualquier fallo del engine degrada a captions simples (§8), jamas rompe.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, replace
from pathlib import Path

import cve_keywords as ck
from core_ass import _scaled_fontsize  # fuente unica de la formula de fontsize (D14)
from styles import POP_LEVELS, StyleConfig, get_style

# ─────────────────────────────────────────────────────────────────────────────
# Safe zones 9:16 (DISENO_CVE.md §5.1) — margenes de UI TikTok/Reels/Shorts
# ─────────────────────────────────────────────────────────────────────────────

SAFE_TOP_PCT = 0.10  # username / sonido
SAFE_BOTTOM_PCT = 0.18  # descripcion / barra de progreso
SAFE_RIGHT_PCT = 0.14  # columna de acciones (like/comment/share)
SAFE_LEFT_PCT = 0.05  # respiro simetrico minimo

INTENSIDADES = ("minimal", "clean", "viral")

# Escala punch derivada de POP_LEVELS (decision d: "reutilizando POP_LEVELS"):
# clean -> 100*medio=130, viral -> 100*fuerte=145, minimal -> 122 (kw normal, sin punch)
_PUNCH_POR_INTENSIDAD = {
    "minimal": ck.KW_SCALE_BASE,
    "clean": int(round(100 * POP_LEVELS["medio"])),
    "viral": int(round(100 * POP_LEVELS["fuerte"])),
}


@dataclass
class RenderPlan:
    """Resultado de resolve_preset: todo lo que el render necesita del engine."""

    preset: str
    style_cfg: StyleConfig
    keywords_mode: str  # "off" | "brain" | "auto+brain" | "manual"
    kw_punch_scale: int  # escala de reposo de la palabra punch
    kw_glow: bool
    overlays_mode: str  # "off" | "brain"
    avoid_faces: bool
    position: str  # "bottom" | "center" | "top" (efecto render: S32)
    video_fx: dict  # declarativo: recomendacion para reframe, no se ejecuta aqui


# Presets built-in v1 (§1). style = nombre de estilo existente; el resto son modos.
_PRESETS: dict[str, dict] = {
    "clean_podcast": {
        "style": "clean",
        "intensidad": "clean",
        "keywords": "off",
        "glow": False,
        "overlays": "off",
        "position": "bottom",
        "video_fx": {"punch_in": False},
    },
    "viral_bounce": {
        "style": "hormozi",  # pop suave + rebote ya es el default del estilo (D20)
        "intensidad": "clean",
        "keywords": "brain",  # enfasis semantico si brain.json existe (fail-open)
        "glow": False,
        "overlays": "off",
        "position": "bottom",
        "video_fx": {"punch_in": False},
    },
    "keyword_punch": {
        "style": "hormozi",
        "intensidad": "viral",
        "keywords": "auto+brain",  # reglas R1-R7 + enriquecimiento brain (§4)
        "glow": True,  # glow aprox sobre el keyword (viral; clean lo apaga)
        "overlays": "off",
        "position": "bottom",
        "video_fx": {"punch_in": True},  # recomendacion; deuda #20 la vota K
    },
}


def list_presets() -> list[str]:
    return sorted(_PRESETS)


def _plan_desde_dict(nombre: str, p: dict, intensidad: str) -> RenderPlan:
    """Construye el RenderPlan aplicando la matriz de intensidades (§6.1)."""
    glow = bool(p.get("glow", False)) and intensidad == "viral"
    style_cfg = get_style(p.get("style", "hormozi"))
    if intensidad == "minimal":
        style_cfg = replace(style_cfg, pop_scale=1.0, overshoot=False)
    if glow != getattr(style_cfg, "kw_glow", False):
        style_cfg = replace(style_cfg, kw_glow=glow)
    return RenderPlan(
        preset=nombre,
        style_cfg=style_cfg,
        keywords_mode=str(p.get("keywords", "off")),
        kw_punch_scale=_PUNCH_POR_INTENSIDAD[intensidad],
        kw_glow=glow,
        overlays_mode=str(p.get("overlays", "off")),
        avoid_faces=bool(p.get("avoid_faces", True)),
        position=str(p.get("position", "bottom")),
        video_fx=dict(p.get("video_fx", {})),
    )


def resolve_preset(nombre: str, intensidad: str | None = None) -> RenderPlan:
    """Resuelve un preset built-in a RenderPlan. Nombre desconocido -> error accionable.

    `intensidad` invalida o None -> la default del preset (fail-safe por campo).
    """
    key = (nombre or "").lower().strip()
    if key not in _PRESETS:
        disponibles = ", ".join(list_presets())
        raise ValueError(f"Preset '{nombre}' no disponible. Opciones: {disponibles}")
    p = _PRESETS[key]
    inten = intensidad if intensidad in INTENSIDADES else p.get("intensidad", "clean")
    return _plan_desde_dict(key, p, inten)


# ─────────────────────────────────────────────────────────────────────────────
# avoid_faces (§5.2): senal binaria desde el CSV de trayectoria del reframe
# ─────────────────────────────────────────────────────────────────────────────


def hay_cara_en_rango(csv_path: Path, t0: float, t1: float) -> bool | None:
    """True/False si el CSV trae detecciones vivas (conf) en [t0,t1]; None = sin senal.

    Sin archivo o sin columna conf_asignada (opcional en reframe) -> None: mismo
    camino que CSV ausente (§5.2), el llamador hace skip con log.
    """
    if not csv_path or not Path(csv_path).exists():
        return None
    try:
        with open(csv_path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if "conf_asignada" not in (reader.fieldnames or []):
                return None
            for row in reader:
                t = float(row["t"])
                if t0 <= t <= t1 and row.get("conf_asignada", "").strip():
                    return True
        return False
    except (OSError, ValueError, KeyError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Aplicacion del engine sobre los grupos (marcado; el render sigue siendo core_ass)
# ─────────────────────────────────────────────────────────────────────────────


def _marcas_manuales(groups: list[dict]) -> list[tuple[int, int, int, str]]:
    """Candidatos manuales desde marcas [strong]/[big] en el texto de cada grupo."""
    result = []
    for g_idx, g in enumerate(groups):
        limpio, marcas, _center = ck.parsear_marcas(g.get("text", ""))
        if not marcas:
            continue
        # El mapeo por indice solo es confiable si el conteo de palabras coincide
        if len(limpio.split()) != len(g.get("words", [])):
            print(f"[cve] grupo {g_idx}: marcas ignoradas (texto editado no coincide)")
            continue
        for w_idx, marca in marcas.items():
            regla = "manual_big" if marca == "big" else "manual"
            result.append((g_idx, w_idx, ck.SCORE_MANUAL, regla))
    return result


def _reunir_candidatos(groups: list[dict], modo: str, brain_data: dict | None) -> list:
    """Junta candidatos segun el modo del preset (manual siempre gana si existe)."""
    candidatos = list(_marcas_manuales(groups))
    if modo in ("brain", "auto+brain"):
        candidatos += ck.candidatos_brain(groups, brain_data)
    if modo == "auto+brain":
        candidatos += ck.detectar_candidatos(groups)
    return candidatos


def _marcar_grupo(g: dict, w_idx: int, regla: str, escala: int | None) -> dict:
    """Copia el grupo con is_keyword (+punch_scale si aplica) en la palabra elegida."""
    words = [dict(w) for w in g["words"]]
    if w_idx >= len(words):
        return g
    words[w_idx]["is_keyword"] = True
    if escala is not None and escala > ck.KW_SCALE_BASE:
        words[w_idx]["punch_scale"] = escala
    return {**g, "words": words}


def aplicar_engine(
    groups: list[dict],
    plan: RenderPlan,
    video_w: int,
    video_h: int,
    brain_data: dict | None = None,
) -> list[dict]:
    """Marca keywords en los grupos segun el plan. Fallo -> grupos originales (§8 nivel 3)."""
    if plan.keywords_mode == "off":
        return groups
    try:
        candidatos = _reunir_candidatos(groups, plan.keywords_mode, brain_data)
        elegidos = ck.elegir_keywords(candidatos, len(groups))
        if not elegidos:
            return groups

        fontsize = _scaled_fontsize(video_w, video_h, plan.style_cfg)
        ancho_util = int(video_w * (1.0 - SAFE_LEFT_PCT - SAFE_RIGHT_PCT))
        result = list(groups)
        for g_idx, (w_idx, _score, regla) in elegidos.items():
            escala = None
            if plan.kw_punch_scale > ck.KW_SCALE_BASE or regla == "manual_big":
                palabra = groups[g_idx]["words"][w_idx]["text"]
                escala = ck.ajustar_escala_punch(palabra, fontsize, ancho_util, plan.kw_punch_scale)
                if escala is None:
                    print(f"[cve] '{palabra}' no cabe ni reducida: punch desactivado (kw normal)")
            result[g_idx] = _marcar_grupo(groups[g_idx], w_idx, regla, escala)
        n = len(elegidos)
        print(f"[cve] preset {plan.preset}: {n} keyword(s) marcadas en {len(groups)} grupos")
        return result
    except Exception as e:  # fallback total: captions con el estilo del preset, sin marcas
        print(f"[cve] engine fallo ({e}) - render sigue con captions simples del estilo")
        return groups
