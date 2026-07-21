"""H1 · P0-1 — Guard de path traversal en todos los endpoints {name}/{stem}.

Cada endpoint que interpola un identificador de usuario en una ruta debe rechazarlo con
404 saneado ANTES de construir cualquier Path, sin escribir/leer fuera del sandbox y sin
lanzar jobs. Todo con TemporaryDirectory (tmp_path) y fixtures sinteticos; sin FFmpeg/GPU.
"""

from __future__ import annotations

import urllib.parse

import pytest
from fastapi.testclient import TestClient

import app as studio_app
import path_safety

# Matriz de nombres inseguros: Windows/POSIX/absolutos/UNC/dot-segments/control/trailing.
NOMBRES_INSEGUROS = [
    "..\\..\\escape",
    "../../escape",
    "/escape",
    "C:\\escape",
    "\\\\srv\\share\\escape",
    ".",
    "..",
    "escape\x00",
    "escape\x1f",
    "escape.",  # Windows recorta el punto final
    "escape ",  # Windows recorta el espacio final
]


class FakeThread:
    created: list = []

    def __init__(self, *, target, args, kwargs=None, daemon=False):
        self.target, self.args, self.kwargs, self.daemon = target, args, kwargs or {}, daemon
        self.__class__.created.append(self)

    def start(self):
        self.started = True


@pytest.fixture
def api(tmp_path, monkeypatch):
    """App con TODOS los dirs redirigidos a tmp_path y jobs/threads neutralizados."""
    FakeThread.created.clear()
    inp = tmp_path / "input"
    trans = tmp_path / "transcripts"
    clips = tmp_path / "output" / "clips"
    for d in (inp, trans, clips):
        d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(studio_app, "ROOT", tmp_path)
    monkeypatch.setattr(studio_app, "INPUT_DIR", inp)
    monkeypatch.setattr(studio_app, "TRANSCRIPTS", trans)
    monkeypatch.setattr(studio_app, "CLIPS_DIR", clips)
    monkeypatch.setattr(studio_app.threading, "Thread", FakeThread)
    monkeypatch.setattr(studio_app.jobs, "new_job", lambda _m: "job-h1")
    return TestClient(studio_app.app, raise_server_exceptions=True), tmp_path


def _do(fn):
    """Ejecuta la request tolerando un rechazo del transporte (URL invalida = seguro)."""
    try:
        return fn()
    except Exception:  # noqa: BLE001 - httpx rechaza la URL: no llega al server -> seguro
        return None


# Endpoints (metodo, plantilla de url, body) que reciben un identificador en la ruta.
ENDPOINTS = [
    ("get", "/api/videos/{n}/transcript", None),
    ("put", "/api/videos/{n}/transcript", []),
    ("post", "/api/videos/{n}/transcribe", None),
    ("post", "/api/videos/{n}/analyze", None),
    ("get", "/api/videos/{n}/brain", None),
    ("put", "/api/videos/{n}/brain", []),
    ("post", "/api/videos/{n}/depurar", None),
    ("post", "/api/videos/{n}/clips", None),
    ("get", "/api/videos/{n}/clips", None),
    ("get", "/api/videos/{n}/source", None),
    ("get", "/api/videos/{n}/keywords", None),
    ("post", "/api/videos/{n}/keywords", {}),
    ("post", "/api/videos/{n}/render", None),
    ("post", "/api/videos/{n}/auto", None),
    ("post", "/api/videos/{n}/submagic", None),
    ("post", "/api/clips/{n}/detectar", None),
    ("post", "/api/clips/{n}/turnos", {}),
    ("post", "/api/clips/{n}/reframe", None),
]


@pytest.mark.parametrize(("method", "tpl", "body"), ENDPOINTS)
@pytest.mark.parametrize("name", NOMBRES_INSEGUROS)
def test_endpoint_rechaza_traversal(api, method, tpl, body, name):
    client, tmp_path = api
    # Centinela fuera del sandbox: un traversal exitoso lo crearia/pisaria.
    centinela = tmp_path.parent / "H1_CENTINELA_no_debe_existir"
    if centinela.exists():
        centinela.unlink()
    url = tpl.format(n=urllib.parse.quote(name, safe=""))
    kwargs = {"json": body} if body is not None else {}
    resp = _do(lambda: getattr(client, method)(url, **kwargs))

    # (1) Si llega al server, la respuesta es un rechazo saneado (nunca 2xx, nunca 5xx).
    if resp is not None:
        assert resp.status_code in (400, 404, 422), (url, resp.status_code)
        assert name not in resp.text  # no refleja la cadena peligrosa
    # (2) Nunca se lanza un job con un nombre inseguro.
    assert FakeThread.created == []
    # (3) Ningun archivo escapo el sandbox.
    assert not centinela.exists()
    for hijo in tmp_path.parent.iterdir():
        assert "escape" not in hijo.name.lower()


@pytest.mark.parametrize("name", NOMBRES_INSEGUROS)
def test_validador_rechaza_matriz(name):
    assert path_safety.is_safe_basename(name) is False


@pytest.mark.parametrize("name", ["demo", "video con espacios", "acentuadó-áéí_1", "clip_9x16"])
def test_validador_acepta_nombres_legitimos(name):
    assert path_safety.is_safe_basename(name) is True


def test_write_traversal_no_escribe_fuera(api, tmp_path):
    """PUT /transcript con traversal Windows NO escribe el {name}_groups.json fuera del sandbox."""
    client, _ = api
    outside = tmp_path.parent / "H1_TRAVERSAL_groups.json"
    if outside.exists():
        outside.unlink()
    name = "..\\..\\H1_TRAVERSAL"
    q = urllib.parse.quote(name, safe="")
    resp = _do(lambda: client.put(f"/api/videos/{q}/transcript", json=[{"id": 0, "text": "x"}]))
    if resp is not None:
        assert resp.status_code == 404
    assert not outside.exists()
    assert not (tmp_path.parent / "H1_TRAVERSAL_groups.json").exists()
