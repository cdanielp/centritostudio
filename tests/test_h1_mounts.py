"""H1 · P0-3/P0-4 — Mounts privados: /input eliminado, /output-/thumbs-/clips por allowlist.

Todo con TemporaryDirectory. El binario fuente se sirve solo por el endpoint validado
/api/videos/{name}/source; los mounts solo entregan tipos permitidos y confinados.
"""

from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app as studio_app


def _mini(mount_cls, directory):
    mini = FastAPI()
    mini.mount("/m", mount_cls(directory=str(directory)), name="m")
    return TestClient(mini)


# ── /output allowlist (P0-3) ─────────────────────────────────────────────────
def test_output_solo_mp4(tmp_path):
    (tmp_path / "r.mp4").write_bytes(b"\x00")
    (tmp_path / "c.ass").write_text("x", encoding="utf-8")
    (tmp_path / "k.json").write_text("{}", encoding="utf-8")
    (tmp_path / "s.srt").write_text("1", encoding="utf-8")
    c = _mini(studio_app._OutputMedia, tmp_path)
    assert c.get("/m/r.mp4").status_code == 200
    for priv in ("c.ass", "k.json", "s.srt"):
        assert c.get(f"/m/{priv}").status_code == 404


# ── /thumbs y /clips allowlist (P0-4) ────────────────────────────────────────
def test_thumbs_solo_imagenes(tmp_path):
    (tmp_path / "t.jpg").write_bytes(b"JPG")
    (tmp_path / "priv.ass").write_text("x", encoding="utf-8")
    (tmp_path / "meta.json").write_text("{}", encoding="utf-8")
    c = _mini(studio_app._ThumbsMedia, tmp_path)
    assert c.get("/m/t.jpg").status_code == 200
    assert c.get("/m/priv.ass").status_code == 404
    assert c.get("/m/meta.json").status_code == 404


def test_clips_solo_mp4(tmp_path):
    (tmp_path / "clip.mp4").write_bytes(b"\x00")
    (tmp_path / "clip_clips.json").write_text("{}", encoding="utf-8")
    (tmp_path / "checkpoint.json").write_text("{}", encoding="utf-8")
    c = _mini(studio_app._ClipsMedia, tmp_path)
    assert c.get("/m/clip.mp4").status_code == 200
    assert c.get("/m/clip_clips.json").status_code == 404
    assert c.get("/m/checkpoint.json").status_code == 404


def test_input_mount_eliminado(tmp_path, monkeypatch):
    """No existe mount publico /input: cualquier /input/* es 404 (ruta inexistente)."""
    monkeypatch.setattr(studio_app, "INPUT_DIR", tmp_path)
    (tmp_path / "fuente.mp4").write_bytes(b"SRC")
    c = TestClient(studio_app.app)
    assert c.get("/input/fuente.mp4").status_code == 404


def test_symlink_rechazado(tmp_path):
    """Un symlink servible se rechaza si apunta FUERA del mount O a un temporal interno reservado.

    Cubre ambos vectores en un solo test (una sola guarda de skip por la limitacion conocida de
    symlink en Windows, para no multiplicar skips): (1) symlink -> secreto fuera del root;
    (2) symlink -> archivo dentro de `.render_tmp` (temporal de publicacion).
    """
    import media_integrity as mi

    served = tmp_path / "served"
    served.mkdir()
    secreto = tmp_path / "secreto.mp4"  # fuera del root servido
    secreto.write_bytes(b"PRIVADO-FUERA")
    render_tmp = served / mi.TEMP_DIRNAME
    render_tmp.mkdir()
    parcial = render_tmp / "parcial.mp4"  # temporal interno reservado
    parcial.write_bytes(b"PARCIAL")
    link_fuera = served / "link_fuera.mp4"
    link_tmp = served / "link_tmp.mp4"
    try:
        os.symlink(secreto, link_fuera)
        os.symlink(parcial, link_tmp)
    except (OSError, NotImplementedError):
        pytest.skip("El SO no permite crear symlinks sin privilegios (misma limitacion conocida)")
    c = _mini(studio_app._OutputMedia, served)
    assert c.get("/m/link_fuera.mp4").status_code == 404
    assert c.get("/m/link_tmp.mp4").status_code == 404


# ── Endpoint validado /api/videos/{name}/source (reemplazo de /input) ─────────
@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(studio_app, "INPUT_DIR", tmp_path)
    return TestClient(studio_app.app), tmp_path


def test_source_sirve_mp4_valido(api):
    client, inp = api
    (inp / "demo.mp4").write_bytes(b"SRCDATA")
    r = client.get("/api/videos/demo/source")
    assert r.status_code == 200 and r.content == b"SRCDATA"
    assert r.headers["content-type"].startswith("video/mp4")


def test_source_sirve_mov(api):
    client, inp = api
    (inp / "clip.mov").write_bytes(b"MOVDATA")
    r = client.get("/api/videos/clip/source")
    assert r.status_code == 200 and r.content == b"MOVDATA"


def test_source_inexistente_404(api):
    client, _ = api
    assert client.get("/api/videos/nada/source").status_code == 404


@pytest.mark.parametrize("name", ["..%2F..%2Fsecreto", "%2Fetc%2Fpasswd", "..%5C..%5Cx"])
def test_source_traversal_404(api, name):
    client, inp = api
    (inp.parent / "secreto.mp4").write_bytes(b"FUERA")
    assert client.get(f"/api/videos/{name}/source").status_code == 404


# ── P2-2: temporales de render nunca expuestos por /output ni por /api/videos ──
def test_output_no_sirve_render_tmp_ni_part(tmp_path):
    """El subdir reservado .render_tmp y los nombres .part- nunca se sirven (aunque sean .mp4)."""
    import media_integrity as mi

    render_tmp = tmp_path / mi.TEMP_DIRNAME
    render_tmp.mkdir()
    (render_tmp / "abcdef123456.mp4").write_bytes(b"\x00")
    (tmp_path / "demo_hormozi.part-deadbeef.mp4").write_bytes(b"\x00")
    (tmp_path / "demo_hormozi.mp4").write_bytes(b"\x00")  # render real
    c = _mini(studio_app._OutputMedia, tmp_path)
    assert c.get("/m/.render_tmp/abcdef123456.mp4").status_code == 404
    assert c.get("/m/demo_hormozi.part-deadbeef.mp4").status_code == 404
    assert c.get("/m/demo_hormozi.mp4").status_code == 200  # el render real si


@pytest.fixture
def videos_api(tmp_path, monkeypatch):
    """App con todos los dirs redirigidos: para ejercitar /api/videos con fixtures sinteticos."""
    inp = tmp_path / "input"
    trans = tmp_path / "transcripts"
    out = tmp_path / "output"
    clips = out / "clips"
    thumbs = tmp_path / "thumbs"
    for d in (inp, trans, out, clips, thumbs):
        d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(studio_app, "ROOT", tmp_path)
    monkeypatch.setattr(studio_app, "INPUT_DIR", inp)
    monkeypatch.setattr(studio_app, "TRANSCRIPTS", trans)
    monkeypatch.setattr(studio_app, "OUTPUT_DIR", out)
    monkeypatch.setattr(studio_app, "CLIPS_DIR", clips)
    monkeypatch.setattr(studio_app, "THUMBS_DIR", thumbs)
    monkeypatch.setattr(studio_app.core, "get_video_info", lambda _p: {"duration": 1.0})
    monkeypatch.setattr(studio_app.core, "extract_thumb", lambda *a, **k: None)
    (inp / "demo.mp4").write_bytes(b"SRC")
    (trans / "demo_info.json").write_text('{"duration":1}', encoding="utf-8")
    (thumbs / "demo.jpg").write_bytes(b"J")
    return TestClient(studio_app.app), tmp_path, out


def test_api_videos_ignora_temporal_abandonado(videos_api):
    """Hard-kill simulado: un temporal en .render_tmp NO marca renderizado ni se lista."""
    client, _tmp, out = videos_api
    render_tmp = out / ".render_tmp"
    render_tmp.mkdir()
    (render_tmp / "abandonado.mp4").write_bytes(b"PARCIAL")
    v = client.get("/api/videos").json()[0]
    assert v["name"] == "demo"
    assert v["status"] == "sin_transcribir"  # el temporal NO lo pone en "renderizado"
    assert v["outputs"] == []


def test_api_videos_lista_render_real(videos_api):
    """Un render final valido si aparece como output y marca renderizado."""
    client, _tmp, out = videos_api
    (out / "demo_hormozi.mp4").write_bytes(b"\x00")
    v = client.get("/api/videos").json()[0]
    assert v["status"] == "renderizado"
    assert "demo_hormozi.mp4" in v["outputs"]


def test_api_videos_ignora_part_suelto(videos_api):
    """Un .part- suelto (legacy) tampoco marca renderizado ni se lista."""
    client, _tmp, out = videos_api
    (out / "demo_hormozi.part-deadbeef.mp4").write_bytes(b"\x00")
    v = client.get("/api/videos").json()[0]
    assert v["status"] == "sin_transcribir"
    assert v["outputs"] == []
