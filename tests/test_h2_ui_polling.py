"""test_h2_ui_polling.py — Gate DOM del cableado de polling en `static/index.html` (H2).

Ejecuta el JS REAL del bundle en el sandbox `vm` (`ui_render_harness.cjs`, que ya inyecta el
motor real `job_polling.js`) para verificar los estados ACCIONABLES y la accesibilidad:
  - renderJobFailureUI: role=alert, mensaje, botones correctos por causa, Reintentar/Cancelar.
  - trackJob: región viva role=status/aria-live mientras corre.
Más aserciones estáticas del contrato (sin setInterval en reframe, motor compartido, pollJobP
estructurado). Node ausente -> skip declarado (no oculta bugs).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
HARNESS = Path(__file__).parent / "ui_render_harness.cjs"
NODE = shutil.which("node")

requires_node = pytest.mark.skipif(NODE is None, reason="Node no disponible para el harness de UI")


def _run(fixture: dict) -> dict:
    proc = subprocess.run(
        [NODE, str(HARNESS), str(ROOT / "static" / "index.html")],
        input=json.dumps(fixture),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert proc.returncode == 0, f"harness fallo: {proc.stderr}"
    data = json.loads(proc.stdout)
    assert not data["initerr"], f"init error: {data['initerr']}"
    assert not data["err"], f"call error: {data['err']}"
    return json.loads(data["out"])


# ─── Contrato estático ─────────────────────────────────────────────────────────
def test_index_carga_el_motor_compartido():
    assert '<script src="/static/job_polling.js"></script>' in HTML
    assert "CentritoJobPolling.createPoller()" in HTML


def test_reframe_sin_setinterval_fugado():
    # _pollReframe ya NO usa setInterval (P1-POLL-2): usa el motor compartido vía trackJob.
    start = HTML.index("function _pollReframe(")
    end = HTML.index("async function startReframe(")
    cuerpo = HTML[start:end]
    assert "setInterval" not in cuerpo, "reframe sigue con setInterval fugado"
    assert "trackJob(" in cuerpo


def test_no_quedan_bucles_de_polling_crudos():
    # Ningún setInterval que consulte /api/jobs; el único polling es el motor compartido.
    assert "setInterval(async" not in HTML
    # pollJob/pollJobP delegan en el poller único (no re-implementan el fetch+setTimeout).
    assert "jobPoller.track(" in HTML


def test_polljobp_devuelve_estructura_no_booleano():
    # POLL-7: los consumidores leen .ok / .job.message (causa exacta), no un booleano pelado.
    assert "if (r.ok) {" in HTML or "if (transc.ok) {" in HTML
    assert "r.job && r.job.message" in HTML or "transc.job && transc.job.message" in HTML


# ─── Estados accionables (role=alert + botones) ────────────────────────────────
@requires_node
def test_failui_unavailable_reintentar_y_cancelar():
    st = _run(
        {"fn": "failui", "res": {"reason": "unavailable", "message": "Se perdió la conexión"}}
    )
    assert st["role"] == "alert"
    assert st["labels"] == ["Reintentar conexión", "Cancelar seguimiento"]


@requires_node
def test_failui_reintentar_reconsulta_mismo_job():
    st = _run(
        {
            "fn": "failui",
            "res": {"reason": "unavailable", "message": "x"},
            "clickLabel": "Reintentar conexión",
        }
    )
    assert st["retried"] == 1 and st["dismissed"] == 0


@requires_node
def test_failui_timeout_seguir_esperando():
    st = _run({"fn": "failui", "res": {"reason": "timeout"}})
    assert st["role"] == "alert"
    assert st["labels"] == ["Seguir esperando", "Cancelar seguimiento"]
    assert "tardando" in st["msg"]


@requires_node
def test_failui_timeout_seguir_esperando_crea_sesion_nueva_sin_job():
    st = _run({"fn": "failui", "res": {"reason": "timeout"}, "clickLabel": "Seguir esperando"})
    assert st["retried"] == 1  # deadline nuevo sobre el MISMO job, sin crear otro


@requires_node
def test_failui_lost_no_ofrece_reintento_infinito():
    st = _run({"fn": "failui", "res": {"reason": "lost"}})
    assert st["role"] == "alert"
    assert st["labels"] == ["Entendido"]  # el job ya no existe: sin Reintentar
    assert "reinició" in st["msg"] or "ya no existe" in st["msg"]


@requires_node
def test_failui_cancelar_seguimiento_no_reintenta():
    st = _run(
        {
            "fn": "failui",
            "res": {"reason": "unavailable", "message": "x"},
            "clickLabel": "Cancelar seguimiento",
        }
    )
    assert st["dismissed"] == 1 and st["retried"] == 0


# ─── Accesibilidad: región viva mientras corre ─────────────────────────────────
@requires_node
def test_trackjob_marca_region_viva():
    st = _run({"fn": "trackaria"})
    assert st["role"] == "status"
    assert st["ariaLive"] == "polite"
    assert st["hasPoller"] is True
