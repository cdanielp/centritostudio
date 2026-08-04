"""HF-3 bloque 1: los limites de `clip_overlay` que el Motor B necesitaba desbloqueados.

Cuatro cosas se fijan aqui, todas sobre STRINGS de filtro (nunca pixeles, invariante I5):

1. Con los valores historicos (`fit="cover"`, `posicion=None`, `mute=True`) los filtros salen
   BYTE IDENTICOS a los de antes de HF-3. Es el freno de I1 a nivel de constructor puro.
2. `fit="nativo"` no emite NINGUN filtro de escala ni de crop.
3. `posicion=(x, y)` coloca coordenadas literales; `None` conserva el centrado por expresion.
4. El validador acepta `mute=False` solo si se le baja `exigir_mute` de forma explicita.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import clip_overlay as co

CLIP = Path("clip.mp4")


def _prep(**kw) -> dict:
    base = {"clip": CLIP, "t0": 1.0, "t1": 3.0, "loop": False, "fade": False}
    c = co.ClipOverlay(**{**base, **kw})
    return co.preparar_clip(c, 1080, 1920, 30.0)


@pytest.fixture(autouse=True)
def _clip_existe(monkeypatch):
    """`preparar_clip` exige que el archivo exista; aqui solo interesan los strings."""
    monkeypatch.setattr(co.Path, "exists", lambda self: True)


# ── 1. Byte identico con los valores historicos ──────────────────────────────


def test_filtro_cover_centrado_es_byte_identico_al_historico():
    prep = _prep()
    assert co.filtro_clip(2, prep, "cb0") == (
        "[2:v]trim=start=0.000:duration=2.000,setpts=PTS-STARTPTS,fps=30.000,"
        "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        "setsar=1,format=yuva420p,setpts=PTS-STARTPTS+1.000/TB[cb0]"
    )
    assert co.overlay_clip("0:v", "cb0", prep, "vcb0") == (
        "[0:v][cb0]overlay=x=(W-w)/2:y=(H-h)/2:"
        "eof_action=pass:repeatlast=0:enable='between(t,1.000,3.000)'[vcb0]"
    )


def test_el_default_de_clipoverlay_no_cambio():
    c = co.ClipOverlay(clip=CLIP, t0=0.0, t1=1.0)
    assert (c.fit, c.posicion, c.mute, c.fade, c.loop) == ("cover", None, True, True, True)


# ── 2. fit nativo ────────────────────────────────────────────────────────────


def test_fit_nativo_no_emite_escala_ni_crop():
    filtro = co.filtro_clip(2, _prep(fit="nativo"), "cb0")
    assert "scale=" not in filtro
    assert "crop=" not in filtro
    assert filtro == (
        "[2:v]trim=start=0.000:duration=2.000,setpts=PTS-STARTPTS,fps=30.000,"
        "setsar=1,format=yuva420p,setpts=PTS-STARTPTS+1.000/TB[cb0]"
    )


def test_fit_nativo_es_valido_y_contain_sigue_sin_serlo():
    assert co.FIT_VALIDOS == frozenset({"cover", "nativo"})
    assert _prep(fit="nativo") is not None
    assert _prep(fit="contain") is None  # fail-open del render: se omite ese clip


# ── 3. posicion ──────────────────────────────────────────────────────────────


def test_posicion_explicita_coloca_coordenadas_literales():
    salida = co.overlay_clip("0:v", "cb0", _prep(posicion=(120, 940)), "vcb0")
    assert "overlay=x=120:y=940:" in salida


def test_posicion_negativa_es_valida_la_pieza_puede_sangrar_fuera_del_cuadro():
    co.validar_posicion((-40, -10))
    assert "overlay=x=-40:y=-10:" in co.overlay_clip("0:v", "c", _prep(posicion=(-40, -10)), "v")


@pytest.mark.parametrize("mala", [(1.5, 2), (1, True), (1,), "10,20", [1, 2, 3]])
def test_posicion_invalida_es_error_de_contrato(mala):
    with pytest.raises(ValueError, match="posicion invalida"):
        co.validar_posicion(mala)


def test_posicion_invalida_desactiva_el_clip_sin_tumbar_el_render():
    assert _prep(posicion=(1.5, 2)) is None


# ── 4. mute parametrizable ───────────────────────────────────────────────────


def _validar(**kw):
    base = {
        "t0": 0.0,
        "t1": 1.0,
        "source_start": 0.0,
        "fit": "cover",
        "size_pct": 1.0,
        "loop": True,
        "mute": True,
    }
    co.validar_clip_overlay(**{**base, **kw})


def test_mute_false_se_rechaza_por_default():
    with pytest.raises(ValueError, match="mute=True es obligatorio"):
        _validar(mute=False)


def test_mute_false_se_acepta_solo_bajando_exigir_mute_a_proposito():
    _validar(mute=False, exigir_mute=False)


def test_mute_no_booleano_se_rechaza_aunque_no_se_exija():
    with pytest.raises(ValueError, match="mute debe ser booleano"):
        _validar(mute="si", exigir_mute=False)


def test_validador_acepta_los_dos_fit_soportados():
    _validar(fit="nativo")
    _validar(fit="cover")
    with pytest.raises(ValueError, match="fit invalido"):
        _validar(fit="contain")
