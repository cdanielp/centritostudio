"""Tests autocontenidos del arnes de smoke pre-HyperFrames.

Vive bajo revision/ (fuera de `testpaths`), asi que la suite principal NO lo colecta. Se corre a
mano como script:

    .\\venv\\Scripts\\python revision\\pre-hyperframes\\test_smoke_harness.py

o bajo pytest (invocacion directa o el gate H5 futuro):

    .\\venv\\Scripts\\python -m pytest revision\\pre-hyperframes\\test_smoke_harness.py

Cubre las funciones PURAS de clasificacion (el contrato de excepciones) y delega el resto de la
matriz (sandbox real, probes, limpieza) al modo `--self-test` del propio smoke.

IMPORTANTE (pytest): las funciones `test_*` **asertan** (no devuelven bool). Pytest trata un
return no-`None` como warning pero marca el test PASSED igual, asi que un clasificador roto
pasaria inadvertido si el test solo `return ok`. Por eso el summary de script usa el helper
`_run_contrato_checks()` (devuelve bool) y los `test_*` asertan su resultado.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import smoke_pre_hyperframes as sm


def _check(name: str, cond: bool) -> bool:
    print(f"{'[OK]' if cond else '[X ]'} {name}")
    return bool(cond)


def _run_contrato_checks() -> bool:
    """Ejercita el contrato de clasificacion. Devuelve bool (para el summary del modo script)."""
    ok = True
    # Una excepcion interna NUNCA es PASS.
    ok &= _check("exc_no_es_pass", sm.classify_traversal("exception", None, False) == "FAIL")
    ok &= _check("exc_exp_no_es_pass", sm.classify_exposure("exception", None, False) == "FAIL")
    # 5xx -> FAIL.
    ok &= _check("500_fail", sm.classify_traversal("response", 500, False) == "FAIL")
    ok &= _check("503_fail", sm.classify_exposure("response", 503, False) == "FAIL")
    # 4xx sin efecto -> PASS.
    ok &= _check("404_pass", sm.classify_traversal("response", 404, False) == "PASS")
    ok &= _check("400_pass", sm.classify_traversal("response", 400, False) == "PASS")
    # 2xx con escape/exposicion -> BLOCKER.
    ok &= _check("2xx_escape_blocker", sm.classify_traversal("response", 200, True) == "BLOCKER")
    ok &= _check("servido_blocker", sm.classify_exposure("response", 200, True) == "BLOCKER")
    # 2xx SIN escape en payload de traversal -> no es PASS (deberia ser 4xx).
    ok &= _check("2xx_sin_escape_no_pass", sm.classify_traversal("response", 200, False) != "PASS")
    # Rechazo del transporte (no llega al server) -> sin efecto -> PASS.
    ok &= _check("transporte_pass", sm.classify_traversal("transport", None, False) == "PASS")
    # Severidad.
    ok &= _check("worst_blocker", sm.worst(["PASS", "FAIL", "BLOCKER"]) == "BLOCKER")
    ok &= _check("worst_fail", sm.worst(["PASS", "FAIL"]) == "FAIL")

    # Review 8efd294 · un ValueError del server NO se clasifica como transporte (evita falso PASS
    # en el payload NUL byte, que lanza "embedded null character" desde Path).
    def _raise_ve():
        raise ValueError("embedded null character")

    ok &= _check("server_valueerror_es_exception", sm._do_request(_raise_ve)[0] == "exception")
    return ok


def test_contrato_excepciones() -> None:
    """Pytest: aserta (no devuelve) para que un clasificador roto FALLE, no pase con warning."""
    assert _run_contrato_checks(), "contrato de clasificacion del arnes roto"


def test_self_test_verde() -> None:
    """Pytest: la matriz completa del arnes (sandbox/probes/limpieza) debe salir verde."""
    assert sm.self_test() == 0, "self-test del smoke en ROJO"


def main() -> int:
    ok = _run_contrato_checks()
    print("\n--- delegando la matriz completa al self-test del smoke ---")
    st = sm.self_test()
    total_ok = ok and st == 0
    print(f"\n=== TEST HARNESS: {'VERDE' if total_ok else 'ROJO'} ===")
    return 0 if total_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
