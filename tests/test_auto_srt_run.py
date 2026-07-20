"""test_auto_srt_run.py — Contexto SRT de un run de Auto (S36-C2A2). Sin FFmpeg."""

from __future__ import annotations

import json

import pytest

import auto_srt_run
import studio_srt
import studio_srt_runtime as rt
import transcript_provenance as tp


def _ts(ms):
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _srt(*cues):
    return "\n".join(f"{i}\n{_ts(s)} --> {_ts(e)}\n{t}\n" for i, s, e, t in cues).encode("utf-8")


_SRT = _srt((1, 0, 2000, "Hola mundo"), (2, 3000, 5000, "Texto"))
_WORDS = {"words": [{"w": "hola", "s": 0.0, "e": 0.5, "prob": 1.0}], "language": "es"}


def _setup(tmp_path, video_filename="demo.mov", with_words=True):
    inp = tmp_path / "input"
    trans = tmp_path / "transcripts"
    inp.mkdir()
    trans.mkdir()
    video = inp / video_filename
    video.write_bytes(b"video-bytes")
    doc, diags = studio_srt.parse_and_validate(_SRT, source_name="s.srt", video_duration_ms=6000)
    studio_srt.store_and_associate(
        doc,
        diags,
        video_stem="demo",
        video_filename=video_filename,
        video_duration_ms=6000,
        data=_SRT,
        storage_root=trans / "studio_srt",
        manifest_dir=trans,
    )
    if with_words:
        arts = tp.resolve_srt_timing_artifacts(
            transcripts_dir=trans, video_stem="demo", video_filename=video_filename
        )
        arts.directory.mkdir(parents=True, exist_ok=True)
        arts.words_path.write_text(
            json.dumps(tp.attach_video_provenance(dict(_WORDS), video)), encoding="utf-8"
        )
    return inp, trans


def test_contexto_resuelto_ok(tmp_path):
    inp, trans = _setup(tmp_path)
    ctx = auto_srt_run.resolve_auto_srt_context(
        "demo", "run-1", input_dir=inp, transcripts_dir=trans
    )
    assert ctx.run_id == "run-1"
    assert ctx.source_filename == "demo.mov"
    assert ctx.binding.path.name == "demo.mov"
    assert len(ctx.srt_document.cues) == 2  # SRT oficial del padre
    assert [w["w"] for w in ctx.parent_words] == ["hola"]  # timings privados del padre
    assert "studio_srt_clips" in str(ctx.run_dir) and ctx.run_dir.name == "run-1"


def test_sin_seleccion_lanza(tmp_path):
    inp = tmp_path / "input"
    trans = tmp_path / "transcripts"
    inp.mkdir()
    trans.mkdir()
    (inp / "demo.mov").write_bytes(b"x")
    with pytest.raises(rt.StudioSrtSelectionMissing):
        auto_srt_run.resolve_auto_srt_context("demo", "run-1", input_dir=inp, transcripts_dir=trans)


def test_video_exacto_ausente_lanza(tmp_path):
    inp, trans = _setup(tmp_path, video_filename="demo.mov")
    (inp / "demo.mov").unlink()  # el video asociado desaparece
    with pytest.raises(rt.StudioSrtSelectedVideoMissing):
        auto_srt_run.resolve_auto_srt_context("demo", "run-1", input_dir=inp, transcripts_dir=trans)


def test_timings_privados_faltantes_lanza(tmp_path):
    inp, trans = _setup(tmp_path, with_words=False)  # sin words privadas
    with pytest.raises(rt.StudioSrtTimingMissing):
        auto_srt_run.resolve_auto_srt_context("demo", "run-1", input_dir=inp, transcripts_dir=trans)


def test_mov_no_se_cruza_con_mp4_decoy(tmp_path):
    inp, trans = _setup(tmp_path, video_filename="demo.mov")
    (inp / "demo.mp4").write_bytes(b"decoy-mp4")  # decoy mismo stem
    ctx = auto_srt_run.resolve_auto_srt_context(
        "demo", "run-1", input_dir=inp, transcripts_dir=trans
    )
    assert ctx.binding.path.name == "demo.mov"  # NUNCA el decoy .mp4


def test_run_id_inseguro_lanza(tmp_path):
    inp, trans = _setup(tmp_path)
    with pytest.raises(auto_srt_artifacts_error()):
        auto_srt_run.resolve_auto_srt_context("demo", "../x", input_dir=inp, transcripts_dir=trans)


def auto_srt_artifacts_error():
    import auto_srt_artifacts

    return auto_srt_artifacts.AutoSrtArtifactError
