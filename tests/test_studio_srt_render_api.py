"""test_studio_srt_render_api.py — Endpoint de render con caption_source (S36-C2A1, D38).

Sin ejecutar renders (FakeThread espia el worker). Verifica que transcript sigue siendo el
default historico y NO consulta la seleccion SRT; que SRT es opt-in con asociacion explicita;
que las combinaciones incompatibles dan 400; y que el worker recibe el objeto interno de
seleccion (no una ruta del cliente). Nada de Auto, clipper ni UI.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import app as studio_app
import studio_srt
import studio_srt_runtime


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


def _srt(*cues: tuple[int, int, int, str]) -> bytes:
    return "\n".join(f"{i}\n{_ts(s)} --> {_ts(e)}\n{t}\n" for i, s, e, t in cues).encode("utf-8")


_SRT_MIX = _srt((1, 0, 2000, "Hola mundo"), (2, 3000, 5000, "Texto sin audio"))
_WORDS = {"words": [{"w": "hola", "s": 0.0, "e": 0.5, "prob": 1.0}], "language": "es"}
_GROUPS = [
    {
        "id": 0,
        "start": 0,
        "end": 1,
        "text": "hola",
        "words": [{"text": "hola", "start": 0, "end": 1, "line_idx": 0}],
    }
]


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
    monkeypatch.setattr(studio_app.jobs, "new_job", lambda _msg: "job-c2a1")
    (inp / "demo.mp4").write_bytes(b"mp4")
    (trans / "demo_groups.json").write_text(json.dumps(_GROUPS), encoding="utf-8")
    return TestClient(studio_app.app), trans


def _associate(trans, stem="demo", data=_SRT_MIX, dur=6000, video_filename=None):
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


def _write_words(trans, stem="demo", video="demo.mp4"):
    # Escribe en el namespace PRIVADO por filename (como run_transcribe SRT), con procedencia.
    import transcript_provenance as tp

    arts = tp.resolve_srt_timing_artifacts(
        transcripts_dir=trans, video_stem=stem, video_filename=video
    )
    arts.directory.mkdir(parents=True, exist_ok=True)
    words = tp.attach_video_provenance(dict(_WORDS), studio_app.INPUT_DIR / video)
    arts.words_path.write_text(json.dumps(words), encoding="utf-8")
    arts.groups_path.write_text(json.dumps([]), encoding="utf-8")


def _thread():
    assert len(FakeThread.created) == 1
    t = FakeThread.created[0]
    assert t.target is studio_app.jobs.run_render and t.started and t.daemon
    return t


# ─── Ruta transcript (default historico) ───────────────────────────────────────
def test_default_es_transcript(api):
    client, _ = api
    r = client.post("/api/videos/demo/render")
    assert r.status_code == 200 and r.json() == {"job_id": "job-c2a1"}
    t = _thread()
    # firma historica: args posicionales + kwargs sin srt_selection
    assert t.args == (
        "job-c2a1",
        studio_app.INPUT_DIR / "demo.mp4",
        studio_app.TRANSCRIPTS / "demo_groups.json",
        "demo",
        "hormozi",
        None,
        False,
        False,
        None,
    )
    assert "srt_selection" not in t.kwargs
    # F6 (PASO F): controles CVE aditivos; siguen sin srt_selection.
    assert set(t.kwargs) == {
        "preset",
        "intensidad",
        "densidad",
        "position",
        "avoid_faces",
        "qa_mode",
        "qa_guion",
    }


def test_transcript_no_consulta_seleccion_srt(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(
        studio_srt_runtime,
        "resolve_selected_srt",
        lambda *_a, **_k: pytest.fail("transcript NO debe resolver SRT"),
    )
    assert client.post("/api/videos/demo/render?caption_source=transcript").status_code == 200


def test_transcript_explicito_igual_al_default(api):
    client, _ = api
    r = client.post("/api/videos/demo/render?caption_source=transcript&style=karaoke")
    assert r.status_code == 200
    assert _thread().args[4] == "karaoke"


# ─── Validaciones de contrato ──────────────────────────────────────────────────
def test_caption_source_invalido_400(api):
    client, _ = api
    assert client.post("/api/videos/demo/render?caption_source=otro").status_code == 400
    assert FakeThread.created == []


def test_srt_sin_asociacion_400(api):
    client, _ = api
    r = client.post("/api/videos/demo/render?caption_source=srt")
    assert r.status_code == 400
    assert "seleccionado" in r.json()["detail"]
    assert FakeThread.created == []


def test_srt_sin_words_400(api):
    client, trans = api
    _associate(trans)
    r = client.post("/api/videos/demo/render?caption_source=srt")
    assert r.status_code == 400
    assert "Transcribe" in r.json()["detail"]
    assert FakeThread.created == []


@pytest.mark.parametrize(
    "query",
    [
        "caption_source=srt&caption_qa=alertas",
        "caption_source=srt&words_per_group=3",
        "caption_source=srt&use_emphasis=true",
    ],
)
def test_srt_combinaciones_incompatibles_400(api, query):
    client, trans = api
    _associate(trans)
    _write_words(trans)
    r = client.post(f"/api/videos/demo/render?{query}")
    assert r.status_code == 400
    assert FakeThread.created == []


# ─── Ruta SRT feliz ────────────────────────────────────────────────────────────
def test_srt_style_valido_arranca_job(api):
    client, trans = api
    _associate(trans)
    _write_words(trans)
    r = client.post("/api/videos/demo/render?caption_source=srt&style=hormozi")
    assert r.status_code == 200 and r.json() == {"job_id": "job-c2a1"}
    t = _thread()
    assert t.kwargs["srt_selection"] is not None
    assert isinstance(t.kwargs["srt_selection"], studio_srt_runtime.SelectedSrtRuntime)


def test_srt_preset_valido_arranca_job(api):
    client, trans = api
    _associate(trans)
    _write_words(trans)
    r = client.post("/api/videos/demo/render?caption_source=srt&preset=viral_bounce")
    assert r.status_code == 200
    assert _thread().kwargs["preset"] == "viral_bounce"


def test_srt_emojis_arranca_job(api):
    client, trans = api
    _associate(trans)
    _write_words(trans)
    r = client.post("/api/videos/demo/render?caption_source=srt&use_emojis=true")
    assert r.status_code == 200
    assert _thread().kwargs["use_emojis"] is True


def test_worker_recibe_objeto_interno_no_ruta(api):
    client, trans = api
    _associate(trans)
    _write_words(trans)
    client.post("/api/videos/demo/render?caption_source=srt")
    sel = _thread().kwargs["srt_selection"]
    assert not isinstance(sel, (str, bytes))  # nunca una ruta enviada por el cliente
    assert sel.source_sha256  # objeto de dominio verificado


def test_respuesta_srt_no_expone_ruta_ni_texto(api):
    client, trans = api
    _associate(trans)
    _write_words(trans)
    r = client.post("/api/videos/demo/render?caption_source=srt")
    body = r.text
    assert r.json() == {"job_id": "job-c2a1"}
    assert "studio_srt" not in body and "Hola" not in body and str(trans) not in body


def test_srt_no_arranca_job_si_validacion_falla(api):
    client, trans = api
    # sin asociacion -> 400 y ningun thread/worker
    client.post("/api/videos/demo/render?caption_source=srt")
    assert FakeThread.created == []


# ─── Identidad video↔SRT (P2): filename exacto del manifiesto ──────────────────
def test_seleccion_mov_con_decoy_mp4_usa_mov(api):
    # El SRT se asocio a demo.mov; luego aparece demo.mp4 (decoy, mismo stem). El render
    # DEBE usar demo.mov (el filename registrado), no el .mp4 que prioriza el resolver generico.
    client, trans = api
    (studio_app.INPUT_DIR / "demo.mov").write_bytes(b"mov-real")  # el .mp4 ya lo crea el fixture
    _associate(trans, video_filename="demo.mov")
    _write_words(trans, video="demo.mov")  # timings del video asociado
    r = client.post("/api/videos/demo/render?caption_source=srt")
    assert r.status_code == 200
    video = _thread().args[1]
    assert video.name == "demo.mov"  # NUNCA demo.mp4


def test_seleccion_mp4_con_decoy_mov_usa_mp4(api):
    client, trans = api
    (studio_app.INPUT_DIR / "demo.mov").write_bytes(b"mov-decoy")
    _associate(trans, video_filename="demo.mp4")  # el .mp4 lo crea el fixture
    _write_words(trans)
    r = client.post("/api/videos/demo/render?caption_source=srt")
    assert r.status_code == 200
    assert _thread().args[1].name == "demo.mp4"


def test_video_exacto_ausente_409(api):
    # Asociado a demo.mov, pero el .mov no existe (solo el decoy .mp4 del fixture) -> 409, sin job.
    client, trans = api
    _associate(trans, video_filename="demo.mov")
    _write_words(trans)
    r = client.post("/api/videos/demo/render?caption_source=srt")
    assert r.status_code == 409
    assert FakeThread.created == []


def test_409_no_expone_filename_ni_ruta(api):
    client, trans = api
    _associate(trans, video_filename="demo.mov")
    _write_words(trans)
    r = client.post("/api/videos/demo/render?caption_source=srt")
    body = r.text
    assert "demo.mov" not in body and "demo.mp4" not in body
    assert "input" not in body and str(trans) not in body


def test_srt_no_usa_resolver_generico(api, monkeypatch):
    # La ruta SRT NO debe usar _resolver_video_input (que prioriza .mp4 por stem).
    client, trans = api
    (studio_app.INPUT_DIR / "demo.mov").write_bytes(b"mov-real")
    _associate(trans, video_filename="demo.mov")
    _write_words(trans, video="demo.mov")
    monkeypatch.setattr(
        studio_app,
        "_resolver_video_input",
        lambda *_a, **_k: pytest.fail("SRT NO usa el resolver generico"),
    )
    assert client.post("/api/videos/demo/render?caption_source=srt").status_code == 200


def test_srt_words_de_otro_video_mismo_stem_409(api):
    # ROJO P2: SRT asociado a demo.mov, pero demo_words.json trae timings de demo.mp4
    # (mismo stem). Hoy el render arranca con timings cruzados; DEBE rechazar con 409.
    client, trans = api
    (studio_app.INPUT_DIR / "demo.mov").write_bytes(b"mov-real")
    mp4 = studio_app.INPUT_DIR / "demo.mp4"  # el fixture ya lo creo
    _associate(trans, video_filename="demo.mov")
    import transcript_provenance as tp

    words = tp.attach_video_provenance(dict(_WORDS), mp4)  # procedencia = demo.mp4
    (trans / "demo_words.json").write_text(json.dumps(words), encoding="utf-8")
    r = client.post("/api/videos/demo/render?caption_source=srt")
    assert r.status_code == 409
    assert FakeThread.created == []


def test_srt_words_legacy_sin_procedencia_409(api):
    # ROJO P2: words historicas sin source_video no sirven para render SRT -> 409.
    client, trans = api
    (studio_app.INPUT_DIR / "demo.mov").write_bytes(b"mov-real")
    _associate(trans, video_filename="demo.mov")
    (trans / "demo_words.json").write_text(json.dumps(_WORDS), encoding="utf-8")  # legacy
    r = client.post("/api/videos/demo/render?caption_source=srt")
    assert r.status_code == 409
    assert FakeThread.created == []


def _private_arts(trans, stem="demo", video="demo.mp4"):
    import transcript_provenance as tp

    arts = tp.resolve_srt_timing_artifacts(
        transcripts_dir=trans, video_stem=stem, video_filename=video
    )
    arts.directory.mkdir(parents=True, exist_ok=True)
    return arts


def test_srt_words_de_mov_en_namespace_mp4_409(api):
    # words con procedencia demo.mov colocadas en el namespace de demo.mp4 -> 409 por identidad.
    client, trans = api
    (studio_app.INPUT_DIR / "demo.mov").write_bytes(b"mov")
    _associate(trans, video_filename="demo.mp4")
    import transcript_provenance as tp

    arts = _private_arts(trans, video="demo.mp4")
    w = tp.attach_video_provenance(
        dict(_WORDS), studio_app.INPUT_DIR / "demo.mov"
    )  # procedencia MOV
    arts.words_path.write_text(json.dumps(w), encoding="utf-8")
    assert client.post("/api/videos/demo/render?caption_source=srt").status_code == 409
    assert FakeThread.created == []


@pytest.mark.parametrize(
    "mut",
    [
        lambda sv: sv.update(size_bytes=sv["size_bytes"] + 1),  # tamaño distinto
        lambda sv: sv.update(mtime_ns=sv["mtime_ns"] + 1),  # mtime distinto
        lambda sv: sv.update(version=99),  # version invalida
        lambda sv: sv.pop("filename"),  # metadata corrupta
    ],
)
def test_srt_procedencia_manipulada_409(api, mut):
    client, trans = api
    _associate(trans)  # selección demo.mp4 (video del fixture)
    import transcript_provenance as tp

    arts = _private_arts(trans, video="demo.mp4")
    w = tp.attach_video_provenance(dict(_WORDS), studio_app.INPUT_DIR / "demo.mp4")
    mut(w["source_video"])
    arts.words_path.write_text(json.dumps(w), encoding="utf-8")
    assert client.post("/api/videos/demo/render?caption_source=srt").status_code == 409
    assert FakeThread.created == []


def test_srt_words_corruptas_409(api):
    client, trans = api
    _associate(trans)
    _private_arts(trans, video="demo.mp4").words_path.write_text("{no es json", encoding="utf-8")
    assert client.post("/api/videos/demo/render?caption_source=srt").status_code == 409
    assert FakeThread.created == []


def test_transcript_no_usa_resolve_selected_video(api, monkeypatch):
    client, _ = api
    import studio_srt_runtime

    monkeypatch.setattr(
        studio_srt_runtime,
        "resolve_selected_video",
        lambda *_a, **_k: pytest.fail("transcript NO resuelve video SRT"),
    )
    assert client.post("/api/videos/demo/render").status_code == 200
