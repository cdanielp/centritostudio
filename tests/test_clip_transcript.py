"""test_clip_transcript.py — words+groups+procedencia por clip (S36-C2A2, contrato 1C). Puro."""

from __future__ import annotations

import pytest

import clip_transcript as ct


def _w(text, s, e, prob=1.0):
    return {"w": text, "s": s, "e": e, "prob": prob}


_WORDS = [_w("hola", 0.0, 0.4), _w("mundo", 0.5, 0.9), _w("esto", 1.2, 1.6), _w("fin", 2.4, 2.9)]


def test_selecciona_intersecta_y_desplaza():
    # clip [500, 2000)ms -> mundo(0.5-0.9) y esto(1.2-1.6); rebase -0.5s
    out = ct.derive_clip_words(_WORDS, 500, 2000)
    assert [x["w"] for x in out] == ["mundo", "esto"]
    assert (out[0]["s"], out[0]["e"]) == (0.0, 0.4)  # 0.5-0.5, 0.9-0.5
    assert (out[1]["s"], out[1]["e"]) == (0.7, 1.1)  # 1.2-0.5, 1.6-0.5


def test_recorta_words_que_cruzan_bordes():
    out = ct.derive_clip_words([_w("larga", 0.5, 3.0)], 1000, 2000)  # [1.0,2.0)
    assert (out[0]["s"], out[0]["e"]) == (0.0, 1.0)  # recortada a [1.0,2.0)-1.0


def test_word_fuera_o_borde_exacto_excluida():
    assert ct.derive_clip_words([_w("antes", 0.0, 0.4)], 1000, 2000) == []
    assert ct.derive_clip_words([_w("borde", 2.0, 3.0)], 1000, 2000) == []  # toca fin exclusivo


def test_conserva_texto_prob_y_campos():
    out = ct.derive_clip_words([{"w": "x", "s": 0.5, "e": 0.9, "prob": 0.77, "extra": 9}], 0, 5000)
    assert out[0]["w"] == "x" and out[0]["prob"] == 0.77 and out[0]["extra"] == 9


def test_no_muta_la_fuente():
    words = [_w("mundo", 0.5, 0.9)]
    snap = [dict(x) for x in words]
    ct.derive_clip_words(words, 400, 1000)
    assert words == snap  # dicts originales intactos


@pytest.mark.parametrize("bad", [(2000, 1000), (1000, 1000), (-1, 500), (True, 500), (0, True)])
def test_rango_invalido_lanza(bad):
    with pytest.raises(ValueError):
        ct.derive_clip_words(_WORDS, *bad)


def test_groups_desde_words_del_clip():
    out = ct.derive_clip_words(_WORDS, 0, 3000)
    groups = ct.derive_clip_groups(out)
    assert isinstance(groups, list) and groups  # el motor historico produce groups
    assert ct.derive_clip_groups([]) == []  # sin words -> sin groups


def test_provenance_liga_padre_rango_y_clip(tmp_path):
    parent = tmp_path / "demo.mov"
    parent.write_bytes(b"parent-bytes")
    clip = tmp_path / "demo_clip1.mp4"
    clip.write_bytes(b"clip-bytes-mas-largas")
    prov = ct.build_clip_provenance(
        parent, source_start_ms=1000, source_end_ms=5000, output_clip=clip
    )
    assert prov["version"] == 1
    assert prov["parent_video"]["filename"] == "demo.mov"
    assert prov["parent_video"]["size_bytes"] == parent.stat().st_size
    assert prov["output_clip"]["filename"] == "demo_clip1.mp4"
    assert prov["clip"] == {"source_start_ms": 1000, "source_end_ms": 5000, "duration_ms": 4000}
    # solo basenames, sin rutas absolutas
    assert str(tmp_path) not in __import__("json").dumps(prov)


def test_provenance_rango_invalido_lanza(tmp_path):
    v = tmp_path / "demo.mp4"
    v.write_bytes(b"x")
    with pytest.raises(ValueError):
        ct.build_clip_provenance(v, source_start_ms=5000, source_end_ms=1000, output_clip=v)
