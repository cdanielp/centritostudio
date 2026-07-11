"""
Tests de contrato de la capa de estilos F5-s2 (s28A).

Cubre: styles.json válido · fallback si falta · fallback si inválido · fallback POR CAMPO
si un estilo está incompleto · --style existente sigue funcionando · animación
activable/desactivable por estilo · hormozi/clean/pms resuelven config sin romper captions.
Corre sin GPU ni FFmpeg (build_ass solo escribe el .ass con pysubs2).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import core_ass
import styles

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _grupo_demo() -> list[dict]:
    """Grupo de 3 palabras; la del medio es keyword. Con line_idx/start/end."""
    return [
        {"text": "hola", "start": 0.0, "end": 0.5, "line_idx": 0, "is_keyword": False},
        {"text": "mundo", "start": 0.5, "end": 1.0, "line_idx": 0, "is_keyword": True},
        {"text": "hoy", "start": 1.0, "end": 1.5, "line_idx": 0, "is_keyword": False},
    ]


# ─────────────────────────────────────────────────────────────────────────────
# --style existente sigue funcionando
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("nombre", ["hormozi", "clean", "karaoke", "bounce", "pms"])
def test_estilos_builtin_resuelven(nombre):
    cfg = styles.get_style(nombre)
    assert cfg.name == nombre
    assert cfg.font_size > 0


def test_clean_es_nuevo_builtin():
    assert "clean" in styles.list_styles()


def test_estilo_inexistente_lanza_error():
    with pytest.raises(ValueError):
        styles.get_style("no_existe_xyz")


# ─────────────────────────────────────────────────────────────────────────────
# Intensidad de pop (suave / fuerte / off / float / inválido fail-safe)
# ─────────────────────────────────────────────────────────────────────────────


def test_pop_niveles_resuelven():
    # Los 4 niveles vigentes (D19): off/suave/medio/fuerte.
    assert styles.get_style("hormozi", "off").pop_scale == pytest.approx(1.0)
    assert styles.get_style("hormozi", "suave").pop_scale == pytest.approx(1.08)
    assert styles.get_style("hormozi", "medio").pop_scale == pytest.approx(1.30)
    assert styles.get_style("hormozi", "fuerte").pop_scale == pytest.approx(1.45)


def test_hormozi_default_es_suave_con_rebote():
    # Default FINAL tras el A/B s28D (cierre D20): suave 1.08 CON rebote.
    cfg = styles.get_style("hormozi")
    assert cfg.pop_scale == pytest.approx(1.08)
    assert cfg.overshoot is True


def test_overshoot_override_en_get_style():
    # get_style permite sobrescribir el rebote (fail-safe: None usa el del estilo).
    assert styles.get_style("hormozi", "suave", overshoot=True).overshoot is True
    assert styles.get_style("hormozi", "suave", overshoot=False).overshoot is False
    assert styles.get_style("hormozi", "suave").overshoot is True  # None -> el del estilo


def test_pop_float_directo():
    assert styles.get_style("hormozi", 1.12).pop_scale == pytest.approx(1.12)


def test_pop_invalido_es_failsafe():
    # Un pop desconocido no rompe: se ignora y se usa el pop_scale del estilo.
    base = styles.get_style("hormozi").pop_scale
    assert styles.get_style("hormozi", "explosivo").pop_scale == pytest.approx(base)
    assert styles.get_style("hormozi", 9.0).pop_scale == pytest.approx(base)


def test_get_style_no_muta_el_registro():
    # Override de pop devuelve copia; el STYLES global no cambia.
    antes = styles.STYLES["hormozi"].pop_scale
    styles.get_style("hormozi", "fuerte")
    assert styles.STYLES["hormozi"].pop_scale == pytest.approx(antes)


# ─────────────────────────────────────────────────────────────────────────────
# Animación activable / desactivable por estilo (sobre el ASS real)
# ─────────────────────────────────────────────────────────────────────────────


def test_rebote_medio_dos_tramos():
    # medio 1.30 con rebote ON -> reposo 130, pico 146 (130*1.12), dos \t.
    cfg = styles.get_style("hormozi", "medio", overshoot=True)
    txt = core_ass._word_event_text(_grupo_demo(), active_idx=0, style_cfg=cfg)
    assert txt.count("\\t(") == 2  # rebote = dos tramos
    assert "\\fscx146" in txt  # pico (overshoot)
    assert "\\fscx130" in txt  # reposo del énfasis (más grande que los vecinos)


def test_rebote_fuerte_pico_162():
    cfg = styles.get_style("hormozi", "fuerte", overshoot=True)  # 1.45 con rebote
    txt = core_ass._word_event_text(_grupo_demo(), active_idx=0, style_cfg=cfg)
    assert "\\fscx162" in txt  # 145*1.12
    assert "\\fscx145" in txt  # reposo


def test_rebote_desactivable_por_estilo():
    cfg = styles.get_style("hormozi", "medio", overshoot=False)
    txt = core_ass._word_event_text(_grupo_demo(), active_idx=0, style_cfg=cfg)
    assert txt.count("\\t(") == 1  # pop simple: un solo tramo, crece y se queda
    assert "\\fscx130" in txt  # reposo del énfasis
    assert "\\fscx146" not in txt  # sin overshoot no hay pico


def test_suave_con_y_sin_rebote():
    # El A/B de s28D: suave 1.08, mismo reposo (108), difieren en el rebote.
    plano = styles.get_style("hormozi", "suave", overshoot=False)
    reb = styles.get_style("hormozi", "suave", overshoot=True)
    t_plano = core_ass._word_event_text(_grupo_demo(), 0, plano)
    t_reb = core_ass._word_event_text(_grupo_demo(), 0, reb)
    assert t_plano.count("\\t(") == 1 and "\\fscx108" in t_plano  # crece y se queda
    assert t_reb.count("\\t(") == 2 and "\\fscx121" in t_reb  # pico round(108*1.12)=121


def test_pop_off_byte_identico_al_estatico():
    # off (pop 1.0) = caption estático: solo color, sin transform \t.
    cfg = styles.get_style("hormozi", "off")
    txt = core_ass._word_event_text(_grupo_demo(), active_idx=0, style_cfg=cfg)
    assert "\\t(" not in txt
    assert "{\\c" + cfg.highlight_color + "}HOLA{\\r}" in txt


def test_animacion_desactivable_clean_sin_pop():
    cfg = styles.get_style("clean")  # pop 1.0 -> sin scale-pop
    txt = core_ass._word_event_text(_grupo_demo(), active_idx=0, style_cfg=cfg)
    # Palabra activa 0 (no-keyword): solo color, sin transform \t.
    assert "\\t(" not in txt
    # Pero el color de realce sí está presente.
    assert cfg.highlight_color in txt


def test_pop_off_no_emite_transform():
    cfg = styles.get_style("hormozi", "off")
    txt = core_ass._word_event_text(_grupo_demo(), active_idx=0, style_cfg=cfg)
    assert "\\t(" not in txt


# ─────────────────────────────────────────────────────────────────────────────
# build_ass no rompe con hormozi/clean/pms
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("nombre", ["hormozi", "clean", "pms"])
def test_build_ass_no_rompe(nombre, tmp_path):
    cfg = styles.get_style(nombre)
    groups = [{"id": 0, "start": 0.0, "end": 1.5, "text": "hola mundo hoy", "words": _grupo_demo()}]
    out = tmp_path / f"{nombre}.ass"
    core_ass.build_ass(groups, 1080, 1920, cfg, out)
    assert out.exists() and out.stat().st_size > 0


# ─────────────────────────────────────────────────────────────────────────────
# _merge_style — fallback POR CAMPO
# ─────────────────────────────────────────────────────────────────────────────


def test_merge_por_campo_aplica_validos_ignora_invalidos():
    base = styles.STYLES["hormozi"]
    merged = styles._merge_style(
        base,
        {
            "font_size": 120,  # válido -> aplica
            "highlight_color": "NO_ES_COLOR",  # inválido -> cae a base
            "campo_desconocido": "x",  # ignorado
        },
    )
    assert merged.font_size == 120
    assert merged.highlight_color == base.highlight_color  # per-field fallback


def test_merge_sin_overrides_devuelve_base():
    base = styles.STYLES["clean"]
    assert styles._merge_style(base, {}) is base


def test_styles_json_sin_overshoot_default_false(monkeypatch, tmp_path):
    # Estilo nuevo en JSON sin 'overshoot' -> default False (pop simple, fail-safe).
    p = tmp_path / "styles.json"
    p.write_text(json.dumps({"marca_x": {"pop_scale": 1.4}}), encoding="utf-8")
    monkeypatch.setattr(styles, "_STYLES_JSON", p)
    built = styles._build_styles()
    assert built["marca_x"].pop_scale == pytest.approx(1.4)
    assert built["marca_x"].overshoot is False


def test_styles_json_overshoot_configurable(monkeypatch, tmp_path):
    p = tmp_path / "styles.json"
    p.write_text(json.dumps({"clean": {"overshoot": True}}), encoding="utf-8")
    monkeypatch.setattr(styles, "_STYLES_JSON", p)
    assert styles._build_styles()["clean"].overshoot is True


# ─────────────────────────────────────────────────────────────────────────────
# _load_overrides / _build_styles — styles.json válido, ausente, inválido
# ─────────────────────────────────────────────────────────────────────────────


def test_styles_json_valido_sobrescribe(monkeypatch, tmp_path):
    p = tmp_path / "styles.json"
    p.write_text(
        json.dumps({"hormozi": {"font_size": 111}, "marca_k": {"font_name": "Impact"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(styles, "_STYLES_JSON", p)
    built = styles._build_styles()
    assert built["hormozi"].font_size == 111  # override sobre existente
    assert "marca_k" in built  # estilo nuevo desde JSON
    assert built["marca_k"].font_name == "Impact"


def test_styles_json_ausente_deja_builtins(monkeypatch, tmp_path):
    monkeypatch.setattr(styles, "_STYLES_JSON", tmp_path / "no_existe.json")
    built = styles._build_styles()
    assert built["hormozi"].font_size == styles._BUILTIN["hormozi"].font_size
    assert set(styles._BUILTIN).issubset(set(built))


def test_styles_json_invalido_deja_builtins(monkeypatch, tmp_path):
    p = tmp_path / "styles.json"
    p.write_text("{ esto no es json valido ][", encoding="utf-8")
    monkeypatch.setattr(styles, "_STYLES_JSON", p)
    built = styles._build_styles()
    assert built["hormozi"].font_size == styles._BUILTIN["hormozi"].font_size


def test_styles_json_estilo_incompleto_cae_por_campo(monkeypatch, tmp_path):
    # Estilo existente con un campo inválido: el válido aplica, el inválido cae a builtin.
    p = tmp_path / "styles.json"
    p.write_text(
        json.dumps({"clean": {"margin_pct": 0.2, "outline_color": "roto"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(styles, "_STYLES_JSON", p)
    built = styles._build_styles()
    assert built["clean"].margin_pct == pytest.approx(0.2)  # válido aplica
    assert built["clean"].outline_color == styles._BUILTIN["clean"].outline_color  # inválido cae


def test_styles_json_seccion_styles_anidada(monkeypatch, tmp_path):
    # Admite el formato {"styles": {...}} además del dict directo.
    p = tmp_path / "styles.json"
    p.write_text(json.dumps({"styles": {"hormozi": {"font_size": 77}}}), encoding="utf-8")
    monkeypatch.setattr(styles, "_STYLES_JSON", p)
    assert styles._build_styles()["hormozi"].font_size == 77


def test_build_styles_default_actual_no_tiene_styles_json():
    # En el repo NO se versiona styles.json: STYLES == built-in (reproducible).
    assert not (Path(__file__).parent.parent / "styles.json").exists()
    assert styles.STYLES["hormozi"].font_size == styles._BUILTIN["hormozi"].font_size
