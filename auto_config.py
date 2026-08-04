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
CAPTION_SOURCES = frozenset({"transcript", "srt"})

# Campos de la capa de letreros (Motor B, HF-3). Con `motion_enabled=False` NO entran al
# `to_dict()` ni al fingerprint: un paquete v2 anterior a HF-3 conserva su fingerprint exacto
# y sigue reanudandose. Es la traduccion del invariante "capa apagada = nada cambia" al
# contrato de reanudacion, no solo a los pixeles.
CAMPOS_MOTION = ("motion_nombre", "motion_rol", "motion_cta")
CAMPOS_MOTION_BOOL = ("motion_textos_llm",)
MOTION_TEXTO_MAX = 120


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
    # Fuente de captions (S36-C2A2). "transcript" (default) = ruta histórica exacta;
    # "srt" = usa la selección SRT explícita del video y deriva SRT/words/groups por clip.
    caption_source: Literal["transcript", "srt"] = "transcript"

    # Capa de letreros del Motor B (HyperFrames, HF-3). DEFAULT OFF y aditiva: apagada, el
    # render y el nombre de salida son los historicos byte a byte. Solo v2: la ruta classic no
    # sella un fingerprint en su marker, asi que un resume no podria distinguir un paquete con
    # letreros de uno sin ellos y mezclaria clips de las dos clases sin avisar.
    motion_enabled: bool = False
    # Textos de marca. Neutros a proposito: los reales los decide K, aqui no se inventan.
    # `motion_nombre` vacio omite el lower_third entero (no se pinta una tarjeta en blanco).
    motion_nombre: str = ""
    motion_rol: str = ""
    motion_cta: str = "Sigue para mas"
    # Los textos de los letreros los escribe el LLM. Las heuristicas de espanol se quedan como
    # respaldo y entran solas si el modelo falla. Solo cuenta con `motion_enabled`.
    motion_textos_llm: bool = True

    target_coverage_pct: float = 0.27
    max_coverage_pct: float = 0.35
    hook_protected_s: float = 3.0
    max_video_windows: int = 1

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise AutoConfigError(f"mode invalido: {self.mode!r} (usa classic o v2)")
        for campo in (
            "broll_enabled",
            "fx_enabled",
            "verify_av",
            "manual_sidecars",
            "motion_enabled",
            "motion_textos_llm",
        ):
            if not _es_bool(getattr(self, campo)):
                raise AutoConfigError(f"{campo} debe ser bool")
        self._validar_motion()
        if self.fx_preset not in FX_PRESETS:
            raise AutoConfigError(f"fx_preset invalido: {self.fx_preset!r}")
        if self.caption_source not in CAPTION_SOURCES:
            raise AutoConfigError(f"caption_source invalido: {self.caption_source!r}")
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

    def _validar_motion(self) -> None:
        """Reglas de la capa de letreros. Textos: str acotado; encendida: solo en v2."""
        for campo in CAMPOS_MOTION:
            valor = getattr(self, campo)
            if not isinstance(valor, str):
                raise AutoConfigError(f"{campo} debe ser texto")
            if len(valor) > MOTION_TEXTO_MAX:
                raise AutoConfigError(f"{campo} supera {MOTION_TEXTO_MAX} caracteres")
            if "\n" in valor or "\r" in valor:
                raise AutoConfigError(f"{campo} no admite saltos de linea")
        if self.motion_enabled and self.mode != "v2":
            raise AutoConfigError(
                "motion_enabled exige mode='v2': el paquete classic no sella un fingerprint de "
                "config en su marker, asi que una reanudacion mezclaria clips con letreros y sin "
                "ellos sin que nadie se entere"
            )

    def to_dict(self) -> dict:
        """Dict JSON-serializable y estable (sin rutas, sin secretos, sin reloj).

        Con la capa de letreros APAGADA sus campos se OMITEN por completo. No es cosmetica:
        `to_dict` alimenta el fingerprint que gobierna la reanudacion, y meter una clave nueva
        habria invalidado de golpe todos los paquetes v2 ya existentes sin que su salida hubiera
        cambiado en un solo byte. Omitirlos tambien es lo correcto en semantica: con la capa
        apagada, `motion_cta` no influye en nada.
        """
        d = asdict(self)
        d["pipeline_version"] = PIPELINE_VERSION
        if not self.motion_enabled:
            for campo in ("motion_enabled", *CAMPOS_MOTION, *CAMPOS_MOTION_BOOL):
                d.pop(campo, None)
        return d

    def fingerprint(self) -> str:
        """SHA256 estable de la config + version del pipeline. Gobierna la reanudacion v2."""
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = ["PIPELINE_VERSION", "CAPTION_SOURCES", "AutoConfig", "AutoConfigError"]
