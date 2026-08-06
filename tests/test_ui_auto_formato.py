"""HF-4 Paso 5: el selector de Formato (9:16 / 16:9 / Ambos) expuesto en la UI del Studio.

Leccion de D49 (srt_modo_parcial vivia solo en la API, inalcanzable desde el Studio): un test
que solo verifique que la funcion Python acepta `formato` no detecta que la opcion nunca llego
al HTML. Estos tests fallan si el `<select>` no existe, y tambien si existe pero `startAuto()`
no lo lee (calcado de tests/test_ui_srt_parcial.py, mismo harness Node real).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlparse

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
    return data


def _auto_params(pre=None) -> dict:
    url = json.loads(_run({"fn": "auto_params", "pre": pre or {}})["out"])["url"]
    return parse_qs(urlparse(url).query)


# ─── Contrato estatico: el selector existe, nace en 9:16, en espanol ──────────


def test_existe_el_selector_de_formato():
    assert 'id="auto-formato"' in HTML


def test_el_selector_tiene_las_tres_opciones():
    i = HTML.index('id="auto-formato"')
    bloque = HTML[i : HTML.index("</select>", i)]
    valores = [v for v in ("9:16", "16:9", "ambos") if f'value="{v}"' in bloque]
    assert valores == ["9:16", "16:9", "ambos"]


def test_9x16_es_la_opcion_seleccionada_por_defecto():
    i = HTML.index('value="9:16"')
    etiqueta = HTML[i : HTML.index(">", i) + 1]
    assert "selected" in etiqueta, etiqueta


def test_el_selector_esta_en_espanol():
    i = HTML.index('id="auto-formato"')
    bloque = HTML[max(0, i - 200) : i]
    assert "Formato" in bloque


def test_el_selector_se_bloquea_mientras_corre_una_corrida():
    """Mismo patron que los demas controles de Auto (setAutoControlsLocked)."""
    assert "'auto-video-select','auto-formato'" in HTML


# ─── Comportamiento: el parametro viaja EXPLICITO en el POST ──────────────────


@requires_node
def test_formato_default_viaja_9x16(_=None):
    q = _auto_params()
    assert q.get("formato") == ["9:16"]


@requires_node
def test_formato_ambos_viaja_explicito(_=None):
    q = _auto_params({"formato": "ambos"})
    assert q.get("formato") == ["ambos"]


@requires_node
def test_formato_16x9_viaja_explicito(_=None):
    q = _auto_params({"formato": "16:9"})
    assert q.get("formato") == ["16:9"]


@requires_node
def test_formato_viaja_tambien_en_modo_v2(_=None):
    q = _auto_params({"mode": "v2", "formato": "ambos"})
    assert q.get("mode") == ["v2"]
    assert q.get("formato") == ["ambos"]
