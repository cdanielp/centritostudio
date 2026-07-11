"""cve.py — caption_viral_engine: capa de orquestacion de presets sobre el motor existente.

El engine COMPONE y CONFIGURA; los motores RENDERIZAN (DISENO_CVE.md §0). No hay logica
de render aqui: resuelve un preset a un RenderPlan (StyleConfig + modos) y marca los
grupos (keywords/marcas/fit) para que core_ass haga lo de siempre.
Fallback total: cualquier fallo del engine degrada a captions simples (§8), jamas rompe.
"""

from __future__ import annotations

import csv
import json
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
    "karaoke_highlight": {
        "style": "karaoke",  # envoltura del modo karaoke existente (\kf progresivo)
        "intensidad": "clean",
        "keywords": "off",  # sobrio: el karaoke ES el enfasis (ante duda, opcion sobria)
        "glow": False,
        "overlays": "off",
        "position": "bottom",
        "video_fx": {"punch_in": False},
        # Karaoke moderno: dichas quedan marcadas (cian, = relleno). Parametrizable:
        # base = primary_color del estilo, activo = highlight_color, pasado = este campo.
        "past_color": "&H00FFFF00",
    },
}


def list_presets() -> list[str]:
    return sorted(_PRESETS)


def info_presets() -> list[dict]:
    """Metadatos de los presets para consumidores (Studio /api/presets, regla 19).

    usa_brain permite a la UI avisar (y ofrecer el fix) cuando falta brain.json.
    """
    result = []
    for nombre in list_presets():
        p = _PRESETS[nombre]
        kw = str(p.get("keywords", "off"))
        result.append(
            {
                "id": nombre,
                "intensidad_default": p.get("intensidad", "clean"),
                "usa_keywords": kw != "off",
                "usa_brain": kw in ("brain", "auto+brain"),
            }
        )
    return result


def _plan_desde_dict(nombre: str, p: dict, intensidad: str) -> RenderPlan:
    """Construye el RenderPlan aplicando la matriz de intensidades (§6.1)."""
    glow = bool(p.get("glow", False)) and intensidad == "viral"
    style_cfg = get_style(p.get("style", "hormozi"))
    if intensidad == "minimal":
        style_cfg = replace(style_cfg, pop_scale=1.0, overshoot=False)
    if glow != getattr(style_cfg, "kw_glow", False):
        style_cfg = replace(style_cfg, kw_glow=glow)
    # past_color solo aplica al modo karaoke; los presets son constantes confiables
    # (los overrides del usuario llegaran validados via cve_presets.json, S33)
    past = p.get("past_color")
    if past and style_cfg.animation_type == "karaoke":
        style_cfg = replace(style_cfg, karaoke_past_color=past)
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


def resolver_preset_seguro(preset: str | None, intensidad: str | None):
    """(plan, aviso) fail-safe: preset invalido o engine roto -> (None, aviso accionable).

    Fuente unica para CLI y Studio (regla #10): el llamador cae a captions clasicos.
    """
    if not preset:
        return None, None
    try:
        return resolve_preset(preset, intensidad), None
    except Exception as exc:
        aviso = f"Preset no resuelto ({exc}) - render con estilo clasico"
        print(f"[cve] {aviso}")
        return None, aviso


def aplicar_preset(
    groups: list[dict],
    plan: RenderPlan,
    brain_path: Path | None,
    video_w: int,
    video_h: int,
) -> tuple[list[dict], RenderPlan, str | None]:
    """Ruta completa del preset: brain fail-open + engine + ajuste de plan a los grupos.

    Fuente unica para CLI y Studio. Devuelve (groups, plan, aviso); el aviso (regla #16)
    dice cuando el preset usa brain y no hay brain.json — el consumidor ofrece el fix.
    """
    brain_data = None
    aviso = None
    if brain_path and Path(brain_path).exists():
        try:
            brain_data = json.loads(Path(brain_path).read_text(encoding="utf-8"))
            print(f"[cve] brain.json encontrado: enriquecimiento activo ({Path(brain_path).name})")
        except (ValueError, OSError):  # ValueError cubre JSON invalido y encoding roto
            print(f"[cve] brain.json ilegible, se ignora: {Path(brain_path).name}")
    if plan.keywords_mode in ("brain", "auto+brain") and brain_data is None:
        aviso = "Sin brain.json: el preset rinde sin keywords semanticas (Analizar IA lo habilita)"
    groups = aplicar_engine(groups, plan, video_w, video_h, brain_data)
    plan = ajustar_plan_a_groups(plan, groups)
    return groups, plan, aviso


def tag_variante(preset: str, intensidad: str | None) -> str:
    """Sufijo de salida de una variante de preset — identico en CLI y Studio."""
    inten_tag = f"_{intensidad}" if intensidad else ""
    return f"_{preset}{inten_tag}"


def _timing_por_palabra_completo(groups: list[dict]) -> bool:
    """True si TODAS las palabras traen start/end numericos (lo que karaoke necesita)."""
    for g in groups:
        for w in g.get("words", []):
            if not isinstance(w.get("start"), (int, float)) or not isinstance(
                w.get("end"), (int, float)
            ):
                return False
    return True


def ajustar_plan_a_groups(plan: RenderPlan, groups: list[dict]) -> RenderPlan:
    """Fallback nivel 3 (§8): karaoke sin timing por-palabra cae a captions simples.

    El relleno progresivo \\kf necesita duracion por palabra; sin ella el estilo del
    preset se conserva pero la animacion cae a highlight (el video JAMAS queda sin
    captions). Con timing completo el plan vuelve intacto.
    """
    if plan.style_cfg.animation_type != "karaoke":
        return plan
    if _timing_por_palabra_completo(groups):
        return plan
    print("[cve] sin timing por-palabra: karaoke cae a captions simples (highlight, nivel 3)")
    style_cfg = replace(plan.style_cfg, animation_type="highlight", karaoke_past_color=None)
    return replace(plan, style_cfg=style_cfg)


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


def _consumir_marcas(groups: list[dict]) -> tuple[list[dict], list[tuple[int, int, int, str]]]:
    """Consume las marcas manuales de texto Y words; devuelve (grupos limpios, candidatos).

    Garantia del voto #34: ninguna marca ([strong], [fuego], [/strong]...) llega como
    texto visible al ASS — valida o invalida, se elimina. Un token que era SOLO marca
    desaparece como palabra (la marca no es una palabra, DISENO §7). Las marcas validas
    se vuelven candidatos manuales (score SCORE_MANUAL) si el mapeo texto→words coincide.
    """
    result: list[dict] = []
    candidatos: list[tuple[int, int, int, str]] = []
    for g_idx, g in enumerate(groups):
        texto = g.get("text", "")
        words = g.get("words", [])
        if "[" not in texto and not any("[" in (w.get("text") or "") for w in words):
            result.append(g)
            continue
        limpio, marcas, center = ck.parsear_marcas(texto)
        nuevas = []
        for w in words:
            t = ck.limpiar_token(w.get("text", ""))
            if t:
                nuevas.append({**w, "text": t})
        g2 = {**g, "text": limpio, "words": nuevas}
        if center:
            g2["center"] = True  # posicion por-grupo: sin consumidor hasta S32
        result.append(g2)
        if not marcas:
            continue
        # El mapeo por indice solo es confiable si el conteo de palabras coincide
        if len(limpio.split()) != len(nuevas):
            print(f"[cve] grupo {g_idx}: marcas ignoradas (texto editado no coincide)")
            continue
        for w_idx, marca in marcas.items():
            regla = "manual_big" if marca == "big" else "manual"
            candidatos.append((g_idx, w_idx, ck.SCORE_MANUAL, regla))
    return result, candidatos


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
    """Marca keywords en los grupos segun el plan. Fallo -> grupos originales (§8 nivel 3).

    Las marcas manuales se consumen SIEMPRE (aun con keywords off): el ASS jamas
    muestra corchetes de marca (voto #34).
    """
    try:
        limpios, manuales = _consumir_marcas(groups)
    except Exception as e:
        print(f"[cve] limpieza de marcas fallo ({e}) - grupos originales")
        limpios, manuales = groups, []
    if plan.keywords_mode == "off":
        return limpios
    try:
        candidatos = list(manuales)
        if plan.keywords_mode in ("brain", "auto+brain"):
            candidatos += ck.candidatos_brain(limpios, brain_data)
        if plan.keywords_mode == "auto+brain":
            candidatos += ck.detectar_candidatos(limpios)
        elegidos = ck.elegir_keywords(candidatos, len(limpios))
        if not elegidos:
            return limpios

        fontsize = _scaled_fontsize(video_w, video_h, plan.style_cfg)
        ancho_util = int(video_w * (1.0 - SAFE_LEFT_PCT - SAFE_RIGHT_PCT))
        result = list(limpios)
        for g_idx, (w_idx, _score, regla) in elegidos.items():
            escala = None
            if plan.kw_punch_scale > ck.KW_SCALE_BASE or regla == "manual_big":
                palabra = limpios[g_idx]["words"][w_idx]["text"]
                escala = ck.ajustar_escala_punch(palabra, fontsize, ancho_util, plan.kw_punch_scale)
                if escala is None:
                    print(f"[cve] '{palabra}' no cabe ni reducida: punch desactivado (kw normal)")
            result[g_idx] = _marcar_grupo(limpios[g_idx], w_idx, regla, escala)
        n = len(elegidos)
        print(f"[cve] preset {plan.preset}: {n} keyword(s) marcadas en {len(limpios)} grupos")
        return result
    except Exception as e:  # fallback total: captions con el estilo del preset, sin marcas
        print(f"[cve] engine fallo ({e}) - render sigue con captions simples del estilo")
        return limpios
