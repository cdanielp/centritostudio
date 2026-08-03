"""Contrato HTTP de offset y alineado parcial en la ruta SRT (S38).

El offset se PROPONE, nunca se auto-aplica: el endpoint solo lo mueve si el llamador manda
`srt_offset_ms` explicito. Pedir estos parametros sin `caption_source=srt` es un error, no
algo que se ignore en silencio: quien manda un offset espera que se aplique.

Reutiliza los helpers de `test_studio_srt_render_api` (mismo sandbox, mismo FakeThread). La
fixture `api` se declara aqui en vez de importarse: importar una fixture y luego recibirla
como parametro la marca como redefinida (F811), y silenciarlo en cada test seria peor.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from test_studio_srt_render_api import (
    _GROUPS,
    FakeThread,
    _associate,
    _thread,
    _write_words,
)

import app as studio_app


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
    monkeypatch.setattr(studio_app.jobs, "new_job", lambda _msg: "job-s38")
    (inp / "demo.mp4").write_bytes(b"mp4")
    (trans / "demo_groups.json").write_text(json.dumps(_GROUPS), encoding="utf-8")
    return TestClient(studio_app.app), trans


def _srt_ready(trans):
    _associate(trans)
    _write_words(trans)


# ── Defaults: byte-identico a la ruta historica ──────────────────────────────


def test_srt_sin_parametros_no_desplaza_ni_interpola(api):
    client, trans = api
    _srt_ready(trans)
    r = client.post("/api/videos/demo/render?caption_source=srt")
    assert r.status_code == 200
    kw = _thread().kwargs
    assert kw["srt_offset_ms"] == 0
    assert kw["srt_modo_parcial"] is False
    assert kw["srt_min_coverage"] is None


def test_parametros_explicitos_llegan_al_worker(api):
    client, trans = api
    _srt_ready(trans)
    r = client.post(
        "/api/videos/demo/render"
        "?caption_source=srt&srt_offset_ms=5280&srt_alineado_parcial=true&srt_min_coverage=0.5"
    )
    assert r.status_code == 200
    kw = _thread().kwargs
    assert kw["srt_offset_ms"] == 5280
    assert kw["srt_modo_parcial"] is True
    assert kw["srt_min_coverage"] == 0.5


def test_offset_negativo_se_acepta(api):
    client, trans = api
    _srt_ready(trans)
    r = client.post("/api/videos/demo/render?caption_source=srt&srt_offset_ms=-1500")
    assert r.status_code == 200
    assert _thread().kwargs["srt_offset_ms"] == -1500


# ── Rechazos explicitos ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "qs",
    [
        "srt_offset_ms=5000",
        "srt_alineado_parcial=true",
        "srt_min_coverage=0.5",
    ],
)
def test_parametros_srt_con_transcript_son_400(api, qs):
    """No se ignoran en silencio: un offset pedido y no aplicado es un render mudo y mal."""
    client, _ = api
    r = client.post(f"/api/videos/demo/render?{qs}")
    assert r.status_code == 400
    assert "caption_source=srt" in r.json()["detail"]
    assert not FakeThread.created, "no se crea job si los parametros son incoherentes"


@pytest.mark.parametrize("offset", [3600001, -3600001, 99999999])
def test_offset_fuera_de_rango_es_400(api, offset):
    client, trans = api
    _srt_ready(trans)
    r = client.post(f"/api/videos/demo/render?caption_source=srt&srt_offset_ms={offset}")
    assert r.status_code == 400
    assert "fuera de rango" in r.json()["detail"]


@pytest.mark.parametrize("mc", [-0.1, 1.1, 2.0])
def test_min_coverage_fuera_de_rango_es_400(api, mc):
    client, trans = api
    _srt_ready(trans)
    r = client.post(f"/api/videos/demo/render?caption_source=srt&srt_min_coverage={mc}")
    assert r.status_code == 400
    assert "entre 0.0 y 1.0" in r.json()["detail"]


def test_offset_en_el_limite_se_acepta(api):
    client, trans = api
    _srt_ready(trans)
    r = client.post("/api/videos/demo/render?caption_source=srt&srt_offset_ms=3600000")
    assert r.status_code == 200
