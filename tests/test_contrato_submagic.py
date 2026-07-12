"""Tests de contrato del motor Submagic nube (S-Submagic-1).

Cubren el reframe-antes-de-subir (TAREA 1) y el listado de templates reales
(TAREA 2). Ningun test toca la red: submagic._request, submagic.enviar_video,
core.get_video_info y el modulo reframe se stubean. Nunca se usa la key real.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import requests

import core
import submagic


class FakeResp:
    """Respuesta HTTP minima para stubear submagic._request."""

    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._payload = payload
        self.text = text
        self.headers = {}

    def json(self):
        if self._payload is None:
            raise ValueError("body no es JSON")
        return self._payload


# ── TAREA 1: decision de reframe (predicados puros) ───────────────────────────


def test_video_vertical_no_reencuadra():
    """Un 1080x1920 ya es 9:16: no se reencuadra."""
    assert submagic.necesita_reframe(1080, 1920) is False
    assert submagic.es_9x16(1080, 1920) is True


def test_video_horizontal_necesita_reframe():
    """Un 1920x1080 (16:9) debe reencuadrarse antes de subir."""
    assert submagic.necesita_reframe(1920, 1080) is True
    assert submagic.es_9x16(1920, 1080) is False


def test_dimensiones_desconocidas_no_reencuadran():
    """Si ffprobe no dio dimensiones (0x0), no se arriesga un reframe a ciegas."""
    assert submagic.necesita_reframe(0, 0) is False


# ── Worker Submagic: stubs comunes ────────────────────────────────────────────


def _stub_worker(monkeypatch, dims_default, dims_staged, capture):
    """Stubea red + reframe + ffprobe del worker. Devuelve nada; llena capture."""

    def fake_info(path):
        return dims_staged if "for_submagic" in str(path) else dims_default

    monkeypatch.setattr(core, "get_video_info", fake_info)

    fake_reframe = types.ModuleType("reframe")

    def fake_reframe_clip(inp, out):
        capture["reframe_in"] = inp
        capture["reframe_out"] = out
        return {"output": str(out)}

    fake_reframe.reframe_clip = fake_reframe_clip
    monkeypatch.setitem(sys.modules, "reframe", fake_reframe)

    monkeypatch.setattr(submagic, "tiene_key", lambda: True)

    def fake_enviar(path, title=None, params=None):
        capture["upload_path"] = path
        capture["title"] = title
        capture["params"] = params
        return "abcdef123456", {}

    monkeypatch.setattr(submagic, "enviar_video", fake_enviar)
    monkeypatch.setattr(
        submagic, "esperar_download_url", lambda pid, progress=None: "http://x/out.mp4"
    )
    monkeypatch.setattr(submagic, "descargar", lambda url, dest: 2048)


def test_worker_vertical_sube_original(monkeypatch):
    """Video ya vertical: se sube el original, sin ruta staged."""
    import jobs

    cap: dict = {}
    _stub_worker(monkeypatch, {"width": 1080, "height": 1920}, {"width": 1080, "height": 1920}, cap)
    mp4 = Path("input/demo.mp4")
    jid = jobs.new_job("t")
    jobs.run_submagic_render(jid, mp4, "demo")
    assert cap["upload_path"] == mp4
    job = jobs.get_job(jid)
    assert job["status"] == "done"
    assert job["result"]["reframe"]["aplicado"] is False


def test_worker_horizontal_elige_ruta_staged(monkeypatch):
    """Video horizontal: se reencuadra y se sube el archivo staged 9:16."""
    import jobs

    cap: dict = {}
    _stub_worker(monkeypatch, {"width": 1920, "height": 1080}, {"width": 1080, "height": 1920}, cap)
    mp4 = Path("input/demo.mp4")
    jid = jobs.new_job("t")
    jobs.run_submagic_render(jid, mp4, "demo")
    assert "for_submagic" in str(cap["upload_path"])
    assert cap["reframe_in"] == mp4
    job = jobs.get_job(jid)
    assert job["status"] == "done"
    assert job["result"]["reframe"]["aplicado"] is True
    assert job["result"]["reframe"]["subido"] == "1080x1920"


def test_worker_pasa_template_elegido(monkeypatch):
    """El templateName elegido llega a enviar_video via params."""
    import jobs

    cap: dict = {}
    _stub_worker(monkeypatch, {"width": 1080, "height": 1920}, {"width": 1080, "height": 1920}, cap)
    jid = jobs.new_job("t")
    jobs.run_submagic_render(jid, Path("input/demo.mp4"), "demo", template_name="Karaoke Pro")
    assert cap["params"] == {"templateName": "Karaoke Pro"}
    assert cap["title"] == "demo"


def test_worker_no_usa_motor_local_captions(monkeypatch):
    """El worker Submagic no pasa por core_ass: build_ass/burn_video jamas se llaman."""
    import jobs

    cap: dict = {}
    _stub_worker(monkeypatch, {"width": 1080, "height": 1920}, {"width": 1080, "height": 1920}, cap)

    def _boom(*a, **k):
        raise AssertionError("el worker Submagic no debe tocar el motor local de captions")

    monkeypatch.setattr(core, "build_ass", _boom, raising=False)
    monkeypatch.setattr(core, "burn_video", _boom, raising=False)
    jid = jobs.new_job("t")
    jobs.run_submagic_render(jid, Path("input/demo.mp4"), "demo")
    assert jobs.get_job(jid)["status"] == "done"


# ── TAREA 2: listar templates ─────────────────────────────────────────────────


def test_templates_respuesta_lista(monkeypatch):
    """Respuesta como lista directa: se extraen strings y dicts."""
    monkeypatch.setattr(submagic, "_templates_cache", None)
    payload = ["Hormozi 2", "Karaoke", {"name": "Beast"}]
    monkeypatch.setattr(submagic, "_request", lambda m, p, **k: FakeResp(200, payload))
    assert submagic.listar_templates() == ["Hormozi 2", "Karaoke", "Beast"]


def test_templates_respuesta_envuelta(monkeypatch):
    """Respuesta envuelta en data/templates/items: tambien se soporta."""
    monkeypatch.setattr(submagic, "_templates_cache", None)
    payload = {"templates": [{"name": "A"}, {"templateName": "B"}]}
    monkeypatch.setattr(submagic, "_request", lambda m, p, **k: FakeResp(200, payload))
    assert submagic.listar_templates() == ["A", "B"]


def test_templates_fallback_hormozi(monkeypatch):
    """API caida o respuesta no-ok: fallback unico a Hormozi 2, sin cachear."""
    monkeypatch.setattr(submagic, "_templates_cache", None)

    def _falla(m, p, **k):
        raise requests.RequestException("sin red")

    monkeypatch.setattr(submagic, "_request", _falla)
    assert submagic.listar_templates() == ["Hormozi 2"]
    # No cacheado: un HTTP 500 tampoco cachea.
    monkeypatch.setattr(submagic, "_request", lambda m, p, **k: FakeResp(500))
    assert submagic.listar_templates() == ["Hormozi 2"]
