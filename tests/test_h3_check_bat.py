"""test_h3_check_bat.py — Contrato de check.bat y arranque.bat (H3, FASE 11.E).

Aserciones estaticas sobre los .bat: guards, preflight, sin rutas privadas, sin 0.0.0.0.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
CHECK = (ROOT / "check.bat").read_text(encoding="utf-8")
ARRANQUE = (ROOT / "arranque.bat").read_text(encoding="utf-8")


# ── check.bat ────────────────────────────────────────────────────────────────
def test_check_tiene_guard_de_venv():
    assert 'if not exist "%PY%"' in CHECK
    assert "venv\\Scripts\\python.exe" in CHECK


def test_check_ejecuta_preflight_estricto():
    assert "system_preflight --strict-local" in CHECK
    assert "entorno" in CHECK.lower()


def test_check_conserva_ruff_format_pytest():
    assert "ruff check ." in CHECK
    assert "ruff format --check" in CHECK
    assert "pytest" in CHECK


def test_check_no_usa_video_privado():
    # check.bat no debe referenciar ningun fixture de video real (p. ej. input/archivo_privado.srt);
    # solo puede usar su fixture SINTETICO _smoke_synth generado con ffmpeg/lavfi.
    fixtures = re.findall(r"input[\\/]([\w.-]+)\.(?:srt|mp4|mov)", CHECK, re.IGNORECASE)
    assert all("_smoke_synth" in f for f in fixtures), fixtures
    assert "tacosjuan" not in CHECK  # nombre no versionado del smoke anterior


def test_check_full_usa_fixture_sintetico():
    assert "_smoke_synth" in CHECK
    assert "lavfi" in CHECK  # se genera con ffmpeg, sin datos privados


def test_check_no_expone_0000():
    assert "0.0.0.0" not in CHECK


# ── arranque.bat ─────────────────────────────────────────────────────────────
def test_arranque_es_wrapper_minimo_con_guard():
    assert 'if not exist "%PY%"' in ARRANQUE
    assert "studio_launcher.py" in ARRANQUE


def test_arranque_no_usa_activate_ni_reload_ni_lan():
    assert "activate.bat" not in ARRANQUE
    assert "--reload" not in ARRANQUE
    assert "0.0.0.0" not in ARRANQUE


def test_arranque_no_abre_navegador_directo():
    # El navegador lo abre studio_launcher.py DESPUES del health; el .bat no debe usar `start ""`.
    assert 'start "" "http' not in ARRANQUE
