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

# Modelo u2net de rembg dentro del repo (Regla #6: modelos en models/, no en home)
os.environ.setdefault("U2NET_HOME", str(ROOT / "models" / "u2net"))

COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")
COMFY_PORTS_FALLBACK = [8188, 8000]  # ComfyUI Desktop suele usar 8000
PROMPT_NODE_ID = "67"  # CLIPTextEncode con titulo PROMPT_CENTRITO
TIMEOUT_S = 120  # segundos maximos de espera por imagen
POLL_INTERVAL_S = 2

# Constantes de overlay (usadas por core_ass.burn_video_with_emojis)
EMOJI_SIZE_PCT = 0.20  # ancho del PNG respecto al ancho del video
EMOJI_MARGIN_PCT = 0.02  # margen desde los bordes
EMOJI_DURATION_S = 1.2  # duracion en pantalla (segundos)
EMOJI_FADE_S = 0.12  # fade in/out del overlay (segundos)

# Template de estilo sticker: fondo blanco liso ayuda a rembg a recortar limpio.
# keywords.json mapea keyword -> concepto; el template envuelve el concepto.
PROMPT_TEMPLATE = (
    "single {concept} emoji sticker, 3D glossy cartoon style, thick white outline, "
    "vibrant colors, centered, isolated on plain white background, no text, no watermark"
)


def _hash_prompt(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


def _quitar_fondo(png_bytes: bytes) -> bytes:
    """Quita el fondo del PNG con rembg; devuelve bytes RGBA.

    Fail-open: si rembg no esta instalado o falla, devuelve los bytes originales
    con un aviso (el overlay saldra con fondo, pero el render no se cae).
    """
    try:
        from rembg import remove  # noqa: PLC0415

        return remove(png_bytes)
    except ImportError:
        print("[assets_comfy] rembg no instalado - PNG sin transparencia")
        print("  -> Accion: .\\venv\\Scripts\\pip install rembg")
        return png_bytes
    except Exception as e:
        print(f"[assets_comfy] rembg fallo ({e}) - PNG sin transparencia")
        return png_bytes


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


def generar_asset(
    prompt: str, timeout: int = TIMEOUT_S, comfy_url: str | None = None
) -> Path | None:
    """Genera o devuelve desde cache el PNG para el prompt.

    comfy_url: URL activa detectada por _probe_comfy_url(); si None usa COMFY_URL.
    Devuelve Path al PNG, o None si ComfyUI no esta disponible (fail-open).
    """
    ASSETS_GENERADOS.mkdir(parents=True, exist_ok=True)

    cached = asset_exists(prompt)
    if cached:
        return cached

    h = _hash_prompt(prompt)
    out_path = ASSETS_GENERADOS / f"{h}.png"
    base_url = comfy_url or COMFY_URL

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
        result = _http_post(f"{base_url}/prompt", payload)
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
        result = _poll_history(prompt_id, out_path, base_url)
        if result is not None:
            return result if result is not False else None

    print(f"[assets_comfy] Timeout ({timeout}s) esperando a ComfyUI")
    return None


def _poll_history(
    prompt_id: str, out_path: Path, base_url: str | None = None
) -> Path | bool | None:
    """Un tick del poll de historia. Devuelve Path si termino, False si error, None si pendiente."""
    url = base_url or COMFY_URL
    try:
        history_raw = _http_get(f"{url}/history/{prompt_id}")
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
            img_bytes = _http_get(f"{url}/view?{qstr}")
            # El cache guarda la version RGBA (fondo removido), no la cruda
            out_path.write_bytes(_quitar_fondo(img_bytes))
            print(f"[assets_comfy] Generado (RGBA): {out_path.name}")
            return out_path
        except Exception as e:
            print(f"[assets_comfy] Error descargando imagen: {e}")
            return False  # error definitivo

    return None  # outputs vacios todavia


def cargar_keywords() -> dict[str, str]:
    """Carga el mapa keyword->prompt desde assets/keywords.json. Fail-open: {} si falta."""
    if not KEYWORDS_PATH.exists():
        return {}
    try:
        return json.loads(KEYWORDS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _probe_comfy_url() -> str | None:
    """Prueba los puertos conocidos de ComfyUI; devuelve la URL activa o None.

    Intenta COMFY_PORTS_FALLBACK en orden. Usa /system_stats (endpoint ligero).
    """
    for port in COMFY_PORTS_FALLBACK:
        url = f"http://127.0.0.1:{port}"
        try:
            _http_get(f"{url}/system_stats", timeout=3)
            return url
        except Exception:
            pass
    return None


def _extraer_brain_kws(groups: list, brain: dict) -> list[tuple[str, float]]:
    """Extrae keywords del brain.json como lista de (texto_lower, t_start). Puro."""
    result: list[tuple[str, float]] = []
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
        result.append((kw_text, t_start))
    return result


def resolver_overlays(
    groups_path: Path,
    brain_path: Path,
) -> list[tuple[Path, float, float]]:
    """Cruza brain.json con keywords.json para producir la lista de overlays.

    Loguea diagnostico separado por causa (ComfyUI / keywords no matcheadas).
    Devuelve lista de (png_path, t_start, t_end). Fail-open: [] ante cualquier falta.
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
        print(f"[emojis] keywords.json no encontrado o vacio: {KEYWORDS_PATH}")
        print("  -> Accion: edita assets/keywords.json con entradas palabra:prompt")
        return []

    brain_kws = _extraer_brain_kws(groups, brain)
    if not brain_kws:
        print("[emojis] brain.json sin keywords marcadas -- analiza el video con IA primero")
        return []

    matched = [(kw, ts) for kw, ts in brain_kws if kw in keywords_map]
    if not matched:
        # .encode+decode para safe ASCII en consola Windows sin PYTHONIOENCODING
        def _ascii(s: str) -> str:
            return s.encode("ascii", "replace").decode("ascii")

        video_kws = _ascii(", ".join(kw for kw, _ in brain_kws))
        mapa_kws = _ascii(", ".join(list(keywords_map.keys())[:10]))
        print(f"[emojis] 0 de {len(keywords_map)} keywords del mapa en la transcripcion")
        print(f"  -> Keywords del video (brain): {video_kws}")
        print(f"  -> Keywords del mapa (assets/keywords.json): {mapa_kws}")
        print("  -> Accion: agrega las palabras del video a assets/keywords.json con su prompt")
        return []

    # Diagnostico de ComfyUI (solo si hay keywords para generar)
    active_url = _probe_comfy_url()
    if active_url is None:
        ports_str = " ni ".join(f"http://127.0.0.1:{p}" for p in COMFY_PORTS_FALLBACK)
        kws_ready = ", ".join(f"{k}@{t:.1f}s" for k, t in matched)
        print(f"[emojis] ComfyUI: no responde en {ports_str}")
        print("  -> Accion: abre ComfyUI Desktop y espera a que cargue los modelos")
        print(f"  -> Keywords listas para generar cuando ComfyUI este activo: {kws_ready}")
        return []

    port_note = " (puerto alternativo)" if active_url != COMFY_URL else ""
    print(f"[emojis] ComfyUI: responde en {active_url}{port_note}")
    kws_str = ", ".join(f"{k}@{t:.1f}s" for k, t in matched)
    print(f"[emojis] keywords encontradas: {kws_str} -- generando {len(matched)} asset(s)")

    overlays: list[tuple[Path, float, float]] = []
    for kw_text, t_start in matched:
        # keywords.json da el CONCEPTO; el template fija el estilo sticker.
        # El hash se calcula sobre el prompt templado -> cambiar template o
        # concepto invalida el cache automaticamente.
        prompt = PROMPT_TEMPLATE.format(concept=keywords_map[kw_text])
        png = generar_asset(prompt, comfy_url=active_url)
        if png:
            overlays.append((png, t_start, t_start + EMOJI_DURATION_S))

    return overlays
