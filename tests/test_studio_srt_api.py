"""test_studio_srt_api.py — Contrato HTTP del router SRT de Studio (S36-C1, D37).

Sin red, sin GPU, sin FFmpeg: la duracion del video se lee de un info.json cacheado en
tmp_path, nunca de ffprobe. Verifica status HTTP, privacidad de la respuesta, que el
almacenamiento no se sirve por ningun mount y que ninguna operacion toca render/Auto/Whisper.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

import app as studio_app
import studio_srt
import studio_srt_routes


def _ts(ms: int) -> str:
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _srt(*cues: tuple[int, int, int, str]) -> bytes:
    blocks = [f"{i}\n{_ts(s)} --> {_ts(e)}\n{t}\n" for i, s, e, t in cues]
    return "\n".join(blocks).encode("utf-8")


_OK = _srt((1, 0, 1000, "uno"), (2, 1000, 2000, "dos"))


@pytest.fixture
def api(tmp_path, monkeypatch):
    inp = tmp_path / "input"
    trans = tmp_path / "transcripts"
    storage = trans / "studio_srt"
    inp.mkdir()
    trans.mkdir()
    # Router SRT
    monkeypatch.setattr(studio_srt_routes, "INPUT_DIR", inp)
    monkeypatch.setattr(studio_srt_routes, "TRANSCRIPTS", trans)
    monkeypatch.setattr(studio_srt_routes, "STUDIO_SRT_DIR", storage)
    # App historico (para que /api/videos no toque input/ real)
    monkeypatch.setattr(studio_app, "INPUT_DIR", inp)
    monkeypatch.setattr(studio_app, "TRANSCRIPTS", trans)
    # Prueba de que NO se llama a ffprobe/Whisper: si core corre, el test falla.
    monkeypatch.setattr(
        studio_app.core, "get_video_info", lambda *_a, **_k: pytest.fail("no debe llamar ffprobe")
    )
    (inp / "demo.mp4").write_bytes(b"mp4")
    (trans / "demo_info.json").write_text(json.dumps({"duration": 12.0}), encoding="utf-8")
    return TestClient(studio_app.app), tmp_path


def _upload(client, name, data, filename="subs.srt", content_type="application/x-subrip"):
    return client.post(f"/api/videos/{name}/srt", files={"file": (filename, data, content_type)})


# ─── Capabilities ──────────────────────────────────────────────────────────────
def test_get_capabilities(api):
    client, _ = api
    r = client.get("/api/srt/capabilities")
    assert r.status_code == 200
    body = r.json()
    assert body["extensions"] == [".srt"]
    assert body["association"] == "one_selected_per_video"
    assert body["render"] is False and body["auto_v2"] is False


# ─── GET sin/ con seleccion ────────────────────────────────────────────────────
def test_get_sin_seleccion(api):
    client, _ = api
    r = client.get("/api/videos/demo/srt")
    assert r.status_code == 200
    assert r.json() == {
        "version": 1,
        "video": {"name": "demo"},
        "selection": {"selected": False},
        "status": "none",
    }


def test_get_video_inexistente_404(api):
    client, _ = api
    assert client.get("/api/videos/nope/srt").status_code == 404


# ─── POST valido / idempotente / reemplazo ─────────────────────────────────────
def test_post_valido_201(api):
    client, _ = api
    r = _upload(client, "demo", _OK)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "ready"
    assert body["selection"]["source_sha256"] == hashlib.sha256(_OK).hexdigest()


def test_post_duplicado_es_200(api):
    client, _ = api
    assert _upload(client, "demo", _OK).status_code == 201
    r2 = _upload(client, "demo", _OK)
    assert r2.status_code == 200
    assert r2.json()["status"] == "ready"


def test_post_reemplazo_201(api):
    client, _ = api
    _upload(client, "demo", _OK)
    otro = _srt((1, 0, 1000, "otro"), (2, 1000, 3000, "texto"))
    r = _upload(client, "demo", otro)
    assert r.status_code == 201
    assert r.json()["selection"]["source_sha256"] == hashlib.sha256(otro).hexdigest()


def test_get_con_seleccion(api):
    client, _ = api
    _upload(client, "demo", _OK)
    r = client.get("/api/videos/demo/srt")
    assert r.status_code == 200
    assert r.json()["selection"]["selected"] is True


# ─── DELETE ────────────────────────────────────────────────────────────────────
def test_delete_desasocia_y_repetido(api):
    client, _ = api
    _upload(client, "demo", _OK)
    r1 = client.delete("/api/videos/demo/srt")
    assert r1.status_code == 200
    assert r1.json() == {
        "video": {"name": "demo"},
        "selection": {"selected": False},
        "status": "none",
    }
    assert client.delete("/api/videos/demo/srt").status_code == 200  # idempotente
    assert client.get("/api/videos/demo/srt").json()["status"] == "none"


# ─── Errores ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", ["..%2Fsecreto", "sub%2Fvideo"])
def test_traversal_en_name_no_resuelve(api, name):
    client, _ = api
    # El path traversal no resuelve a un video valido -> 404 (nunca 200 con archivo servido)
    assert client.get(f"/api/videos/{name}/srt").status_code in (404, 400)


def test_post_video_inexistente_404(api):
    client, _ = api
    assert _upload(client, "nope", _OK).status_code == 404


def test_post_extension_incorrecta_415(api):
    client, _ = api
    assert _upload(client, "demo", _OK, filename="subs.txt").status_code == 415


def test_post_srt_malformado_400(api):
    client, _ = api
    assert _upload(client, "demo", b"basura suelta\nsin timing\n").status_code == 400


def test_post_demasiado_grande_413(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(studio_srt, "MAX_SRT_BYTES", 8)
    assert _upload(client, "demo", _OK).status_code == 413


def test_warning_no_bloquea(api):
    client, _ = api
    data = _srt((1, 0, 1000, "uno"), (5, 1000, 2000, "dos"))  # indice no consecutivo -> warning
    r = _upload(client, "demo", data)
    assert r.status_code == 201
    assert r.json()["summary"]["n_warnings"] >= 1


def test_error_bloquea(api):
    client, _ = api
    data = _srt((1, 0, 1000, "ok"), (2, 2000, 2000, "end<=start"))
    assert _upload(client, "demo", data).status_code == 400


def test_no_confia_en_content_type(api):
    client, _ = api
    # extension .srt correcta pero MIME mentiroso -> se acepta (la extension/parser mandan)
    r = _upload(client, "demo", _OK, content_type="image/png")
    assert r.status_code == 201


# ─── Privacidad de la respuesta ────────────────────────────────────────────────
def test_respuesta_no_expone_ruta_ni_texto(api):
    client, tmp_path = api
    body = _upload(client, "demo", _OK).json()
    blob = json.dumps(body)
    assert "uno" not in blob and "dos" not in blob
    assert str(tmp_path) not in blob
    assert "managed_path" not in blob
    assert "/" not in body["selection"]["managed_file"]


# ─── Almacenamiento privado no se sirve por ningun mount ───────────────────────
def test_almacenamiento_no_se_publica(api):
    client, _ = api
    body = _upload(client, "demo", _OK).json()
    managed = body["selection"]["managed_file"]
    # No hay mount /transcripts; ninguna ruta publica sirve el .srt administrado.
    for prefix in ("/input", "/output", "/clips", "/static", "/transcripts"):
        r = client.get(f"{prefix}/studio_srt/demo/{managed}")
        assert r.status_code == 404
        r2 = client.get(f"{prefix}/demo/{managed}")
        assert r2.status_code == 404


def test_manifest_no_servido_por_input(api):
    client, _ = api
    _upload(client, "demo", _OK)
    assert client.get("/input/demo_srt_selection.json").status_code == 404
    assert client.get("/transcripts/demo_srt_selection.json").status_code == 404


# ─── Endpoints historicos intactos ─────────────────────────────────────────────
def test_endpoints_historicos_siguen(api):
    client, _ = api
    assert client.get("/api/videos").status_code == 200  # input vacio de videos reales -> []
    assert client.get("/api/auto/capabilities").status_code == 200
    assert client.get("/api/styles").status_code == 200


def test_auto_capabilities_no_cambia(api):
    client, _ = api
    caps = client.get("/api/auto/capabilities").json()
    assert caps["default_mode"] == "classic"


# ─── Ninguna operacion lanza job / render / Auto ───────────────────────────────
def test_ninguna_operacion_inicia_job(api, monkeypatch):
    client, _ = api
    # Si el flujo SRT tocara jobs/threading, estos sentinelas harian fallar el test.
    monkeypatch.setattr(studio_app.jobs, "new_job", lambda *_a, **_k: pytest.fail("no job"))
    monkeypatch.setattr(studio_app.threading, "Thread", lambda *_a, **_k: pytest.fail("no thread"))
    assert _upload(client, "demo", _OK).status_code == 201
    assert client.get("/api/videos/demo/srt").status_code == 200
    assert client.delete("/api/videos/demo/srt").status_code == 200
