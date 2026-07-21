"""test_h2_job_polling_js.py — Ejecuta la suite Node del motor REAL `static/job_polling.js`.

Corre el harness `tests/job_polling_harness.cjs` (fetch/timers/reloj/AbortController inyectables)
sobre el archivo real y falla si Node devuelve un código != 0 o si algún caso del motor falla.
No hay red ni datos privados. Si Node no está disponible se salta (mismo patrón de skip conocido
que el resto de tests de UI); NO oculta bugs porque el motor no depende de que el JS sea inseguro.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
HARNESS = Path(__file__).parent / "job_polling_harness.cjs"
ENGINE = ROOT / "static" / "job_polling.js"
NODE = shutil.which("node")

requires_node = pytest.mark.skipif(
    NODE is None, reason="Node no disponible para el harness del poller"
)


def test_existe_el_motor_compartido():
    # Contrato estático: el archivo real existe y expone el punto de entrada del navegador.
    src = ENGINE.read_text(encoding="utf-8")
    assert "CentritoJobPolling" in src
    assert "module.exports" in src
    for terminal in (
        "done",
        "job_error",
        "lost",
        "unavailable",
        "timeout",
        "cancelled",
        "invalid_response",
    ):
        assert terminal in src, f"falta el estado terminal {terminal}"


@requires_node
def test_motor_de_polling_pasa_toda_la_suite_node():
    proc = subprocess.run(
        [NODE, str(HARNESS), str(ENGINE)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    # El harness sale != 0 si algún caso del motor falla: eso DEBE tumbar este test.
    assert proc.returncode == 0, (
        f"harness Node falló (rc={proc.returncode}):\n{proc.stdout}\n{proc.stderr}"
    )
    data = json.loads(proc.stdout)
    assert data["ok"] is True, f"casos fallidos: {[r for r in data['results'] if not r['pass']]}"
    assert data["passed"] == data["total"] and data["total"] >= 20, data
