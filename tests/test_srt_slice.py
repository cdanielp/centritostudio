"""test_srt_slice.py — Contrato de recorte/rebase/reindex del SRT (S36-B, D36B-8/9).

Semantica [start_ms, end_ms). Nunca modifica la fuente. Tiempos int ms. Solo sintetico.
"""

from __future__ import annotations

import pytest

from srt_import import parse_srt_text, serialize_srt
from srt_slice import slice_srt
from srt_types import SrtCue, SrtDocument, SrtError


def _doc(*cues):
    return SrtDocument(tuple(cues), "utf-8", "0" * 64, (), "x.srt")


def _cue(index, start, end, lines, pos=0):
    return SrtCue(index, start, end, tuple(lines), pos)


def _multi():
    return _doc(
        _cue(1, 0, 1000, ["uno"], 0),
        _cue(2, 2000, 3000, ["dos"], 1),
        _cue(3, 4000, 5000, ["tres"], 2),
    )


# ============================== POSICION RELATIVA ==============================


def test_cue_completamente_dentro():
    d = slice_srt(_doc(_cue(1, 1200, 1800, ["x"])), 1000, 2000)
    assert len(d.cues) == 1
    assert (d.cues[0].start_ms, d.cues[0].end_ms) == (200, 800)


def test_cue_cruza_inicio():
    d = slice_srt(_doc(_cue(1, 500, 1500, ["x"])), 1000, 2000)
    assert (d.cues[0].start_ms, d.cues[0].end_ms) == (0, 500)


def test_cue_cruza_fin():
    d = slice_srt(_doc(_cue(1, 1500, 2500, ["x"])), 1000, 2000)
    assert (d.cues[0].start_ms, d.cues[0].end_ms) == (500, 1000)


def test_cue_cubre_todo_el_clip():
    d = slice_srt(_doc(_cue(1, 0, 9000, ["x"])), 1000, 2000)
    assert (d.cues[0].start_ms, d.cues[0].end_ms) == (0, 1000)


def test_cue_toca_borde_izquierdo_excluido():
    # cue termina exactamente en start -> sin solape (fin exclusivo del cue vs [start,end))
    d = slice_srt(_doc(_cue(1, 0, 1000, ["x"])), 1000, 2000)
    assert d.cues == ()


def test_cue_toca_borde_derecho_excluido():
    d = slice_srt(_doc(_cue(1, 2000, 3000, ["x"])), 1000, 2000)
    assert d.cues == ()


# ============================== MULTI / MULTILINEA ==============================


def test_multiples_cues():
    d = slice_srt(_multi(), 0, 3000)
    assert [c.text for c in d.cues] == ["uno", "dos"]


def test_multilinea_preservada():
    d = slice_srt(_doc(_cue(1, 100, 900, ["linea uno", "linea dos"])), 0, 1000)
    assert d.cues[0].lines == ("linea uno", "linea dos")


# ============================== REBASE / REINDEX ==============================


def test_rebase_true():
    d = slice_srt(_doc(_cue(5, 4200, 4800, ["x"])), 4000, 5000, rebase=True)
    assert (d.cues[0].start_ms, d.cues[0].end_ms) == (200, 800)


def test_rebase_false():
    d = slice_srt(_doc(_cue(5, 4200, 4800, ["x"])), 4000, 5000, rebase=False)
    assert (d.cues[0].start_ms, d.cues[0].end_ms) == (4200, 4800)


def test_reindex_true():
    d = slice_srt(_multi(), 1500, 5000, reindex=True)
    assert [c.index for c in d.cues] == [1, 2]


def test_reindex_false_conserva_indices():
    d = slice_srt(_multi(), 1500, 5000, reindex=False)
    assert [c.index for c in d.cues] == [2, 3]


# ============================== VACIOS / INVALIDOS ==============================


def test_documento_vacio():
    assert slice_srt(_doc(), 0, 1000).cues == ()


def test_clip_sin_cues():
    assert slice_srt(_multi(), 10_000, 20_000).cues == ()


def test_intervalo_invalido_lanza():
    with pytest.raises(SrtError):
        slice_srt(_multi(), 2000, 2000)
    with pytest.raises(SrtError):
        slice_srt(_multi(), 3000, 2000)


def test_start_negativo_lanza():
    with pytest.raises(SrtError):
        slice_srt(_multi(), -100, 1000)


def test_ms_no_enteros_lanza():
    with pytest.raises(SrtError):
        slice_srt(_multi(), 0.5, 1000)  # type: ignore[arg-type]


# ============================== INVARIANTES ==============================


def test_tiempos_enteros():
    d = slice_srt(_doc(_cue(1, 1200, 1800, ["x"])), 1000, 2000)
    assert isinstance(d.cues[0].start_ms, int) and isinstance(d.cues[0].end_ms, int)


def test_fuente_no_mutada():
    src = _multi()
    antes = [(c.index, c.start_ms, c.end_ms, c.lines) for c in src.cues]
    slice_srt(src, 0, 3000)
    assert [(c.index, c.start_ms, c.end_ms, c.lines) for c in src.cues] == antes


def test_serialize_parse_roundtrip():
    d = slice_srt(_multi(), 0, 3000)
    reparsed = parse_srt_text(serialize_srt(d))
    assert [c.text for c in reparsed.cues] == ["uno", "dos"]


def test_duracion_no_excede_clip():
    d = slice_srt(_doc(_cue(1, 0, 100_000, ["x"])), 1000, 2000)
    dur = d.cues[0].end_ms - d.cues[0].start_ms
    assert dur <= 1000


def test_overlap_recortado_no_excede():
    d = slice_srt(_doc(_cue(1, 0, 5000, ["a"]), _cue(2, 4000, 9000, ["b"])), 3000, 6000)
    for c in d.cues:
        assert 0 <= c.start_ms < c.end_ms <= 3000  # rebasado, ninguno excede el clip


def test_ms_independiente_de_fps():
    # 29.97 fps no cambia nada: trabajamos en ms enteros, no en frames
    d1 = slice_srt(_doc(_cue(1, 1001, 1999, ["x"])), 1000, 2000)
    d2 = slice_srt(_doc(_cue(1, 1001, 1999, ["x"])), 1000, 2000)
    assert d1.cues[0].start_ms == d2.cues[0].start_ms == 1


def test_sin_drift_acumulado():
    # recortar el mismo cue en dos clips contiguos y recomponer = tiempos originales
    src = _doc(_cue(1, 500, 2500, ["x"]))
    a = slice_srt(src, 0, 1500, rebase=False)
    b = slice_srt(src, 1500, 3000, rebase=False)
    assert a.cues[0].end_ms == b.cues[0].start_ms == 1500
