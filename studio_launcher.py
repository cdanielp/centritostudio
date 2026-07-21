"""studio_launcher.py — Arranque robusto y diagnosticable de Centrito Studio (H3).

Reemplaza la logica fragil de arranque.bat (que abria el navegador ANTES del server y reventaba
con traceback si el puerto estaba ocupado). Cierra P2-BOOT-3/4/5 desde Python testeable:

  A. Preflight bloqueante: entorno fatal (Python no soportado, venv invalido, import critico
     ausente) -> mensaje accionable + exit != 0. Dependencia OPCIONAL ausente (ffmpeg/modelos)
     -> warning, pero continua (la UI arranca en modo degradado).
  B. Puerto libre -> Uvicorn en 127.0.0.1 (loopback, sin --reload, sin LAN).
  C. Puerto ocupado por otro Centrito Studio -> abre esa instancia, no inicia un segundo server.
  D. Puerto ocupado por otra app -> mensaje accionable, sin traceback, exit != 0.
  E. Navegador: NO se abre antes del server; se sondea /api/system/health y se abre tras el
     primer 200 valido; si el server no queda listo en el timeout -> no abre + mensaje.
  F. Uvicorn: sin --reload en el arranque normal; Ctrl+C limpio; bind error -> mensaje accionable.

Todas las dependencias externas se INYECTAN para tests deterministas (sin abrir puertos, sin red,
sin abrir el navegador ni matar procesos reales).
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
import webbrowser
from collections.abc import Callable
from pathlib import Path

import system_preflight

HOST = "127.0.0.1"  # H1: SIEMPRE loopback. Nunca 0.0.0.0 (sin LAN en esta fase).
PORT = 8787
HEALTH_PATH = "/api/system/health"
DEFAULT_READY_TIMEOUT_S = 30.0
SERVICE_NAME = "Centrito Studio"

# Exit codes
EXIT_OK = 0
EXIT_BLOCKED = 2  # preflight fatal
EXIT_PORT_BUSY = 3  # puerto ocupado por otra app
EXIT_NOT_READY = 4  # el server no quedo listo a tiempo
EXIT_BIND_ERROR = 5  # error de bind al iniciar Uvicorn


def _health_url(host: str = HOST, port: int = PORT) -> str:
    return f"http://{host}:{port}{HEALTH_PATH}"


def _app_url(host: str = HOST, port: int = PORT) -> str:
    return f"http://{host}:{port}/"


# ── Sondas por defecto (inyectables) ──────────────────────────────────────────
def _default_http_get(url: str, timeout: float = 1.0) -> tuple[int, dict | None]:
    """GET simple a loopback. Devuelve (status, json|None). Nunca lanza."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "centrito-launcher"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (loopback)
            body = resp.read()
            status = resp.getcode()
    except Exception:
        return (0, None)
    try:
        return (status, json.loads(body))
    except (ValueError, TypeError):
        return (status, None)


def _default_serve(host: str, port: int) -> None:
    """Arranca Uvicorn (bloqueante) sin --reload. Ctrl+C lo termina limpio."""
    import uvicorn  # noqa: PLC0415

    uvicorn.run("app:app", host=host, port=port, reload=False)


# ── Clasificacion del estado del puerto ───────────────────────────────────────
def classify_port(
    host: str,
    port: int,
    *,
    port_in_use: Callable[[str, int], bool],
    http_get: Callable[[str], tuple[int, dict | None]],
) -> str:
    """'free' | 'centrito' | 'other'.

    Libre -> 'free'. Ocupado y /api/system/health identifica a Centrito Studio -> 'centrito'.
    Ocupado por cualquier otra cosa -> 'other'.
    """
    if not port_in_use(host, port):
        return "free"
    status, body = http_get(_health_url(host, port))
    if status == 200 and isinstance(body, dict) and body.get("service") == SERVICE_NAME:
        return "centrito"
    return "other"


def wait_for_health(
    url: str,
    *,
    http_get: Callable[[str], tuple[int, dict | None]],
    timeout: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    interval: float = 0.4,
) -> bool:
    """Sondea `url` hasta un 200 valido o hasta agotar el timeout. True si quedo listo."""
    inicio = clock()
    while clock() - inicio < timeout:
        status, body = http_get(url)
        if status == 200 and isinstance(body, dict) and body.get("service") == SERVICE_NAME:
            return True
        sleep(interval)
    return False


def open_browser_when_ready(
    app_url: str,
    health_url: str,
    *,
    http_get: Callable[[str], tuple[int, dict | None]],
    open_browser: Callable[[str], None],
    timeout: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    out: Callable[[str], None] = print,
) -> bool:
    """Abre el navegador SOLO tras un health 200. Nunca antes. Se abre a lo sumo UNA vez.

    Devuelve True si abrio; False si el server no quedo listo (no abre, informa).
    """
    if wait_for_health(health_url, http_get=http_get, timeout=timeout, sleep=sleep, clock=clock):
        open_browser(app_url)
        return True
    out(
        "El servidor no respondio a tiempo; no se abrio el navegador. "
        f"Revisa la consola e intenta abrir {app_url} manualmente."
    )
    return False


# ── Orquestacion ──────────────────────────────────────────────────────────────
def run(
    *,
    host: str = HOST,
    port: int = PORT,
    ready_timeout: float = DEFAULT_READY_TIMEOUT_S,
    preflight: Callable[..., dict] = system_preflight.check_environment,
    port_in_use: Callable[[str, int], bool] = system_preflight._default_port_in_use,
    http_get: Callable[[str], tuple[int, dict | None]] = _default_http_get,
    open_browser: Callable[[str], None] = webbrowser.open,
    serve: Callable[[str, int], None] = _default_serve,
    root: Path | None = None,
    out: Callable[[str], None] = print,
) -> int:
    """Arranca el Studio segun el estado de entorno y del puerto. Devuelve un exit code."""
    root = root if root is not None else Path(__file__).resolve().parent

    # A. Preflight bloqueante (solo 'blocked' detiene el arranque).
    report = preflight(root=root)
    if report["status"] == "blocked":
        out("[X] No se puede iniciar Centrito Studio de forma segura:")
        for c in report["checks"]:
            if c["status"] == "error":
                out(f"    - {c['message']}")
                if c["action"]:
                    out(f"      -> {c['action']}")
        return EXIT_BLOCKED
    if report["status"] == "degraded":
        out("[!] Centrito Studio arranca en modo degradado (falta una capacidad opcional):")
        for c in report["checks"]:
            if c["status"] == "warning":
                out(f"    - {c['message']}")

    # B/C/D. Estado del puerto.
    estado = classify_port(host, port, port_in_use=port_in_use, http_get=http_get)
    if estado == "centrito":
        out(
            f"Centrito Studio ya esta ejecutandose en {_app_url(host, port)}; abriendo esa "
            "instancia."
        )
        open_browser(_app_url(host, port))
        return EXIT_OK
    if estado == "other":
        out(f"El puerto {port} esta ocupado por otra aplicacion.")
        out(
            "    Cierra esa aplicacion y reintenta, o inicia en modo diagnostico con otro puerto: "
            "venv\\Scripts\\python.exe studio_launcher.py --port <OTRO_PUERTO>"
        )
        return EXIT_PORT_BUSY

    # E. Navegador: hilo que espera el health y abre despues. Nunca antes del server.
    out(f"Iniciando Centrito Studio en {_app_url(host, port)}")
    hilo = threading.Thread(
        target=open_browser_when_ready,
        args=(_app_url(host, port), _health_url(host, port)),
        kwargs={
            "http_get": http_get,
            "open_browser": open_browser,
            "timeout": ready_timeout,
            "out": out,
        },
        daemon=True,
    )
    hilo.start()

    # F. Uvicorn bloqueante. Ctrl+C limpio; bind error -> mensaje accionable (sin traceback).
    try:
        serve(host, port)
    except OSError:
        out(f"No se pudo iniciar el servidor en {host}:{port} (el puerto podria estar ocupado).")
        return EXIT_BIND_ERROR
    except KeyboardInterrupt:
        out("\nCentrito Studio detenido.")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(description="Arranque de Centrito Studio.")
    parser.add_argument("--port", type=int, default=PORT, help="Puerto (modo diagnostico).")
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_READY_TIMEOUT_S, help="Timeout de health (s)."
    )
    parser.add_argument("--no-browser", action="store_true", help="No abrir el navegador.")
    args = parser.parse_args(argv)

    open_fn = (lambda _url: None) if args.no_browser else webbrowser.open
    return run(port=args.port, ready_timeout=args.timeout, open_browser=open_fn)


if __name__ == "__main__":
    raise SystemExit(main())
