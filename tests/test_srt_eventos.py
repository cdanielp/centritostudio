"""Motor de reparto de eventos dentro de un cue (S38-v2, gate visual de K).

K rechazo la primera version por el TIMING dentro del cue (el texto era correcto). Cuatro
defectos medidos, cuatro invariantes que este modulo tiene que garantizar SIEMPRE:

  D1 arranque: el primer evento empieza en `cue_start_ms` exacto (antes entraba en la primera
     ancla, hasta 0.57 s tarde) y el ultimo termina en `cue_end_ms` exacto.
  D2 degenerados: ningun evento dura menos de `min_evento_ms` (default 150). Un token que no
     alcanza el minimo se ABSORBE en el evento anterior: se pierde su resalte, nunca su texto.
  D3 solapes: los eventos son contiguos y estrictamente crecientes. Cero duplicados.
  D4 porton: este modulo no decide QUE cues se animan; solo reparte. La unica razon para
     devolver None es que el cue no da ni para un evento del minimo.
"""

from __future__ import annotations

import pytest

import srt_eventos


def _ok(evs, cue_start, cue_end, min_ms=srt_eventos.MIN_EVENTO_MS):
    """Comprueba las cuatro invariantes de golpe sobre una lista de eventos."""
    assert evs, "siempre hay al menos un evento"
    assert evs[0].start_ms == cue_start, "D1: el primer evento no arranca en cue_start"
    assert evs[-1].end_ms == cue_end, "D1: el ultimo evento no termina en cue_end"
    for e in evs:
        assert e.end_ms - e.start_ms >= min_ms, f"D2: evento degenerado {e}"
    for a, b in zip(evs, evs[1:], strict=False):
        assert a.end_ms == b.start_ms, "D3: hueco o solape entre eventos"
        assert b.start_ms > a.start_ms, "D3: starts no estrictamente crecientes"
    vistos = [(e.start_ms, e.end_ms) for e in evs]
    assert len(vistos) == len(set(vistos)), "D3: eventos duplicados"


# ── D1 · arranque y cierre exactos ───────────────────────────────────────────


def test_arranca_en_cue_start_aunque_la_primera_ancla_llegue_tarde():
    """El caso que K vio: ancla a 320 ms del inicio => el caption entraba tarde."""
    evs = srt_eventos.distribuir_eventos(3, {0: (2320, 2600), 2: (3400, 3700)}, 2000, 4000)
    _ok(evs, 2000, 4000)
    assert evs[0].start_ms == 2000, "el token anclado se adelanta al inicio del cue"


def test_arranca_en_cue_start_con_todos_los_tokens_anclados():
    """Modo word_aligned: si TODOS anclan, el primero igual arranca en cue_start."""
    anclas = {0: (1200, 1500), 1: (1600, 1900), 2: (2100, 2400)}
    evs = srt_eventos.distribuir_eventos(3, anclas, 1000, 3000)
    _ok(evs, 1000, 3000)


def test_un_solo_token_ocupa_el_cue_entero():
    evs = srt_eventos.distribuir_eventos(1, {0: (500, 700)}, 0, 2000)
    _ok(evs, 0, 2000)
    assert len(evs) == 1


@pytest.mark.parametrize("n_tok", [1, 2, 3, 5, 8, 13])
def test_invariantes_para_cualquier_conteo(n_tok):
    anclas = {0: (1100, 1300)} if n_tok > 1 else {}
    evs = srt_eventos.distribuir_eventos(n_tok, anclas, 1000, 1000 + 200 * n_tok)
    _ok(evs, 1000, 1000 + 200 * n_tok)


# ── D2 · duracion minima y absorcion ─────────────────────────────────────────


def test_absorbe_cuando_no_caben_todos_los_tokens():
    """6 tokens en 500 ms con minimo 150: caben 3 eventos, se absorben 3 tokens."""
    evs = srt_eventos.distribuir_eventos(6, {0: (0, 100)}, 0, 500)
    _ok(evs, 0, 500)
    assert len(evs) == 3, "cap = 500 // 150"
    assert sum(len(e.indices) for e in evs) == 6, "ningun token se pierde"
    assert [i for e in evs for i in e.indices] == [0, 1, 2, 3, 4, 5], "orden intacto"


def test_absorcion_conserva_todos_los_indices_en_orden():
    evs = srt_eventos.distribuir_eventos(20, {0: (0, 50), 10: (300, 350)}, 0, 900)
    _ok(evs, 0, 900)
    assert [i for e in evs for i in e.indices] == list(range(20))


def test_minimo_configurable():
    evs = srt_eventos.distribuir_eventos(10, {}, 0, 1000, min_evento_ms=400)
    _ok(evs, 0, 1000, min_ms=400)
    assert len(evs) == 2


def test_cue_mas_corto_que_el_minimo_devuelve_none():
    """No se inventa un evento imposible: el llamador cae a estatico honesto."""
    assert srt_eventos.distribuir_eventos(3, {0: (0, 50)}, 0, 100) is None


def test_cue_justo_del_minimo_da_un_evento():
    evs = srt_eventos.distribuir_eventos(5, {}, 0, 150)
    _ok(evs, 0, 150)
    assert len(evs) == 1 and len(evs[0].indices) == 5


# ── D3 · monotonia estricta pese a anclas hostiles ───────────────────────────


def test_anclas_solapadas_no_producen_solape():
    anclas = {0: (1000, 1800), 1: (1200, 1400), 2: (1100, 1600)}  # invertidas y solapadas
    evs = srt_eventos.distribuir_eventos(3, anclas, 1000, 2500)
    _ok(evs, 1000, 2500)


def test_anclas_identicas_no_producen_duplicados():
    anclas = {0: (1500, 1600), 1: (1500, 1600), 2: (1500, 1600)}
    evs = srt_eventos.distribuir_eventos(3, anclas, 1000, 2500)
    _ok(evs, 1000, 2500)


def test_ancla_que_empieza_antes_del_cue_se_clampa():
    """Antes esto tiraba el cue entero a estatico (219 cues reales). Ahora se acota."""
    evs = srt_eventos.distribuir_eventos(3, {0: (200, 900), 2: (1800, 2000)}, 1000, 2500)
    _ok(evs, 1000, 2500)


def test_ancla_que_termina_despues_del_cue_se_clampa():
    evs = srt_eventos.distribuir_eventos(3, {0: (1100, 1300), 2: (2400, 9000)}, 1000, 2500)
    _ok(evs, 1000, 2500)


def test_todas_las_anclas_fuera_del_rango():
    evs = srt_eventos.distribuir_eventos(3, {0: (50, 80), 1: (60, 90), 2: (70, 95)}, 1000, 2500)
    _ok(evs, 1000, 2500)


# ── Determinismo y no-mutacion ───────────────────────────────────────────────


def test_es_determinista():
    args = (7, {0: (1100, 1200), 3: (1700, 1900), 6: (2300, 2400)}, 1000, 3000)
    assert srt_eventos.distribuir_eventos(*args) == srt_eventos.distribuir_eventos(*args)


def test_no_muta_las_anclas():
    anclas = {0: (1100, 1200), 2: (1700, 1900)}
    copia = dict(anclas)
    srt_eventos.distribuir_eventos(3, anclas, 1000, 3000)
    assert anclas == copia


def test_respeta_las_anclas_cuando_hay_sitio():
    """Con hueco de sobra, un token anclado arranca en su tiempo real (salvo el primero)."""
    evs = srt_eventos.distribuir_eventos(3, {1: (2000, 2200)}, 1000, 4000)
    _ok(evs, 1000, 4000)
    assert evs[1].start_ms == 2000
