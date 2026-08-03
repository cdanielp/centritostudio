"""Contrato del gate de cues parciales (S39).

Regla que se fija aqui: en un cue `word_partial` el enfasis AUTOMATICO solo cae sobre una
palabra con ancla REAL y con carga semantica. Todo lo demas queda registrado con su razon
exacta — sin_candidato / sin_ancla_real / freno_densidad / antispam_r7 — porque un sidecar
que no sabe por que decidio, miente (D45).

Los cues `word_aligned` y la ruta clasica no pasan por el gate: eso tambien se fija aqui.
"""

from __future__ import annotations

import cve
import cve_keywords as ck
import cve_parciales as cp

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _grupo(gid: int, modo: str, palabras, texto: str | None = None) -> dict:
    """palabras = [(texto, kind), ...]. Un evento por palabra, 1 s por grupo."""
    base = float(gid)
    paso = 1.0 / max(len(palabras), 1)
    words = [
        {
            "text": t,
            "start": round(base + paso * i, 3),
            "end": round(base + paso * (i + 1), 3),
            "line_idx": 0,
            "kind": k,
        }
        for i, (t, k) in enumerate(palabras)
    ]
    return {
        "id": gid,
        "timing_mode": modo,
        "start": base,
        "end": base + 1.0,
        "text": texto if texto is not None else " ".join(t for t, _k in palabras),
        "words": words,
    }


def _correr(groups, preset: str = "keyword_punch"):
    """Aplica el engine con gate y devuelve (groups marcados, resumen del gate)."""
    plan = cve.resolve_preset(preset)
    gate = cp.GateParciales()
    marcados = cve.aplicar_engine(groups, plan, 1080, 1920, gate=gate)
    return marcados, gate.resumen()


def _por_cue(resumen: dict) -> dict[int, dict]:
    return {r["cue"]: r for r in resumen["cues"]}


def _keywords(g: dict) -> list[str]:
    return [w["text"] for w in g["words"] if w.get("is_keyword")]


# ─────────────────────────────────────────────────────────────────────────────
# es_ancla_real
# ─────────────────────────────────────────────────────────────────────────────


def test_solo_exact_y_substitution_son_ancla_real():
    assert cp.es_ancla_real({"kind": "exact_match"}) is True
    assert cp.es_ancla_real({"kind": "substitution_match"}) is True
    assert cp.es_ancla_real({"kind": "interpolado"}) is False
    assert cp.es_ancla_real({"kind": "absorbido"}) is False


def test_palabra_sin_kind_no_puede_afirmar_ancla():
    """Un group que no declara procedencia del timing no la tiene: nunca se asume."""
    assert cp.es_ancla_real({"text": "gratis"}) is False


# ─────────────────────────────────────────────────────────────────────────────
# La regla: enfasis solo sobre timing medido
# ─────────────────────────────────────────────────────────────────────────────


def test_ancla_real_recibe_el_enfasis():
    groups = [_grupo(0, "word_partial", [("todo", "interpolado"), ("gratis", "exact_match")])]
    marcados, resumen = _correr(groups)
    assert _keywords(marcados[0]) == ["gratis"]
    r = _por_cue(resumen)[0]
    assert (r["preset"], r["razon"], r["palabra"]) == (True, cp.RAZON_OK, "gratis")


def test_timing_interpolado_no_recibe_enfasis():
    """Misma palabra, mismo cue: cambia SOLO la procedencia del timing."""
    groups = [_grupo(0, "word_partial", [("todo", "interpolado"), ("gratis", "interpolado")])]
    marcados, resumen = _correr(groups)
    assert _keywords(marcados[0]) == []
    r = _por_cue(resumen)[0]
    assert (r["preset"], r["razon"]) == (False, cp.RAZON_SIN_ANCLA)


def test_evento_absorbido_no_recibe_enfasis():
    """Un evento absorbido muestra VARIOS tokens a la vez: resaltarlo resalta de mas.

    'cuesta 50%' es un solo evento con dos tokens dentro. R2 dispara igual (el '%' esta ahi),
    asi que sin gate el punch crecia sobre las dos palabras y con timing repartido.
    """
    groups = [_grupo(0, "word_partial", [("hola", "exact_match"), ("cuesta 50%", "absorbido")])]
    marcados, resumen = _correr(groups)
    assert _keywords(marcados[0]) == []
    assert _por_cue(resumen)[0]["razon"] == cp.RAZON_SIN_ANCLA


def test_cue_sin_ninguna_regla_disparada_es_sin_candidato():
    groups = [_grupo(0, "word_partial", [("hola", "exact_match"), ("mundo", "exact_match")])]
    _marcados, resumen = _correr(groups)
    r = _por_cue(resumen)[0]
    assert (r["preset"], r["razon"], r["palabra"]) == (False, cp.RAZON_SIN_CANDIDATO, None)


def test_palabra_vacia_de_la_lista_ampliada_no_es_candidata():
    """R6 propone la palabra tras un contraste; 'puede' no dice nada aunque este anclada."""
    groups = [_grupo(0, "word_partial", [("pero", "exact_match"), ("puede", "exact_match")])]
    marcados, resumen = _correr(groups)
    assert _keywords(marcados[0]) == []
    r = _por_cue(resumen)[0]
    assert (r["preset"], r["razon"]) == (False, cp.RAZON_SIN_CANDIDATO)
    assert r["detalle"] == "debil:puede"  # la razon dice CUAL palabra se descarto


def test_palabra_vacia_no_afecta_a_la_ruta_clasica():
    """La lista ampliada es exclusiva del gate: sin gate, 'puede' sigue siendo keyword."""
    groups = [_grupo(0, "word_partial", [("pero", "exact_match"), ("puede", "exact_match")])]
    plan = cve.resolve_preset("keyword_punch")
    marcados = cve.aplicar_engine(groups, plan, 1080, 1920)
    assert _keywords(marcados[0]) == ["puede"]


# ─────────────────────────────────────────────────────────────────────────────
# Frenos: densidad y anti-spam se distinguen de verdad
# ─────────────────────────────────────────────────────────────────────────────


def test_freno_densidad_se_reporta_como_tal():
    """Dos candidatas validas, tope automatico 1: la segunda NO es 'sin candidato'."""
    groups = [
        _grupo(0, "word_partial", [("todo", "interpolado"), ("gratis", "exact_match")]),
        _grupo(1, "word_partial", [("son", "interpolado"), ("5000", "exact_match")]),
    ]
    marcados, resumen = _correr(groups)
    assert resumen["max_auto"] == 1 and resumen["densidad"] == "baja"
    cues = _por_cue(resumen)
    assert (cues[0]["preset"], cues[0]["razon"]) == (True, cp.RAZON_OK)
    assert (cues[1]["preset"], cues[1]["razon"]) == (False, cp.RAZON_DENSIDAD)
    # La razon apunta a la palabra que SE HABRIA destacado: eso es lo auditable.
    assert cues[1]["palabra"] == "5000"
    assert _keywords(marcados[1]) == []


def test_antispam_r7_no_se_disfraza_de_freno_densidad():
    palabras = [("carpeta", "exact_match"), ("nueva", "exact_match")]
    groups = [_grupo(i, "word_partial", palabras) for i in range(3)]
    _marcados, resumen = _correr(groups)
    cues = _por_cue(resumen)
    assert cues[0]["razon"] == cp.RAZON_ANTISPAM  # dos R7 seguidas: cae la primera
    assert cues[1]["razon"] == cp.RAZON_OK
    assert cues[2]["razon"] == cp.RAZON_SIN_CANDIDATO  # R7 solo marca 2 apariciones


# ─────────────────────────────────────────────────────────────────────────────
# Exenciones
# ─────────────────────────────────────────────────────────────────────────────


def test_marca_manual_esta_exenta_del_gate():
    """Destacar es intencion explicita del usuario y gana a todo (voto #34)."""
    g = _grupo(
        0, "word_partial", [("hola", "interpolado"), ("[strong]mundo[/strong]", "interpolado")]
    )
    g["text"] = "hola [strong]mundo[/strong]"
    marcados, resumen = _correr([g])
    assert _keywords(marcados[0]) == ["mundo"]
    r = _por_cue(resumen)[0]
    assert (r["preset"], r["razon"], r["palabra"]) == (True, cp.RAZON_MANUAL, "mundo")


def test_cues_completos_no_pasan_por_el_gate():
    """word_aligned = todos sus tokens son anclas reales; no se audita ni se filtra."""
    groups = [
        _grupo(0, "word_aligned", [("todo", "exact_match"), ("gratis", "exact_match")]),
        _grupo(1, "word_partial", [("hola", "interpolado"), ("mundo", "interpolado")]),
    ]
    marcados, resumen = _correr(groups)
    assert _keywords(marcados[0]) == ["gratis"]
    assert resumen["n_cues_parciales"] == 1
    assert list(_por_cue(resumen)) == [1]


# ─────────────────────────────────────────────────────────────────────────────
# Resumen auditable
# ─────────────────────────────────────────────────────────────────────────────


def test_los_totales_cuadran_con_los_cues():
    groups = [
        _grupo(0, "word_partial", [("todo", "interpolado"), ("gratis", "exact_match")]),
        _grupo(1, "word_partial", [("son", "interpolado"), ("5000", "exact_match")]),
        _grupo(2, "word_partial", [("hola", "exact_match"), ("mundo", "exact_match")]),
        _grupo(3, "word_partial", [("dame", "interpolado"), ("50%", "interpolado")]),
    ]
    _marcados, resumen = _correr(groups)
    totales = resumen["totales"]
    assert set(totales) == set(cp.RAZONES)  # vocabulario cerrado, siempre completo
    assert sum(totales.values()) == resumen["n_cues_parciales"] == 4
    assert totales[cp.RAZON_OK] == resumen["con_preset"] == 1
    assert totales[cp.RAZON_DENSIDAD] == 1
    assert totales[cp.RAZON_SIN_CANDIDATO] == 1
    assert totales[cp.RAZON_SIN_ANCLA] == 1


# ─────────────────────────────────────────────────────────────────────────────
# La auditoria NUNCA afirma un enfasis que no se aplico
# ─────────────────────────────────────────────────────────────────────────────


def test_si_el_engine_falla_la_auditoria_no_afirma_enfasis(monkeypatch):
    """Fallback total del engine (§8): salen grupos SIN marcas -> el resumen no dice preset."""
    groups = [_grupo(0, "word_partial", [("todo", "interpolado"), ("gratis", "exact_match")])]
    plan = cve.resolve_preset("keyword_punch")
    gate = cp.GateParciales()

    def _explota(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(cve, "_marcar_grupo", _explota)
    marcados = cve.aplicar_engine(groups, plan, 1080, 1920, gate=gate)
    assert _keywords(marcados[0]) == []
    resumen = gate.resumen()
    assert resumen["con_preset"] == 0 and resumen["n_cues_parciales"] == 0


def test_preset_sin_keywords_lo_dice_en_vez_de_reportar_cero_cues():
    """`keywords: off` con cues parciales: 'el preset no destaca' != 'no habia parciales'."""
    groups = [_grupo(0, "word_partial", [("todo", "interpolado"), ("gratis", "exact_match")])]
    _marcados, resumen = _correr(groups, preset="clean_podcast")
    assert resumen["n_cues_parciales"] == 1 and resumen["con_preset"] == 0
    assert _por_cue(resumen)[0]["razon"] == cp.RAZON_KEYWORDS_OFF


def test_resumen_sin_cues_parciales_es_vacio_no_falso_positivo():
    resumen = cp.GateParciales().resumen()
    assert resumen["n_cues_parciales"] == 0
    assert sum(resumen["totales"].values()) == 0
    assert cp.linea_reporte(resumen) is None
    assert cp.linea_reporte(None) is None


def test_linea_reporte_publica_los_totales():
    groups = [
        _grupo(0, "word_partial", [("todo", "interpolado"), ("gratis", "exact_match")]),
        _grupo(1, "word_partial", [("son", "interpolado"), ("5000", "exact_match")]),
    ]
    _marcados, resumen = _correr(groups)
    linea = cp.linea_reporte(resumen)
    assert "1/2" in linea and "freno_densidad=1" in linea and "tope automatico 1" in linea


# ─────────────────────────────────────────────────────────────────────────────
# La seleccion detallada no cambia la seleccion
# ─────────────────────────────────────────────────────────────────────────────


def test_elegir_keywords_detallado_no_altera_la_eleccion():
    candidatos = [
        (0, 1, ck.SCORE_R2_DINERO, "R2"),
        (1, 0, ck.SCORE_R1_NUMEROS, "R1"),
        (2, 2, ck.SCORE_R7_REPETIDA, "R7"),
        (3, 0, ck.SCORE_R7_REPETIDA, "R7"),
        (3, 1, ck.SCORE_MANUAL, "manual"),
        (4, 0, ck.SCORE_BRAIN, "brain"),
    ]
    for densidad in (None, "baja", "media", "alta"):
        for n in (1, 3, 5, 40):
            detallado = ck.elegir_keywords_detallado(candidatos, n, densidad)
            assert detallado.elegidas == ck.elegir_keywords(candidatos, n, densidad)


def test_los_recortes_son_disjuntos_de_lo_elegido():
    candidatos = [(g, 0, ck.SCORE_R1_NUMEROS, "R1") for g in range(6)]
    d = ck.elegir_keywords_detallado(candidatos, 6, "baja")
    assert set(d.elegidas) & set(d.recorte_densidad) == set()
    assert len(d.elegidas) == d.max_auto
    assert set(d.elegidas) | set(d.recorte_densidad) | set(d.recorte_antispam) == set(range(6))
