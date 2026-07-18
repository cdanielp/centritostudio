"""auto_fx.py — FX del Modo Automatico v2: generacion + arbitraje contra cutaways (S37-B, #47e).

Usa el motor EXISTENTE (`fx.cargar_brain_fx` / `fx.generar_plan_fx` y sus dataclasses); aqui
no se crea ningun efecto nuevo ni se cambian parametros visuales. La unica logica propia es
el ARBITRAJE: un punch/flash/scanner que se traslapa con un cutaway (imagen o video, manual
o automatico) se ELIMINA — nunca se desplaza (#47e). El logo/outro se conserva; si un sidecar
manual ocupa la zona del outro premium se registra un warning (manual gana por ser manual).

Funciones puras sobre dataclasses frozen: el FXPlan original jamas se muta; el resultado es
un FXPlan nuevo + auditoria (eliminados, warnings, conteos antes/despues).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fx import FXPlan, cargar_brain_fx, generar_plan_fx

_MARCA_DIR = Path(__file__).parent / "assets" / "marca"

# Codigos estables de auditoria (#47e)
COD_PUNCH = "punch_removed_cutaway"
COD_FLASH = "flash_removed_cutaway"
COD_SCANNER = "scanner_removed_cutaway"
COD_OUTRO_MANUAL = "premium_outro_manual_conflict"


@dataclass(frozen=True)
class FXArbitrationResult:
    """Plan final + auditoria del arbitraje. `removed` lista dicts serializables."""

    plan: FXPlan
    removed: tuple[dict, ...]
    warnings: tuple[str, ...]
    before: dict
    after: dict


def _logo_png() -> Path | None:
    """Logo de marca para el FX (mismo criterio que caption._logo_png). None si no hay."""
    if not _MARCA_DIR.exists():
        return None
    for cand in sorted(_MARCA_DIR.glob("*.png")):
        return cand
    return None


def generar_fx_v2(
    duration: float, preset: str, brain_sidecar: Path, *, enabled: bool = True
) -> FXPlan | None:
    """FXPlan del preset para un clip v2. Motor existente, fail-open como caption.py.

    enabled=False -> None (sin FX, registrado por el caller). Brain ausente/roto ->
    fallback por intervalos del propio motor.
    """
    if not enabled:
        return None
    brain_data = cargar_brain_fx(brain_sidecar)  # fail-open interno: None si no hay brain util
    plan = generar_plan_fx(duration, preset, brain_data, _logo_png())
    return None if plan.vacio() else plan


def _overlap(a0: float, a1: float, b0: float, b1: float) -> bool:
    """Traslape con semantica [start, end): tocar borde NO es conflicto."""
    return a0 < b1 and b0 < a1


def _choca(t0: float, t1: float, blocked: list[tuple[float, float]]) -> tuple[float, float] | None:
    for b0, b1 in blocked:
        if _overlap(t0, t1, b0, b1):
            return (b0, b1)
    return None


def _conteos(plan: FXPlan | None) -> dict:
    if plan is None:
        return {"punch": 0, "flash": 0, "scanner": 0, "logo": 0}
    return {
        "punch": len(plan.punch_ins),
        "flash": len(plan.flashes),
        "scanner": len(plan.scanners),
        "logo": 1 if plan.logo else 0,
    }


def intervalos_cutaway(popups: list, clips: list) -> list[tuple[float, float]]:
    """Intervalos [t0, t1) bloqueados por cutaways (popups cutaway=True y todo ClipOverlay)."""
    out: list[tuple[float, float]] = []
    for p in popups:
        if getattr(p, "cutaway", False):
            out.append((float(p.t0), float(p.t1)))
    for c in clips:
        out.append((float(c.t0), float(c.t1)))
    return sorted(out)


def arbitrar_fx(
    fx_plan: FXPlan | None, blocked_intervals: list[tuple[float, float]]
) -> FXArbitrationResult:
    """Arbitraje #47e: elimina (no desplaza) punch/flash/scanner que traslapan un cutaway.

    Logo/outro se conserva; un intervalo bloqueado que invade la zona del outro genera un
    warning `premium_outro_manual_conflict` (riesgo visual registrado, intencion manual gana).
    Puro: no muta `fx_plan`; devuelve un FXPlan nuevo con las mismas dataclasses de fx.py.
    """
    before = _conteos(fx_plan)
    if fx_plan is None:
        return FXArbitrationResult(FXPlan(), (), (), before, before)
    blocked = sorted(blocked_intervals)
    removed: list[dict] = []
    warnings: list[str] = []

    punch = []
    for p in fx_plan.punch_ins:
        hit = _choca(p.t0, p.t1, blocked)
        if hit:
            removed.append({"code": COD_PUNCH, "t0": p.t0, "t1": p.t1, "cutaway": list(hit)})
        else:
            punch.append(p)
    flash = []
    for f in fx_plan.flashes:
        hit = _choca(f.t0, f.t0 + f.dur, blocked)
        if hit:
            removed.append(
                {"code": COD_FLASH, "t0": f.t0, "t1": round(f.t0 + f.dur, 3), "cutaway": list(hit)}
            )
        else:
            flash.append(f)
    scanners = []
    for s in fx_plan.scanners:
        hit = _choca(s.t0, s.t1, blocked)
        if hit:
            removed.append({"code": COD_SCANNER, "t0": s.t0, "t1": s.t1, "cutaway": list(hit)})
        else:
            scanners.append(s)

    logo = fx_plan.logo
    if logo is not None:
        hit = _choca(logo.start, logo.end, blocked)
        if hit:
            warnings.append(
                f"{COD_OUTRO_MANUAL}: cutaway {hit[0]:.2f}-{hit[1]:.2f}s invade la zona "
                f"del logo/outro ({logo.start:.2f}-{logo.end:.2f}s); se conserva por intencion"
            )

    final = FXPlan(punch, flash, scanners, logo, fx_plan.preset)
    return FXArbitrationResult(final, tuple(removed), tuple(warnings), before, _conteos(final))


__all__ = [
    "FXArbitrationResult",
    "generar_fx_v2",
    "intervalos_cutaway",
    "arbitrar_fx",
    "COD_PUNCH",
    "COD_FLASH",
    "COD_SCANNER",
    "COD_OUTRO_MANUAL",
]
