"""Tests de contrato para assets_comfy.py.

Contratos verificados:
- Hash de prompt es estable (mismo prompt → mismo hash siempre)
- asset_exists devuelve None si no hay PNG cacheado
- generar_asset devuelve None (fail-open) si ComfyUI no responde en URL falsa
- cargar_keywords devuelve {} si keywords.json no existe
- resolver_overlays devuelve [] si brain.json no existe
- El nodo PROMPT_CENTRITO se sustituye correctamente en el workflow
"""

from __future__ import annotations

import json

import assets_comfy as ac

# ── Fixtures ──────────────────────────────────────────────────────────────────

PROMPT_A = "a glowing purple workflow node"
PROMPT_B = "a golden render icon"


# ── Hash estable ──────────────────────────────────────────────────────────────


def test_hash_prompt_estable():
    h1 = ac._hash_prompt(PROMPT_A)
    h2 = ac._hash_prompt(PROMPT_A)
    assert h1 == h2, "El hash debe ser determinista"


def test_hash_prompts_distintos():
    h1 = ac._hash_prompt(PROMPT_A)
    h2 = ac._hash_prompt(PROMPT_B)
    assert h1 != h2, "Prompts distintos deben producir hashes distintos"


def test_hash_longitud():
    h = ac._hash_prompt(PROMPT_A)
    assert len(h) == 16, "Hash debe tener 16 caracteres"


# ── Cache ─────────────────────────────────────────────────────────────────────


def test_asset_exists_miss(tmp_path, monkeypatch):
    monkeypatch.setattr(ac, "ASSETS_GENERADOS", tmp_path)
    assert ac.asset_exists(PROMPT_A) is None


def test_asset_exists_hit(tmp_path, monkeypatch):
    monkeypatch.setattr(ac, "ASSETS_GENERADOS", tmp_path)
    h = ac._hash_prompt(PROMPT_A)
    png = tmp_path / f"{h}.png"
    png.write_bytes(b"\x89PNG")
    result = ac.asset_exists(PROMPT_A)
    assert result == png


# ── Fallback sin ComfyUI ──────────────────────────────────────────────────────


def test_generar_asset_sin_comfyui(tmp_path, monkeypatch):
    """generar_asset debe devolver None (no lanzar excepcion) si ComfyUI no corre."""
    monkeypatch.setattr(ac, "ASSETS_GENERADOS", tmp_path)
    monkeypatch.setattr(ac, "COMFY_URL", "http://127.0.0.1:19999")  # puerto inexistente
    result = ac.generar_asset(PROMPT_A, timeout=5)
    assert result is None, "Debe devolver None si ComfyUI no esta disponible"


# ── Sustitucion del nodo PROMPT_CENTRITO ──────────────────────────────────────


def test_sustitucion_prompt_en_workflow(tmp_path, monkeypatch):
    """El campo text del nodo PROMPT_NODE_ID debe reemplazarse con el prompt dado."""
    workflow = {
        ac.PROMPT_NODE_ID: {
            "inputs": {"text": "texto original"},
            "class_type": "CLIPTextEncode",
        },
        "9": {"inputs": {"images": [ac.PROMPT_NODE_ID, 0]}, "class_type": "SaveImage"},
    }
    wf_path = tmp_path / "asset_base.json"
    wf_path.write_text(json.dumps(workflow), encoding="utf-8")
    monkeypatch.setattr(ac, "WORKFLOW_PATH", wf_path)
    monkeypatch.setattr(ac, "ASSETS_GENERADOS", tmp_path)
    monkeypatch.setattr(ac, "COMFY_URL", "http://127.0.0.1:19999")

    nuevo_prompt = "a shiny new prompt"

    # Capturamos el payload enviado a ComfyUI
    posted: list[dict] = []

    def fake_post(url, data, timeout=10):
        posted.append(json.loads(data))
        raise OSError("mock no conecta")

    monkeypatch.setattr(ac, "_http_post", fake_post)
    ac.generar_asset(nuevo_prompt, timeout=1)

    assert posted, "Se debe haber intentado enviar el workflow"
    wf_sent = posted[0]["prompt"]
    assert wf_sent[ac.PROMPT_NODE_ID]["inputs"]["text"] == nuevo_prompt


# ── cargar_keywords ───────────────────────────────────────────────────────────


def test_cargar_keywords_sin_archivo(tmp_path, monkeypatch):
    monkeypatch.setattr(ac, "KEYWORDS_PATH", tmp_path / "no_existe.json")
    assert ac.cargar_keywords() == {}


def test_cargar_keywords_con_archivo(tmp_path, monkeypatch):
    data = {"nodo": "a glowing node", "render": "a render farm"}
    kw_path = tmp_path / "keywords.json"
    kw_path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(ac, "KEYWORDS_PATH", kw_path)
    result = ac.cargar_keywords()
    assert result == data


# ── resolver_overlays ─────────────────────────────────────────────────────────


def test_resolver_overlays_sin_brain(tmp_path):
    result = ac.resolver_overlays(
        groups_path=tmp_path / "no_groups.json",
        brain_path=tmp_path / "no_brain.json",
    )
    assert result == []


def test_resolver_overlays_sin_keywords(tmp_path, monkeypatch):
    monkeypatch.setattr(ac, "KEYWORDS_PATH", tmp_path / "no_kw.json")

    groups = [{"words": [{"text": "nodo", "start": 1.0, "end": 1.5}]}]
    brain = {"groups": [{"g": 0, "kw": 0, "kw_ts": 1.0}]}

    g_path = tmp_path / "g.json"
    b_path = tmp_path / "b.json"
    g_path.write_text(json.dumps(groups), encoding="utf-8")
    b_path.write_text(json.dumps(brain), encoding="utf-8")

    result = ac.resolver_overlays(g_path, b_path)
    assert result == []


def test_resolver_overlays_con_cache(tmp_path, monkeypatch):
    """Si el PNG esta cacheado, resolver_overlays lo devuelve sin llamar ComfyUI."""
    monkeypatch.setattr(ac, "ASSETS_GENERADOS", tmp_path)

    keywords = {"nodo": "a glowing node"}
    kw_path = tmp_path / "keywords.json"
    kw_path.write_text(json.dumps(keywords), encoding="utf-8")
    monkeypatch.setattr(ac, "KEYWORDS_PATH", kw_path)

    # Pre-poblar cache
    h = ac._hash_prompt("a glowing node")
    png = tmp_path / f"{h}.png"
    png.write_bytes(b"\x89PNG mock")

    groups = [{"words": [{"text": "nodo", "start": 1.0, "end": 1.5}]}]
    brain = {"groups": [{"g": 0, "kw": 0, "kw_ts": 1.0}]}
    g_path = tmp_path / "g.json"
    b_path = tmp_path / "b.json"
    g_path.write_text(json.dumps(groups), encoding="utf-8")
    b_path.write_text(json.dumps(brain), encoding="utf-8")

    result = ac.resolver_overlays(g_path, b_path)
    assert len(result) == 1
    found_path, t_start, t_end = result[0]
    assert found_path == png
    assert abs(t_start - 1.0) < 0.01
    assert abs(t_end - (1.0 + ac.EMOJI_DURATION_S)) < 0.01
