"""broll_plan_types.py — Tipos, excepciones, codigos y limites del planner de b-roll (S37-A).

Base de datos PURA (ver DECISIONES D34). Solo libreria estandar. Todo inmutable
(frozen dataclasses): el planner nunca muta groups, brain ni config. Los tiempos
viven en segundos float, redondeados de forma estable a 3 decimales en la salida.

Este modulo NO decide nada ni toca red/FFmpeg/Pexels: solo declara el contrato que
`broll_planner.plan_broll` produce y que un futuro resolver (PR B) consumira.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

# --- Version e identidad del contrato JSON ---
PLAN_VERSION = 1
PLANNER_NAME = "centrito_broll_planner"

# Redondeo estable de tiempos y tolerancia interna para comparar floats.
TIME_DECIMALS = 3
TIME_EPS = 1e-6

MediaType = Literal["image", "video"]

# --- Presets FX validos en V1 (informativos para el planner; el render los aplica en PR B) ---
FX_PRESETS = frozenset({"express", "pro", "premium"})

# --- Razones de ventana aceptada (por que se coloco y con que tipo) ---
REASON_IMAGE_DEFAULT = "brain_keyword_default_image"
REASON_VIDEO_MOTION = "brain_keyword_motion_video"
REASON_VIDEO_DOWNGRADED = "brain_keyword_video_downgraded_to_image"

# --- Razones de zona protegida ---
ZONE_HOOK = "hook_protected"
ZONE_OUTRO = "premium_outro_reserved"

# --- Codigos de rechazo / degradacion (estables para PR B) ---
REJ_BRAIN_MISSING_GROUPS = "brain_missing_groups"
REJ_BRAIN_ITEM_NOT_OBJECT = "brain_item_not_object"
REJ_GROUP_NOT_FOUND = "group_not_found"
REJ_GROUP_WORDS_INVALID = "group_words_invalid"
REJ_KEYWORD_NOT_SELECTED = "keyword_not_selected"
REJ_KEYWORD_INDEX_INVALID = "keyword_index_invalid"
REJ_KEYWORD_EMPTY = "keyword_empty"
REJ_KW_TS_MISSING = "kw_ts_missing"
REJ_KW_TS_INVALID = "kw_ts_invalid"
REJ_KW_TS_OUT_OF_RANGE = "kw_ts_out_of_range"
REJ_QUERY_EMPTY = "query_empty"
REJ_PROTECTED_HOOK = "protected_hook"
REJ_PROTECTED_OUTRO = "protected_outro"
REJ_DURATION_BELOW_MIN = "duration_below_min"
REJ_OVERLAP_UNRESOLVABLE = "overlap_unresolvable"
REJ_MAX_COVERAGE_EXCEEDED = "max_coverage_exceeded"
REJ_TARGET_COVERAGE_REACHED = "target_coverage_reached"
REJ_DUPLICATE_QUERY = "duplicate_query"
REJ_VIDEO_LIMIT_FALLBACK = "video_limit_fallback_to_image"

# --- Warnings del plan (nivel plan, no candidato) ---
WARN_NO_USABLE_TIMELINE = "no_usable_timeline"
WARN_DISABLED_BY_CONFIG = "disabled_by_config"
WARN_BRAIN_MISSING_GROUPS = "brain_missing_groups"

# Fuente de toda senal en V1 (el brain marca la keyword; el planner deriva la ventana).
SIGNAL_SOURCE = "brain_keyword"


class BrollPlanError(Exception):
    """Base de errores de contrato del planner (errores de USUARIO, no bugs)."""


class BrollConfigError(BrollPlanError):
    """Config incoherente (porcentajes, duraciones o presets fuera de contrato)."""


class BrollInputError(BrollPlanError):
    """Entrada de nivel superior invalida (groups no-lista, brain no-dict, duracion invalida)."""


def _is_real(x: object) -> bool:
    """True si x es un numero real finito y NO un bool (los bool no son porcentajes ni tiempos)."""
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def round_time(value: float) -> float:
    """Redondeo estable de un tiempo a TIME_DECIMALS (evita drift y -0.0)."""
    r = round(float(value), TIME_DECIMALS)
    return r + 0.0  # normaliza -0.0 -> 0.0


@dataclass(frozen=True)
class BrollConfig:
    """Config editorial explicita. Se valida al construir: nunca escapa una config invalida."""

    enabled: bool = True
    target_coverage_pct: float = 0.27
    max_coverage_pct: float = 0.35
    hook_protected_s: float = 3.0
    image_min_s: float = 2.5
    image_preferred_s: float = 3.5
    image_max_s: float = 4.5
    video_min_s: float = 3.0
    video_preferred_s: float = 4.5
    video_max_s: float = 6.0
    max_video_windows: int = 1
    fx_preset: str = "express"
    premium_outro_s: float = 2.5
    lead_in_s: float = 0.25
    max_query_terms: int = 4

    def __post_init__(self) -> None:
        _validate_config(self)

    @property
    def reserves_outro(self) -> bool:
        """El outro solo se reserva con preset premium y una duracion util positiva."""
        return self.fx_preset == "premium" and self.premium_outro_s > 0.0


def _validate_config(c: BrollConfig) -> None:
    """Valida la config con errores de contrato (BrollConfigError). No usa assert."""
    if not isinstance(c.enabled, bool):
        raise BrollConfigError("enabled debe ser bool")
    for name in (
        "target_coverage_pct",
        "max_coverage_pct",
        "hook_protected_s",
        "premium_outro_s",
        "lead_in_s",
    ):
        if not _is_real(getattr(c, name)):
            raise BrollConfigError(f"{name} debe ser un numero real finito")
    if c.max_coverage_pct < 0.0 or c.max_coverage_pct > 1.0:
        raise BrollConfigError("max_coverage_pct debe estar en [0, 1]")
    if c.target_coverage_pct < 0.0 or c.target_coverage_pct > c.max_coverage_pct:
        raise BrollConfigError("target_coverage_pct debe estar en [0, max_coverage_pct]")
    if c.hook_protected_s < 0.0 or c.premium_outro_s < 0.0 or c.lead_in_s < 0.0:
        raise BrollConfigError("hook/outro/lead-in no pueden ser negativos")
    _validate_durations(c, "image", c.image_min_s, c.image_preferred_s, c.image_max_s)
    _validate_durations(c, "video", c.video_min_s, c.video_preferred_s, c.video_max_s)
    if isinstance(c.max_video_windows, bool) or not isinstance(c.max_video_windows, int):
        raise BrollConfigError("max_video_windows debe ser int")
    if c.max_video_windows not in (0, 1):
        raise BrollConfigError("max_video_windows solo admite 0 o 1 en V1")
    if c.fx_preset not in FX_PRESETS:
        raise BrollConfigError(f"fx_preset desconocido: {c.fx_preset!r}")
    if isinstance(c.max_query_terms, bool) or not isinstance(c.max_query_terms, int):
        raise BrollConfigError("max_query_terms debe ser int")
    if c.max_query_terms < 1:
        raise BrollConfigError("max_query_terms debe ser un entero positivo")


def _validate_durations(c: BrollConfig, kind: str, dmin: float, dpref: float, dmax: float) -> None:
    """Verifica 0 < min <= preferred <= max para un tipo de asset."""
    for label, val in (
        (f"{kind}_min_s", dmin),
        (f"{kind}_preferred_s", dpref),
        (f"{kind}_max_s", dmax),
    ):
        if not _is_real(val):
            raise BrollConfigError(f"{label} debe ser un numero real finito")
    if not (0.0 < dmin <= dpref <= dmax):
        raise BrollConfigError(f"duraciones de {kind} deben cumplir 0 < min <= preferred <= max")


@dataclass(frozen=True)
class BrollSignal:
    """Senal editorial derivada de UN item de brain: la keyword y su ancla temporal."""

    group_id: int
    group_position: int
    keyword_index: int
    keyword: str
    kw_ts: float
    group_text: str
    motion_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProtectedZone:
    """Ventana intocable del timeline (hook u outro premium)."""

    kind: str
    start_s: float
    end_s: float
    reason: str


@dataclass(frozen=True)
class BrollWindow:
    """Ventana de b-roll aceptada: intencion editorial, no asset resuelto."""

    window_id: str
    start_s: float
    end_s: float
    duration_s: float
    media_type: MediaType
    query: str
    reason: str
    signal: BrollSignal
    query_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class BrollRejected:
    """Candidato rechazado o degradado, con codigo estable y razon legible."""

    code: str
    reason: str
    signal: BrollSignal | None = None


@dataclass(frozen=True)
class BrollPlan:
    """Plan inmutable, determinista y auditable de b-roll para un clip."""

    version: int
    clip_duration_s: float
    config: BrollConfig
    protected_zones: tuple[ProtectedZone, ...]
    windows: tuple[BrollWindow, ...]
    rejected: tuple[BrollRejected, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)
    signals_total: int = 0
    candidates_valid: int = 0


__all__ = [
    "PLAN_VERSION",
    "PLANNER_NAME",
    "TIME_DECIMALS",
    "TIME_EPS",
    "MediaType",
    "FX_PRESETS",
    "SIGNAL_SOURCE",
    "BrollPlanError",
    "BrollConfigError",
    "BrollInputError",
    "BrollConfig",
    "BrollSignal",
    "ProtectedZone",
    "BrollWindow",
    "BrollRejected",
    "BrollPlan",
    "round_time",
]
