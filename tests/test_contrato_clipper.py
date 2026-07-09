"""Tests de CONTRATO del clipper (Fase 4 — sesion de diseño).

Fijan el contrato de validacion de respuestas LLM (valida, malformada, vacia)
y el scoring determinista de duracion/total. Los stubs de orquestacion aun no
implementan; estos tests DEBEN pasar desde la sesion de diseño.
Diseño: revision/fase-4/DISENO_CLIPPER.md
"""

from pathlib import Path

import pytest

import clipper
import clipper_brain as cb

# ── validar_segmentacion ─────────────────────────────────────────────────────

RESP_SEG_OK = {
    "segments": [
        {"f_ini": 0, "f_fin": 4, "tipo": "corto", "tema": "gancho de apertura"},
        {"f_ini": 2, "f_fin": 15, "tipo": "largo", "tema": "explicacion completa"},
    ]
}


def test_segmentacion_valida():
    out = cb.validar_segmentacion(RESP_SEG_OK, n_frases=20)
    assert len(out) == 2
    assert out[0] == {"f_ini": 0, "f_fin": 4, "tipo": "corto", "tema": "gancho de apertura"}


def test_segmentacion_respuesta_vacia():
    assert cb.validar_segmentacion({}, 20) == []
    assert cb.validar_segmentacion({"segments": []}, 20) == []


def test_segmentacion_estructura_invalida_no_lanza():
    assert cb.validar_segmentacion(None, 20) == []
    assert cb.validar_segmentacion("no json", 20) == []
    assert cb.validar_segmentacion({"segments": "nope"}, 20) == []
    assert cb.validar_segmentacion({"otro": []}, 20) == []


def test_segmentacion_items_malformados_se_descartan():
    raw = {
        "segments": [
            {"f_ini": "0", "f_fin": 4, "tipo": "corto"},  # indice como string
            {"f_ini": 5, "f_fin": 3, "tipo": "corto"},  # rango invertido
            {"f_ini": 0, "f_fin": 99, "tipo": "largo"},  # fuera de rango
            {"f_ini": -1, "f_fin": 2, "tipo": "corto"},  # negativo
            {"f_ini": 1, "f_fin": 2, "tipo": "mediano"},  # tipo invalido
            {"f_ini": True, "f_fin": 2, "tipo": "corto"},  # bool no es indice
            {"f_fin": 2, "tipo": "corto"},  # falta f_ini
            "no soy un dict",
            {"f_ini": 1, "f_fin": 2, "tipo": "corto", "tema": None},  # solo tema roto: pasa
        ]
    }
    out = cb.validar_segmentacion(raw, n_frases=20)
    assert len(out) == 1
    assert out[0]["f_ini"] == 1 and out[0]["f_fin"] == 2
    assert out[0]["tema"] == "(sin tema)"  # cosmetico roto = default, no descarte


def test_segmentacion_indices_float_enteros_se_aceptan():
    raw = {
        "segments": [
            {"f_ini": 3.0, "f_fin": 7.0, "tipo": "corto", "tema": "x"},  # JSON "3.0"
            {"f_ini": 3.5, "f_fin": 7, "tipo": "corto", "tema": "x"},  # fraccion: fuera
        ]
    }
    out = cb.validar_segmentacion(raw, n_frases=20)
    assert len(out) == 1
    assert out[0]["f_ini"] == 3 and isinstance(out[0]["f_ini"], int)


# ── validar_scoring ──────────────────────────────────────────────────────────

RESP_SCORE_OK = {
    "clips": [
        {
            "c": 0,
            "hook": 82,
            "autocontenido": 71,
            "densidad": 65,
            "cierre": 88,
            "titulo": "El error que arruina tus prompts",
            "razon": "Pregunta directa y cierre con dato.",
        },
        {
            "c": 1,
            "hook": 40,
            "autocontenido": 90,
            "densidad": 55,
            "cierre": 30,
            "titulo": "Nodos explicados en un minuto",
            "razon": "Autocontenido pero arranque plano.",
        },
    ]
}


def test_scoring_valido():
    out = cb.validar_scoring(RESP_SCORE_OK, n_candidatos=2)
    assert len(out) == 2
    assert out[0]["hook"] == 82
    assert out[1]["titulo"] == "Nodos explicados en un minuto"


def test_scoring_respuesta_vacia():
    assert cb.validar_scoring({}, 5) == []
    assert cb.validar_scoring({"clips": []}, 5) == []
    assert cb.validar_scoring(None, 5) == []


def test_scoring_items_malformados_se_descartan():
    raw = {
        "clips": [
            {"c": 0, "hook": 101, "autocontenido": 50, "densidad": 50, "cierre": 50},  # >100
            {"c": 1, "hook": -5, "autocontenido": 50, "densidad": 50, "cierre": 50},  # <0
            {"c": 2, "hook": "alto", "autocontenido": 50, "densidad": 50, "cierre": 50},  # str
            {"c": 3, "autocontenido": 50, "densidad": 50, "cierre": 50},  # falta hook
            {"c": 99, "hook": 50, "autocontenido": 50, "densidad": 50, "cierre": 50},  # c fuera
            # json.loads acepta NaN/Infinity: no deben lanzar
            {"c": 5, "hook": float("nan"), "autocontenido": 50, "densidad": 50, "cierre": 50},
            {"c": 6, "hook": float("inf"), "autocontenido": 50, "densidad": 50, "cierre": 50},
            {"c": 4, "hook": 60, "autocontenido": 60, "densidad": 60, "cierre": 60},  # valido
        ]
    }
    out = cb.validar_scoring(raw, n_candidatos=10)
    assert len(out) == 1
    assert out[0]["c"] == 4
    assert out[0]["titulo"] == "Clip sin titulo"  # cosmetico ausente = default
    assert out[0]["razon"] == "(sin razon)"


def test_scoring_subscore_float_se_redondea():
    raw = {
        "clips": [
            {"c": 0, "hook": 85.0, "autocontenido": 70.4, "densidad": 50, "cierre": 50},
        ]
    }
    out = cb.validar_scoring(raw, n_candidatos=1)
    assert len(out) == 1
    assert out[0]["hook"] == 85
    assert out[0]["autocontenido"] == 70


def test_scoring_c_duplicado_gana_el_primero():
    raw = {
        "clips": [
            {"c": 0, "hook": 90, "autocontenido": 90, "densidad": 90, "cierre": 90, "titulo": "A"},
            {"c": 0, "hook": 10, "autocontenido": 10, "densidad": 10, "cierre": 10, "titulo": "B"},
        ]
    }
    out = cb.validar_scoring(raw, n_candidatos=1)
    assert len(out) == 1
    assert out[0]["hook"] == 90


# ── Scoring determinista (duracion + total ponderado) ────────────────────────


def test_score_duracion_contrato():
    assert clipper.score_duracion(30.0, "corto") == 100  # objetivo exacto
    assert clipper.score_duracion(20.0, "corto") == 50  # borde inferior
    assert clipper.score_duracion(40.0, "corto") == 50  # borde superior
    assert clipper.score_duracion(19.9, "corto") == 0  # fuera de rango
    assert clipper.score_duracion(41.0, "corto") == 0
    assert clipper.score_duracion(75.0, "largo") == 100
    assert clipper.score_duracion(55.0, "largo") == 50
    assert clipper.score_duracion(100.0, "largo") == 50
    assert clipper.score_duracion(101.0, "largo") == 0


def test_score_total_pesos_del_arquitecto():
    """Hook 30% / Autocontenido 25% / Densidad 20% / Cierre 15% / Duracion 10%."""
    subs_max = {"hook": 100, "autocontenido": 100, "densidad": 100, "cierre": 100}
    assert clipper.calcular_score_total(subs_max, 30.0, "corto") == 100

    subs_cero = {k: 0 for k in subs_max}
    assert clipper.calcular_score_total(subs_cero, 30.0, "corto") == 10  # solo duracion

    solo_hook = {"hook": 100, "autocontenido": 0, "densidad": 0, "cierre": 0}
    assert clipper.calcular_score_total(solo_hook, 30.0, "corto") == 40  # 30 + 10

    assert sum(clipper.PESOS.values()) == pytest.approx(1.0)


def test_el_llm_nunca_calcula_el_total():
    """Un 'score' o 'total' inyectado por el LLM en su JSON se ignora por completo."""
    raw = {
        "clips": [
            {
                "c": 0,
                "hook": 50,
                "autocontenido": 50,
                "densidad": 50,
                "cierre": 50,
                "score": 100,
                "total": 100,
            },
        ]
    }
    out = cb.validar_scoring(raw, n_candidatos=1)
    assert "score" not in out[0] and "total" not in out[0]
    assert clipper.calcular_score_total(out[0], 30.0, "corto") == 55  # 50*0.9 + 100*0.1


# ── Comportamiento real con inputs vacios (sesion de implementacion) ──────────


def test_generar_clips_sin_key_retorna_error():
    """Sin DEEPSEEK_API_KEY y provider != mock, retorna error accionable (no crashea)."""
    import os

    orig = os.environ.pop("DEEPSEEK_API_KEY", None)
    orig_prov = os.environ.pop("LLM_PROVIDER", None)
    try:
        one_word = [{"w": "hola", "s": 0.0, "e": 0.5, "prob": 1.0}]
        result = clipper.generar_clips(Path("x.mp4"), one_word)
        assert result["clips"] == []
        assert result["error"] is not None
        assert "DEEPSEEK_API_KEY" in result["error"]
    finally:
        if orig is not None:
            os.environ["DEEPSEEK_API_KEY"] = orig
        if orig_prov is not None:
            os.environ["LLM_PROVIDER"] = orig_prov


def test_build_frases_vacio():
    assert clipper.build_frases([]) == []


def test_build_frases_minimo():
    words = [{"w": "Hola.", "s": 0.0, "e": 0.5, "prob": 1.0}]
    frases = clipper.build_frases(words)
    assert len(frases) == 1
    assert frases[0]["wi"] == 0 and frases[0]["wf"] == 0
    assert frases[0]["text"] == "Hola."


def test_build_frases_corta_por_puntuacion():
    words = [
        {"w": "Hola.", "s": 0.0, "e": 0.5, "prob": 1.0},
        {"w": "mundo", "s": 0.55, "e": 1.0, "prob": 1.0},
    ]
    frases = clipper.build_frases(words)
    # "Hola." termina en punto -> frase 1; "mundo" -> frase 2
    assert len(frases) == 2


def test_build_frases_corta_por_pausa():
    words = [
        {"w": "hola", "s": 0.0, "e": 0.3, "prob": 1.0},
        {"w": "mundo", "s": 1.1, "e": 1.5, "prob": 1.0},  # pausa 0.8s > FRASE_PAUSA_S
    ]
    frases = clipper.build_frases(words)
    assert len(frases) == 2


def test_dedup_segmentos_quita_duplicados():
    segs = [
        {"f_ini": 0, "f_fin": 5, "tipo": "corto", "tema": "a", "wi": 0, "wf": 50},
        {"f_ini": 1, "f_fin": 6, "tipo": "corto", "tema": "b", "wi": 5, "wf": 55},  # IoU alto
        {"f_ini": 10, "f_fin": 20, "tipo": "largo", "tema": "c", "wi": 100, "wf": 200},
    ]
    out = clipper.dedup_segmentos(segs)
    # El primero y el tercero pasan; el segundo tiene IoU alto con el primero
    assert len(out) == 2
    assert out[0]["wi"] == 0
    assert out[1]["wi"] == 100


def test_segmentar_transcript_vacio():
    segs, tels = cb.segmentar_transcript([], "ctx")
    assert segs == []
    assert tels == []


def test_puntuar_candidatos_vacio():
    scores, tels = cb.puntuar_candidatos([])
    assert scores == []
    assert tels == []
