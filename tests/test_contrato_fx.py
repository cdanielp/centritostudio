"""Tests de contrato de la capa FX local (S36-FX): fx.py puro.

Contratos verificados:
- Preset desconocido / None -> plan vacio (apagado por default).
- Plan desde brain usa kw_ts para los punch-ins.
- Fallback (sin brain) genera POCOS efectos y respeta los limites visuales.
- Filtro punch-in contiene crop/scale con easing no lineal (sin()).
- Filtro flash contiene blanco con alpha en ventana temporal (enable/between).
- Filtro scanner contiene drawbox rojo con ventana temporal.
- Duraciones/zoom dentro de los rangos S36-FX.
- logo/outro se materializa como Popup real (PNG, encima del ass).
- El brain roto/ausente cae a None (fail-open).
"""

from __future__ import annotations

import json

import fx


def _brain(kw_ts):
    return {
        "kw_ts": list(kw_ts),
        "segment_bounds": fx._bounds_por_gap(list(kw_ts), fx.SEG_GAP_S),
        "emphasis_ts": fx._espaciar(list(kw_ts), fx.SCANNER_MIN_GAP_S),
    }


# ── plan apagado por default ─────────────────────────────────────────────────


def test_preset_none_plan_vacio():
    p = fx.generar_plan_fx(30.0, None)
    assert p.vacio()
    assert p.punch_ins == [] and p.logo is None


def test_preset_desconocido_plan_vacio():
    assert fx.generar_plan_fx(30.0, "marte").vacio()


def test_duracion_cero_plan_vacio():
    assert fx.generar_plan_fx(0.0, "pro").vacio()


# ── plan desde brain usa kw_ts ───────────────────────────────────────────────


def test_plan_desde_brain_usa_kw_ts():
    kw = [0.0, 2.4, 6.0, 11.0, 16.0, 22.0, 28.0]
    p = fx.generar_plan_fx(32.0, "pro", _brain(kw))
    assert p.punch_ins, "hay punch-ins"
    # cada punch arranca en un kw_ts real (respetando separacion minima)
    for pi in p.punch_ins:
        assert pi.t0 in kw, f"punch en {pi.t0} no viene de kw_ts"
    # separacion minima respetada
    for a, b in zip(p.punch_ins, p.punch_ins[1:], strict=False):
        assert b.t0 - a.t0 >= fx.PUNCH_MIN_GAP_S


def test_flash_desde_fronteras_de_segmento():
    # kw_ts con un salto grande (>= SEG_GAP_S) => frontera => flash en pro
    kw = [1.0, 1.5, 2.0, 10.0, 10.5]  # frontera en 10.0
    p = fx.generar_plan_fx(20.0, "pro", _brain(kw))
    assert any(abs(fl.t0 - 10.0) < 0.001 for fl in p.flashes)


# ── fallback: pocos efectos, dentro de limites ───────────────────────────────


def test_fallback_sin_brain_pocos_efectos():
    p = fx.generar_plan_fx(30.0, "pro", brain_data=None)
    # cadencia ~5.5s punch, ~11s scanner en 30s -> conteos chicos
    assert 1 <= len(p.punch_ins) <= 30 // int(fx.PUNCH_MIN_GAP_S)
    assert len(p.scanners) <= 4
    assert p.flashes == [], "sin datos no hay fronteras -> sin flash"


def test_fallback_respeta_rangos():
    p = fx.generar_plan_fx_fallback(40.0, "premium")
    for pi in p.punch_ins:
        assert 0.6 <= round(pi.t1 - pi.t0, 3) <= 1.2
        assert 1.08 <= pi.zoom <= 1.12
    for sc in p.scanners:
        assert 0.5 <= round(sc.t1 - sc.t0, 3) <= 0.8


def test_express_solo_punch_y_logo(tmp_path):
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"\x89PNG")
    p = fx.generar_plan_fx(20.0, "express", brain_data=None, logo_png=logo)
    assert p.punch_ins and not p.flashes and not p.scanners
    assert p.logo is not None and p.logo.pos == "top_right"


def test_premium_tiene_outro(tmp_path):
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"\x89PNG")
    p = fx.generar_plan_fx_fallback(20.0, "premium", logo_png=logo)
    assert p.logo is not None and p.logo.pos == "center"
    assert p.logo.start >= 20.0 - fx.OUTRO_S - 0.01


# ── filtros FFmpeg ───────────────────────────────────────────────────────────


def test_filtro_punch_tiene_zoom_y_easing():
    p = fx.FXPlan(punch_ins=[fx.PunchIn(2.0, 2.9, 1.10)])
    chain, out = fx.construir_filtro_video_fx("0:v", p, 1080, 1920, fps=30.0)
    assert out == "vfx"
    # zoompan = zoom animado por frame (equivalente a scale/crop para punch-in)
    assert "zoompan=" in chain and "s=1080x1920" in chain
    assert "sin(" in chain, "easing no lineal obligatorio"
    assert "fps=30.0000" in chain, "fps de la fuente para no desincronizar audio"


def test_filtro_flash_blanco_con_alpha_temporal():
    p = fx.FXPlan(flashes=[fx.Flash(5.0, 0.14, 0.7)])
    chain, _ = fx.construir_filtro_video_fx("0:v", p, 1080, 1920)
    assert "drawbox" in chain and "white@" in chain
    assert "enable='between(t,5.000,5.140)'" in chain


def test_filtro_scanner_rojo_drawbox_temporal():
    p = fx.FXPlan(scanners=[fx.Scanner(8.0, 8.6)])
    chain, _ = fx.construir_filtro_video_fx("0:v", p, 1080, 1920)
    assert "red@" in chain and chain.count("drawbox") == fx.SCANNER_STEPS
    # barrido escalonado: la primera barra arranca en el inicio de la ventana
    assert "enable='between(t,8.000," in chain
    # y estatica distinta por paso (arriba en el primer paso, abajo en el ultimo)
    assert "y=0:" in chain, "primer paso arriba"


def test_filtro_vacio_sin_efectos():
    chain, out = fx.construir_filtro_video_fx("0:v", fx.FXPlan(), 1080, 1920)
    assert chain == "" and out == "0:v", "sin efectos: no altera la cadena"


# ── logo como Popup real ─────────────────────────────────────────────────────


def test_logo_a_popup(tmp_path):
    logo = tmp_path / "marca.png"
    logo.write_bytes(b"\x89PNG")
    p = fx.generar_plan_fx(20.0, "express", brain_data=None, logo_png=logo)
    popup = fx.logo_a_popup(p)
    assert popup is not None
    assert popup.png == logo and popup.behind_text is False
    assert popup.pos == "top_right"


def test_logo_a_popup_none_sin_logo():
    assert fx.logo_a_popup(fx.FXPlan()) is None


# ── carga de brain fail-open ─────────────────────────────────────────────────


def test_cargar_brain_ausente_none(tmp_path):
    assert fx.cargar_brain_fx(tmp_path / "no_existe.brain.json") is None


def test_cargar_brain_roto_none(tmp_path):
    p = tmp_path / "x.brain.json"
    p.write_text("{roto", encoding="utf-8")
    assert fx.cargar_brain_fx(p) is None


def test_cargar_brain_extrae_kw_ts(tmp_path):
    p = tmp_path / "x.brain.json"
    data = {"groups": [{"g": 0, "kw_ts": 1.0}, {"g": 1, "kw_ts": None}, {"g": 2, "kw_ts": 5.5}]}
    p.write_text(json.dumps(data), encoding="utf-8")
    out = fx.cargar_brain_fx(p)
    assert out is not None and out["kw_ts"] == [1.0, 5.5]


# ── integracion con core_overlays.construir_comando ──────────────────────────


def _args_base():
    from pathlib import Path

    return (Path("in.mp4"), "out/x.ass", Path("out.mp4"), [], 216, 1300, 0.12)


def test_construir_comando_sin_fx_ruta_ass_sobre_0v():
    import core_overlays as co

    cmd = co.construir_comando(*_args_base(), 1080, 1920, None, None)
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "[0:v]ass=" in fc, "sin fx el ass se aplica sobre 0:v (ruta historica)"
    assert "vfx" not in fc


def test_construir_comando_con_fx_ass_sobre_vfx_y_audio_intacto():
    import core_overlays as co

    plan = fx.FXPlan(punch_ins=[fx.PunchIn(2.0, 2.9, 1.10)], flashes=[fx.Flash(5.0, 0.14, 0.7)])
    chain, _ = fx.construir_filtro_video_fx("0:v", plan, 1080, 1920)
    cmd = co.construir_comando(*_args_base(), 1080, 1920, None, chain)
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert fc.startswith("[0:v]zoompan="), "el FX consume 0:v primero"
    assert "[vfx]ass=" in fc, "el ass se quema DESPUES del FX (captions no deformadas)"
    # audio jamas se toca
    maps = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-map"]
    assert "0:a" in maps
    assert cmd[cmd.index("-c:a") + 1] == "copy"


def test_burn_delega_sin_fx_ni_overlays(monkeypatch, tmp_path):
    import core_ass

    llamado = []
    monkeypatch.setattr(core_ass, "burn_video", lambda *a: llamado.append(a) or 1.0)
    r = core_ass.burn_video_with_emojis(
        tmp_path / "in.mp4", tmp_path / "x.ass", tmp_path / "out.mp4", [], None, None, None
    )
    assert llamado and r == 1.0, "sin fx/emojis/popups sigue delegando en burn_video"
