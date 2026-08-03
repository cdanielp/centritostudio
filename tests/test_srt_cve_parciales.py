"""Integracion del gate de cues parciales con la ruta SRT (S39).

Cierra el circuito completo: alineador -> groups con procedencia de timing -> preset CVE con
gate -> auditoria en el sidecar. Lo que se demuestra aqui es el efecto VISIBLE: en un cue
parcial el enfasis se mueve de la palabra con timing inventado a la que se midio de verdad.
"""

from __future__ import annotations

from pathlib import Path

import cve
import srt_align
import srt_caption
import srt_render
from srt_types import SrtCue, SrtDocument

_SIN_BRAIN = Path("no_existe_brain.json")


def _doc(texto: str, end_ms: int = 4000):
    return SrtDocument((SrtCue(1, 0, end_ms, (texto,), 1),), "utf-8", "sha", (), "x.srt")


def _w(tok, s, e):
    return {"w": tok, "s": s, "e": e, "prob": 0.9}


def _groups_parciales():
    """Cue parcial real: 'cuesta' y '5000' anclan; 'pesos' y 'hoy' se interpolan.

    Las reglas del motor puntuan 'pesos' (R2 dinero, 95) por encima de '5000' (R1 numeros,
    90). Sin gate el punch cae sobre 'pesos', cuyo tiempo NO se midio.
    """
    doc = _doc("cuesta 5000 pesos hoy")
    words = [_w("cuesta", 0.0, 0.4), _w("5000", 1.0, 1.5)]
    result = srt_align.align_srt_to_words(doc, words, modo_parcial=True, min_coverage=0.5)
    assert result.cues[0].mode == "word_partial"
    return srt_caption.construir_groups(result)


def _aplicar(groups):
    plan = cve.resolve_preset("keyword_punch")
    return srt_render.apply_preset_to_srt_groups(
        groups, plan, brain_path=_SIN_BRAIN, width=1080, height=1920
    )


def _keywords(g):
    return [w["text"] for w in g["words"] if w.get("is_keyword")]


# ─────────────────────────────────────────────────────────────────────────────
# La procedencia del timing viaja hasta el motor
# ─────────────────────────────────────────────────────────────────────────────


def test_los_groups_declaran_la_procedencia_de_cada_timing():
    kinds = [w["kind"] for w in _groups_parciales()[0]["words"]]
    assert kinds == ["exact_match", "exact_match", "interpolado", "interpolado"]


def test_un_cue_completo_solo_trae_anclas_reales():
    doc = _doc("hola mundo", end_ms=1000)
    result = srt_align.align_srt_to_words(doc, [_w("hola", 0.0, 0.4), _w("mundo", 0.5, 0.9)])
    groups = srt_caption.construir_groups(result)
    assert {w["kind"] for w in groups[0]["words"]} == {"exact_match"}


def test_el_fallback_estatico_no_finge_procedencia():
    """Un cue_fallback no tiene timing por palabra: sus words son lineas, sin `kind`."""
    result = srt_align.align_srt_to_words(_doc("uno dos tres"), [_w("nada", 9.0, 9.5)])
    groups = srt_caption.construir_groups(result)
    assert groups[0]["timing_mode"] == "cue_fallback"
    assert "kind" not in groups[0]["words"][0]


# ─────────────────────────────────────────────────────────────────────────────
# El efecto visible
# ─────────────────────────────────────────────────────────────────────────────


def test_sin_gate_el_enfasis_cae_sobre_timing_inventado():
    """Comportamiento HISTORICO (S38), documentado aqui como el defecto que se corrige."""
    groups = _groups_parciales()
    plan = cve.resolve_preset("keyword_punch")
    marcados = cve.aplicar_engine(groups, plan, 1080, 1920)
    assert _keywords(marcados[0]) == ["pesos"]  # interpolado


def test_con_gate_el_enfasis_se_mueve_a_la_palabra_medida():
    groups, plan, _aviso = _aplicar(_groups_parciales())
    assert _keywords(groups[0]) == ["5000"]  # exact_match
    resumen = plan.kw_parciales
    assert resumen["n_cues_parciales"] == 1 and resumen["con_preset"] == 1
    assert resumen["cues"][0]["razon"] == "con_preset"
    assert resumen["cues"][0]["palabra"] == "5000"


def test_el_texto_y_el_timing_del_cue_no_los_toca_el_gate():
    """El gate quita ENFASIS, jamas texto ni tiempos (D36B-1/D36B-2)."""
    antes = _groups_parciales()
    despues, _plan, _aviso = _aplicar(_groups_parciales())
    assert [w["text"] for w in despues[0]["words"]] == [w["text"] for w in antes[0]["words"]]
    assert [(w["start"], w["end"]) for w in despues[0]["words"]] == [
        (w["start"], w["end"]) for w in antes[0]["words"]
    ]
    assert despues[0]["text"] == antes[0]["text"]


# ─────────────────────────────────────────────────────────────────────────────
# Sin cues parciales, nada cambia
# ─────────────────────────────────────────────────────────────────────────────


def test_un_plan_reutilizado_no_arrastra_la_auditoria_anterior():
    """`apply_preset_to_srt_groups` es la fuente unica de CLI y Studio: no puede dejar residuo."""
    plan = cve.resolve_preset("keyword_punch")
    srt_render.apply_preset_to_srt_groups(
        _groups_parciales(), plan, brain_path=_SIN_BRAIN, width=1080, height=1920
    )
    assert plan.kw_parciales is not None

    doc = _doc("hola mundo", end_ms=1000)
    completos = srt_caption.construir_groups(
        srt_align.align_srt_to_words(doc, [_w("hola", 0.0, 0.4), _w("mundo", 0.5, 0.9)])
    )
    _g, plan2, _a = srt_render.apply_preset_to_srt_groups(
        completos, plan, brain_path=_SIN_BRAIN, width=1080, height=1920
    )
    assert plan2.kw_parciales is None


def test_sin_cues_parciales_no_hay_gate_ni_auditoria():
    doc = _doc("cuesta 5000 pesos hoy")
    words = [
        _w(t, i * 0.5, i * 0.5 + 0.4) for i, t in enumerate(("cuesta", "5000", "pesos", "hoy"))
    ]
    result = srt_align.align_srt_to_words(doc, words)
    assert result.cues[0].mode == "word_aligned"
    groups, plan, _aviso = _aplicar(srt_caption.construir_groups(result))
    assert plan.kw_parciales is None  # no se audita lo que no paso por el gate
    assert _keywords(groups[0]) == ["pesos"]  # cue completo: la regla de siempre manda


# ─────────────────────────────────────────────────────────────────────────────
# Sidecar
# ─────────────────────────────────────────────────────────────────────────────


def test_el_sidecar_publica_la_auditoria_del_gate():
    groups, plan, _aviso = _aplicar(_groups_parciales())
    data = cve.construir_seleccion(groups, plan)
    parciales = data["parciales"]
    assert parciales["totales"]["con_preset"] == 1
    assert parciales["max_auto"] == 1 and parciales["densidad"] == "baja"
    assert [c["cue"] for c in parciales["cues"]] == [0]


def test_el_sidecar_clasico_no_gana_claves_nuevas():
    """Byte-identidad: un render sin cues parciales produce el sidecar de siempre."""
    plan = cve.resolve_preset("keyword_punch")
    data = cve.construir_seleccion([], plan)
    assert set(data) == {
        "preset",
        "densidad",
        "punch_scale",
        "keywords",
        "descartadas",
        "posiciones",
    }
