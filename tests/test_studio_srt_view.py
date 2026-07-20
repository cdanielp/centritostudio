"""test_studio_srt_view.py — View model saneado de la selección SRT para Studio (S36-C2B).

Verifica el resumen único que consume la UI: caption_source default transcript; estados de
selección/timings (none/missing/valid/mismatch/corrupt); readiness render/auto; acción
sugerida; y privacidad (nunca rutas, hashes completos ni texto de cues). Vía TestClient real.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import app as studio_app
import studio_srt


def _ts(ms: int) -> str:
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _srt(*cues: tuple[int, int, int, str]) -> bytes:
    return "\n".join(f"{i}\n{_ts(s)} --> {_ts(e)}\n{t}\n" for i, s, e, t in cues).encode("utf-8")


_SRT = _srt((1, 0, 2000, "Hola mundo"), (2, 3000, 5000, "Segundo cue"))
_WORDS = {"words": [{"w": "hola", "s": 0.0, "e": 0.5, "prob": 1.0}], "language": "es"}


@pytest.fixture
def api(tmp_path, monkeypatch):
    inp = tmp_path / "input"
    trans = tmp_path / "transcripts"
    inp.mkdir()
    trans.mkdir()
    monkeypatch.setattr(studio_app, "INPUT_DIR", inp)
    monkeypatch.setattr(studio_app, "TRANSCRIPTS", trans)
    # El router SRT tiene sus propios globals; se reapuntan para el view model.
    import studio_srt_routes

    monkeypatch.setattr(studio_srt_routes, "INPUT_DIR", inp)
    monkeypatch.setattr(studio_srt_routes, "TRANSCRIPTS", trans)
    monkeypatch.setattr(studio_srt_routes, "STUDIO_SRT_DIR", trans / "studio_srt")
    (inp / "demo.mp4").write_bytes(b"mp4-bytes")
    return TestClient(studio_app.app), trans, inp


def _associate(trans, stem="demo", data=_SRT, dur=6000, video_filename=None):
    doc, diags = studio_srt.parse_and_validate(data, source_name="subs.srt", video_duration_ms=dur)
    studio_srt.store_and_associate(
        doc,
        diags,
        video_stem=stem,
        video_filename=video_filename or f"{stem}.mp4",
        video_duration_ms=dur,
        data=data,
        storage_root=trans / "studio_srt",
        manifest_dir=trans,
    )


def _write_words(trans, inp, stem="demo", video="demo.mp4", provenance_video=None):
    import transcript_provenance as tp

    arts = tp.resolve_srt_timing_artifacts(
        transcripts_dir=trans, video_stem=stem, video_filename=video
    )
    arts.directory.mkdir(parents=True, exist_ok=True)
    words = tp.attach_video_provenance(dict(_WORDS), inp / (provenance_video or video))
    arts.words_path.write_text(json.dumps(words), encoding="utf-8")


def _view(client, name="demo", caption_source=None):
    q = f"?caption_source={caption_source}" if caption_source else ""
    r = client.get(f"/api/videos/{name}/srt/view{q}")
    assert r.status_code == 200
    return r.json()


# ─── caption_source ────────────────────────────────────────────────────────────
def test_default_caption_source_transcript(api):
    client, *_ = api
    assert _view(client)["caption_source"] == "transcript"


def test_caption_source_srt_se_refleja(api):
    client, *_ = api
    assert _view(client, caption_source="srt")["caption_source"] == "srt"


def test_caption_source_invalido_cae_a_transcript(api):
    client, *_ = api
    assert _view(client, caption_source="otro")["caption_source"] == "transcript"


# ─── Estados de selección/timings ──────────────────────────────────────────────
def test_sin_seleccion(api):
    client, *_ = api
    srt = _view(client)["srt"]
    assert srt["selected"] is False and srt["timings"] == "none"
    assert srt["ready_render"] is False and srt["ready_auto"] is False
    assert srt["action"] == "select_srt"


def test_asociado_sin_timings_missing(api):
    client, trans, _ = api
    _associate(trans)
    srt = _view(client)["srt"]
    assert srt["selected"] is True and srt["timings"] == "missing"
    assert srt["ready_render"] is False and srt["action"] == "transcribe"
    assert srt["source_name"] == "subs.srt"


def test_asociado_con_timings_valid_ready(api):
    client, trans, inp = api
    _associate(trans)
    _write_words(trans, inp)
    srt = _view(client)["srt"]
    assert srt["timings"] == "valid" and srt["video_available"] is True
    assert srt["ready_render"] is True and srt["ready_auto"] is True
    assert srt["action"] == "ready"


def test_timings_mismatch_retranscribe(api):
    client, trans, inp = api
    (inp / "demo.mov").write_bytes(b"mov-real")
    _associate(trans, video_filename="demo.mov")
    # words en el namespace de demo.mov pero con procedencia de demo.mp4 (otro archivo).
    _write_words(trans, inp, video="demo.mov", provenance_video="demo.mp4")
    srt = _view(client)["srt"]
    assert srt["timings"] == "mismatch" and srt["ready_render"] is False
    assert srt["action"] == "retranscribe"


def test_video_exacto_ausente_restore(api):
    client, trans, _ = api
    _associate(trans, video_filename="demo.mov")  # asociado a .mov, solo existe .mp4 (fixture)
    srt = _view(client)["srt"]
    assert srt["selected"] is True and srt["video_available"] is False
    assert srt["ready_render"] is False and srt["action"] == "restore_video"


def test_srt_administrado_corrupto(api):
    client, trans, _ = api
    _associate(trans)
    # Manipula el archivo administrado: su hash deja de coincidir -> integridad rota.
    managed_dir = trans / "studio_srt" / "demo"
    managed = next(managed_dir.glob("*.srt"))
    managed.write_bytes(b"contenido manipulado")
    srt = _view(client)["srt"]
    assert srt["timings"] == "corrupt" and srt["action"] == "replace_srt"
    assert srt["ready_render"] is False


# ─── Privacidad ────────────────────────────────────────────────────────────────
def test_view_no_expone_ruta_hash_ni_texto(api):
    client, trans, inp = api
    _associate(trans)
    _write_words(trans, inp)
    r = client.get("/api/videos/demo/srt/view")
    body = r.text
    assert str(trans) not in body and "studio_srt" not in body
    assert "Hola" not in body and "Segundo cue" not in body
    assert "0" * 64 not in body  # ningún sha256 completo
    # source_name (basename original) sí es público; nada más sensible.
    assert "managed_file" not in body and "source_sha256" not in body


def test_video_inexistente_404(api):
    client, *_ = api
    assert client.get("/api/videos/nadie/srt/view").status_code == 404
