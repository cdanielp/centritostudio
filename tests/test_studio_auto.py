"""Contrato publico de configuracion del Automatico en Studio (S37-C)."""

import json

import pytest

import studio_auto
from auto_config import AutoConfig


def test_capabilities_default_y_catalogos_exactos():
    data = studio_auto.capacidades_auto()
    assert data["default_mode"] == "classic"
    assert [m["id"] for m in data["modes"]] == ["classic", "v2"]
    assert data["fx_presets"] == ["express", "pro", "premium"]


def test_capabilities_defaults_v2_y_reglas_fijas():
    data = studio_auto.capacidades_auto()
    assert data["v2_defaults"] == {
        "broll_enabled": True,
        "fx_enabled": True,
        "fx_preset": "express",
        "verify_av": True,
        "manual_sidecars": True,
    }
    assert data["fixed_rules"] == {
        "hook_protected_s": 3.0,
        "max_video_windows": 1,
        "max_coverage_pct": 0.35,
        "captions": True,
        "reframe": "9:16",
    }


def test_capabilities_no_exponen_secretos_ni_rutas():
    texto = json.dumps(studio_auto.capacidades_auto()).lower()
    for forbidden in ("api_key", "authorization", "c:\\", "transcripts/", "output/"):
        assert forbidden not in texto


def test_pexels_status_fail_open(monkeypatch):
    monkeypatch.setattr(
        studio_auto, "import_module", lambda _name: (_ for _ in ()).throw(ImportError())
    )
    data = studio_auto.capacidades_auto()
    assert data["pexels"]["images"]["enabled"] is False
    assert data["pexels"]["videos"]["enabled"] is False
    assert "pipeline" in data["pexels"]["images"]["message"]


def test_construir_classic_devuelve_none():
    assert (
        studio_auto.construir_auto_config(
            mode="classic", broll_enabled=True, fx_enabled=True, fx_preset="express"
        )
        is None
    )


@pytest.mark.parametrize("preset", ["express", "pro", "premium"])
def test_construir_v2_exacto_y_protecciones_forzadas(preset):
    config = studio_auto.construir_auto_config(
        mode="v2", broll_enabled=False, fx_enabled=False, fx_preset=preset
    )
    assert isinstance(config, AutoConfig)
    assert config.mode == "v2"
    assert config.broll_enabled is False and config.fx_enabled is False
    assert config.fx_preset == preset
    assert config.verify_av is True and config.manual_sidecars is True


@pytest.mark.parametrize(("field", "value"), [("mode", "auto"), ("fx_preset", "ultra")])
def test_parametro_invalido(field, value):
    kwargs = dict(mode="v2", broll_enabled=True, fx_enabled=True, fx_preset="express")
    kwargs[field] = value
    with pytest.raises(ValueError):
        studio_auto.construir_auto_config(**kwargs)


@pytest.mark.parametrize(("field", "value"), [("broll_enabled", "true"), ("fx_enabled", 1)])
def test_funcion_pura_rechaza_bools_ambiguos(field, value):
    kwargs = dict(mode="v2", broll_enabled=True, fx_enabled=True, fx_preset="express")
    kwargs[field] = value
    with pytest.raises(TypeError):
        studio_auto.construir_auto_config(**kwargs)
