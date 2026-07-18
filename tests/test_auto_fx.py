"""test_auto_fx.py — FX v2: generacion con motor existente + arbitraje #47e (S37-B).

Sin red, sin FFmpeg: todo son dataclasses puras de fx.py y funciones de auto_fx.
"""

from __future__ import annotations

import json

import pytest

import auto_fx
from auto_fx import (
    COD_FLASH,
    COD_OUTRO_MANUAL,
    COD_PUNCH,
    COD_SCANNER,
    arbitrar_fx,
    generar_fx_v2,
    intervalos_cutaway,
)
from fx import Flash, FXPlan, LogoOutro, PunchIn, Scanner


@pytest.fixture(autouse=True)
def _sin_red(monkeypatch):
    import socket

    def _bloqueado(*a, **k):
        raise RuntimeError("red bloqueada en tests (S37-B)")

    monkeypatch.setattr(socket.socket, "connect", _bloqueado)


def plan_demo(preset="express"):
    return FXPlan(
        punch_ins=[PunchIn(5.0, 5.7, 1.08), PunchIn(11.0, 11.7, 1.08)],
        flashes=[Flash(8.0, 0.14, 0.5)],
        scanners=[Scanner(14.0, 14.6)],
        logo=LogoOutro(17.5, 20.0, "logo.png"),
        preset=preset,
    )


# ── Generacion (motor existente) ─────────────────────────────────────────────


def test_generar_disabled_devuelve_none(tmp_path):
    assert generar_fx_v2(30.0, "express", tmp_path / "no.brain.json", enabled=False) is None


def test_generar_express_fallback_sin_brain(tmp_path):
    plan = generar_fx_v2(30.0, "express", tmp_path / "no.brain.json")
    assert plan is not None and plan.punch_ins  # fallback por intervalos del motor
    assert not plan.flashes  # sin datos no hay flash (regla del motor)


def test_generar_pro_con_brain(tmp_path):
    brain = tmp_path / "x.brain.json"
    brain.write_text(
        json.dumps({"groups": [{"kw_ts": 4.0}, {"kw_ts": 9.0}, {"kw_ts": 15.0}]}),
        encoding="utf-8",
    )
    plan = generar_fx_v2(30.0, "pro", brain)
    assert plan is not None and plan.punch_ins
    assert plan.preset == "pro"


def test_generar_premium_reserva_outro_si_hay_logo(tmp_path, monkeypatch):
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"png")
    monkeypatch.setattr(auto_fx, "_logo_png", lambda: logo)
    plan = generar_fx_v2(30.0, "premium", tmp_path / "no.brain.json")
    assert plan.logo is not None and plan.logo.start == 27.5  # outro 2.5s (motor existente)


def test_generar_preset_desconocido_plan_vacio_none(tmp_path):
    assert generar_fx_v2(30.0, "noexiste", tmp_path / "no.brain.json") is None


# ── Intervalos de cutaway ────────────────────────────────────────────────────


class _P:
    def __init__(self, t0, t1, cutaway=True):
        self.t0, self.t1, self.cutaway = t0, t1, cutaway


class _C:
    def __init__(self, t0, t1):
        self.t0, self.t1 = t0, t1


def test_intervalos_solo_cutaways():
    popups = [_P(4.0, 7.5), _P(9.0, 10.0, cutaway=False)]  # popup chico NO bloquea FX
    clips = [_C(12.0, 16.5)]
    assert intervalos_cutaway(popups, clips) == [(4.0, 7.5), (12.0, 16.5)]


# ── Arbitraje (#47e) ─────────────────────────────────────────────────────────


def test_punch_sin_choque_queda():
    res = arbitrar_fx(plan_demo(), [(0.0, 2.0)])
    assert len(res.plan.punch_ins) == 2 and res.removed == ()


def test_punch_con_choque_eliminado_no_desplazado():
    res = arbitrar_fx(plan_demo(), [(5.2, 6.0)])
    assert len(res.plan.punch_ins) == 1
    assert res.plan.punch_ins[0].t0 == 11.0  # el otro queda intacto (no se desplaza nada)
    assert res.removed[0]["code"] == COD_PUNCH


def test_flash_con_choque_eliminado():
    res = arbitrar_fx(plan_demo(), [(8.05, 9.0)])
    assert res.plan.flashes == []
    assert res.removed[0]["code"] == COD_FLASH


def test_scanner_con_choque_eliminado():
    res = arbitrar_fx(plan_demo(), [(14.2, 15.0)])
    assert res.plan.scanners == []
    assert res.removed[0]["code"] == COD_SCANNER


def test_tocar_borde_no_elimina():
    # cutaway termina exactamente donde inicia el punch [5.0, 5.7)
    res = arbitrar_fx(plan_demo(), [(3.0, 5.0)])
    assert len(res.plan.punch_ins) == 2 and res.removed == ()


def test_multiples_cutaways_eliminan_varios():
    res = arbitrar_fx(plan_demo(), [(5.0, 6.0), (8.0, 8.5), (14.0, 15.0)])
    codigos = sorted(r["code"] for r in res.removed)
    assert codigos == [COD_FLASH, COD_PUNCH, COD_SCANNER]
    assert len(res.plan.punch_ins) == 1


def test_logo_outro_se_conserva_con_warning():
    res = arbitrar_fx(plan_demo(), [(18.0, 19.0)])
    assert res.plan.logo is not None  # nunca se elimina
    assert any(COD_OUTRO_MANUAL in w for w in res.warnings)


def test_logo_sin_conflicto_sin_warning():
    res = arbitrar_fx(plan_demo(), [(2.0, 3.0)])
    assert res.plan.logo is not None and res.warnings == ()


def test_plan_original_no_mutado():
    plan = plan_demo()
    antes = (list(plan.punch_ins), list(plan.flashes), list(plan.scanners))
    arbitrar_fx(plan, [(5.0, 20.0)])
    assert (list(plan.punch_ins), list(plan.flashes), list(plan.scanners)) == antes


def test_conteos_before_after():
    res = arbitrar_fx(plan_demo(), [(5.0, 15.0)])
    assert res.before == {"punch": 2, "flash": 1, "scanner": 1, "logo": 1}
    assert res.after == {"punch": 0, "flash": 0, "scanner": 0, "logo": 1}


def test_plan_none_resultado_vacio():
    res = arbitrar_fx(None, [(1.0, 2.0)])
    assert res.plan.vacio() and res.removed == () and res.warnings == ()


def test_preset_se_conserva_en_plan_final():
    res = arbitrar_fx(plan_demo("premium"), [(5.0, 6.0)])
    assert res.plan.preset == "premium"


def test_removed_serializable():
    res = arbitrar_fx(plan_demo(), [(5.0, 15.0)])
    assert json.loads(json.dumps(list(res.removed))) == list(res.removed)


def test_sin_intervalos_nada_cambia():
    plan = plan_demo()
    res = arbitrar_fx(plan, [])
    assert res.plan.punch_ins == plan.punch_ins and res.removed == ()


def test_logo_png_none_sin_marca(monkeypatch, tmp_path):
    monkeypatch.setattr(auto_fx, "_MARCA_DIR", tmp_path / "no-existe")
    assert auto_fx._logo_png() is None


def test_logo_png_elige_primero_ordenado(monkeypatch, tmp_path):
    (tmp_path / "b.png").write_bytes(b"x")
    (tmp_path / "a.png").write_bytes(b"x")
    monkeypatch.setattr(auto_fx, "_MARCA_DIR", tmp_path)
    assert auto_fx._logo_png() == tmp_path / "a.png"
