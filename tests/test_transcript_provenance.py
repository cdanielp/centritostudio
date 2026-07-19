"""test_transcript_provenance.py — Procedencia del video en el artefacto de timings (S36-C2A1).

Liga `{stem}_words.json` al video EXACTO (filename+size+mtime). Sin red, sin FFmpeg. tmp_path.
"""

from __future__ import annotations

import pytest

import transcript_provenance as tp

_BASE = {"words": [{"w": "hola", "s": 0.0, "e": 0.5, "prob": 1.0}], "language": "es"}


def _video(tmp_path, name="demo.mp4", data=b"video-bytes"):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def _ok(transcript, video, filename=None):
    tp.validate_video_provenance(
        transcript, expected_video=video, expected_filename=filename or video.name
    )


def _bad(transcript, video, filename=None):
    with pytest.raises(tp.TimingProvenanceError):
        _ok(transcript, video, filename)


# ─── build / attach ────────────────────────────────────────────────────────────
def test_build_provenance_campos(tmp_path):
    v = _video(tmp_path)
    prov = tp.build_video_provenance(v)
    assert prov["version"] == 1
    assert prov["filename"] == "demo.mp4"
    assert prov["size_bytes"] == v.stat().st_size
    assert prov["mtime_ns"] == v.stat().st_mtime_ns
    assert "/" not in prov["filename"] and "\\" not in prov["filename"]  # solo basename


def test_attach_no_muta_original_y_preserva_campos(tmp_path):
    v = _video(tmp_path)
    original = {"words": _BASE["words"], "language": "es", "extra": 1}
    snapshot = dict(original)
    out = tp.attach_video_provenance(original, v)
    assert original == snapshot  # (17) no muta el original
    assert out["words"] == _BASE["words"]  # (18) words preservadas
    assert out["words"][0]["s"] == 0.0 and out["words"][0]["e"] == 0.5  # (19) timings preservados
    assert out["language"] == "es"  # (20) language preservado
    assert out["extra"] == 1
    assert out["source_video"]["filename"] == "demo.mp4"


# ─── validate: OK ────────────────────────────────────────────────────────────
def test_valida_mp4(tmp_path):
    v = _video(tmp_path, "demo.mp4")
    _ok(tp.attach_video_provenance(_BASE, v), v)  # (1)


def test_valida_mov(tmp_path):
    v = _video(tmp_path, "demo.mov")
    _ok(tp.attach_video_provenance(_BASE, v), v)  # (2)


# ─── validate: rechazos ──────────────────────────────────────────────────────
def test_filename_distinto(tmp_path):
    v = _video(tmp_path, "demo.mp4")
    t = tp.attach_video_provenance(_BASE, v)
    _bad(t, tmp_path / "otro.mp4", filename="otro.mp4")  # (3) filename distinto


def test_mismo_stem_extension_distinta(tmp_path):
    mov = _video(tmp_path, "demo.mov")
    t = tp.attach_video_provenance(_BASE, mov)  # procedencia demo.mov
    mp4 = _video(tmp_path, "demo.mp4")
    _bad(t, mp4, filename="demo.mp4")  # (4) mismo stem, .mp4 vs .mov


def test_tamano_distinto(tmp_path):
    v = _video(tmp_path, "demo.mp4", b"12345")
    t = tp.attach_video_provenance(_BASE, v)
    v.write_bytes(b"1234567890")  # cambia el tamano
    _bad(t, v)  # (5)


def test_mtime_distinto(tmp_path):
    v = _video(tmp_path, "demo.mp4")
    t = tp.attach_video_provenance(_BASE, v)
    t["source_video"]["mtime_ns"] = t["source_video"]["mtime_ns"] + 10_000_000  # (6)
    _bad(t, v)


def test_metadata_ausente_legacy(tmp_path):
    v = _video(tmp_path, "demo.mp4")
    _bad(dict(_BASE), v)  # (7) sin source_video -> legacy rechazado


@pytest.mark.parametrize("bad_version", [2, "1", 1.0, True, None])
def test_version_invalida(tmp_path, bad_version):
    v = _video(tmp_path, "demo.mp4")
    t = tp.attach_video_provenance(_BASE, v)
    t["source_video"]["version"] = bad_version  # (8)
    _bad(t, v)


def test_bool_en_size_o_mtime(tmp_path):
    v = _video(tmp_path, "demo.mp4")
    t = tp.attach_video_provenance(_BASE, v)
    t["source_video"]["size_bytes"] = True  # (9) bool no cuenta como int
    _bad(t, v)
    t = tp.attach_video_provenance(_BASE, v)
    t["source_video"]["mtime_ns"] = True  # (10)
    _bad(t, v)


@pytest.mark.parametrize("bad_fn", ["../demo.mp4", "sub/demo.mp4", "demo\x00.mp4", "demo.txt", ""])
def test_filename_inseguro_o_extension(tmp_path, bad_fn):
    v = _video(tmp_path, "demo.mp4")
    t = tp.attach_video_provenance(_BASE, v)
    t["source_video"]["filename"] = bad_fn  # (11) traversal / (12) control / ext
    _bad(t, v, filename=bad_fn)


@pytest.mark.parametrize("bad_sv", [None, "x", 3, []])
def test_source_video_no_dict(tmp_path, bad_sv):
    v = _video(tmp_path, "demo.mp4")
    t = dict(_BASE)
    t["source_video"] = bad_sv  # (13)
    _bad(t, v)


def test_video_ausente(tmp_path):
    v = tmp_path / "demo.mp4"  # no existe
    t = {
        **_BASE,
        "source_video": {"version": 1, "filename": "demo.mp4", "size_bytes": 5, "mtime_ns": 1},
    }
    _bad(t, v)  # (14) video esperado ausente


def test_words_no_lista_rechazado(tmp_path):
    v = _video(tmp_path, "demo.mp4")
    t = tp.attach_video_provenance({"words": "no-lista", "language": "es"}, v)
    _bad(t, v)


def test_error_no_expone_ruta_ni_valor(tmp_path):
    v = _video(tmp_path, "demo.mp4")
    t = tp.attach_video_provenance(_BASE, v)
    t["source_video"]["filename"] = "otro-secreto.mov"  # (16)
    try:
        _ok(t, v)
    except tp.TimingProvenanceError as exc:
        assert "otro-secreto" not in str(exc) and str(tmp_path) not in str(exc)
