"""test_studio_srt_api.py — Contrato HTTP del router SRT de Studio (S36-C1, D37).

Sin red, sin GPU, sin FFmpeg: la duracion del video se lee de un info.json cacheado en
tmp_path, nunca de ffprobe. Verifica status HTTP, lectura acotada del upload, validacion
del cache de duracion, privacidad de la respuesta, mensajes de error que no reflejan el
input del usuario, que el storage no se sirve por ningun mount y que ninguna operacion
toca render/Auto/Whisper.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app as studio_app
import core
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


class FakeUpload:
    """UploadFile falso para probar la lectura acotada sin Starlette."""

    def __init__(self, data: bytes, size: int | None = None, filename: str = "subs.srt"):
        self._buf = io.BytesIO(data)
        self.size = size
        self.filename = filename
        self.reads = 0

    async def read(self, n: int = -1) -> bytes:
        self.reads += 1
        return self._buf.read(n)


@pytest.fixture
def api(tmp_path, monkeypatch):
    inp = tmp_path / "input"
    trans = tmp_path / "transcripts"
    storage = trans / "studio_srt"
    inp.mkdir()
    trans.mkdir()
    monkeypatch.setattr(studio_srt_routes, "INPUT_DIR", inp)
    monkeypatch.setattr(studio_srt_routes, "TRANSCRIPTS", trans)
    monkeypatch.setattr(studio_srt_routes, "STUDIO_SRT_DIR", storage)
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


# ─── Capabilities / GET ────────────────────────────────────────────────────────
def test_get_capabilities(api):
    client, _ = api
    body = client.get("/api/srt/capabilities").json()
    assert body["extensions"] == [".srt"]
    assert body["association"] == "one_selected_per_video"
    assert body["render"] is False and body["auto_v2"] is False


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
    assert r.json()["status"] == "ready"
    assert r.json()["selection"]["source_sha256"] == hashlib.sha256(_OK).hexdigest()


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
    assert r.json()["selection"]["managed_file"] == f"{hashlib.sha256(_OK).hexdigest()}.srt"


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
    assert client.delete("/api/videos/demo/srt").status_code == 200
    assert client.get("/api/videos/demo/srt").json()["status"] == "none"


# ─── Errores ───────────────────────────────────────────────────────────────────
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
    data = _srt((1, 0, 1000, "uno"), (5, 1000, 2000, "dos"))
    r = _upload(client, "demo", data)
    assert r.status_code == 201
    assert r.json()["summary"]["n_warnings"] >= 1


def test_error_bloquea(api):
    client, _ = api
    data = _srt((1, 0, 1000, "ok"), (2, 2000, 2000, "end<=start"))
    assert _upload(client, "demo", data).status_code == 400


def test_no_confia_en_content_type(api):
    client, _ = api
    r = _upload(client, "demo", _OK, content_type="image/png")
    assert r.status_code == 201


# ─── Bloqueante 1: lectura acotada del upload ──────────────────────────────────
def test_read_limited_size_none_pequeno_valido():
    up = FakeUpload(_OK, size=None)
    data = asyncio.run(studio_srt_routes._read_upload_limited(up, 10_000))
    assert data == _OK


def test_read_limited_size_none_excede_413():
    payload = b"x" * 101
    up = FakeUpload(payload, size=None)
    with pytest.raises(studio_srt.StudioSrtTooLarge):
        asyncio.run(studio_srt_routes._read_upload_limited(up, 100))


def test_read_limited_size_mentiroso_menor_413():
    payload = b"x" * 200
    up = FakeUpload(payload, size=5)  # miente: dice 5, trae 200
    with pytest.raises(studio_srt.StudioSrtTooLarge):
        asyncio.run(studio_srt_routes._read_upload_limited(up, 50))


def test_read_limited_exacto_max_llega_al_parser():
    payload = b"x" * 100
    up = FakeUpload(payload, size=None)
    data = asyncio.run(studio_srt_routes._read_upload_limited(up, 100))
    assert data == payload  # exactamente max_bytes se acepta


def test_read_limited_maxmas1_aborta():
    payload = b"x" * 101
    up = FakeUpload(payload, size=None)
    with pytest.raises(studio_srt.StudioSrtTooLarge):
        asyncio.run(studio_srt_routes._read_upload_limited(up, 100))


def test_read_limited_multiples_chunks(monkeypatch):
    monkeypatch.setattr(studio_srt_routes, "_UPLOAD_CHUNK", 4)
    up = FakeUpload(b"x" * 20, size=None)
    data = asyncio.run(studio_srt_routes._read_upload_limited(up, 1000))
    assert data == b"x" * 20
    assert up.reads >= 3  # se leyo en varios chunks, no de una sola vez


def test_oversize_no_llama_parse_ni_store(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(
        studio_srt, "parse_and_validate", lambda *_a, **_k: pytest.fail("no debe parsear")
    )
    monkeypatch.setattr(
        studio_srt, "store_and_associate", lambda *_a, **_k: pytest.fail("no debe almacenar")
    )
    monkeypatch.setattr(studio_srt, "MAX_SRT_BYTES", 8)
    assert _upload(client, "demo", _OK).status_code == 413


def test_seleccion_previa_intacta_tras_exceso(api):
    client, _ = api
    assert _upload(client, "demo", _OK).status_code == 201
    orig = studio_srt.MAX_SRT_BYTES
    studio_srt.MAX_SRT_BYTES = 8
    try:
        assert _upload(client, "demo", _OK).status_code == 413  # el nuevo excede
    finally:
        studio_srt.MAX_SRT_BYTES = orig
    r = client.get("/api/videos/demo/srt")
    assert r.json()["selection"]["source_sha256"] == hashlib.sha256(_OK).hexdigest()


# ─── Bloqueante 2: duracion real, no cache obsoleto ────────────────────────────
@pytest.mark.parametrize(
    ("value", "ok"),
    [
        (12.0, True),
        (12, True),
        (0, False),
        (-3.0, False),
        (float("nan"), False),
        (float("inf"), False),
        (True, False),
        ("12", False),
        (None, False),
    ],
)
def test_finite_positive(value, ok):
    result = studio_srt_routes._finite_positive(value)
    assert (result is not None) == ok


def _write_info(trans, name, obj, mtime=None):
    p = trans / f"{name}_info.json"
    p.write_text(json.dumps(obj), encoding="utf-8")
    if mtime is not None:
        import os

        os.utime(p, (mtime, mtime))
    return p


def test_cache_reciente_valido_se_reutiliza(api, monkeypatch):
    _, tmp_path = api
    trans = tmp_path / "transcripts"
    video = tmp_path / "input" / "demo.mp4"
    _write_info(trans, "demo", {"duration": 7.5})  # escrito despues del video -> fresco
    monkeypatch.setattr(
        core, "get_video_info", lambda *_a, **_k: pytest.fail("no debe usar ffprobe")
    )
    assert studio_srt_routes._duracion_ms(video, "demo") == 7500


def test_cache_anterior_al_video_se_ignora(api, monkeypatch):
    import os

    _, tmp_path = api
    trans = tmp_path / "transcripts"
    video = tmp_path / "input" / "demo.mp4"
    info = _write_info(trans, "demo", {"duration": 99.0})
    os.utime(info, (1, 1))  # cache viejisimo -> anterior al video
    called = {}

    def _probe(_p):
        called["hit"] = True
        return {"duration": 4.0}

    monkeypatch.setattr(core, "get_video_info", _probe)
    assert studio_srt_routes._duracion_ms(video, "demo") == 4000
    assert called.get("hit")  # cayo al fallback, no uso el cache obsoleto


@pytest.mark.parametrize(
    "obj",
    [{"duration": 0}, {"duration": -1.0}, {"otra": 1}, {"duration": float("nan")}],
)
def test_cache_invalido_cae_al_fallback(api, monkeypatch, obj):
    _, tmp_path = api
    trans = tmp_path / "transcripts"
    video = tmp_path / "input" / "demo.mp4"
    _write_info(trans, "demo", obj)
    monkeypatch.setattr(core, "get_video_info", lambda *_a, **_k: {"duration": 5.0})
    assert studio_srt_routes._duracion_ms(video, "demo") == 5000


def test_cache_json_corrupto_cae_al_fallback(api, monkeypatch):
    _, tmp_path = api
    trans = tmp_path / "transcripts"
    video = tmp_path / "input" / "demo.mp4"
    (trans / "demo_info.json").write_text("{ roto", encoding="utf-8")
    monkeypatch.setattr(core, "get_video_info", lambda *_a, **_k: {"duration": 6.0})
    assert studio_srt_routes._duracion_ms(video, "demo") == 6000


def test_duracion_redondea_a_ms(api, monkeypatch):
    _, tmp_path = api
    trans = tmp_path / "transcripts"
    video = tmp_path / "input" / "demo.mp4"
    (trans / "demo_info.json").unlink()
    monkeypatch.setattr(core, "get_video_info", lambda *_a, **_k: {"duration": 1.2346})
    assert studio_srt_routes._duracion_ms(video, "demo") == 1235


def test_ffprobe_fallo_respuesta_generica_sin_ruta(api, monkeypatch):
    client, _ = api

    def _boom(_p):
        raise RuntimeError("ffprobe /ruta/interna/secreta reventó")

    monkeypatch.setattr(core, "get_video_info", _boom)
    (studio_srt_routes.TRANSCRIPTS / "demo_info.json").unlink()  # sin cache -> fuerza ffprobe
    r = _upload(client, "demo", _OK)
    assert r.status_code == 500
    assert "ruta" not in r.text and "ffprobe" not in r.text and "Traceback" not in r.text


# ─── Errores publicos que no reflejan el input del usuario ─────────────────────
def test_resolver_no_refleja_name():
    for name in ["../../etc/passwd", "C:\\Windows\\system32", "malo\x00ctrl", "sub/dir"]:
        with pytest.raises(HTTPException) as ei:
            studio_srt_routes._resolver_video(name)
        assert ei.value.detail == "Video no encontrado en input."
        assert name not in str(ei.value.detail)


def test_404_body_no_echoa_name(api):
    client, _ = api
    r = client.get("/api/videos/evil..payload/srt")
    assert r.status_code == 404
    assert "evil..payload" not in r.text


def test_manifest_corrupto_no_filtra_internos(api):
    client, tmp_path = api
    _upload(client, "demo", _OK)
    manifest = tmp_path / "transcripts" / "demo_srt_selection.json"
    manifest.write_text(
        '{"version":1,"selection":{"selected":true},"basura":"x"}', encoding="utf-8"
    )
    r = client.get("/api/videos/demo/srt")
    assert r.status_code == 500
    assert str(tmp_path) not in r.text and "Traceback" not in r.text


# ─── Privacidad / mounts ───────────────────────────────────────────────────────
def test_respuesta_no_expone_ruta_ni_texto(api):
    client, tmp_path = api
    body = _upload(client, "demo", _OK).json()
    blob = json.dumps(body)
    assert "uno" not in blob and "dos" not in blob
    assert str(tmp_path) not in blob
    assert "managed_path" not in blob
    assert "/" not in body["selection"]["managed_file"]


def test_almacenamiento_no_se_publica(api):
    client, _ = api
    body = _upload(client, "demo", _OK).json()
    managed = body["selection"]["managed_file"]
    for prefix in ("/input", "/output", "/clips", "/static", "/transcripts"):
        assert client.get(f"{prefix}/studio_srt/demo/{managed}").status_code == 404
        assert client.get(f"{prefix}/demo/{managed}").status_code == 404


def test_manifest_no_servido_por_input(api):
    client, _ = api
    _upload(client, "demo", _OK)
    assert client.get("/input/demo_srt_selection.json").status_code == 404
    assert client.get("/transcripts/demo_srt_selection.json").status_code == 404


# ─── Endpoints historicos intactos ─────────────────────────────────────────────
def test_endpoints_historicos_siguen(api):
    client, _ = api
    assert client.get("/api/videos").status_code == 200
    assert client.get("/api/auto/capabilities").status_code == 200
    assert client.get("/api/styles").status_code == 200


def test_auto_capabilities_no_cambia(api):
    client, _ = api
    assert client.get("/api/auto/capabilities").json()["default_mode"] == "classic"


# ─── Ninguna operacion lanza job / render / Auto ───────────────────────────────
def test_ninguna_operacion_inicia_job(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(studio_app.jobs, "new_job", lambda *_a, **_k: pytest.fail("no job"))
    monkeypatch.setattr(studio_app.threading, "Thread", lambda *_a, **_k: pytest.fail("no thread"))
    assert _upload(client, "demo", _OK).status_code == 201
    assert client.get("/api/videos/demo/srt").status_code == 200
    assert client.delete("/api/videos/demo/srt").status_code == 200
