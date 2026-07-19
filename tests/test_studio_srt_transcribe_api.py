"""test_studio_srt_transcribe_api.py — Transcripción ligada al video SRT (S36-C2A1, D38).

`POST /transcribe?caption_source=srt` transcribe el video EXACTO asociado y `run_transcribe`
graba la procedencia (`source_video`). Sin GPU/FFmpeg (core mockeado). tmp_path.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import app as studio_app
import jobs
import jobs_registry
import studio_srt


class FakeThread:
    created = []

    def __init__(self, *, target, args, kwargs=None, daemon=False):
        self.target, self.args, self.kwargs, self.daemon = target, args, kwargs or {}, daemon
        self.started = False
        self.__class__.created.append(self)

    def start(self):
        self.started = True


def _ts(ms: int) -> str:
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _srt(*cues):
    return "\n".join(f"{i}\n{_ts(s)} --> {_ts(e)}\n{t}\n" for i, s, e, t in cues).encode("utf-8")


_SRT = _srt((1, 0, 2000, "Hola mundo"), (2, 3000, 5000, "Texto"))


@pytest.fixture
def api(tmp_path, monkeypatch):
    FakeThread.created.clear()
    inp = tmp_path / "input"
    trans = tmp_path / "transcripts"
    inp.mkdir()
    trans.mkdir()
    monkeypatch.setattr(studio_app, "INPUT_DIR", inp)
    monkeypatch.setattr(studio_app, "TRANSCRIPTS", trans)
    monkeypatch.setattr(studio_app.threading, "Thread", FakeThread)
    monkeypatch.setattr(studio_app.jobs, "new_job", lambda _m: "job-tr")
    (inp / "demo.mp4").write_bytes(b"mp4")
    return TestClient(studio_app.app), inp, trans


def _associate(trans, video_filename="demo.mp4"):
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


def _thread():
    assert len(FakeThread.created) == 1
    t = FakeThread.created[0]
    assert t.target is studio_app.jobs.run_transcribe and t.started
    return t


# ─── Endpoint ────────────────────────────────────────────────────────────────
def test_default_transcript_historico(api):
    client, inp, _ = api
    r = client.post("/api/videos/demo/transcribe")
    assert r.status_code == 200 and r.json() == {"job_id": "job-tr"}
    assert _thread().args[1] == inp / "demo.mp4"  # ruta historica


def test_transcript_no_consulta_seleccion(api, monkeypatch):
    client, _, _ = api
    import studio_srt_runtime

    monkeypatch.setattr(
        studio_srt_runtime, "resolve_selected_srt", lambda *a, **k: pytest.fail("no debe resolver")
    )
    assert client.post("/api/videos/demo/transcribe").status_code == 200


def test_caption_source_invalido_400(api):
    client, _, _ = api
    assert client.post("/api/videos/demo/transcribe?caption_source=otro").status_code == 400
    assert FakeThread.created == []


def test_srt_sin_seleccion_400(api):
    client, _, _ = api
    assert client.post("/api/videos/demo/transcribe?caption_source=srt").status_code == 400
    assert FakeThread.created == []


def test_srt_video_exacto_ausente_409(api):
    client, _, trans = api
    _associate(trans, video_filename="demo.mov")  # el .mov no existe
    r = client.post("/api/videos/demo/transcribe?caption_source=srt")
    assert r.status_code == 409
    assert FakeThread.created == []


def test_srt_seleccion_mov_con_decoy_mp4_transcribe_mov(api):
    client, inp, trans = api
    (inp / "demo.mov").write_bytes(b"mov-real")
    _associate(trans, video_filename="demo.mov")
    r = client.post("/api/videos/demo/transcribe?caption_source=srt")
    assert r.status_code == 200
    assert _thread().args[1].name == "demo.mov"  # transcribe el MOV, no el decoy .mp4


def test_srt_seleccion_mp4_con_decoy_mov_transcribe_mp4(api):
    client, inp, trans = api
    (inp / "demo.mov").write_bytes(b"mov-decoy")
    _associate(trans, video_filename="demo.mp4")
    r = client.post("/api/videos/demo/transcribe?caption_source=srt")
    assert r.status_code == 200
    assert _thread().args[1].name == "demo.mp4"


def test_respuesta_no_expone_ruta(api):
    client, inp, trans = api
    (inp / "demo.mov").write_bytes(b"mov")
    _associate(trans, video_filename="demo.mov")
    r = client.post("/api/videos/demo/transcribe?caption_source=srt")
    assert r.json() == {"job_id": "job-tr"}
    assert "demo.mov" not in r.text and str(trans) not in r.text


def test_no_inicia_render_ni_auto_ni_clipper(api):
    client, inp, trans = api
    (inp / "demo.mov").write_bytes(b"mov")
    _associate(trans, video_filename="demo.mov")
    client.post("/api/videos/demo/transcribe?caption_source=srt")
    t = _thread()
    assert t.target is studio_app.jobs.run_transcribe  # ni run_render ni run_auto ni clipper


# ─── run_transcribe: escribe la procedencia ──────────────────────────────────
@pytest.fixture
def worker(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "TRANSCRIPTS", tmp_path)
    monkeypatch.setattr(jobs.core, "detect_device", lambda: ("cpu", "int8"))
    monkeypatch.setattr(jobs.core, "resolve_model", lambda _m: ("p", "label"))
    monkeypatch.setattr(
        jobs.core,
        "transcribe_video",
        lambda *_a: {"words": [{"w": "hola", "s": 0.0, "e": 0.5}], "language": "es"},
    )
    monkeypatch.setattr(jobs.core, "group_words", lambda _w: [{"id": 0, "text": "hola"}])
    return tmp_path


def _transcribe(tmp_path, name="demo", filename="demo.mov", data=b"movdata"):
    video = tmp_path / filename
    video.write_bytes(data)
    jid = jobs_registry.new_job("t")
    jobs.run_transcribe(jid, video, "es", "auto", name)
    saved = json.loads((tmp_path / f"{name}_words.json").read_text(encoding="utf-8"))
    return video, saved, jobs_registry.get_job(jid)


def test_run_transcribe_graba_procedencia(worker):
    video, saved, job = _transcribe(worker)
    sv = saved["source_video"]
    assert job["status"] == "done"
    assert sv["version"] == 1  # (1)
    assert sv["filename"] == "demo.mov"  # (2)
    assert sv["size_bytes"] == video.stat().st_size  # (3)
    assert sv["mtime_ns"] == video.stat().st_mtime_ns  # (4)
    assert saved["words"] == [{"w": "hola", "s": 0.0, "e": 0.5}]  # (5) words preservadas
    assert saved["language"] == "es"  # (6)
    assert json.loads((worker / "demo_groups.json").read_text())  # (7) groups siguen
    assert str(worker) not in json.dumps(saved)  # (8) sin rutas


def test_run_transcribe_mov_y_mp4_distinguibles(worker):
    _v1, mov, _j = _transcribe(worker, filename="demo.mov", data=b"aaaa")
    # (10) un segundo transcript de otra extension reemplaza el artefacto stem-only,
    # pero su metadata revela inequivocamente la nueva procedencia.
    _v2, mp4, _j2 = _transcribe(worker, filename="demo.mp4", data=b"bbbbbb")
    assert mov["source_video"]["filename"] == "demo.mov"
    assert mp4["source_video"]["filename"] == "demo.mp4"  # (9) distinguibles
    assert mov["source_video"]["size_bytes"] != mp4["source_video"]["size_bytes"]
