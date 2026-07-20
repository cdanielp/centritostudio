"""test_clip_srt.py — SRT derivado por clip (S36-C2A2, contrato 1B). Puro, sin FFmpeg."""

from __future__ import annotations

import pytest

import clip_srt
from srt_types import SrtCue, SrtDocument, SrtError


def _cue(i, s, e, *lines):
    return SrtCue(i, s, e, tuple(lines), i - 1)


def _doc(*cues):
    return SrtDocument(
        cues=tuple(cues),
        encoding="utf-8",
        source_sha256="0" * 64,
        diagnostics=(),
        source_name="x.srt",
    )


def _derive(doc, a, b):
    return clip_srt.derive_clip_srt(doc, a, b).cues


def test_cue_completamente_dentro_rebasado():
    d = _derive(_doc(_cue(1, 2000, 3000, "hola")), 1000, 4000)
    assert len(d) == 1 and (d[0].start_ms, d[0].end_ms) == (1000, 2000)  # rebase -1000
    assert d[0].index == 1 and d[0].lines == ("hola",)


def test_cue_antes_del_clip_se_excluye():
    assert _derive(_doc(_cue(1, 0, 500, "antes")), 1000, 2000) == ()


def test_cue_despues_del_clip_se_excluye():
    assert _derive(_doc(_cue(1, 3000, 4000, "despues")), 1000, 2000) == ()


def test_cue_cruza_inicio_se_recorta():
    d = _derive(_doc(_cue(1, 500, 1500, "cruza")), 1000, 2000)
    assert (d[0].start_ms, d[0].end_ms) == (0, 500)  # [1000,1500) - 1000


def test_cue_cruza_final_se_recorta():
    d = _derive(_doc(_cue(1, 1800, 2500, "cruza")), 1000, 2000)
    assert (d[0].start_ms, d[0].end_ms) == (800, 1000)  # [1800,2000) - 1000


def test_cue_cubre_todo_el_clip():
    d = _derive(_doc(_cue(1, 0, 9000, "todo")), 1000, 2000)
    assert (d[0].start_ms, d[0].end_ms) == (0, 1000)


def test_cue_degenerado_menor_50ms_se_descarta():
    # [1000,1030) tras recorte = 30ms < 50 -> descartado
    assert _derive(_doc(_cue(1, 1000, 1030, "x")), 1000, 5000) == ()
    # exactamente 50ms se conserva
    d = _derive(_doc(_cue(1, 1000, 1050, "y")), 1000, 5000)
    assert len(d) == 1 and (d[0].end_ms - d[0].start_ms) == 50


def test_multiples_cues_orden_e_indices():
    d = _derive(
        _doc(_cue(1, 1000, 1500, "a"), _cue(5, 2000, 2500, "b"), _cue(9, 3000, 3500, "c")),
        1200,
        3200,
    )
    assert [c.index for c in d] == [1, 2, 3]  # renumerados desde 1
    assert [c.lines[0] for c in d] == ["a", "b", "c"]  # orden preservado
    assert d[0].start_ms == 0  # el primer cue conservado arranca cerca de 0 tras rebase


def test_unicode_puntuacion_multiline_exactos():
    d = _derive(_doc(_cue(1, 1000, 2000, "¿Qué?", "Café ñ —")), 0, 5000)
    assert d[0].lines == ("¿Qué?", "Café ñ —")  # texto EXACTO, multiline preservado


def test_limites_exactos_fin_exclusivo():
    # cue que toca el borde exacto [2000,2000) no cuenta; end exclusivo
    assert _derive(_doc(_cue(1, 2000, 3000, "borde")), 1000, 2000) == ()


def test_clip_no_comienza_en_cero():
    d = _derive(_doc(_cue(1, 5000, 6000, "z")), 4500, 7000)
    assert (d[0].start_ms, d[0].end_ms) == (500, 1500)  # rebase -4500


@pytest.mark.parametrize("bad", [(2000, 1000), (1000, 1000), (-1, 500)])
def test_rango_invalido_lanza(bad):
    with pytest.raises(SrtError):
        clip_srt.derive_clip_srt(_doc(_cue(1, 0, 500, "x")), *bad)


def test_no_muta_la_fuente():
    doc = _doc(_cue(1, 1000, 2000, "orig"))
    snapshot = tuple((c.index, c.start_ms, c.end_ms, c.lines) for c in doc.cues)
    clip_srt.derive_clip_srt(doc, 500, 3000)
    assert tuple((c.index, c.start_ms, c.end_ms, c.lines) for c in doc.cues) == snapshot
