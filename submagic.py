"""submagic.py - Cliente del motor nube Submagic (estacion independiente).

Motor OPT-IN paralelo al pipeline local. Submagic quema los captions en su
nube: el resultado NO pasa por caption.py ni core_ass.py. Este modulo solo
habla HTTP con la API y descarga el MP4 final.

Seguridad (regla #9): la key vive en SUBMAGIC_API_KEY (.env) y NUNCA se imprime
en logs, errores ni reportes. Los headers de request jamas se logean.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

BASE = "https://api.submagic.co/v1"
HEALTH_URL = "https://api.submagic.co/health"  # health es publico y vive en la raiz
# Endpoint protegido para validar la key sin crear nada: 404 = key ok, 401 = key mala.
_AUTH_PROBE = "/projects/00000000-0000-0000-0000-000000000000"

# Parametros de edicion por defecto (spec del motor). Sobre-escribibles por llamada.
DEFAULT_PARAMS = {
    "language": "es",
    "templateName": "Hormozi 2",
    "magicZooms": True,
    "magicBrolls": True,
    "dictionary": ["Centrito Studio", "Prompt Models Studio"],
    "autoRender": True,
}

# Backoff para 429 sin Retry-After (segundos). Limite razonable, no logica fija.
_BACKOFF = [2, 5, 10, 20, 30]
_POLL_INTERVAL = 5.0  # segundos entre polls
_POLL_TIMEOUT = 900.0  # 15 min tope por fase de espera

# Reframe: Submagic NO reencuadra (devuelve el mismo aspect ratio). Para short-form
# el video debe llegar ya en 9:16. Ratio objetivo y tolerancia para clasificar.
ASPECTO_VERTICAL = 9 / 16  # 0.5625
_ASPECTO_TOL = 0.02

# Templates: fallback unico permitido si la API falla o no devuelve nada util.
TEMPLATE_FALLBACK = "Hormozi 2"
_templates_cache: list[str] | None = None

ProgressCb = Callable[[str, int], None]


def es_9x16(width: int, height: int, tol: float = _ASPECTO_TOL) -> bool:
    """True si el aspect ratio ya es ~9:16 vertical (dimensiones desconocidas -> False)."""
    if width <= 0 or height <= 0:
        return False
    return abs(width / height - ASPECTO_VERTICAL) <= tol


def necesita_reframe(width: int, height: int, tol: float = _ASPECTO_TOL) -> bool:
    """True si el video es mas ancho que 9:16 y debe reencuadrarse antes de subir.

    Ya vertical (9:16 o mas alto) -> False. Dimensiones desconocidas -> False
    (no arriesgar un reframe a ciegas; se sube el original)."""
    if width <= 0 or height <= 0:
        return False
    return (width / height) > (ASPECTO_VERTICAL + tol)


def tiene_key() -> bool:
    """True si SUBMAGIC_API_KEY esta configurada (sin revelar su valor)."""
    return bool(os.getenv("SUBMAGIC_API_KEY", "").strip())


def _key() -> str:
    key = os.getenv("SUBMAGIC_API_KEY", "").strip()
    if not key:
        raise ValueError(
            "SUBMAGIC_API_KEY no configurada. Agregala a .env "
            "(ver .env.example) para usar el motor Submagic."
        )
    return key


def _headers() -> dict:
    """Headers con auth. NUNCA logear este dict (contiene la key)."""
    return {"x-api-key": _key()}


def _rate_headers(resp: requests.Response) -> dict:
    """Extrae headers de rate limit relevantes (sin secretos) para evidencia."""
    out = {}
    for h in ("X-RateLimit-Remaining", "X-RateLimit-Limit", "Retry-After"):
        if h in resp.headers:
            out[h] = resp.headers[h]
    return out


def _safe_error(resp: requests.Response) -> str:
    """Mensaje de error sin secretos: status + texto acotado del body."""
    try:
        body = resp.json()
        detalle = body.get("message") or body.get("error") or json.dumps(body)[:200]
    except ValueError:
        detalle = (resp.text or "")[:200]
    return f"HTTP {resp.status_code}: {detalle}"


def _request(method: str, path: str, **kwargs) -> requests.Response:
    """Request con manejo de 429 (Retry-After o backoff exponencial acotado)."""
    url = f"{BASE}{path}"
    intento = 0
    while True:
        resp = requests.request(method, url, headers=_headers(), timeout=120, **kwargs)
        if resp.status_code != 429:
            return resp
        # Rate limit: respetar Retry-After; si no viene, backoff exponencial.
        retry_after = resp.headers.get("Retry-After")
        if retry_after and retry_after.isdigit():
            espera = int(retry_after)
        else:
            espera = _BACKOFF[min(intento, len(_BACKOFF) - 1)]
        if intento >= len(_BACKOFF):
            return resp  # se agoto el backoff: devolver 429 para que el worker falle
        print(f"[submagic] 429 rate limit, reintento en {espera}s")
        time.sleep(espera)
        intento += 1


def health_check() -> dict:
    """GET /health (publico, raiz). Devuelve {ok, status, rate}. No lanza por status."""
    resp = requests.get(HEALTH_URL, timeout=30)
    return {"ok": resp.ok, "status": resp.status_code, "rate": _rate_headers(resp)}


def probar_key() -> dict:
    """Valida API + key. Mensaje accionable, sin revelar secretos.

    Health confirma que la API responde; un GET a un endpoint protegido
    distingue key valida (404 proyecto inexistente) de key mala (401/403)."""
    if not tiene_key():
        return {"ok": False, "message": "Falta SUBMAGIC_API_KEY en .env"}
    try:
        hc = health_check()
    except requests.RequestException:
        return {"ok": False, "message": "No se pudo contactar api.submagic.co"}
    if not hc["ok"]:
        return {"ok": False, "message": f"API respondio {hc['status']} en /health"}
    resp = _request("GET", _AUTH_PROBE)
    if resp.status_code == 404:
        return {"ok": True, "message": "Key valida - API Submagic accesible"}
    if resp.status_code in (401, 403):
        return {"ok": False, "message": "Key rechazada (401/403) - revisa SUBMAGIC_API_KEY"}
    return {"ok": False, "message": f"Auth respondio {resp.status_code}"}


def _extraer_nombres(payload) -> list[str]:
    """Extrae nombres de template de una respuesta arbitraria. Puro y robusto.

    Soporta lista directa o envuelta en templates/data/items/results; cada item
    puede ser string o dict (name/templateName/title/id)."""
    items = None
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        for clave in ("templates", "data", "items", "results"):
            if isinstance(payload.get(clave), list):
                items = payload[clave]
                break
    if items is None:
        return []
    nombres = []
    for it in items:
        if isinstance(it, str) and it.strip():
            nombres.append(it.strip())
        elif isinstance(it, dict):
            nombre = it.get("name") or it.get("templateName") or it.get("title") or it.get("id")
            if nombre:
                nombres.append(str(nombre))
    return nombres


def listar_templates(force_refresh: bool = False) -> list[str]:
    """GET /templates -> lista de nombres reales. Cachea el resultado exitoso.

    Fallback a [TEMPLATE_FALLBACK] si la API falla, responde error o no trae
    nombres reconocibles. El fallback NO se cachea: el proximo intento reintenta."""
    global _templates_cache
    if _templates_cache is not None and not force_refresh:
        return _templates_cache
    try:
        resp = _request("GET", "/templates")
        if not resp.ok:
            print(f"[submagic] templates HTTP {resp.status_code} -- fallback {TEMPLATE_FALLBACK}")
            return [TEMPLATE_FALLBACK]
        nombres = _extraer_nombres(resp.json())
    except (requests.RequestException, ValueError) as exc:
        print(f"[submagic] templates fallo ({type(exc).__name__}) -- fallback {TEMPLATE_FALLBACK}")
        return [TEMPLATE_FALLBACK]
    if not nombres:
        print(f"[submagic] templates vacio -- fallback {TEMPLATE_FALLBACK}")
        return [TEMPLATE_FALLBACK]
    _templates_cache = nombres
    return nombres


def enviar_video(
    path: Path, title: str | None = None, params: dict | None = None
) -> tuple[str, dict]:
    """POST /projects/upload multipart (sin base64). Devuelve (project_id, rate).

    La API exige `title` y `language`; title cae al nombre del archivo si no se pasa."""
    p = {**DEFAULT_PARAMS, "title": title or path.stem, **(params or {})}
    # Form-data: escalares como string, listas/bools serializados de forma estable.
    data = {}
    for k, v in p.items():
        if isinstance(v, bool):
            data[k] = "true" if v else "false"
        elif isinstance(v, (list, dict)):
            data[k] = json.dumps(v, ensure_ascii=False)
        else:
            data[k] = str(v)
    with open(path, "rb") as fh:
        files = {"file": (path.name, fh, "video/mp4")}
        resp = _request("POST", "/projects/upload", data=data, files=files)
    if not resp.ok:
        raise RuntimeError(_safe_error(resp))
    body = resp.json()
    pid = body.get("id") or body.get("projectId") or body.get("project", {}).get("id")
    if not pid:
        raise RuntimeError("Upload sin project id en la respuesta")
    return str(pid), _rate_headers(resp)


def estado(project_id: str) -> dict:
    """GET /projects/{id}. Devuelve el JSON del proyecto."""
    resp = _request("GET", f"/projects/{project_id}")
    if not resp.ok:
        raise RuntimeError(_safe_error(resp))
    return resp.json()


def exportar(project_id: str) -> dict:
    """POST /projects/{id}/export. Fallback si autoRender no disparo el render."""
    resp = _request("POST", f"/projects/{project_id}/export")
    if not resp.ok:
        raise RuntimeError(_safe_error(resp))
    return resp.json()


def _es_fallo(st: dict) -> str | None:
    """Devuelve mensaje si el proyecto fallo, si no None."""
    for campo in ("status", "transcriptionStatus", "renderStatus"):
        val = str(st.get(campo, "")).lower()
        if val in ("failed", "error", "canceled", "cancelled"):
            return f"Submagic reporto {campo}={val}"
    return None


def esperar_download_url(
    project_id: str, progress: ProgressCb | None = None, timeout: float = _POLL_TIMEOUT
) -> str:
    """Poll GET /projects/{id} hasta que aparezca downloadUrl. Lanza si falla/expira."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        st = estado(project_id)
        fallo = _es_fallo(st)
        if fallo:
            raise RuntimeError(fallo)
        url = st.get("downloadUrl") or st.get("outputUrl") or st.get("videoUrl")
        if url:
            return str(url)
        if progress:
            fase = st.get("status") or st.get("transcriptionStatus") or "procesando"
            progress(f"Submagic: {fase}...", -1)
        time.sleep(_POLL_INTERVAL)
    raise TimeoutError(f"Sin downloadUrl tras {int(timeout)}s de espera")


def descargar(url: str, dest: Path) -> int:
    """Descarga el MP4 final a dest. Devuelve bytes escritos."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        total = 0
        with open(dest, "wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 16):
                if chunk:
                    fh.write(chunk)
                    total += len(chunk)
    return total
