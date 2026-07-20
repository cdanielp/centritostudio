"""test_auto_srt_e2e.py — Integración Auto caption_source=srt (S36-C2A2). FFmpeg mockeado.

Prueba el wiring real de `ejecutar_auto` con SRT: contexto del run, derivación de artefactos por
clip, render por clip con groups SRT, aislamiento de fallo y resume. reframe/get_video_info/
build_ass/burn se mockean; `clip_srt`/`clip_transcript`/`srt_caption`/`auto_srt_artifacts` corren
de verdad. Sin GPU/red/FFmpeg.
"""

from __future__ import annotations

import json

import pytest

import auto
import studio_srt
import transcript_provenance as tp
from auto_config import AutoConfig


def _ts(ms):
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _srt(*cues):
    return "\n".join(f"{i}\n{_ts(s)} --> {_ts(e)}\n{t}\n" for i, s, e, t in cues).encode("utf-8")


# SRT del padre: cues repartidos por el timeline para que caigan en clips distintos.
_SRT = _srt(
    (1, 0, 2000, "Uno dentro"),
    (2, 4000, 6000, "Dos"),
    (3, 9000, 11000, "Tres cruza"),
    (4, 14000, 16000, "Cuatro"),
)
_PARENT_WORDS = {
    "words": [
        {"w": "uno", "s": 0.5, "e": 0.9, "prob": 1.0},
        {"w": "dos", "s": 4.5, "e": 4.9, "prob": 1.0},
        {"w": "tres", "s": 9.5, "e": 9.9, "prob": 1.0},
        {"w": "cuatro", "s": 14.5, "e": 14.9, "prob": 1.0},
    ],
    "language": "es",
}
_CLIPS = [
    {"archivo": "demo_clip1_single.mp4", "start": 0.0, "end": 5.0, "dur_s": 5.0, "titulo": "C1"},
    {"archivo": "demo_clip2_single.mp4", "start": 8.0, "end": 12.0, "dur_s": 4.0, "titulo": "C2"},
    {"archivo": "demo_clip3_single.mp4", "start": 13.0, "end": 17.0, "dur_s": 4.0, "titulo": "C3"},
]


@pytest.fixture
def env(tmp_path, monkeypatch):
    trans = tmp_path / "transcripts"
    clips = tmp_path / "output" / "clips"
    paquetes = tmp_path / "output" / "paquetes"
    inp = tmp_path / "input"
    for d in (trans, clips, paquetes, inp, tmp_path / "output"):
        d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(auto, "TRANSCRIPTS", trans)
    monkeypatch.setattr(auto, "CLIPS_DIR", clips)
    monkeypatch.setattr(auto, "PAQUETES_DIR", paquetes)
    monkeypatch.setattr(auto, "ROOT", tmp_path)
    video = inp / "demo.mov"
    video.write_bytes(b"parent-video-bytes")
    # transcript del padre (para la SELECCIÓN de clips) + selección SRT + words privadas
    (trans / "demo_words.json").write_text(json.dumps(_PARENT_WORDS), encoding="utf-8")
    doc, diags = studio_srt.parse_and_validate(_SRT, source_name="s.srt", video_duration_ms=20000)
    studio_srt.store_and_associate(
        doc,
        diags,
        video_stem="demo",
        video_filename="demo.mov",
        video_duration_ms=20000,
        data=_SRT,
        storage_root=trans / "studio_srt",
        manifest_dir=trans,
    )
    parts = tp.resolve_srt_timing_artifacts(
        transcripts_dir=trans, video_stem="demo", video_filename="demo.mov"
    )
    parts.directory.mkdir(parents=True, exist_ok=True)
    parts.words_path.write_text(
        json.dumps(tp.attach_video_provenance(dict(_PARENT_WORDS), video)), encoding="utf-8"
    )

    captured: dict = {"build_ass": []}

    def fake_generar_clips(mp4, words, tipos):
        for c in _CLIPS:
            (clips / c["archivo"]).write_bytes(b"clip-mp4-" + c["archivo"].encode())
        return {
            "clips": [dict(c) for c in _CLIPS],
            "casi": [],
            "telemetria_resumen": {"costo_usd": 0.0},
        }

    def fake_reframe(clip_path, out_path, **kw):
        out_path.write_bytes(b"9x16-" + out_path.name.encode())
        return {"output": str(out_path), "segmentos": []}

    def fake_build_ass(groups, w, h, style_cfg, ass_path):
        captured["build_ass"].append([dict(g) for g in groups])
        from pathlib import Path as _P

        _P(ass_path).write_text("[ass]", encoding="utf-8")

    def fake_burn(inp_mp4, ass, out, overlays, style_cfg):
        from pathlib import Path as _P

        _P(out).write_bytes(b"final-" + _P(out).name.encode())
        return 1.0

    import assets_comfy
    import core
    import reframe

    monkeypatch.setattr(
        auto, "_asegurar_clips", lambda v, w, n: (fake_generar_clips(v, w, "x"), False)
    )
    monkeypatch.setattr(reframe, "reframe_clip", fake_reframe)
    monkeypatch.setattr(
        core, "get_video_info", lambda p: {"width": 1080, "height": 1920, "duration": 4.0}
    )
    monkeypatch.setattr(core, "build_ass", fake_build_ass)
    monkeypatch.setattr(core, "burn_video_with_emojis", fake_burn)
    monkeypatch.setattr(assets_comfy, "resolver_overlays", lambda *a: [])
    return {"video": video, "trans": trans, "clips": clips, "captured": captured, "core": core}


def test_auto_srt_produce_clips_con_captions_srt(env):
    r = auto.ejecutar_auto(env["video"], "demo", config=AutoConfig(caption_source="srt"))
    assert len(r["clips"]) == 3
    for info in r["clips"]:
        assert info["caption_source"] == "srt" and "clip_id" in info
    # los groups que llegan a build_ass son el TEXTO OFICIAL del SRT (no el transcript del padre).
    textos = " ".join(g["text"] for grupos in env["captured"]["build_ass"] for g in grupos)
    assert "Uno dentro" in textos or "Dos" in textos  # texto del SRT
    # artefactos privados por clip creados en el namespace del run.
    ns = env["trans"] / "studio_srt_clips" / "demo"
    srts = list(ns.rglob("clip.srt"))
    assert len(srts) == 3 and all(s.parent.parent.name == "clips" for s in srts)


def test_auto_srt_no_usa_stem_root_como_captions(env):
    # {stem}_groups.json histórico NO debe alimentar los captions SRT.
    (env["trans"] / "demo_groups.json").write_text(
        json.dumps([{"id": 0, "text": "TRANSCRIPT VIEJO", "words": [], "start": 0, "end": 1}]),
        encoding="utf-8",
    )
    auto.ejecutar_auto(env["video"], "demo", config=AutoConfig(caption_source="srt"))
    textos = " ".join(g["text"] for grupos in env["captured"]["build_ass"] for g in grupos)
    assert "TRANSCRIPT VIEJO" not in textos


def test_auto_srt_clip_cruza_corte_rebasado_a_cero(env):
    auto.ejecutar_auto(env["video"], "demo", config=AutoConfig(caption_source="srt"))
    # clip3 [13000,17000): cue4 [14000,16000)->[1000,3000) rebasado. clip.srt arranca cerca de 0.
    ns = env["trans"] / "studio_srt_clips" / "demo"
    c3 = [s for s in ns.rglob("clip.srt") if "clip3" in str(s)][0]
    txt = c3.read_text(encoding="utf-8")
    assert "Cuatro" in txt and "00:00:01,000 --> 00:00:03,000" in txt  # rebasado a t=0


def test_auto_srt_fallo_de_un_clip_no_detiene_los_demas(env, monkeypatch):
    # el burn del clip 2 revienta; clips 1 y 3 deben quedar OK.
    orig_burn = env["core"].burn_video_with_emojis

    def burn_falla(inp_mp4, ass, out, overlays, style_cfg):
        if "clip2" in str(out):
            raise RuntimeError("fallo-controlado-clip2")
        return orig_burn(inp_mp4, ass, out, overlays, style_cfg)

    monkeypatch.setattr(env["core"], "burn_video_with_emojis", burn_falla)
    r = auto.ejecutar_auto(env["video"], "demo", config=AutoConfig(caption_source="srt"))
    n_error = sum(1 for c in r["clips"] if c.get("status") == "error")
    assert n_error == 1  # solo el clip 2 falló
    assert len(r["clips"]) == 3  # los otros dos siguieron
    assert any(c.get("error_code") == "RuntimeError" for c in r["clips"])


def test_transcript_default_no_toca_srt(env, monkeypatch):
    # caption_source por defecto (transcript) no debe resolver contexto SRT.
    import auto_srt_run

    monkeypatch.setattr(
        auto_srt_run,
        "resolve_auto_srt_context",
        lambda *a, **k: pytest.fail("transcript NO resuelve SRT"),
    )
    # basta con que NO se llame a auto_srt_run; se mockea _procesar_clip para evitar FFmpeg real.
    monkeypatch.setattr(
        auto, "_procesar_clip", lambda clip, pdir: {"archivo": clip["archivo"], "titulo": ""}
    )
    r = auto.ejecutar_auto(env["video"], "demo")  # sin config = transcript histórico
    assert len(r["clips"]) == 3
    assert all(c.get("caption_source") != "srt" for c in r["clips"])
