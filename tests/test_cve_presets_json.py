"""Tests de carga segura de cve_presets.json (F6 esencial, PASO E; DISENO_CVE §6).

Mismo patron fail-safe por-campo de styles.json. Garantias:
- Ausente / JSON roto / no-dict -> {} (built-ins intactos).
- Allowlists + validacion de tipos/rangos: campo invalido/desconocido -> se ignora.
- Preset nuevo sin `base` valido hereda de clean_podcast (el mas sobrio).
- Sin ejecucion arbitraria; sin rutas privadas: solo un allowlist de campos.
- Built-ins existentes intactos (override campo por campo).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import cve
import cve_presets

_STYLES = {"clean", "hormozi", "karaoke"}


def _builtins() -> dict:
    # Copia superficial de los presets built-in reales del motor.
    import copy

    return copy.deepcopy(cve._PRESETS_BUILTIN)


# ── cargar: fail-safe de lectura ──────────────────────────────────────────────


def test_cargar_ausente_es_vacio(tmp_path):
    assert cve_presets.cargar(tmp_path / "no_existe.json") == {}


def test_cargar_json_corrupto_es_vacio(tmp_path):
    p = tmp_path / "cve_presets.json"
    p.write_text("{ esto no es json ", encoding="utf-8")
    assert cve_presets.cargar(p) == {}


def test_cargar_no_dict_es_vacio(tmp_path):
    p = tmp_path / "cve_presets.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    assert cve_presets.cargar(p) == {}


def test_cargar_desenvuelve_presets(tmp_path):
    p = tmp_path / "cve_presets.json"
    p.write_text('{"presets": {"mio": {"base": "clean_podcast"}}}', encoding="utf-8")
    assert cve_presets.cargar(p) == {"mio": {"base": "clean_podcast"}}


# ── construir_presets: built-ins intactos ─────────────────────────────────────


def test_user_vacio_deja_builtins_intactos():
    b = _builtins()
    assert cve_presets.construir_presets(b, {}, _STYLES) == b


def test_override_de_builtin_campo_por_campo():
    out = cve_presets.construir_presets(
        _builtins(), {"keyword_punch": {"posicion": "center", "avoid_faces": False}}, _STYLES
    )
    assert out["keyword_punch"]["position"] == "center"
    assert out["keyword_punch"]["avoid_faces"] is False
    # el resto del built-in intacto
    assert out["keyword_punch"]["keywords"] == "auto+brain"


# ── validacion / allowlists ───────────────────────────────────────────────────


def test_intensidad_invalida_se_ignora():
    out = cve_presets.construir_presets(
        _builtins(), {"clean_podcast": {"intensidad": "explosiva"}}, _STYLES
    )
    assert out["clean_podcast"]["intensidad"] == "clean"  # base intacto


def test_campo_desconocido_no_se_copia():
    out = cve_presets.construir_presets(
        _builtins(), {"clean_podcast": {"comando": "rm -rf", "foo": 1}}, _STYLES
    )
    assert "comando" not in out["clean_podcast"] and "foo" not in out["clean_podcast"]


def test_posicion_fuera_de_allowlist_se_ignora():
    out = cve_presets.construir_presets(
        _builtins(), {"clean_podcast": {"posicion": "diagonal"}}, _STYLES
    )
    assert out["clean_podcast"]["position"] == "bottom"


def test_overlays_bool_se_mapea():
    out = cve_presets.construir_presets(_builtins(), {"clean_podcast": {"overlays": True}}, _STYLES)
    assert out["clean_podcast"]["overlays"] == "brain"


def test_keywords_allowlist():
    out = cve_presets.construir_presets(
        _builtins(),
        {"a": {"keywords": "manual"}, "b": {"keywords": "inventado"}},
        _STYLES,
    )
    assert out["a"]["keywords"] == "manual"
    assert out["b"]["keywords"] == "off"  # invalido -> hereda de clean_podcast (off)


# ── presets nuevos / defaults ─────────────────────────────────────────────────


def test_preset_nuevo_sin_base_hereda_clean_podcast():
    out = cve_presets.construir_presets(_builtins(), {"mio": {"densidad": "alta"}}, _STYLES)
    assert out["mio"]["style"] == "clean"  # el de clean_podcast
    assert out["mio"]["keywords"] == "off"
    assert out["mio"]["densidad"] == "alta"


def test_preset_nuevo_con_base_valida_hereda_de_ella():
    out = cve_presets.construir_presets(
        _builtins(), {"mio": {"base": "keyword_punch", "posicion": "top"}}, _STYLES
    )
    assert out["mio"]["keywords"] == "auto+brain"  # heredado de keyword_punch
    assert out["mio"]["position"] == "top"


def test_base_desconocida_cae_a_clean_podcast():
    out = cve_presets.construir_presets(_builtins(), {"mio": {"base": "no_existe"}}, _STYLES)
    assert out["mio"]["keywords"] == "off"  # clean_podcast


def test_preset_incompleto_es_igual_a_su_base():
    out = cve_presets.construir_presets(_builtins(), {"mio": {}}, _STYLES)
    assert {k: out["mio"][k] for k in ("style", "keywords", "position")} == {
        "style": "clean",
        "keywords": "off",
        "position": "bottom",
    }


# ── style: nombre valido / invalido / dict de overrides ───────────────────────


def test_style_nombre_valido():
    out = cve_presets.construir_presets(_builtins(), {"mio": {"style": "hormozi"}}, _STYLES)
    assert out["mio"]["style"] == "hormozi"


def test_style_nombre_invalido_se_ignora():
    out = cve_presets.construir_presets(_builtins(), {"mio": {"style": "inexistente"}}, _STYLES)
    assert out["mio"]["style"] == "clean"  # base clean_podcast


def test_style_dict_overrides_validos():
    out = cve_presets.construir_presets(_builtins(), {"mio": {"style": {"font_size": 95}}}, _STYLES)
    assert out["mio"]["style_overrides"] == {"font_size": 95}


# ── integracion con el motor ──────────────────────────────────────────────────


def test_plan_desde_dict_aplica_style_overrides():
    preset = {"style": "clean", "style_overrides": {"font_size": 95}}
    plan = cve._plan_desde_dict("mio", preset, "clean", None)
    assert plan.style_cfg.font_size == 95


def test_builtins_reales_intactos_sin_json():
    # Sin cve_presets.json en la raiz, el registro efectivo = built-ins (4 presets)
    assert cve.list_presets() == [
        "clean_podcast",
        "karaoke_highlight",
        "keyword_punch",
        "viral_bounce",
    ]
