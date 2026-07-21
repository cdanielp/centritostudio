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


def test_symlink_fuera_del_directorio_rechazado(tmp_path):
    """Un symlink DENTRO del mount que apunta FUERA debe rechazarse (no exfiltra el target)."""
    secreto = tmp_path / "secreto.mp4"
    secreto.write_bytes(b"PRIVADO-FUERA")
    served = tmp_path / "served"
    served.mkdir()
    link = served / "link.mp4"
    try:
        os.symlink(secreto, link)
    except (OSError, NotImplementedError):
        pytest.skip("El SO no permite crear symlinks sin privilegios (misma limitacion conocida)")
    c = _mini(studio_app._ClipsMedia, served)
    assert c.get("/m/link.mp4").status_code == 404


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
