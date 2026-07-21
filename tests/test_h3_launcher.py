"""test_h3_launcher.py — Arranque robusto (H3, FASE 11.D).

Todo inyectado: sin abrir puertos reales, sin red, sin abrir el navegador ni matar procesos.
"""

from __future__ import annotations

import threading

import studio_launcher as sl

READY = (200, {"status": "ready", "service": "Centrito Studio"})
NOT_READY = (0, None)
OTRA_APP = (200, {"hola": "mundo"})


def _preflight(status="ready"):
    def _p(**_k):
        checks = []
        if status == "blocked":
            checks = [
                {
                    "id": "python",
                    "status": "error",
                    "message": "Python 3.11 no soportado.",
                    "action": "py -3.12 -m venv venv",
                    "required_for": ["ui"],
                }
            ]
        return {"status": status, "checks": checks, "capabilities": {}}

    return _p


# ── classify_port ──────────────────────────────────────────────────────────────
def test_classify_puerto_libre():
    estado = sl.classify_port(
        "127.0.0.1", 8787, port_in_use=lambda h, p: False, http_get=lambda u: NOT_READY
    )
    assert estado == "free"


def test_classify_puerto_ocupado_por_centrito():
    estado = sl.classify_port(
        "127.0.0.1", 8787, port_in_use=lambda h, p: True, http_get=lambda u: READY
    )
    assert estado == "centrito"


def test_classify_puerto_ocupado_por_otra_app():
    estado = sl.classify_port(
        "127.0.0.1", 8787, port_in_use=lambda h, p: True, http_get=lambda u: OTRA_APP
    )
    assert estado == "other"


# ── wait_for_health ────────────────────────────────────────────────────────────
def test_wait_for_health_tarda_y_luego_responde():
    respuestas = [NOT_READY, NOT_READY, READY]

    def _get(_u):
        return respuestas.pop(0)

    t = [0.0]

    def _clock():
        t[0] += 0.1
        return t[0]

    ok = sl.wait_for_health(
        "http://x/health",
        http_get=_get,
        timeout=5.0,
        sleep=lambda _s: None,
        clock=_clock,
        interval=0.01,
    )
    assert ok is True


def test_wait_for_health_nunca_responde():
    t = [0.0]

    def _clock():
        t[0] += 1.0
        return t[0]

    ok = sl.wait_for_health(
        "http://x/health",
        http_get=lambda u: NOT_READY,
        timeout=3.0,
        sleep=lambda _s: None,
        clock=_clock,
        interval=0.01,
    )
    assert ok is False


# ── open_browser_when_ready ────────────────────────────────────────────────────
def test_navegador_abre_solo_tras_health_200():
    abiertos = []
    ok = sl.open_browser_when_ready(
        "http://app/",
        "http://app/health",
        http_get=lambda u: READY,
        open_browser=abiertos.append,
        timeout=2.0,
        sleep=lambda _s: None,
        clock=lambda: 0.0,
        out=lambda _m: None,
    )
    assert ok is True and abiertos == ["http://app/"]  # abre EXACTAMENTE una vez


def test_navegador_no_abre_si_health_no_responde():
    abiertos = []
    t = [0.0]

    def _clock():
        t[0] += 1.0
        return t[0]

    ok = sl.open_browser_when_ready(
        "http://app/",
        "http://app/health",
        http_get=lambda u: NOT_READY,
        open_browser=abiertos.append,
        timeout=2.0,
        sleep=lambda _s: None,
        clock=_clock,
        out=lambda _m: None,
    )
    assert ok is False and abiertos == []


# ── run(): control de flujo ─────────────────────────────────────────────────────
def test_run_preflight_blocked_no_arranca_ni_abre(tmp_path):
    servido = []
    abiertos = []
    rc = sl.run(
        preflight=_preflight("blocked"),
        port_in_use=lambda h, p: False,
        http_get=lambda u: NOT_READY,
        open_browser=abiertos.append,
        serve=lambda h, p: servido.append((h, p)),
        root=tmp_path,
        out=lambda _m: None,
    )
    assert rc == sl.EXIT_BLOCKED and servido == [] and abiertos == []


def test_run_puerto_ocupado_por_centrito_abre_esa_instancia(tmp_path):
    servido = []
    abiertos = []
    rc = sl.run(
        preflight=_preflight("ready"),
        port_in_use=lambda h, p: True,
        http_get=lambda u: READY,
        open_browser=abiertos.append,
        serve=lambda h, p: servido.append((h, p)),
        root=tmp_path,
        out=lambda _m: None,
    )
    assert rc == sl.EXIT_OK and servido == []  # no inicia un segundo server
    assert abiertos == ["http://127.0.0.1:8787/"]


def test_run_puerto_ocupado_por_otra_app_mensaje_accionable(tmp_path):
    servido = []
    abiertos = []
    salida = []
    rc = sl.run(
        preflight=_preflight("ready"),
        port_in_use=lambda h, p: True,
        http_get=lambda u: OTRA_APP,
        open_browser=abiertos.append,
        serve=lambda h, p: servido.append((h, p)),
        root=tmp_path,
        out=salida.append,
    )
    assert rc == sl.EXIT_PORT_BUSY and servido == [] and abiertos == []
    assert any("ocupado por otra aplicacion" in m for m in salida)


def test_run_puerto_libre_arranca_en_loopback(tmp_path):
    servido = []
    abiertos = []
    listo = threading.Event()

    def _serve(host, port):
        servido.append((host, port))
        listo.wait(timeout=2.0)  # espera a que el hilo del navegador termine

    def _open(url):
        abiertos.append(url)
        listo.set()

    rc = sl.run(
        preflight=_preflight("ready"),
        port_in_use=lambda h, p: False,
        http_get=lambda u: READY,
        open_browser=_open,
        serve=_serve,
        ready_timeout=2.0,
        root=tmp_path,
        out=lambda _m: None,
    )
    assert rc == sl.EXIT_OK
    assert servido == [("127.0.0.1", 8787)]  # SIEMPRE loopback, nunca 0.0.0.0
    assert abiertos == ["http://127.0.0.1:8787/"]  # y una sola vez


def test_run_bind_error_mensaje_sin_traceback(tmp_path):
    salida = []

    def _serve(h, p):
        raise OSError("address in use")

    rc = sl.run(
        preflight=_preflight("ready"),
        port_in_use=lambda h, p: False,
        http_get=lambda u: NOT_READY,
        open_browser=lambda u: None,
        serve=_serve,
        ready_timeout=0.1,
        root=tmp_path,
        out=salida.append,
    )
    assert rc == sl.EXIT_BIND_ERROR
    assert any("No se pudo iniciar el servidor" in m for m in salida)


def test_run_ctrl_c_limpio(tmp_path):
    def _serve(h, p):
        raise KeyboardInterrupt

    rc = sl.run(
        preflight=_preflight("ready"),
        port_in_use=lambda h, p: False,
        http_get=lambda u: NOT_READY,
        open_browser=lambda u: None,
        serve=_serve,
        ready_timeout=0.1,
        root=tmp_path,
        out=lambda _m: None,
    )
    assert rc == sl.EXIT_OK


def test_host_siempre_loopback():
    assert sl.HOST == "127.0.0.1"
