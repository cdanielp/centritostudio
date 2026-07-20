"""Tests de naming de variantes sin colisiones (P2 revision PR #23, F6).

Dos configuraciones que producen salida audiovisual distinta NO pueden escribir el
mismo MP4/ASS/sidecar. El tag es un helper unico y determinista (`cve.tag_variante`)
usado por CLI y Studio; los defaults conservan el naming historico (sin token).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import cve
import cve_presets
import jobs_render
import styles


@pytest.fixture
def custom_presets():
    """Inyecta presets personalizados reales (via construir_presets) y restaura _PRESETS."""
    original = cve._PRESETS
    cve._PRESETS = cve_presets.construir_presets(
        cve._PRESETS_BUILTIN,
        {
            "custom_top": {"base": "clean_podcast", "posicion": "top"},
            "custom_center": {"base": "clean_podcast", "posicion": "center"},
            "custom_nofaces": {"base": "clean_podcast", "avoid_faces": False},
        },
        set(styles.STYLES),
    )
    try:
        yield cve._PRESETS
    finally:
        cve._PRESETS = original


# ── tag_variante: allowlist + tokens compactos + determinista ─────────────────


def test_tag_historico_intacto():
    # Sin params nuevos, el naming historico no cambia (compat CLI + Studio)
    assert cve.tag_variante("karaoke_highlight", None) == "_karaoke_highlight"
    assert cve.tag_variante("keyword_punch", "viral") == "_keyword_punch_viral"
    assert cve.tag_variante("keyword_punch", "clean", "media") == "_keyword_punch_clean_media"


def test_densidad_baja_vs_alta_tags_distintos():
    baja = cve.tag_variante("keyword_punch", "clean", "baja")
    alta = cve.tag_variante("keyword_punch", "clean", "alta")
    assert baja != alta and "baja" in baja and "alta" in alta


def test_position_cambia_tag_solo_si_no_default():
    assert cve.tag_variante("clean_podcast", None, None, "bottom") == "_clean_podcast"  # default
    assert cve.tag_variante("clean_podcast", None, None, "center") != "_clean_podcast"
    assert cve.tag_variante("clean_podcast", None, None, "top") != cve.tag_variante(
        "clean_podcast", None, None, "center"
    )


def test_avoid_faces_false_cambia_tag_true_no():
    assert cve.tag_variante("clean_podcast", None, None, None, True) == "_clean_podcast"  # default
    assert cve.tag_variante("clean_podcast", None, None, None, None) == "_clean_podcast"
    assert cve.tag_variante("clean_podcast", None, None, None, False) != "_clean_podcast"


def test_tag_determinista():
    a = cve.tag_variante("keyword_punch", "viral", "alta", "center", False)
    b = cve.tag_variante("keyword_punch", "viral", "alta", "center", False)
    assert a == b


def test_tag_valores_invalidos_no_agregan_token_inseguro():
    # allowlist: intensidad/densidad/position fuera de rango no meten valores libres
    assert cve.tag_variante("keyword_punch", "rm -rf", "../etc", "diagonal") == "_keyword_punch"


# ── _rutas_render (Studio): densidad/position/avoid_faces separan salidas ──────


def _rutas(tmp_path, monkeypatch, plan, **kw):
    monkeypatch.setattr(jobs_render, "OUTPUT_DIR", tmp_path)
    return jobs_render._rutas_render("demo", plan, "hormozi", None, "clean", False, False, **kw)


def test_rutas_densidad_separa_mp4_ass_y_sidecar(tmp_path, monkeypatch):
    plan = cve.resolve_preset("keyword_punch", "clean", "baja")
    ass_b, mp4_b = _rutas(tmp_path, monkeypatch, plan, densidad="baja")
    ass_a, mp4_a = _rutas(tmp_path, monkeypatch, plan, densidad="alta")
    assert mp4_b != mp4_a and ass_b != ass_a
    # el sidecar de seleccion se deriva del mp4 -> tambien distinto
    assert mp4_b.with_suffix(".keyword_selection.json") != mp4_a.with_suffix(
        ".keyword_selection.json"
    )


def test_rutas_position_y_avoid_faces_separan(tmp_path, monkeypatch):
    plan = cve.resolve_preset("keyword_punch", "clean")
    _ass0, mp4_base = _rutas(tmp_path, monkeypatch, plan)
    _ass1, mp4_center = _rutas(tmp_path, monkeypatch, plan, position="center")
    _ass2, mp4_nofaces = _rutas(tmp_path, monkeypatch, plan, avoid_faces=False)
    assert len({mp4_base, mp4_center, mp4_nofaces}) == 3


def test_rutas_misma_config_determinista(tmp_path, monkeypatch):
    plan = cve.resolve_preset("keyword_punch", "clean", "alta")
    a = _rutas(tmp_path, monkeypatch, plan, densidad="alta", position="center", avoid_faces=False)
    b = _rutas(tmp_path, monkeypatch, plan, densidad="alta", position="center", avoid_faces=False)
    assert a == b


def test_rutas_sin_cve_conserva_naming_historico(tmp_path, monkeypatch):
    ass, mp4 = _rutas(tmp_path, monkeypatch, None)
    assert mp4.name == "demo_hormozi.mp4" and ass.name == "demo_hormozi.ass"


def test_rutas_usa_tag_variante_como_fuente_unica(tmp_path, monkeypatch):
    plan = cve.resolve_preset("keyword_punch", "clean")
    _ass, mp4 = _rutas(
        tmp_path, monkeypatch, plan, densidad="alta", position="top", avoid_faces=False
    )
    tag = cve.tag_variante("keyword_punch", "clean", "alta", "top", False)
    assert mp4.name == f"demo{tag}.mp4"


# ── BLOQUEO 4: naming compara override contra el default DEL PRESET ────────────


def test_custom_default_top_vs_override_bottom_distintos(custom_presets):
    # preset custom con default top: el default no agrega token; override bottom si
    por_default = cve.tag_variante("custom_top", None, None, "top")
    override = cve.tag_variante("custom_top", None, None, "bottom")
    assert por_default == "_custom_top"  # top == default -> historico
    assert override == "_custom_top_bottom"
    assert por_default != override


def test_custom_default_center_vs_override_bottom_distintos(custom_presets):
    por_default = cve.tag_variante("custom_center", None, None, "center")
    override = cve.tag_variante("custom_center", None, None, "bottom")
    assert por_default == "_custom_center" and override == "_custom_center_bottom"
    assert por_default != override


def test_custom_default_avoid_false_vs_override_true_distintos(custom_presets):
    por_default = cve.tag_variante("custom_nofaces", None, None, None, False)
    override = cve.tag_variante("custom_nofaces", None, None, None, True)
    assert por_default == "_custom_nofaces"  # False == default -> historico
    assert override == "_custom_nofaces_faces"
    assert por_default != override


def test_custom_default_avoid_true_vs_override_false_distintos(custom_presets):
    # built-in clean_podcast: default avoid True -> True historico, False -> _nofaces
    por_default = cve.tag_variante("clean_podcast", None, None, None, True)
    override = cve.tag_variante("clean_podcast", None, None, None, False)
    assert por_default == "_clean_podcast" and override == "_clean_podcast_nofaces"
    assert por_default != override


def test_default_efectivo_y_override_igual_no_colisiona(custom_presets):
    # position=None (usa default top) y position="top" (== default) -> mismo tag efectivo
    a = cve.tag_variante("custom_top", None, None, None)
    b = cve.tag_variante("custom_top", None, None, "top")
    assert a == b == "_custom_top"


def test_custom_preset_mp4_ass_sidecar_cambian_juntos(custom_presets, tmp_path, monkeypatch):
    plan = cve.resolve_preset("custom_top")  # default top
    ass_def, mp4_def = _rutas(tmp_path, monkeypatch, plan)  # sin override -> historico
    ass_ov, mp4_ov = _rutas(tmp_path, monkeypatch, plan, position="bottom")  # override
    assert mp4_def != mp4_ov and ass_def != ass_ov
    # el sidecar de seleccion se deriva del mp4 -> tambien distinto
    assert mp4_def.with_suffix(".keyword_selection.json") != mp4_ov.with_suffix(
        ".keyword_selection.json"
    )


def test_historicos_builtins_intactos_con_custom_presets_cargados(custom_presets):
    # cargar presets custom no altera el naming historico de los cuatro built-ins
    assert cve.tag_variante("clean_podcast", None) == "_clean_podcast"
    assert cve.tag_variante("viral_bounce", None) == "_viral_bounce"
    assert cve.tag_variante("keyword_punch", "viral") == "_keyword_punch_viral"
    assert cve.tag_variante("karaoke_highlight", None) == "_karaoke_highlight"
    # built-in default bottom: center/top agregan token (historico)
    assert cve.tag_variante("clean_podcast", None, None, "center") == "_clean_podcast_center"
    assert cve.tag_variante("clean_podcast", None, None, "top") == "_clean_podcast_top"


def test_valores_invalidos_nunca_entran_al_nombre(custom_presets):
    assert cve.tag_variante("custom_top", "rm -rf", "../etc", "diagonal") == "_custom_top"
    # avoid_faces no-bool (None) nunca agrega token
    assert cve.tag_variante("custom_nofaces", None, None, None, None) == "_custom_nofaces"


def test_cli_pasar_defaults_del_preset_es_byte_identico(custom_presets):
    # La CLI pasa plan.position/plan.avoid_faces (defaults del preset): mismo tag que omitirlos
    for preset in ("clean_podcast", "keyword_punch", "custom_top", "custom_nofaces"):
        plan = cve.resolve_preset(preset)
        con = cve.tag_variante(preset, None, None, plan.position, plan.avoid_faces)
        sin = cve.tag_variante(preset, None, None)
        assert con == sin == f"_{preset}"  # defaults del preset -> sin token (historico)
