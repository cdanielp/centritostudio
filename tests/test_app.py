"""Endpoint HTTP del Modo Automatico Studio (S37-C), sin ejecutar renders."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as studio_app


class FakeThread:
    created = []

    def __init__(self, *, target, args, kwargs=None, daemon=False):
        self.target, self.args, self.kwargs, self.daemon = target, args, kwargs or {}, daemon
        self.started = False
        self.__class__.created.append(self)

    def start(self):
        self.started = True


@pytest.fixture
def api(tmp_path, monkeypatch):
    FakeThread.created.clear()
    monkeypatch.setattr(studio_app, "INPUT_DIR", tmp_path)
    monkeypatch.setattr(studio_app.threading, "Thread", FakeThread)
    monkeypatch.setattr(studio_app.jobs, "new_job", lambda _msg: "job-s37c")
    (tmp_path / "demo.mp4").write_bytes(b"mp4")
    return TestClient(studio_app.app), tmp_path


def _thread():
    assert len(FakeThread.created) == 1
    thread = FakeThread.created[0]
    assert thread.target is studio_app.jobs.run_auto and thread.started and thread.daemon
    return thread


def test_capabilities_endpoint(api):
    client, _ = api
    data = client.get("/api/auto/capabilities").json()
    assert data["default_mode"] == "classic" and data["v2_defaults"]["verify_av"] is True


@pytest.mark.parametrize("query", ["", "?mode=classic"])
def test_classic_historico_y_explicito_pasan_config_none(api, query):
    client, _ = api
    response = client.post("/api/videos/demo/auto" + query)
    assert response.status_code == 200 and response.json() == {"job_id": "job-s37c"}
    assert _thread().kwargs == {"config": None}


@pytest.mark.parametrize(
    ("query", "broll", "fx", "preset"),
    [
        ("?mode=v2", True, True, "express"),
        ("?mode=v2&broll_enabled=false", False, True, "express"),
        ("?mode=v2&fx_enabled=false", True, False, "express"),
        ("?mode=v2&fx_preset=pro", True, True, "pro"),
        ("?mode=v2&fx_preset=premium", True, True, "premium"),
    ],
)
def test_v2_construye_config_correcta(api, query, broll, fx, preset):
    client, _ = api
    assert client.post("/api/videos/demo/auto" + query).status_code == 200
    config = _thread().kwargs["config"]
    assert (config.mode, config.broll_enabled, config.fx_enabled, config.fx_preset) == (
        "v2",
        broll,
        fx,
        preset,
    )
    assert config.verify_av is True and config.manual_sidecars is True


@pytest.mark.parametrize("query", ["?mode=otro", "?mode=v2&fx_preset=otro", "?objetivo=otro"])
def test_contrato_invalido_es_400(api, query):
    client, _ = api
    assert client.post("/api/videos/demo/auto" + query).status_code == 400
    assert FakeThread.created == []


def test_video_inexistente_404(api):
    client, _ = api
    assert client.post("/api/videos/no-existe/auto?mode=v2").status_code == 404


@pytest.mark.parametrize("name", ["../fuera", "..\\fuera", "C:\\fuera", "/tmp/fuera"])
def test_resolver_video_rechaza_traversal_multiplataforma(api, name):
    _, root = api
    outside = root.parent / "fuera.mp4"
    outside.write_bytes(b"privado")
    assert studio_app._resolver_video_input(name) is None


def test_mov_soportado(api):
    client, root = api
    (root / "movil.mov").write_bytes(b"mov")
    assert client.post("/api/videos/movil/auto?mode=v2").status_code == 200
    assert Path(_thread().args[1]).suffix == ".mov"


def test_endpoint_no_acepta_fingerprint_del_cliente(api):
    client, _ = api
    client.post("/api/videos/demo/auto?mode=v2&fingerprint=controlado-por-cliente")
    config = _thread().kwargs["config"]
    assert config.fingerprint() != "controlado-por-cliente"


def test_error_inesperado_se_sanea(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(
        studio_app.jobs, "new_job", lambda _msg: (_ for _ in ()).throw(RuntimeError("KEY-SECRETA"))
    )
    response = client.post("/api/videos/demo/auto?mode=v2")
    assert response.status_code == 500
    assert response.json()["detail"] == "No se pudo iniciar el Modo Automatico"
    assert "KEY-SECRETA" not in response.text
