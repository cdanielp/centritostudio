"""test_auto_srt_manifest.py — Manifiesto FINAL saneado de un run Auto SRT (S36-C2C). Puro."""

from __future__ import annotations

import pytest

import auto_srt_manifest as m


def _clip(cid, *, status="done", archivo=None, dur_s=5.0, cov=0.9, fb=0.1):
    d = {"clip_id": cid, "dur_s": dur_s, "caption_coverage": cov, "fallback_ratio": fb}
    if status == "error":
        d["status"] = "error"
    if archivo is not None:
        d["archivo"] = archivo
    elif status != "error":
        d["archivo"] = f"{cid}.mp4"
    return d


def _build(clips, run="demo_v2_20260720-1430", fn="demo.mov"):
    return m.build_run_manifest(run_id=run, source_filename=fn, srt_selected=True, clips=clips)


# ─── Forma y contrato ──────────────────────────────────────────────────────────
def test_forma_v1_completa():
    man = _build([_clip("clip1"), _clip("clip2")])
    assert man["version"] == 1
    assert man["run_id"] == "demo_v2_20260720-1430"
    assert man["caption_source"] == "srt"
    assert man["source"] == {"video_filename": "demo.mov", "srt_selected": True}
    assert man["summary"] == {"total": 2, "done": 2, "error": 0}
    c = man["clips"][0]
    assert set(c) == {
        "clip_id",
        "status",
        "output",
        "duration_ms",
        "caption_coverage",
        "fallback_ratio",
    }
    assert c["clip_id"] == "clip1" and c["status"] == "done" and c["output"] == "clip1.mp4"
    assert c["duration_ms"] == 5000


def test_summary_cuenta_done_y_error():
    man = _build([_clip("c1"), _clip("c2", status="error"), _clip("c3")])
    assert man["summary"] == {"total": 3, "done": 2, "error": 1}


# ─── Clip en error nunca es publicable ─────────────────────────────────────────
def test_clip_error_no_expone_output():
    man = _build([_clip("boom", status="error", archivo="boom.mp4")])
    c = man["clips"][0]
    assert c["status"] == "error" and c["output"] is None  # sin MP4 publicable


def test_clip_error_sin_cobertura_default_cero():
    man = _build([{"clip_id": "boom", "status": "error", "error_code": "IndexError"}])
    c = man["clips"][0]
    assert c["caption_coverage"] == 0.0 and c["fallback_ratio"] == 0.0
    assert c["duration_ms"] == 0 and c["output"] is None


# ─── Saneamiento ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("cid", ["../x", "a/b", "", ".", "..", None, "c\x00"])
def test_clip_id_inseguro_rechazado(cid):
    with pytest.raises(m.AutoSrtManifestError):
        _build([_clip(cid)])


@pytest.mark.parametrize("run", ["../evil", "a/b", "", ".", ".."])
def test_run_id_inseguro_rechazado(run):
    with pytest.raises(m.AutoSrtManifestError):
        _build([_clip("c1")], run=run)


@pytest.mark.parametrize("fn", ["../demo.mov", "a/b.mov", ""])
def test_source_filename_inseguro_rechazado(fn):
    with pytest.raises(m.AutoSrtManifestError):
        _build([_clip("c1")], fn=fn)


def test_output_con_ruta_rechazado():
    with pytest.raises(m.AutoSrtManifestError):
        _build([_clip("c1", archivo="../escape.mp4")])


@pytest.mark.parametrize(
    "raw,expected",
    [(1.5, 1.0), (-0.3, 0.0), (0.6667, 0.6667), (True, 0.0), ("x", 0.0), (float("nan"), 0.0)],
)
def test_ratio_clampeado(raw, expected):
    man = _build([{"clip_id": "c1", "archivo": "c1.mp4", "caption_coverage": raw, "dur_s": 1}])
    assert man["clips"][0]["caption_coverage"] == expected


@pytest.mark.parametrize("dur,ms", [(-5, 0), (True, 0), (3, 3), (None, 0)])
def test_duration_ms_estricta(dur, ms):
    man = _build([{"clip_id": "c1", "archivo": "c1.mp4", "duration_ms": dur}])
    assert man["clips"][0]["duration_ms"] == ms


def test_dur_s_a_ms_cuando_no_hay_duration_ms():
    man = _build([{"clip_id": "c1", "archivo": "c1.mp4", "dur_s": 4.2}])
    assert man["clips"][0]["duration_ms"] == 4200


# ─── MP4 y MOV con el mismo stem no colisionan en el manifiesto ───────────────
def test_mp4_y_mov_mismo_stem_distinto_filename():
    man_mov = _build([_clip("c1")], fn="demo.mov")
    man_mp4 = _build([_clip("c1")], fn="demo.mp4")
    assert man_mov["source"]["video_filename"] == "demo.mov"
    assert man_mp4["source"]["video_filename"] == "demo.mp4"


# ─── Sin rutas ni texto privado en el JSON serializado ─────────────────────────
def test_manifiesto_no_expone_rutas_ni_texto():
    import json

    man = _build([_clip("c1", cov=0.8, fb=0.2), _clip("c2", status="error")])
    blob = json.dumps(man)
    assert "/" not in blob.replace("://", "")  # sin separadores de ruta
    assert "error_code" not in blob and "razon" not in blob and "titulo" not in blob


def test_run_vacio_summary_cero():
    man = _build([])
    assert man["summary"] == {"total": 0, "done": 0, "error": 0} and man["clips"] == []
