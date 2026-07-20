"""Tests de naming de variantes sin colisiones (P2 revision PR #23, F6).

Dos configuraciones que producen salida audiovisual distinta NO pueden escribir el
mismo MP4/ASS/sidecar. El tag es un helper unico y determinista (`cve.tag_variante`)
usado por CLI y Studio; los defaults conservan el naming historico (sin token).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import cve
import jobs_render

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
