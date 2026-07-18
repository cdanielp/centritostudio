"""test_broll_planner.py — Contrato completo del planner de b-roll (S37-A, DECISIONES D34).

PURO: sin red, sin GPU, sin FFmpeg, sin Pexels, sin keys, sin archivos reales del usuario.
Todas las fixtures son sinteticas e inventadas. Cubre config, inputs, query, movimiento,
hook, outro, duraciones, solapes, densidad, determinismo, pureza y el sidecar JSON v1.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from broll_plan_io import broll_plan_to_dict, load_broll_inputs, write_broll_plan
from broll_plan_query import build_query, detect_motion, fold, tokenize
from broll_plan_types import (
    PLAN_VERSION,
    BrollConfig,
    BrollConfigError,
    BrollInputError,
    BrollPlan,
    round_time,
)
from broll_planner import plan_broll

# --------------------------------------------------------------------------- #
# Helpers sinteticos (nada real del usuario)                                  #
# --------------------------------------------------------------------------- #


def make_group(gid: int, text: str, start: float = 0.0, end: float = 10.0) -> dict:
    words = [{"text": w, "start": 0.0, "end": 0.0, "line_idx": 0} for w in text.split()]
    return {"id": gid, "start": start, "end": end, "text": text, "words": words}


def item(g: int, kw, kw_ts, **extra) -> dict:
    d = {"g": g, "kw": kw, "kw_ts": kw_ts}
    d.update(extra)
    return d


def base_groups() -> list[dict]:
    return [
        make_group(0, "Bienvenidos al taller de cafe artesanal", 0.0, 3.0),
        make_group(1, "Primero tostamos los granos verdes selectos", 3.0, 8.0),
        make_group(2, "Ahora servimos la taza perfecta caliente", 8.0, 13.0),
        make_group(3, "El aroma inunda toda la cocina pequena", 13.0, 18.0),
        make_group(4, "Disfruta tu bebida favorita cada dia", 18.0, 24.0),
    ]


def base_brain() -> dict:
    return {
        "groups": [
            item(0, 2, 1.0),  # dentro del hook
            item(1, 1, 4.0),
            item(2, 1, 9.0),
            item(3, 1, 14.0),
            item(4, 1, 19.0),
        ]
    }


def only(brain_items: list[dict]) -> dict:
    return {"groups": brain_items}


def codes(plan: BrollPlan) -> list[str]:
    return [r.code for r in plan.rejected]


# --------------------------------------------------------------------------- #
# CONFIG                                                                       #
# --------------------------------------------------------------------------- #


def test_config_default_valida():
    c = BrollConfig()
    assert c.enabled is True
    assert c.target_coverage_pct == 0.27
    assert c.max_coverage_pct == 0.35
    assert c.fx_preset == "express"


def test_config_target_27_max_35():
    c = BrollConfig()
    assert c.target_coverage_pct == 0.27 and c.max_coverage_pct == 0.35


def test_config_target_mayor_que_max_rechazado():
    with pytest.raises(BrollConfigError):
        BrollConfig(target_coverage_pct=0.5, max_coverage_pct=0.3)


def test_config_max_mayor_a_uno_rechazado():
    with pytest.raises(BrollConfigError):
        BrollConfig(max_coverage_pct=1.5)


def test_config_max_negativo_rechazado():
    with pytest.raises(BrollConfigError):
        BrollConfig(max_coverage_pct=-0.1)


def test_config_target_negativo_rechazado():
    with pytest.raises(BrollConfigError):
        BrollConfig(target_coverage_pct=-0.1)


def test_config_bool_como_porcentaje_rechazado():
    with pytest.raises(BrollConfigError):
        BrollConfig(target_coverage_pct=True)


def test_config_min_mayor_que_preferred_rechazado():
    with pytest.raises(BrollConfigError):
        BrollConfig(image_min_s=4.0, image_preferred_s=3.5)


def test_config_preferred_mayor_que_max_rechazado():
    with pytest.raises(BrollConfigError):
        BrollConfig(video_preferred_s=7.0, video_max_s=6.0)


def test_config_min_cero_rechazado():
    with pytest.raises(BrollConfigError):
        BrollConfig(image_min_s=0.0)


def test_config_duracion_no_finita_rechazada():
    with pytest.raises(BrollConfigError):
        BrollConfig(image_max_s=float("inf"))


def test_config_max_video_windows_cero_ok():
    assert BrollConfig(max_video_windows=0).max_video_windows == 0


def test_config_max_video_windows_uno_ok():
    assert BrollConfig(max_video_windows=1).max_video_windows == 1


def test_config_max_video_windows_dos_rechazado():
    with pytest.raises(BrollConfigError):
        BrollConfig(max_video_windows=2)


def test_config_max_video_windows_bool_rechazado():
    with pytest.raises(BrollConfigError):
        BrollConfig(max_video_windows=True)


@pytest.mark.parametrize("preset", ["express", "pro", "premium"])
def test_config_presets_validos(preset):
    assert BrollConfig(fx_preset=preset).fx_preset == preset


def test_config_preset_desconocido_rechazado():
    with pytest.raises(BrollConfigError):
        BrollConfig(fx_preset="cinematic")


def test_config_max_query_terms_invalido_rechazado():
    with pytest.raises(BrollConfigError):
        BrollConfig(max_query_terms=0)


def test_config_max_query_terms_bool_rechazado():
    with pytest.raises(BrollConfigError):
        BrollConfig(max_query_terms=True)


def test_config_hook_negativo_rechazado():
    with pytest.raises(BrollConfigError):
        BrollConfig(hook_protected_s=-1.0)


def test_config_lead_in_negativo_rechazado():
    with pytest.raises(BrollConfigError):
        BrollConfig(lead_in_s=-0.1)


# --------------------------------------------------------------------------- #
# CLIP DURATION                                                                #
# --------------------------------------------------------------------------- #


def test_clip_duration_bool_rechazada():
    with pytest.raises(BrollInputError):
        plan_broll(base_groups(), base_brain(), True)


def test_clip_duration_cero_rechazada():
    with pytest.raises(BrollInputError):
        plan_broll(base_groups(), base_brain(), 0.0)


def test_clip_duration_negativa_rechazada():
    with pytest.raises(BrollInputError):
        plan_broll(base_groups(), base_brain(), -5.0)


def test_clip_duration_nan_rechazada():
    with pytest.raises(BrollInputError):
        plan_broll(base_groups(), base_brain(), float("nan"))


def test_clip_duration_inf_rechazada():
    with pytest.raises(BrollInputError):
        plan_broll(base_groups(), base_brain(), float("inf"))


def test_clip_duration_string_rechazada():
    with pytest.raises(BrollInputError):
        plan_broll(base_groups(), base_brain(), "30")


# --------------------------------------------------------------------------- #
# INPUTS                                                                       #
# --------------------------------------------------------------------------- #


def test_groups_no_lista_rechazado():
    with pytest.raises(BrollInputError):
        plan_broll({"no": "lista"}, base_brain(), 24.0)


def test_brain_no_dict_rechazado():
    with pytest.raises(BrollInputError):
        plan_broll(base_groups(), ["no", "dict"], 24.0)


def test_brain_sin_groups_plan_vacio_con_warning():
    plan = plan_broll(base_groups(), {"provider": "x"}, 24.0)
    assert plan.windows == ()
    assert "brain_missing_groups" in plan.warnings


def test_brain_groups_vacio_plan_vacio_valido():
    plan = plan_broll(base_groups(), {"groups": []}, 24.0)
    assert plan.windows == ()
    assert plan.signals_total == 0


def test_item_brain_no_dict_rechazado_sin_romper():
    brain = only([item(1, 1, 4.0), "no soy objeto", item(2, 1, 9.0)])
    plan = plan_broll(base_groups(), brain, 24.0)
    assert "brain_item_not_object" in codes(plan)
    assert plan.candidates_valid == 2


def test_group_inexistente_rechazado():
    plan = plan_broll(base_groups(), only([item(99, 1, 4.0)]), 24.0)
    assert "group_not_found" in codes(plan)


def test_group_id_no_igual_a_posicion():
    groups = [make_group(50, "hola mundo entero grande", 0.0, 10.0)]
    plan = plan_broll(groups, only([item(50, 1, 5.0)]), 12.0)
    assert plan.candidates_valid == 1
    assert plan.windows[0].signal.group_id == 50
    assert plan.windows[0].signal.group_position == 0


def test_words_ausente_rechazado():
    groups = [{"id": 0, "start": 0.0, "end": 10.0, "text": "hola"}]
    plan = plan_broll(groups, only([item(0, 0, 5.0)]), 12.0)
    assert "group_words_invalid" in codes(plan)


def test_words_no_lista_rechazado():
    groups = [{"id": 0, "text": "hola", "words": "no-lista"}]
    plan = plan_broll(groups, only([item(0, 0, 5.0)]), 12.0)
    assert "group_words_invalid" in codes(plan)


def test_kw_none_no_es_candidato():
    plan = plan_broll(base_groups(), only([item(1, None, 4.0)]), 24.0)
    assert "keyword_not_selected" in codes(plan)
    assert plan.candidates_valid == 0


def test_kw_negativo_rechazado():
    plan = plan_broll(base_groups(), only([item(1, -1, 4.0)]), 24.0)
    assert "keyword_index_invalid" in codes(plan)


def test_kw_fuera_de_rango_rechazado():
    plan = plan_broll(base_groups(), only([item(1, 999, 4.0)]), 24.0)
    assert "keyword_index_invalid" in codes(plan)


def test_kw_bool_rechazado():
    plan = plan_broll(base_groups(), only([item(1, True, 4.0)]), 24.0)
    assert "keyword_index_invalid" in codes(plan)


def test_word_no_dict_rechazado():
    groups = [{"id": 0, "text": "", "words": ["no-dict"]}]
    plan = plan_broll(groups, only([item(0, 0, 5.0)]), 12.0)
    assert "keyword_empty" in codes(plan)


def test_keyword_vacia_rechazada():
    groups = [make_group(0, "hola , mundo", 0.0, 10.0)]
    # el token "," queda vacio tras limpieza estructural
    plan = plan_broll(groups, only([item(0, 1, 5.0)]), 12.0)
    assert "keyword_empty" in codes(plan)


def test_kw_ts_ausente_rechazado():
    plan = plan_broll(base_groups(), only([{"g": 1, "kw": 1}]), 24.0)
    assert "kw_ts_missing" in codes(plan)


def test_kw_ts_string_rechazado():
    plan = plan_broll(base_groups(), only([item(1, 1, "cuatro")]), 24.0)
    assert "kw_ts_invalid" in codes(plan)


def test_kw_ts_bool_rechazado():
    plan = plan_broll(base_groups(), only([item(1, 1, True)]), 24.0)
    assert "kw_ts_invalid" in codes(plan)


def test_kw_ts_negativo_rechazado():
    plan = plan_broll(base_groups(), only([item(1, 1, -1.0)]), 24.0)
    assert "kw_ts_out_of_range" in codes(plan)


def test_kw_ts_igual_a_duration_rechazado():
    plan = plan_broll(base_groups(), only([item(1, 1, 24.0)]), 24.0)
    assert "kw_ts_out_of_range" in codes(plan)


def test_kw_ts_mayor_a_duration_rechazado():
    plan = plan_broll(base_groups(), only([item(1, 1, 30.0)]), 24.0)
    assert "kw_ts_out_of_range" in codes(plan)


def test_item_invalido_no_bloquea_valido_posterior():
    brain = only([item(99, 1, 4.0), item(2, 1, 9.0)])
    plan = plan_broll(base_groups(), brain, 24.0)
    assert plan.candidates_valid == 1
    assert len(plan.windows) == 1


# --------------------------------------------------------------------------- #
# QUERY                                                                        #
# --------------------------------------------------------------------------- #


def test_query_keyword_primero():
    q, chosen, _ = build_query("conectamos", "Ahora conectamos el modelo al workflow", 4)
    assert chosen[0] == "conectamos"


def test_query_elimina_stopwords():
    q, chosen, dropped = build_query("modelo", "el modelo de la empresa", 4)
    assert "el" not in chosen and "de" not in chosen and "la" not in chosen
    assert "el" in dropped


def test_query_elimina_puntuacion_aislada():
    q, chosen, _ = build_query("modelo", "modelo , workflow", 4)
    assert "," not in q


def test_query_conserva_acentos():
    q, chosen, _ = build_query("máquina", "la máquina rápida potente", 4)
    assert "máquina" in q


def test_query_conserva_enie():
    q, chosen, _ = build_query("niño", "el niño pequeño feliz", 4)
    assert "niño" in q


def test_query_no_duplica_tokens():
    q, chosen, _ = build_query("dato", "dato dato dato importante", 4)
    assert chosen.count("dato") == 1


def test_query_respeta_max_terms():
    q, chosen, _ = build_query("uno", "uno arbol casa perro gato pez", 3)
    assert len(chosen) == 3


def test_query_orden_determinista():
    a = build_query("uno", "uno dos tres cuatro", 4)
    b = build_query("uno", "uno dos tres cuatro", 4)
    assert a == b


def test_query_keyword_con_puntuacion_periferica():
    q, chosen, _ = build_query("modelo,", "modelo, entrenado hoy", 4)
    assert chosen[0] == "modelo"


def test_query_multiples_espacios():
    q, chosen, _ = build_query("cafe", "cafe    negro    fuerte", 4)
    assert chosen == ("cafe", "negro", "fuerte")


def test_query_no_toma_palabras_de_otro_grupo():
    groups = [
        make_group(0, "primero granos verdes", 0.0, 5.0),
        make_group(1, "segundo azucar blanca", 5.0, 10.0),
    ]
    plan = plan_broll(groups, only([item(1, 1, 6.0)]), 12.0)
    assert "granos" not in plan.windows[0].query
    assert "azucar" in plan.windows[0].query


def test_query_registra_query_terms():
    plan = plan_broll(base_groups(), only([item(1, 1, 4.0)]), 24.0)
    assert plan.windows[0].query_terms
    assert plan.windows[0].query_terms[0] == "tostamos"


def test_query_no_traduce_al_ingles():
    q, chosen, _ = build_query("cocina", "la cocina moderna elegante", 4)
    assert "kitchen" not in q and "cocina" in q


# --------------------------------------------------------------------------- #
# MOVIMIENTO                                                                    #
# --------------------------------------------------------------------------- #


def test_motion_sustantivo_estatico_image():
    assert detect_motion("montana", "una montana hermosa lejana") == ()


def test_motion_verbo_movimiento_video():
    assert "caminar" in detect_motion("caminar", "vamos a caminar")


def test_motion_proceso_explicito_video():
    assert "proceso" in detect_motion("intro", "el proceso completo hoy")


def test_motion_transformacion_video():
    assert "transformacion" in detect_motion("cambio", "una transformacion total")


def test_motion_case_insensitive():
    assert "correr" in detect_motion("CORRER", "vamos a CORRER")


def test_motion_con_acentos():
    # "conexión" pliega a "conexion" (en la lista de movimiento)
    assert "conexion" in detect_motion("conexión", "una conexión estable")


def test_motion_palabra_parecida_no_es_movimiento():
    # "correo" NO debe activar video aunque comparta prefijo con "correr"
    assert detect_motion("correo", "el correo llego temprano") == ()


def test_motion_frase_paso_a_paso():
    assert "paso a paso" in detect_motion("guia", "te enseno paso a paso")


def test_motion_dos_candidatos_solo_un_video():
    groups = [
        make_group(0, "intro estatica normal tranquila", 0.0, 5.0),
        make_group(1, "caminamos por el sendero largo", 5.0, 11.0),
        make_group(2, "corremos hacia la meta final", 11.0, 17.0),
    ]
    brain = only([item(1, 0, 6.0), item(2, 0, 12.0)])
    cfg = BrollConfig(target_coverage_pct=0.9, max_coverage_pct=0.95)
    plan = plan_broll(groups, brain, 20.0, cfg)
    videos = [w for w in plan.windows if w.media_type == "video"]
    assert len(videos) == 1


def test_motion_segundo_video_se_degrada_a_image():
    groups = [
        make_group(0, "caminamos por el sendero largo", 0.0, 8.0),
        make_group(1, "corremos hacia la meta final", 8.0, 16.0),
    ]
    # anclas separadas para que ambas quepan sin solaparse (4.0 -> video 3.75-8.25; 12.0 -> imagen)
    brain = only([item(0, 0, 4.0), item(1, 0, 12.0)])
    cfg = BrollConfig(target_coverage_pct=0.9, max_coverage_pct=0.95)
    plan = plan_broll(groups, brain, 20.0, cfg)
    assert "video_limit_fallback_to_image" in codes(plan)
    assert sum(1 for w in plan.windows if w.media_type == "video") == 1
    assert sum(1 for w in plan.windows if w.media_type == "image") == 1


def test_motion_max_video_cero_todos_image():
    groups = [make_group(0, "caminamos corremos saltamos rapido", 0.0, 8.0)]
    cfg = BrollConfig(max_video_windows=0, target_coverage_pct=0.9, max_coverage_pct=0.95)
    plan = plan_broll(groups, only([item(0, 0, 5.0)]), 12.0, cfg)
    assert all(w.media_type == "image" for w in plan.windows)


def test_motion_razon_contiene_termino_activador():
    groups = [make_group(0, "intro con proceso completo hoy", 0.0, 8.0)]
    cfg = BrollConfig(target_coverage_pct=0.9, max_coverage_pct=0.95)
    plan = plan_broll(groups, only([item(0, 0, 5.0)]), 12.0, cfg)
    w = plan.windows[0]
    assert w.media_type == "video"
    assert "proceso" in w.signal.motion_terms


# --------------------------------------------------------------------------- #
# HOOK                                                                          #
# --------------------------------------------------------------------------- #


def test_hook_zona_declarada():
    plan = plan_broll(base_groups(), base_brain(), 24.0)
    hooks = [z for z in plan.protected_zones if z.kind == "hook"]
    assert len(hooks) == 1
    assert hooks[0].start_s == 0.0 and hooks[0].end_s == 3.0


def test_hook_kw_dentro_de_3s_rechazada():
    plan = plan_broll(base_groups(), only([item(0, 2, 1.5)]), 24.0)
    assert "protected_hook" in codes(plan)
    assert plan.windows == ()


def test_hook_kw_exactamente_en_3s_no_rechazada():
    groups = [make_group(1, "tostamos los granos verdes selectos", 3.0, 9.0)]
    plan = plan_broll(groups, only([item(1, 0, 3.0)]), 24.0)
    assert "protected_hook" not in codes(plan)


def test_hook_lead_in_no_entra_al_hook():
    groups = [make_group(1, "tostamos los granos verdes selectos", 3.0, 9.0)]
    plan = plan_broll(groups, only([item(1, 0, 3.0)]), 24.0)
    assert plan.windows[0].start_s >= 3.0


def test_hook_clip_menor_a_3s():
    groups = [make_group(0, "hola mundo bonito grande", 0.0, 2.0)]
    plan = plan_broll(groups, only([item(0, 0, 1.0)]), 2.5)
    hooks = [z for z in plan.protected_zones if z.kind == "hook"]
    assert hooks[0].end_s == 2.5  # hook se clampa al clip


def test_hook_ocupa_todo_clip_no_usable_timeline():
    groups = [make_group(0, "hola mundo bonito grande", 0.0, 2.0)]
    plan = plan_broll(groups, only([item(0, 0, 1.0)]), 3.0)
    assert "no_usable_timeline" in plan.warnings
    assert plan.windows == ()


# --------------------------------------------------------------------------- #
# OUTRO                                                                         #
# --------------------------------------------------------------------------- #


def test_outro_express_no_reserva():
    plan = plan_broll(base_groups(), base_brain(), 24.0, BrollConfig(fx_preset="express"))
    assert all(z.kind != "outro" for z in plan.protected_zones)


def test_outro_pro_no_reserva():
    plan = plan_broll(base_groups(), base_brain(), 24.0, BrollConfig(fx_preset="pro"))
    assert all(z.kind != "outro" for z in plan.protected_zones)


def test_outro_premium_reserva_2_5s():
    plan = plan_broll(base_groups(), base_brain(), 24.0, BrollConfig(fx_preset="premium"))
    outro = [z for z in plan.protected_zones if z.kind == "outro"]
    assert len(outro) == 1
    assert outro[0].start_s == 21.5 and outro[0].end_s == 24.0


def test_outro_senal_dentro_del_outro_rechazada():
    cfg = BrollConfig(fx_preset="premium", target_coverage_pct=0.9, max_coverage_pct=0.95)
    plan = plan_broll(base_groups(), only([item(4, 1, 22.5)]), 24.0, cfg)
    assert "protected_outro" in codes(plan)


def test_outro_ventana_no_atraviesa_outro():
    cfg = BrollConfig(fx_preset="premium", target_coverage_pct=0.9, max_coverage_pct=0.95)
    groups = [make_group(0, "servimos la taza perfecta caliente rica", 8.0, 21.0)]
    plan = plan_broll(groups, only([item(0, 0, 20.0)]), 24.0, cfg)
    for w in plan.windows:
        assert w.end_s <= 21.5


def test_outro_premium_clip_menor_a_outro():
    cfg = BrollConfig(fx_preset="premium")
    groups = [make_group(0, "hola mundo bonito grande", 0.0, 2.0)]
    plan = plan_broll(groups, only([item(0, 0, 1.0)]), 2.0, cfg)
    # clip 2s < hook 3s: sin timeline util, no explota
    assert isinstance(plan, BrollPlan)


# --------------------------------------------------------------------------- #
# DURACIONES                                                                    #
# --------------------------------------------------------------------------- #


def test_duracion_image_preferred_3_5():
    groups = [make_group(0, "servimos taza perfecta caliente rica sabrosa", 5.0, 15.0)]
    plan = plan_broll(groups, only([item(0, 0, 8.0)]), 30.0)
    assert plan.windows[0].media_type == "image"
    assert plan.windows[0].duration_s == 3.5


def test_duracion_video_preferred_4_5():
    groups = [make_group(0, "el proceso completo funciona bien hoy", 5.0, 15.0)]
    cfg = BrollConfig(target_coverage_pct=0.9, max_coverage_pct=0.95)
    plan = plan_broll(groups, only([item(0, 1, 8.0)]), 30.0, cfg)
    assert plan.windows[0].media_type == "video"
    assert plan.windows[0].duration_s == 4.5


def test_duracion_image_nunca_supera_max():
    groups = base_groups()
    plan = plan_broll(
        groups, base_brain(), 60.0, BrollConfig(max_coverage_pct=0.9, target_coverage_pct=0.9)
    )
    for w in plan.windows:
        if w.media_type == "image":
            assert 2.5 <= w.duration_s <= 4.5


def test_duracion_video_en_rango():
    groups = [make_group(0, "el proceso completo funciona bien hoy", 5.0, 15.0)]
    cfg = BrollConfig(target_coverage_pct=0.9, max_coverage_pct=0.95)
    plan = plan_broll(groups, only([item(0, 1, 8.0)]), 30.0, cfg)
    for w in plan.windows:
        if w.media_type == "video":
            assert 3.0 <= w.duration_s <= 6.0


def test_duracion_se_reduce_pero_no_bajo_min():
    # hueco util de solo 3.0s (hook 3 -> clip 6) obliga a reducir la imagen a <=3.0 pero >=2.5
    groups = [make_group(0, "servimos taza perfecta caliente rica sabrosa", 3.0, 6.0)]
    cfg = BrollConfig(max_coverage_pct=0.95, target_coverage_pct=0.9)
    plan = plan_broll(groups, only([item(0, 0, 4.0)]), 6.0, cfg)
    for w in plan.windows:
        assert w.duration_s >= 2.5


def test_duracion_ventana_no_excede_clip():
    plan = plan_broll(base_groups(), base_brain(), 24.0)
    for w in plan.windows:
        assert w.end_s <= 24.0


def test_duracion_redondeada_3_decimales():
    plan = plan_broll(base_groups(), base_brain(), 24.0)
    for w in plan.windows:
        assert w.start_s == round(w.start_s, 3)
        assert w.end_s == round(w.end_s, 3)
        assert w.duration_s == round(w.duration_s, 3)


def test_duracion_start_end_duration_consistentes():
    plan = plan_broll(base_groups(), base_brain(), 24.0)
    for w in plan.windows:
        assert abs((w.start_s + w.duration_s) - w.end_s) < 1e-6


# --------------------------------------------------------------------------- #
# TRASLAPES                                                                     #
# --------------------------------------------------------------------------- #


def test_solape_dos_senales_separadas_aceptadas():
    groups = [
        make_group(0, "primero granos verdes selectos frescos", 3.0, 8.0),
        make_group(1, "luego azucar blanca refinada pura", 12.0, 18.0),
    ]
    brain = only([item(0, 0, 5.0), item(1, 0, 14.0)])
    cfg = BrollConfig(target_coverage_pct=0.9, max_coverage_pct=0.95)
    plan = plan_broll(groups, brain, 30.0, cfg)
    assert len(plan.windows) == 2


def test_solape_imposible_se_rechaza():
    groups = [make_group(0, "primero granos verdes selectos frescos ricos", 3.0, 12.0)]
    brain = only([item(0, 0, 5.0), item(0, 1, 5.2)])
    cfg = BrollConfig(target_coverage_pct=0.9, max_coverage_pct=0.95)
    plan = plan_broll(groups, brain, 30.0, cfg)
    assert "overlap_unresolvable" in codes(plan)
    assert len(plan.windows) == 1


def test_solape_ventanas_quedan_ordenadas():
    plan = plan_broll(
        base_groups(),
        base_brain(),
        60.0,
        BrollConfig(target_coverage_pct=0.9, max_coverage_pct=0.9),
    )
    starts = [w.start_s for w in plan.windows]
    assert starts == sorted(starts)


def test_solape_borde_end_igual_start_permitido():
    groups = [make_group(0, "servimos taza perfecta caliente rica sabrosa deliciosa", 3.0, 20.0)]
    brain = only([item(0, 0, 4.0), item(0, 3, 7.5)])
    cfg = BrollConfig(target_coverage_pct=0.9, max_coverage_pct=0.95, lead_in_s=0.0)
    plan = plan_broll(groups, brain, 30.0, cfg)
    # primera 4.0-7.5, segunda ancla 7.5 puede tocar el borde sin solapar
    assert len(plan.windows) == 2
    assert plan.windows[0].end_s <= plan.windows[1].start_s + 1e-6


# --------------------------------------------------------------------------- #
# DENSIDAD                                                                      #
# --------------------------------------------------------------------------- #


def test_densidad_cero_senales_cero_cobertura():
    plan = plan_broll(base_groups(), {"groups": []}, 24.0)
    d = broll_plan_to_dict(plan)
    assert d["summary"]["coverage_pct"] == 0.0


def test_densidad_nunca_supera_max():
    plan = plan_broll(base_groups(), base_brain(), 30.0)
    d = broll_plan_to_dict(plan)
    assert d["summary"]["coverage_pct"] <= 0.35 + 1e-9


def test_densidad_candidato_que_superaria_max_se_rechaza():
    # clip corto: la primera imagen (min 2.5) ya excede 0.35*6=2.1
    groups = [make_group(0, "servimos taza perfecta caliente rica", 3.0, 6.0)]
    plan = plan_broll(groups, only([item(0, 0, 4.0)]), 6.0)
    assert "max_coverage_exceeded" in codes(plan)
    assert plan.windows == ()


def test_densidad_target_alcanzado_detiene_greedy():
    plan = plan_broll(base_groups(), base_brain(), 24.0)
    assert "target_coverage_reached" in codes(plan)


def test_densidad_no_inventa_ventanas_para_target():
    # una sola senal: cobertura puede quedar debajo del target sin rellenar
    plan = plan_broll(base_groups(), only([item(1, 1, 4.0)]), 60.0)
    d = broll_plan_to_dict(plan)
    assert len(plan.windows) == 1
    assert d["summary"]["coverage_pct"] < 0.27


def test_densidad_coverage_pct_correcto():
    plan = plan_broll(base_groups(), base_brain(), 24.0)
    d = broll_plan_to_dict(plan)
    esperado = round_time(sum(w.duration_s for w in plan.windows) / 24.0)
    assert d["summary"]["coverage_pct"] == esperado


def test_densidad_target_reached_flag():
    plan = plan_broll(base_groups(), base_brain(), 24.0)
    d = broll_plan_to_dict(plan)
    assert d["summary"]["target_reached"] is True


# --------------------------------------------------------------------------- #
# PLAN DESACTIVADO                                                              #
# --------------------------------------------------------------------------- #


def test_disabled_plan_vacio_con_razon():
    plan = plan_broll(base_groups(), base_brain(), 24.0, BrollConfig(enabled=False))
    assert plan.windows == ()
    assert "disabled_by_config" in plan.warnings


def test_disabled_no_muta_inputs():
    g, b = base_groups(), base_brain()
    g0, b0 = copy.deepcopy(g), copy.deepcopy(b)
    plan_broll(g, b, 24.0, BrollConfig(enabled=False))
    assert g == g0 and b == b0


# --------------------------------------------------------------------------- #
# DETERMINISMO Y PUREZA                                                         #
# --------------------------------------------------------------------------- #


def test_determinismo_misma_entrada_mismo_plan():
    a = broll_plan_to_dict(plan_broll(base_groups(), base_brain(), 24.0))
    b = broll_plan_to_dict(plan_broll(base_groups(), base_brain(), 24.0))
    assert a == b


def test_determinismo_ids_estables():
    plan = plan_broll(
        base_groups(),
        base_brain(),
        60.0,
        BrollConfig(target_coverage_pct=0.9, max_coverage_pct=0.9),
    )
    ids = [w.window_id for w in plan.windows]
    assert ids == [f"broll-{i:04d}" for i in range(1, len(ids) + 1)]


def test_determinismo_rejected_estable():
    a = codes(plan_broll(base_groups(), base_brain(), 24.0))
    b = codes(plan_broll(base_groups(), base_brain(), 24.0))
    assert a == b


def test_pureza_no_muta_groups():
    g = base_groups()
    g0 = copy.deepcopy(g)
    plan_broll(g, base_brain(), 24.0)
    assert g == g0


def test_pureza_no_muta_brain():
    b = base_brain()
    b0 = copy.deepcopy(b)
    plan_broll(base_groups(), b, 24.0)
    assert b == b0


def test_pureza_config_no_mutada():
    c = BrollConfig()
    plan_broll(base_groups(), base_brain(), 24.0, c)
    assert c == BrollConfig()


def test_pureza_serialize_estable():
    plan = plan_broll(base_groups(), base_brain(), 24.0)
    assert broll_plan_to_dict(plan) == broll_plan_to_dict(plan)


def test_pureza_no_toca_filesystem(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    plan_broll(base_groups(), base_brain(), 24.0)
    assert list(tmp_path.iterdir()) == []


def test_pureza_source_sin_imports_prohibidos():
    import re

    prohibidos = [
        r"\bimport\s+requests\b",
        r"\bimport\s+httpx\b",
        r"\bimport\s+openai\b",
        r"\bimport\s+subprocess\b",
        r"\brandom\.",
        r"\btime\.",
    ]
    for mod in ("broll_plan_types", "broll_plan_query", "broll_plan_place", "broll_planner"):
        src = Path(f"{mod}.py").read_text(encoding="utf-8")
        for pat in prohibidos:
            assert not re.search(pat, src), f"{mod}: patron prohibido {pat}"


# --------------------------------------------------------------------------- #
# PROPIEDADES (parametrizadas, sin Hypothesis)                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("clip", [12.0, 18.0, 24.0, 30.0, 45.0, 60.0])
def test_prop_cobertura_en_rango(clip):
    plan = plan_broll(base_groups(), base_brain(), clip)
    d = broll_plan_to_dict(plan)
    assert 0.0 <= d["summary"]["coverage_pct"] <= 0.35 + 1e-9


@pytest.mark.parametrize("clip", [12.0, 18.0, 24.0, 30.0, 45.0, 60.0])
def test_prop_ventanas_dentro_del_clip(clip):
    plan = plan_broll(base_groups(), base_brain(), clip)
    for w in plan.windows:
        assert 0.0 <= w.start_s < w.end_s <= clip + 1e-9


@pytest.mark.parametrize("clip", [24.0, 30.0, 45.0, 60.0])
def test_prop_ventanas_no_se_solapan(clip):
    cfg = BrollConfig(target_coverage_pct=0.35, max_coverage_pct=0.35)
    plan = plan_broll(base_groups(), base_brain(), clip, cfg)
    ws = sorted(plan.windows, key=lambda w: w.start_s)
    for a, b in zip(ws, ws[1:], strict=False):
        assert a.end_s <= b.start_s + 1e-6


@pytest.mark.parametrize("clip", [24.0, 30.0, 45.0, 60.0])
def test_prop_maximo_un_video(clip):
    cfg = BrollConfig(target_coverage_pct=0.35, max_coverage_pct=0.35)
    groups = [
        make_group(0, "caminamos corriendo saltando girando avanzando", 3.0, 9.0),
        make_group(1, "cocinamos mezclando cortando instalando conectando", 9.0, 15.0),
    ]
    brain = only([item(0, 0, 5.0), item(1, 0, 11.0)])
    plan = plan_broll(groups, brain, clip, cfg)
    assert sum(1 for w in plan.windows if w.media_type == "video") <= 1


@pytest.mark.parametrize("clip", [12.0, 24.0, 48.0])
def test_prop_no_intersecta_zonas_protegidas(clip):
    cfg = BrollConfig(fx_preset="premium", target_coverage_pct=0.35, max_coverage_pct=0.35)
    plan = plan_broll(base_groups(), base_brain(), clip, cfg)
    for w in plan.windows:
        for z in plan.protected_zones:
            assert w.end_s <= z.start_s + 1e-6 or w.start_s >= z.end_s - 1e-6


# --------------------------------------------------------------------------- #
# SIDECAR JSON V1                                                               #
# --------------------------------------------------------------------------- #


def test_sidecar_dict_serializable():
    d = broll_plan_to_dict(plan_broll(base_groups(), base_brain(), 24.0))
    assert json.dumps(d, ensure_ascii=False)


def test_sidecar_version_1():
    d = broll_plan_to_dict(plan_broll(base_groups(), base_brain(), 24.0))
    assert d["version"] == 1 == PLAN_VERSION
    assert d["planner"] == "centrito_broll_planner"


def test_sidecar_sin_nan_ni_inf():
    d = broll_plan_to_dict(plan_broll(base_groups(), base_brain(), 24.0))
    txt = json.dumps(d, ensure_ascii=False)
    assert "NaN" not in txt and "Infinity" not in txt


def test_sidecar_config_anidada():
    d = broll_plan_to_dict(plan_broll(base_groups(), base_brain(), 24.0))
    assert d["config"]["image_duration_s"] == {"min": 2.5, "preferred": 3.5, "max": 4.5}
    assert d["config"]["video_duration_s"] == {"min": 3.0, "preferred": 4.5, "max": 6.0}


def test_sidecar_window_trace():
    d = broll_plan_to_dict(plan_broll(base_groups(), base_brain(), 24.0))
    w = d["windows"][0]
    assert set(w) >= {
        "id",
        "start_s",
        "end_s",
        "duration_s",
        "media_type",
        "query",
        "signal",
        "trace",
    }
    assert w["trace"]["source"] == "brain_keyword"


def test_sidecar_protected_zones_correctas():
    d = broll_plan_to_dict(
        plan_broll(base_groups(), base_brain(), 24.0, BrollConfig(fx_preset="premium"))
    )
    kinds = {z["kind"] for z in d["protected_zones"]}
    assert kinds == {"hook", "outro"}


def test_sidecar_summary_counts_correctos():
    d = broll_plan_to_dict(plan_broll(base_groups(), base_brain(), 24.0))
    s = d["summary"]
    assert s["windows_planned"] == s["image_windows"] + s["video_windows"]


def test_sidecar_rejected_serializable():
    d = broll_plan_to_dict(plan_broll(base_groups(), base_brain(), 24.0))
    for r in d["rejected"]:
        assert "code" in r and "reason" in r
    assert json.dumps(d["rejected"], ensure_ascii=False)


def test_sidecar_sin_paths_ni_bytes():
    d = broll_plan_to_dict(plan_broll(base_groups(), base_brain(), 24.0))
    txt = json.dumps(d, ensure_ascii=False)
    assert "\\\\" not in txt and "C:" not in txt


# --------------------------------------------------------------------------- #
# ESCRITURA DEL SIDECAR                                                         #
# --------------------------------------------------------------------------- #


def test_write_crea_json_utf8(tmp_path):
    plan = plan_broll(base_groups(), base_brain(), 24.0)
    dest = tmp_path / "clip_broll_plan.json"
    out = write_broll_plan(plan, dest)
    assert out == dest
    txt = dest.read_text(encoding="utf-8")
    assert txt.endswith("\n")
    assert json.loads(txt)["version"] == 1


def test_write_no_sobreescribe_por_default(tmp_path):
    plan = plan_broll(base_groups(), base_brain(), 24.0)
    dest = tmp_path / "clip_broll_plan.json"
    write_broll_plan(plan, dest)
    with pytest.raises(BrollInputError):
        write_broll_plan(plan, dest)


def test_write_overwrite_explicito(tmp_path):
    plan = plan_broll(base_groups(), base_brain(), 24.0)
    dest = tmp_path / "clip_broll_plan.json"
    write_broll_plan(plan, dest)
    assert write_broll_plan(plan, dest, overwrite=True) == dest


def test_write_destino_no_json_rechazado(tmp_path):
    plan = plan_broll(base_groups(), base_brain(), 24.0)
    with pytest.raises(BrollInputError):
        write_broll_plan(plan, tmp_path / "clip.txt")


def test_write_destino_directorio_rechazado(tmp_path):
    plan = plan_broll(base_groups(), base_brain(), 24.0)
    d = tmp_path / "subdir.json"
    d.mkdir()
    with pytest.raises(BrollInputError):
        write_broll_plan(plan, d)


def test_write_no_deja_temporales(tmp_path):
    plan = plan_broll(base_groups(), base_brain(), 24.0)
    dest = tmp_path / "clip_broll_plan.json"
    write_broll_plan(plan, dest)
    assert [p.name for p in tmp_path.iterdir()] == ["clip_broll_plan.json"]


def test_write_conserva_acentos(tmp_path):
    groups = [make_group(0, "la máquina rápida del niño pequeño", 3.0, 10.0)]
    plan = plan_broll(groups, only([item(0, 1, 5.0)]), 30.0)
    dest = tmp_path / "acentos_broll_plan.json"
    write_broll_plan(plan, dest)
    txt = dest.read_text(encoding="utf-8")
    assert "máquina" in txt


# --------------------------------------------------------------------------- #
# CARGA DE FIXTURES                                                            #
# --------------------------------------------------------------------------- #


def test_load_inputs_roundtrip(tmp_path):
    gp = tmp_path / "g.json"
    bp = tmp_path / "b.json"
    gp.write_text(json.dumps(base_groups()), encoding="utf-8")
    bp.write_text(json.dumps(base_brain()), encoding="utf-8")
    groups, brain = load_broll_inputs(gp, bp)
    assert isinstance(groups, list) and isinstance(brain, dict)
    plan = plan_broll(groups, brain, 24.0)
    assert isinstance(plan, BrollPlan)


def test_load_inputs_groups_no_lista_rechazado(tmp_path):
    gp = tmp_path / "g.json"
    bp = tmp_path / "b.json"
    gp.write_text(json.dumps({"no": "lista"}), encoding="utf-8")
    bp.write_text(json.dumps(base_brain()), encoding="utf-8")
    with pytest.raises(BrollInputError):
        load_broll_inputs(gp, bp)


# --------------------------------------------------------------------------- #
# UTILIDADES DE TEXTO                                                          #
# --------------------------------------------------------------------------- #


def test_fold_pliega_acentos():
    assert fold("Máquiña") == "maquina"


def test_tokenize_limpia_bordes():
    assert tokenize("  hola,  mundo!  ") == ["hola", "mundo"]
