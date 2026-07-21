"""H1 · P0-4 — El servidor solo debe bindear loopback en produccion (arranque + __main__)."""

from __future__ import annotations

from pathlib import Path

import app as studio_app

ROOT = Path(__file__).resolve().parents[1]


def test_constante_host_es_loopback():
    assert studio_app.LISTEN_HOST == "127.0.0.1"


def test_app_main_no_bindea_todas_las_interfaces():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    # El bloque de arranque usa la constante loopback y NO deja un 0.0.0.0 literal de produccion.
    assert 'host="0.0.0.0"' not in src
    assert "uvicorn.run(" in src and "host=LISTEN_HOST" in src


def test_arranque_bat_usa_loopback():
    bat = (ROOT / "arranque.bat").read_text(encoding="utf-8")
    assert "--host 127.0.0.1" in bat
    assert "0.0.0.0" not in bat
