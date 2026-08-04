"""Contrato del Modo Automatico expuesto por Studio (S37-C).

Studio configura; ``auto.ejecutar_auto`` orquesta. Este modulo no usa red, no
renderiza y no escribe: valida parametros publicos, construye ``AutoConfig`` y
publica capacidades saneadas para la UI.
"""

from __future__ import annotations

from importlib import import_module

from auto_config import AutoConfig

AUTO_MODES = ("classic", "v2")
AUTO_FX_PRESETS = ("express", "pro", "premium")
AUTO_CAPTION_SOURCES = ("transcript", "srt")


def construir_auto_config(
    *,
    mode: str,
    broll_enabled: bool,
    fx_enabled: bool,
    fx_preset: str,
    caption_source: str = "transcript",
    motion_enabled: bool = False,
    motion_nombre: str | None = None,
    motion_rol: str | None = None,
    motion_cta: str | None = None,
) -> AutoConfig | None:
    """Parametros publicos de Studio -> contrato inmutable del pipeline.

    classic + transcript = None (ruta historica EXACTA). caption_source="srt" SIEMPRE devuelve
    un AutoConfig (aunque mode=classic): la ruta SRT no es la historica.

    `motion_enabled` es la capa de letreros del Motor B, apagada por default. Solo tiene sentido
    con mode=v2 (lo impone `AutoConfig`); pedirla en classic es un error del llamador y sube como
    400, no como un run silencioso sin letreros.
    """
    if mode not in AUTO_MODES:
        raise ValueError(f"mode invalido: {mode!r}")
    if fx_preset not in AUTO_FX_PRESETS:
        raise ValueError(f"fx_preset invalido: {fx_preset!r}")
    if caption_source not in AUTO_CAPTION_SOURCES:
        raise ValueError(f"caption_source invalido: {caption_source!r}")
    if not isinstance(broll_enabled, bool) or not isinstance(fx_enabled, bool):
        raise TypeError("broll_enabled y fx_enabled deben ser bool")
    if not isinstance(motion_enabled, bool):
        raise TypeError("motion_enabled debe ser bool")
    if mode == "classic" and caption_source == "transcript" and not motion_enabled:
        return None  # ruta historica exacta
    # Un campo que Studio no manda NO se pasa: asi el default de `AutoConfig` (que es donde vive
    # el unico valor neutro de cada texto) gana, en vez de que un "" del formulario lo pise.
    extra: dict = {}
    if motion_enabled:
        extra["motion_enabled"] = True
        for clave, valor in (
            ("motion_nombre", motion_nombre),
            ("motion_rol", motion_rol),
            ("motion_cta", motion_cta),
        ):
            if valor is not None:
                extra[clave] = valor
    return AutoConfig(
        mode="v2" if mode == "v2" else "classic",
        broll_enabled=broll_enabled,
        fx_enabled=fx_enabled,
        fx_preset=fx_preset,
        verify_av=True,
        manual_sidecars=True,
        caption_source=caption_source,
        **extra,
    )


def _estado_pexels(modulo: str, funcion: str) -> dict:
    """Estado local de un fetcher opcional; nunca prueba la key contra internet."""
    try:
        estado = getattr(import_module(modulo), funcion)()
        enabled = bool(estado.get("habilitado"))
    except Exception:  # lectura opcional fail-open: el Studio debe seguir util
        return {"enabled": False, "message": "Estado no disponible; el pipeline seguira."}
    message = "Pexels listo." if enabled else "Pexels no configurado; se omitira o usara fallback."
    return {"enabled": enabled, "message": message}


def capacidades_auto() -> dict:
    """Vista publica segura de modos, defaults y reglas fijas del Studio."""
    defaults = AutoConfig(mode="v2")
    return {
        "default_mode": "classic",
        "modes": [
            {
                "id": "classic",
                "label": "Clasico",
                "description": "Reframe, captions y emojis con el flujo historico.",
            },
            {
                "id": "v2",
                "label": "Automatico v2",
                "description": "Agrega b-roll, FX y verificacion A/V al mismo pipeline.",
            },
        ],
        "fx_presets": list(AUTO_FX_PRESETS),
        "v2_defaults": {
            "broll_enabled": defaults.broll_enabled,
            "fx_enabled": defaults.fx_enabled,
            "fx_preset": defaults.fx_preset,
            "verify_av": defaults.verify_av,
            "manual_sidecars": defaults.manual_sidecars,
            "motion_enabled": defaults.motion_enabled,
            "motion_cta": defaults.motion_cta,
        },
        # Capa de letreros del Motor B. Se publica para que la UI sepa que existe, que viene
        # apagada y que solo esta disponible en v2.
        "motion": {
            "available_modes": ["v2"],
            "default_enabled": defaults.motion_enabled,
            "plantillas": ["hook", "lower_third", "dato_destacado", "cierre"],
            "description": (
                "Letreros animados colocados solos segun la duracion del clip. Capa aditiva: "
                "si falla, el clip sale igual pero sin letreros."
            ),
        },
        "fixed_rules": {
            "hook_protected_s": defaults.hook_protected_s,
            "max_video_windows": defaults.max_video_windows,
            "max_coverage_pct": defaults.max_coverage_pct,
            "captions": True,
            "reframe": "9:16",
        },
        "pexels": {
            "images": _estado_pexels("broll_stock", "estado_pexels"),
            "videos": _estado_pexels("broll_video_stock", "estado_pexels_video"),
        },
    }


__all__ = [
    "AUTO_MODES",
    "AUTO_FX_PRESETS",
    "AUTO_CAPTION_SOURCES",
    "capacidades_auto",
    "construir_auto_config",
]
