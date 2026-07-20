"""Tests backend de los controles CVE minimos en Studio (F6 esencial, PASO F).

- resolve_preset acepta overrides position/avoid_faces (fail-safe por campo).
- studio_keywords: saneado estricto + IO atomico del sidecar {stem}_keywords.json.
- Endpoint /render acepta densidad/position/avoid_faces (invalidos -> 400) y los pasa
  al worker; endpoints GET/POST /keywords guardan/leen el sidecar saneado.
- Privacidad: el sidecar y las respuestas no exponen rutas.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import app as studio_app
import cve
import studio_keywords


class FakeThread:
    created = []

    def __init__(self, *, target, args, kwargs=None, daemon=False):
        self.target, self.args, self.kwargs, self.daemon = target, args, kwargs or {}, daemon
        self.started = False
        self.__class__.created.append(self)

    def start(self):
        self.started = True


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
    monkeypatch.setattr(studio_app.jobs, "new_job", lambda _msg: "job-f6")
    (inp / "demo.mp4").write_bytes(b"mp4")
    (trans / "demo_groups.json").write_text(json.dumps(_GROUPS), encoding="utf-8")
    return TestClient(studio_app.app), trans


# ── resolve_preset overrides ──────────────────────────────────────────────────


def test_resolve_preset_position_override():
    plan = cve.resolve_preset("clean_podcast", position="center")
    assert plan.position == "center"


def test_resolve_preset_avoid_faces_override():
    plan = cve.resolve_preset("clean_podcast", avoid_faces=False)
    assert plan.avoid_faces is False


def test_resolve_preset_position_invalida_cae_a_default():
    plan = cve.resolve_preset("clean_podcast", position="diagonal")
    assert plan.position == "bottom"  # default del preset


# ── studio_keywords: saneado ──────────────────────────────────────────────────


def test_sanitize_frase_multi_palabra():
    out = studio_keywords.sanitize_entries({"keywords": [{"frase": "sin costo"}]})
    assert out == [{"frase": "sin costo"}]


def test_sanitize_una_palabra_es_palabra():
    assert studio_keywords.sanitize_entries([{"frase": "gratis"}]) == [{"palabra": "gratis"}]


def test_sanitize_intensidad_big():
    out = studio_keywords.sanitize_entries([{"frase": "muy importante", "intensidad": "big"}])
    assert out == [{"frase": "muy importante", "intensidad": "big"}]


def test_sanitize_quita_corchetes_y_espacios():
    out = studio_keywords.sanitize_entries([{"frase": "  [center]la   clave]  "}])
    assert out == [{"frase": "center la clave"}]  # sin corchetes, espacios colapsados


def test_sanitize_descarta_malformadas():
    data = [{"palabra": ""}, {"no": "dict"}, 42, {"frase": "  "}, {"palabra": "ok"}]
    assert studio_keywords.sanitize_entries(data) == [{"palabra": "ok"}]


def test_sanitize_cota_dura():
    muchas = [{"palabra": f"w{i}"} for i in range(500)]
    assert len(studio_keywords.sanitize_entries(muchas)) == 200


def test_write_read_roundtrip(tmp_path):
    p = tmp_path / "demo_keywords.json"
    studio_keywords.write_entries(p, [{"frase": "sin costo"}])
    assert studio_keywords.read_entries(p) == [{"frase": "sin costo"}]


def test_write_vacio_borra_sidecar(tmp_path):
    p = tmp_path / "demo_keywords.json"
    p.write_text('{"keywords": [{"palabra": "x"}]}', encoding="utf-8")
    studio_keywords.write_entries(p, [])
    assert not p.exists()


# ── Endpoints ─────────────────────────────────────────────────────────────────


def test_render_acepta_controles_cve(api):
    client, _ = api
    r = client.post(
        "/api/videos/demo/render",
        params={
            "preset": "keyword_punch",
            "densidad": "alta",
            "position": "center",
            "avoid_faces": "false",
        },
    )
    assert r.status_code == 200
    t = FakeThread.created[0]
    assert t.kwargs["densidad"] == "alta"
    assert t.kwargs["position"] == "center"
    assert t.kwargs["avoid_faces"] is False


def test_render_position_invalida_400(api):
    client, _ = api
    r = client.post("/api/videos/demo/render", params={"position": "diagonal"})
    assert r.status_code == 400


def test_render_densidad_invalida_400(api):
    client, _ = api
    r = client.post("/api/videos/demo/render", params={"densidad": "extrema"})
    assert r.status_code == 400


def test_keywords_post_get_roundtrip(api):
    client, trans = api
    r = client.post(
        "/api/videos/demo/keywords",
        json={"keywords": [{"frase": "sin costo"}, {"palabra": "gratis", "intensidad": "big"}]},
    )
    assert r.status_code == 200 and r.json() == {"guardadas": 2}
    got = client.get("/api/videos/demo/keywords").json()
    assert got == {"keywords": [{"frase": "sin costo"}, {"palabra": "gratis", "intensidad": "big"}]}
    # el sidecar existe en transcripts y no expone rutas por la API
    assert (trans / "demo_keywords.json").exists()


def test_keywords_nombre_invalido_400(api):
    client, _ = api
    assert client.get("/api/videos/..%2Fetc/keywords").status_code in (400, 404)


def test_keywords_get_vacio_sin_sidecar(api):
    client, _ = api
    assert client.get("/api/videos/demo/keywords").json() == {"keywords": []}


def test_render_srt_no_regresa_por_controles(api, monkeypatch):
    # Sanity: los nuevos params no rompen la validacion previa (caption_source invalido -> 400)
    client, _ = api
    r = client.post("/api/videos/demo/render", params={"caption_source": "otro"})
    assert r.status_code == 400
