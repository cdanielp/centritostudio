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


def construir_auto_config(
    *, mode: str, broll_enabled: bool, fx_enabled: bool, fx_preset: str
) -> AutoConfig | None:
    """Parametros publicos de Studio -> contrato inmutable del pipeline."""
    if mode not in AUTO_MODES:
        raise ValueError(f"mode invalido: {mode!r}")
    if fx_preset not in AUTO_FX_PRESETS:
        raise ValueError(f"fx_preset invalido: {fx_preset!r}")
    if not isinstance(broll_enabled, bool) or not isinstance(fx_enabled, bool):
        raise TypeError("broll_enabled y fx_enabled deben ser bool")
    if mode == "classic":
        return None
    return AutoConfig(
        mode="v2",
        broll_enabled=broll_enabled,
        fx_enabled=fx_enabled,
        fx_preset=fx_preset,
        verify_av=True,
        manual_sidecars=True,
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


__all__ = ["AUTO_MODES", "AUTO_FX_PRESETS", "capacidades_auto", "construir_auto_config"]
