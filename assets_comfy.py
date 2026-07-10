"""assets_comfy.py — Puente ComfyUI para generar assets PNG desde prompts.

Flujo:
  1. Recibe un prompt de texto para una keyword del brain.
  2. Calcula SHA-256[:16] del prompt → clave de cache.
  3. Si existe assets/generados/{hash}.png: devuelve la ruta (cache hit).
  4. Si no: envía el workflow a ComfyUI local, espera el resultado y guarda el PNG.
  5. Si ComfyUI no está disponible: devuelve None (fail-open, la capa se omite).

Constantes sobreescribibles via env vars:
  COMFY_URL   (default http://127.0.0.1:8188)
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
WORKFLOW_PATH = ROOT / "workflows" / "asset_base.json"
ASSETS_GENERADOS = ROOT / "assets" / "generados"
KEYWORDS_PATH = ROOT / "assets" / "keywords.json"

COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")
PROMPT_NODE_ID = "67"  # CLIPTextEncode con titulo PROMPT_CENTRITO
TIMEOUT_S = 120  # segundos maximos de espera por imagen
POLL_INTERVAL_S = 2

# Constantes de overlay (usadas por core_ass.burn_video_with_emojis)
EMOJI_SIZE_PCT = 0.18  # ancho del PNG respecto al ancho del video
EMOJI_MARGIN_PCT = 0.02  # margen desde los bordes
EMOJI_DURATION_S = 1.2  # duracion en pantalla (segundos)


def _hash_prompt(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


def asset_exists(prompt: str) -> Path | None:
    """Devuelve la ruta del PNG cacheado o None."""
    ASSETS_GENERADOS.mkdir(parents=True, exist_ok=True)
    p = ASSETS_GENERADOS / f"{_hash_prompt(prompt)}.png"
    return p if p.exists() else None


def _http_post(url: str, data: bytes, timeout: int = 10) -> dict:
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _http_get(url: str, timeout: int = 10) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read()


def generar_asset(prompt: str, timeout: int = TIMEOUT_S) -> Path | None:
    """Genera o devuelve desde cache el PNG para el prompt.

    Devuelve Path al PNG, o None si ComfyUI no está disponible (fail-open).
    """
    ASSETS_GENERADOS.mkdir(parents=True, exist_ok=True)

    cached = asset_exists(prompt)
    if cached:
        return cached

    h = _hash_prompt(prompt)
    out_path = ASSETS_GENERADOS / f"{h}.png"

    if not WORKFLOW_PATH.exists():
        print(f"[assets_comfy] Workflow no encontrado: {WORKFLOW_PATH}")
        return None

    workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    if PROMPT_NODE_ID not in workflow:
        print(f"[assets_comfy] Nodo {PROMPT_NODE_ID} no encontrado en el workflow")
        return None

    workflow[PROMPT_NODE_ID]["inputs"]["text"] = prompt
    payload = json.dumps({"prompt": workflow}).encode("utf-8")

    try:
        result = _http_post(f"{COMFY_URL}/prompt", payload)
        prompt_id = result.get("prompt_id")
        if not prompt_id:
            print("[assets_comfy] Sin prompt_id en respuesta - ComfyUI ocupado?")
            return None
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        print(f"[assets_comfy] ComfyUI no disponible ({e}) - capa de emojis omitida")
        return None

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL_S)
        result = _poll_history(prompt_id, out_path)
        if result is not None:
            return result if result is not False else None

    print(f"[assets_comfy] Timeout ({timeout}s) esperando a ComfyUI")
    return None


def _poll_history(prompt_id: str, out_path: Path) -> Path | bool | None:
    """Un tick del poll de historia. Devuelve Path si terminó, False si error, None si pendiente."""
    try:
        history_raw = _http_get(f"{COMFY_URL}/history/{prompt_id}")
        history = json.loads(history_raw)
    except Exception:
        return None  # seguir esperando

    if prompt_id not in history:
        return None

    outputs = history[prompt_id].get("outputs", {})
    for _node_id, node_out in outputs.items():
        images = node_out.get("images", [])
        if not images:
            continue
        img = images[0]
        fname = img["filename"]
        subfolder = img.get("subfolder", "")
        img_type = img.get("type", "output")
        qstr = f"filename={fname}&type={img_type}"
        if subfolder:
            qstr += f"&subfolder={subfolder}"
        try:
            img_bytes = _http_get(f"{COMFY_URL}/view?{qstr}")
            out_path.write_bytes(img_bytes)
            print(f"[assets_comfy] Generado: {out_path.name}")
            return out_path
        except Exception as e:
            print(f"[assets_comfy] Error descargando imagen: {e}")
            return False  # error definitivo

    return None  # outputs vacios todavia


def cargar_keywords() -> dict[str, str]:
    """Carga el mapa keyword→prompt desde assets/keywords.json. Fail-open: {} si falta."""
    if not KEYWORDS_PATH.exists():
        return {}
    try:
        return json.loads(KEYWORDS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def resolver_overlays(
    groups_path: Path,
    brain_path: Path,
) -> list[tuple[Path, float, float]]:
    """Cruza brain.json con keywords.json para producir la lista de overlays.

    Devuelve lista de (png_path, t_start, t_end) para cada keyword que tenga
    un prompt en keywords.json y su PNG generado (o cacheado) con exito.
    Silencioso ante faltas: si falta el JSON o ComfyUI no corre, devuelve [].
    """
    if not groups_path.exists() or not brain_path.exists():
        return []

    try:
        groups = json.loads(groups_path.read_text(encoding="utf-8"))
        brain = json.loads(brain_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    keywords_map = cargar_keywords()
    if not keywords_map:
        return []

    overlays: list[tuple[Path, float, float]] = []

    for item in brain.get("groups", []):
        g_idx = item.get("g")
        kw_idx = item.get("kw")
        if g_idx is None or kw_idx is None:
            continue
        if g_idx >= len(groups):
            continue
        g_words = groups[g_idx].get("words", [])
        if kw_idx >= len(g_words):
            continue

        word = g_words[kw_idx]
        kw_text = word.get("text", "").lower().strip(".,!?;:")
        t_start = float(item.get("kw_ts") or word.get("start", 0))
        t_end = t_start + EMOJI_DURATION_S

        if kw_text not in keywords_map:
            continue

        prompt = keywords_map[kw_text]
        png = generar_asset(prompt)
        if png:
            overlays.append((png, t_start, t_end))

    return overlays
