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
    # H3: el bind loopback migro del .bat al launcher (studio_launcher.py). arranque.bat delega
    # en el launcher y NO deja un 0.0.0.0. La garantia loopback se prueba en studio_launcher.HOST.
    bat = (ROOT / "arranque.bat").read_text(encoding="utf-8")
    assert "studio_launcher.py" in bat
    assert "0.0.0.0" not in bat


def test_launcher_bindea_loopback():
    import studio_launcher

    assert studio_launcher.HOST == "127.0.0.1"
    src = (ROOT / "studio_launcher.py").read_text(encoding="utf-8")
    # Sin bind literal a todas las interfaces (el comentario que menciona 0.0.0.0 es informativo).
    assert 'host="0.0.0.0"' not in src
    assert '"0.0.0.0"' not in src.replace("Nunca 0.0.0.0", "")
