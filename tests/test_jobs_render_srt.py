"""test_jobs_render_srt.py — Worker de render con SRT seleccionado (S36-C2A1, D38).

FFmpeg mockeado (build_ass/burn_video). Verifica que la ruta transcript sigue igual y no
importa el runtime SRT; que la ruta SRT usa el texto oficial, anima solo cues alineados,
conserva el fallback estatico, escribe sidecar, nombra con `_srt`, devuelve un summary
saneado y ante integridad rota publica un error sin caer al transcript.
"""

from __future__ import annotations

import hashlib
import json

import pytest

import core
import jobs_registry
import jobs_render
import studio_srt
import studio_srt_runtime as rt


def _ts(ms: int) -> str:
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _srt(*cues: tuple[int, int, int, str]) -> bytes:
    return "\n".join(f"{i}\n{_ts(s)} --> {_ts(e)}\n{t}\n" for i, s, e, t in cues).encode("utf-8")


_SRT_MIX = _srt((1, 0, 2000, "Hola mundo"), (2, 3000, 5000, "Texto sin audio"))
_WORDS = {
    "words": [
        {"w": "hola", "s": 0.0, "e": 0.5, "prob": 1.0},
        {"w": "mundo", "s": 0.6, "e": 1.0, "prob": 1.0},
    ],
    "language": "es",
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    trans = tmp_path / "transcripts"
    out = tmp_path / "output"
    trans.mkdir()
    out.mkdir()
    monkeypatch.setattr(jobs_render, "TRANSCRIPTS", trans)
    monkeypatch.setattr(jobs_render, "OUTPUT_DIR", out)
    captured: dict = {}

    def fake_build_ass(groups, w, h, style_cfg, ass_path):
        captured["groups"] = [dict(g) for g in groups]
        from pathlib import Path

        Path(ass_path).write_text("[ass]", encoding="utf-8")
        captured["ass"] = Path(ass_path).name

    def fake_burn(mp4, ass, out_path):
        from pathlib import Path

        Path(out_path).write_bytes(b"MP4")
        captured["out"] = Path(out_path).name
        return 1.5

    monkeypatch.setattr(
        core, "get_video_info", lambda _p: {"width": 1080, "height": 1920, "duration": 6.0}
    )
    monkeypatch.setattr(core, "build_ass", fake_build_ass)
    monkeypatch.setattr(core, "burn_video", fake_burn)
    monkeypatch.setattr(
        core, "burn_video_with_emojis", lambda *a, **k: fake_burn(a[0], a[1], a[2]) or 1.5
    )
    return trans, out, captured


def _selection(trans, stem="demo", data=_SRT_MIX, words=_WORDS, dur=6000):
    doc, diags = studio_srt.parse_and_validate(data, source_name="subs.srt", video_duration_ms=dur)
    studio_srt.store_and_associate(
        doc,
        diags,
        video_stem=stem,
        video_filename=f"{stem}.mp4",
        video_duration_ms=dur,
        data=data,
        storage_root=trans / "studio_srt",
        manifest_dir=trans,
    )
    if words is not None:
        (trans / f"{stem}_words.json").write_text(json.dumps(words), encoding="utf-8")
    return rt.resolve_selected_srt(stem, storage_root=trans / "studio_srt", manifest_dir=trans)


def _run_srt(sel, name="demo", **kw):
    jid = jobs_registry.new_job("test")
    jobs_render.run_render(
        jid,
        jobs_render.OUTPUT_DIR / f"{name}.mp4",
        None,
        name,
        "hormozi",
        None,
        srt_selection=sel,
        **kw,
    )
    return jobs_registry.get_job(jid)


# ─── Ruta SRT feliz ────────────────────────────────────────────────────────────
def test_srt_prepara_groups_y_escribe_sidecar(env):
    trans, out, cap = env
    sel = _selection(trans)
    job = _run_srt(sel)
    assert job["status"] == "done"
    assert (trans / "demo_srt_alignment.json").is_file()
    modes = [g["timing_mode"] for g in cap["groups"]]
    assert modes == ["word_aligned", "cue_fallback"]


def test_srt_usa_texto_oficial(env):
    trans, _out, cap = env
    sel = _selection(trans)
    _run_srt(sel)
    assert cap["groups"][0]["text"] == "Hola mundo"  # del SRT, no del transcript


def test_output_y_ass_llevan_srt(env):
    trans, _out, cap = env
    sel = _selection(trans)
    job = _run_srt(sel)
    assert cap["ass"] == "demo_hormozi_srt.ass"
    assert cap["out"] == "demo_hormozi_srt.mp4"
    assert job["result"]["output"] == "demo_hormozi_srt.mp4"


def test_job_result_lleva_summary_saneado(env):
    trans, _out, _cap = env
    sel = _selection(trans)
    job = _run_srt(sel)
    s = job["result"]["srt"]
    assert s["source"] == "srt" and s["n_cues"] == 2
    assert s["word_aligned"] + s["cue_fallback"] == s["n_cues"]
    blob = json.dumps(job["result"])
    assert "Hola" not in blob and "studio_srt" not in blob and str(trans) not in blob


def test_preset_solo_anima_aligned_fallback_intacto(env):
    trans, _out, cap = env
    sel = _selection(trans)
    job = _run_srt(sel, preset="viral_bounce")
    assert job["status"] == "done"
    modes = [g["timing_mode"] for g in cap["groups"]]
    assert modes == ["word_aligned", "cue_fallback"]  # el fallback nunca se vuelve word-by-word


def test_emojis_disponibles(env, monkeypatch):
    trans, _out, cap = env
    import assets_comfy

    monkeypatch.setattr(assets_comfy, "resolver_overlays", lambda *_a, **_k: [])
    sel = _selection(trans)
    job = _run_srt(sel, use_emojis=True)
    assert job["status"] == "done"
    assert cap["out"] == "demo_hormozi_srt_emojis.mp4"


# ─── Integridad / errores (sin fallback al transcript) ─────────────────────────
def test_integridad_rota_error_publico_sin_fallback(env):
    trans, out, _cap = env
    sel = _selection(trans)
    sel.managed_path.unlink()  # se borra el SRT entre endpoint y worker
    job = _run_srt(sel)
    assert job["status"] == "error"
    assert "no existe" in job["message"] or "administrado" in job["message"]
    assert str(trans) not in job["message"]
    assert list(out.glob("*.mp4")) == []  # no se produjo output


def test_sin_words_error(env):
    trans, _out, _cap = env
    sel = _selection(trans, words=None)  # sin words.json
    job = _run_srt(sel)
    assert job["status"] == "error"


def test_srt_no_modifica_fuente(env):
    trans, _out, _cap = env
    sel = _selection(trans)
    sha_antes = hashlib.sha256(sel.managed_path.read_bytes()).hexdigest()
    _run_srt(sel)
    assert (
        hashlib.sha256(sel.managed_path.read_bytes()).hexdigest() == sha_antes == sel.source_sha256
    )


# ─── Ruta transcript intacta / no importa runtime ──────────────────────────────
def test_transcript_no_importa_runtime(env, monkeypatch):
    trans, out, _cap = env
    (trans / "demo_groups.json").write_text(
        json.dumps(
            [
                {
                    "id": 0,
                    "start": 0,
                    "end": 1,
                    "text": "hola",
                    "words": [{"text": "hola", "start": 0, "end": 1, "line_idx": 0}],
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        rt, "resolve_selected_srt", lambda *_a, **_k: pytest.fail("transcript NO resuelve SRT")
    )
    monkeypatch.setattr(
        rt,
        "prepare_selected_srt_groups",
        lambda *_a, **_k: pytest.fail("transcript NO prepara SRT"),
    )
    jid = jobs_registry.new_job("test")
    jobs_render.run_render(
        jid, out / "demo.mp4", trans / "demo_groups.json", "demo", "hormozi", None
    )
    assert jobs_registry.get_job(jid)["status"] == "done"
