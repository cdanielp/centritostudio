"""auto_config.py — Contrato inmutable del Modo Automatico (S37-B, DECISIONES D34/#47).

`AutoConfig` es la unica llave que activa el pipeline v2: el default es `mode="classic"`,
lo que garantiza que `ejecutar_auto(...)` sin config = comportamiento historico exacto
(sin Pexels, sin planner, sin FX, sin sidecars nuevos).

PURO: no lee entorno, ni disco, ni reloj; no contiene resolvers ni callables; es
serializable y produce un fingerprint SHA256 estable que gobierna la reanudacion de
paquetes v2 (mismo fingerprint = mismo pipeline = checkpoint reutilizable).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Literal

# Version del pipeline v2: cambia solo si el contrato del render/sidecars cambia de
# forma incompatible (invalida checkpoints previos via fingerprint).
PIPELINE_VERSION = 2

MODES = frozenset({"classic", "v2"})
FX_PRESETS = frozenset({"express", "pro", "premium"})


class AutoConfigError(ValueError):
    """Config del Modo Automatico invalida (error de contrato, no bug)."""


def _es_bool(x: object) -> bool:
    return isinstance(x, bool)


def _es_pct(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and 0.0 <= float(x) <= 1.0


@dataclass(frozen=True)
class AutoConfig:
    """Configuracion del Modo Automatico. Frozen: se valida al construir y jamas muta."""

    mode: Literal["classic", "v2"] = "classic"
    broll_enabled: bool = True
    fx_enabled: bool = True
    fx_preset: Literal["express", "pro", "premium"] = "express"
    verify_av: bool = True
    manual_sidecars: bool = True

    target_coverage_pct: float = 0.27
    max_coverage_pct: float = 0.35
    hook_protected_s: float = 3.0
    max_video_windows: int = 1

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise AutoConfigError(f"mode invalido: {self.mode!r} (usa classic o v2)")
        for campo in ("broll_enabled", "fx_enabled", "verify_av", "manual_sidecars"):
            if not _es_bool(getattr(self, campo)):
                raise AutoConfigError(f"{campo} debe ser bool")
        if self.fx_preset not in FX_PRESETS:
            raise AutoConfigError(f"fx_preset invalido: {self.fx_preset!r}")
        if not _es_pct(self.target_coverage_pct) or not _es_pct(self.max_coverage_pct):
            raise AutoConfigError("target/max_coverage_pct deben ser numeros en [0, 1]")
        if self.target_coverage_pct > self.max_coverage_pct:
            raise AutoConfigError("target_coverage_pct no puede superar max_coverage_pct")
        if (
            isinstance(self.hook_protected_s, bool)
            or not isinstance(self.hook_protected_s, (int, float))
            or self.hook_protected_s < 0
        ):
            raise AutoConfigError("hook_protected_s debe ser un numero >= 0")
        if isinstance(self.max_video_windows, bool) or self.max_video_windows not in (0, 1):
            raise AutoConfigError("max_video_windows solo admite 0 o 1 en V1")

    def to_dict(self) -> dict:
        """Dict JSON-serializable y estable (sin rutas, sin secretos, sin reloj)."""
        d = asdict(self)
        d["pipeline_version"] = PIPELINE_VERSION
        return d

    def fingerprint(self) -> str:
        """SHA256 estable de la config + version del pipeline. Gobierna la reanudacion v2."""
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = ["PIPELINE_VERSION", "AutoConfig", "AutoConfigError"]
