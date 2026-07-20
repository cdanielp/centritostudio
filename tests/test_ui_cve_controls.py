"""test_ui_cve_controls.py — Controles CVE minimos en Render (F6 esencial, PASO F).

Ejecuta el JS REAL de static/index.html en el sandbox `vm` (ui_render_harness.cjs):
- Con preset + transcript, densidad/position/avoid_faces se envian en el POST /render.
- Sin preset no se envian (el backend los ignoraria).
- Con SRT los controles CVE F6 se ocultan y NO se envian (respeta incompatibilidad SRT).
- La UI explica los controles y no expone rutas/JSON/tracebacks.
Si Node no esta disponible, se salta (skip declarado).
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


def _render(source: str, pre: dict) -> dict:
    return _run({"fn": "render_params", "source": source, "pre": pre})


def _preset_defaults(pre: dict) -> dict:
    return _run({"fn": "preset_defaults", "pre": pre})


_CVE_PRESETS_META = [
    {"id": "clean_podcast", "position_default": "bottom", "avoid_faces_default": True},
    {"id": "custom_top", "position_default": "top", "avoid_faces_default": False},
]


# ─── Contrato estatico (existe UI + textos, sin rutas/JSON) ─────────────────────


def test_existe_bloque_cve_f6_con_explicacion():
    assert 'id="field-cve-f6"' in HTML
    assert 'id="render-densidad"' in HTML
    assert 'id="render-position"' in HTML
    assert 'id="use-avoid-faces"' in HTML
    assert 'id="render-keywords"' in HTML
    # explica brevemente cada control
    assert "Evitar tapar caras" in HTML
    assert "Palabras o frases a destacar" in HTML


def test_no_expone_rutas_ni_json_interno():
    # La UI no filtra el nombre del sidecar manual, la trayectoria del reframe ni tracebacks
    assert "_keywords.json" not in HTML
    assert "trayectoria_" not in HTML
    assert "Traceback" not in HTML


# ─── Params enviados ────────────────────────────────────────────────────────────


@requires_node
def test_transcript_con_preset_envia_controles_cve():
    out = _render(
        "transcript",
        {"preset": "keyword_punch", "densidad": "alta", "position": "center", "avoidFaces": False},
    )
    url = out["url"]
    assert "preset=keyword_punch" in url
    assert "densidad=alta" in url
    assert "position=center" in url
    assert "avoid_faces=false" in url


@requires_node
def test_avoid_faces_default_true_se_envia():
    out = _render("transcript", {"preset": "keyword_punch"})
    assert "avoid_faces=true" in out["url"]


@requires_node
def test_sin_preset_no_envia_controles_cve():
    out = _render("transcript", {})
    url = out["url"]
    assert "densidad=" not in url
    assert "position=" not in url
    assert "avoid_faces=" not in url


# ─── BLOQUEO 4: onPresetChange inicializa los controles con defaults del preset ──


@requires_node
def test_preset_custom_inicializa_position_y_avoid_faces():
    # preset con default top + avoid_faces false: los controles se inicializan a eso
    out = _preset_defaults({"cvePresets": _CVE_PRESETS_META, "preset": "custom_top"})
    assert out["position"] == "top"
    assert out["avoid_faces"] is False


@requires_node
def test_preset_builtin_inicializa_bottom_y_avoid_true():
    out = _preset_defaults({"cvePresets": _CVE_PRESETS_META, "preset": "clean_podcast"})
    assert out["position"] == "bottom"
    assert out["avoid_faces"] is True


@requires_node
def test_cambiar_de_preset_actualiza_los_controles():
    # cambiar de custom_top a clean_podcast reinicia los controles al default del nuevo
    a = _preset_defaults({"cvePresets": _CVE_PRESETS_META, "preset": "custom_top"})
    b = _preset_defaults({"cvePresets": _CVE_PRESETS_META, "preset": "clean_podcast"})
    assert (a["position"], a["avoid_faces"]) == ("top", False)
    assert (b["position"], b["avoid_faces"]) == ("bottom", True)


@requires_node
def test_srt_oculta_f6_y_no_envia_cve():
    out = _render("srt", {"preset": "keyword_punch", "densidad": "alta", "position": "center"})
    url = out["url"]
    assert out["f6_hidden"] is True
    assert "densidad=" not in url
    assert "position=" not in url
    assert "avoid_faces=" not in url
    assert "caption_source=srt" in url
