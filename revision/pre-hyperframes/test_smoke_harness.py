"""Tests autocontenidos del arnes de smoke pre-HyperFrames.

Vive bajo revision/ (fuera de `testpaths`), asi que la suite principal NO lo colecta. Se corre a
mano para validar el propio arnes sin depender de red/GPU:

    .\\venv\\Scripts\\python revision\\pre-hyperframes\\test_smoke_harness.py

Cubre las funciones PURAS de clasificacion (el contrato de excepciones) y delega el resto de la
matriz (sandbox real, probes, limpieza) al modo `--self-test` del propio smoke.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import smoke_pre_hyperframes as sm


def _assert(name: str, cond: bool) -> bool:
    print(f"{'[OK]' if cond else '[X ]'} {name}")
    return bool(cond)


def test_contrato_excepciones() -> bool:
    ok = True
    # Una excepcion interna NUNCA es PASS.
    ok &= _assert("exc_no_es_pass", sm.classify_traversal("exception", None, False) == "FAIL")
    ok &= _assert(
        "exc_exposure_no_es_pass", sm.classify_exposure("exception", None, False) == "FAIL"
    )
    # 5xx -> FAIL.
    ok &= _assert("500_fail", sm.classify_traversal("response", 500, False) == "FAIL")
    ok &= _assert("503_fail", sm.classify_exposure("response", 503, False) == "FAIL")
    # 4xx sin efecto -> PASS.
    ok &= _assert("404_pass", sm.classify_traversal("response", 404, False) == "PASS")
    ok &= _assert("400_pass", sm.classify_traversal("response", 400, False) == "PASS")
    # 2xx con escape/exposicion -> BLOCKER.
    ok &= _assert("2xx_escape_blocker", sm.classify_traversal("response", 200, True) == "BLOCKER")
    ok &= _assert("servido_blocker", sm.classify_exposure("response", 200, True) == "BLOCKER")
    # 2xx SIN escape en payload de traversal -> no es PASS (deberia ser 4xx).
    ok &= _assert("2xx_sin_escape_no_pass", sm.classify_traversal("response", 200, False) != "PASS")
    # Rechazo del transporte (no llega al server) -> sin efecto -> PASS.
    ok &= _assert("transporte_pass", sm.classify_traversal("transport", None, False) == "PASS")
    # Severidad.
    ok &= _assert("worst_blocker", sm.worst(["PASS", "FAIL", "BLOCKER"]) == "BLOCKER")
    ok &= _assert("worst_fail", sm.worst(["PASS", "FAIL"]) == "FAIL")
    return ok


def main() -> int:
    ok = test_contrato_excepciones()
    print("\n--- delegando la matriz completa al self-test del smoke ---")
    st = sm.self_test()
    total_ok = ok and st == 0
    print(f"\n=== TEST HARNESS: {'VERDE' if total_ok else 'ROJO'} ===")
    return 0 if total_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
