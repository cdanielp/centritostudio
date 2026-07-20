"""test_auto_srt_artifacts.py — Namespace y artefactos por clip de Auto SRT (S36-C2A2). Puro."""

from __future__ import annotations

import json

import pytest

import auto_srt_artifacts as a
from srt_types import SrtCue, SrtDocument


def _doc(*cues):
    c = tuple(SrtCue(i + 1, s, e, (t,), i) for i, (s, e, t) in enumerate(cues))
    return SrtDocument(
        cues=c, encoding="utf-8", source_sha256="0" * 64, diagnostics=(), source_name="x.srt"
    )


def _run(tmp_path, stem="demo", fn="demo.mov", run="run-1"):
    return a.resolve_run_dir(
        transcripts_dir=tmp_path, source_stem=stem, source_filename=fn, run_id=run
    )


# ─── Namespace: confinamiento e identidad ──────────────────────────────────────
def test_run_dir_confinado_y_key_del_filename(tmp_path):
    rd_mov = _run(tmp_path, fn="demo.mov")
    rd_mp4 = _run(tmp_path, fn="demo.mp4")
    assert a.SRT_CLIPS_DIR in str(rd_mov)
    assert rd_mov != rd_mp4  # mov y mp4 (mismo stem) -> dirs distintos (key del filename)
    assert rd_mov.resolve().is_relative_to((tmp_path / a.SRT_CLIPS_DIR).resolve())


def test_dos_runs_no_colisionan(tmp_path):
    assert _run(tmp_path, run="run-1") != _run(tmp_path, run="run-2")


@pytest.mark.parametrize("run", ["../evil", "a/b", "", "run\x00x"])
def test_run_id_inseguro_rechazado(tmp_path, run):
    with pytest.raises(a.AutoSrtArtifactError):
        _run(tmp_path, run=run)


@pytest.mark.parametrize("fn", ["demo.txt", "otro.mov", "../demo.mov"])
def test_filename_invalido_rechazado(tmp_path, fn):
    with pytest.raises(a.AutoSrtArtifactError):
        _run(tmp_path, fn=fn)


@pytest.mark.parametrize("cid", ["../x", "a/b", "", "c\x00"])
def test_clip_id_inseguro_rechazado(tmp_path, cid):
    with pytest.raises(a.AutoSrtArtifactError):
        a.resolve_clip_artifacts(_run(tmp_path), cid)


def test_clip_artifacts_paths_confinados(tmp_path):
    arts = a.resolve_clip_artifacts(_run(tmp_path), "clip-001")
    assert arts.srt_path.name == "clip.srt" and arts.words_path.name == "words.json"
    assert arts.groups_path.name == "groups.json" and arts.manifest_path.name == "manifest.json"
    assert arts.directory.name == "clip-001"


# ─── Derivación por clip ───────────────────────────────────────────────────────
def _derive(tmp_path, start_ms, end_ms, cid="clip-001"):
    (tmp_path / "demo.mov").write_bytes(b"parent-bytes")
    clip = tmp_path / "demo_c.mp4"
    clip.write_bytes(b"clip-bytes-mas-largas")
    doc = _doc((0, 2000, "Hola"), (3000, 5000, "Mundo"), (6000, 6020, "corto"))
    words = [
        {"w": "hola", "s": 0.5, "e": 0.9, "prob": 1.0},
        {"w": "mundo", "s": 3.5, "e": 3.9, "prob": 1.0},
    ]
    arts = a.resolve_clip_artifacts(_run(tmp_path), cid)
    summary = a.derive_clip_artifacts(
        arts,
        srt_document=doc,
        parent_words=words,
        parent_video=tmp_path / "demo.mov",
        output_clip=clip,
        source_start_ms=start_ms,
        source_end_ms=end_ms,
    )
    return arts, summary


def test_deriva_srt_rebasado_y_recortado(tmp_path):
    arts, summary = _derive(tmp_path, 1000, 4000)  # cue1->[0,1000), cue2->[2000,3000)
    srt = arts.srt_path.read_text(encoding="utf-8")
    assert srt.startswith("1\n00:00:00,000 --> 00:00:01,000\nHola")
    assert "00:00:02,000 --> 00:00:03,000\nMundo" in srt
    assert "corto" not in srt  # cue [6000,6020) fuera del clip
    assert summary["n_cues"] == 2


def test_words_rebasadas_y_groups(tmp_path):
    arts, summary = _derive(tmp_path, 1000, 4000)
    words = json.loads(arts.words_path.read_text(encoding="utf-8"))["words"]
    assert [w["w"] for w in words] == ["mundo"]  # hola (0.5-0.9) fuera; mundo (3.5-3.9) dentro
    assert words[0]["s"] == 2.5 and words[0]["e"] == 2.9  # rebasado -1.0s
    groups = json.loads(arts.groups_path.read_text(encoding="utf-8"))
    assert isinstance(groups, list) and summary["n_words"] == 1


def test_manifest_procedencia_sin_rutas(tmp_path):
    arts, _ = _derive(tmp_path, 1000, 4000)
    m = json.loads(arts.manifest_path.read_text(encoding="utf-8"))
    assert m["version"] == 1 and m["clip_id"] == "clip-001"
    assert m["parent_video"]["filename"] == "demo.mov"
    assert m["output_clip"]["filename"] == "demo_c.mp4"
    assert m["clip"]["source_start_ms"] == 1000 and m["clip"]["source_end_ms"] == 4000
    assert str(tmp_path) not in arts.manifest_path.read_text(encoding="utf-8")


def test_clip_sin_cues_coverage_cero(tmp_path):
    # clip [10000,12000) sin cues -> SRT vacío, coverage 0.0 (clip válido sin captions)
    arts, summary = _derive(tmp_path, 10000, 12000)
    assert summary["n_cues"] == 0 and summary["caption_coverage"] == 0.0
    assert arts.srt_path.read_text(encoding="utf-8") == ""


def test_coverage_parcial(tmp_path):
    _arts, summary = _derive(tmp_path, 1000, 4000)  # 2000ms cues / 3000ms
    assert summary["caption_coverage"] == 0.667


def test_no_muta_fuente(tmp_path):
    (tmp_path / "demo.mov").write_bytes(b"p")
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"c")
    doc = _doc((0, 2000, "Hola"))
    words = [{"w": "hola", "s": 0.5, "e": 0.9, "prob": 1.0}]
    snap_w = [dict(w) for w in words]
    arts = a.resolve_clip_artifacts(_run(tmp_path), "clip-001")
    a.derive_clip_artifacts(
        arts,
        srt_document=doc,
        parent_words=words,
        parent_video=tmp_path / "demo.mov",
        output_clip=clip,
        source_start_ms=0,
        source_end_ms=3000,
    )
    assert words == snap_w and len(doc.cues) == 1  # fuente intacta


def test_reescritura_idempotente_no_deja_tmp(tmp_path):
    a1, _ = _derive(tmp_path, 1000, 4000)
    a2, _ = _derive(tmp_path, 1000, 4000)  # re-deriva mismo clip
    assert a1.words_path == a2.words_path and a1.words_path.is_file()
    assert not any(p.name.endswith(".tmp") for p in a1.directory.iterdir())
