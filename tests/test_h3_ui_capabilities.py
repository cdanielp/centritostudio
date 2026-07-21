"""test_h3_ui_capabilities.py — UI en modo degradado (H3, FASE 11.F).

Aserciones estaticas del bundle + gate de comportamiento del modulo REAL system_capabilities.js
ejecutado en Node (harness). Node ausente -> skip declarado (no oculta bugs).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
HARNESS = Path(__file__).parent / "ui_capabilities_harness.cjs"
NODE = shutil.which("node")
requires_node = pytest.mark.skipif(NODE is None, reason="Node no disponible para el harness de UI")


def _run(fixture: dict) -> dict:
    proc = subprocess.run(
        [NODE, str(HARNESS)],
        input=json.dumps(fixture),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert proc.returncode == 0, f"harness fallo: {proc.stderr}"
    return json.loads(proc.stdout)


_READY = {
    "ffmpeg": {"available": True, "message": "ok"},
    "ffprobe": {"available": True, "message": "ok"},
    "render": {"available": True, "message": "ok"},
    "auto": {"available": True, "message": "ok"},
    "upload_validation": {"available": True, "message": "ok"},
    "reframe": {"available": True, "message": "ok"},
    "detector_yunet": {"available": True},
    "detector_blazeface": {"available": True},
}


def _degradado_sin_ffmpeg():
    d = json.loads(json.dumps(_READY))
    d["ffmpeg"] = {"available": False, "message": "FFmpeg no esta instalado."}
    d["render"] = {"available": False, "message": "Requiere ffmpeg y ffprobe."}
    d["auto"] = {"available": False, "message": "Requiere ffmpeg y ffprobe."}
    d["reframe"] = {"available": False, "message": "Requiere ffmpeg, ffprobe y un detector."}
    return d


# ── Estatico ────────────────────────────────────────────────────────────────────
def test_index_carga_modulo_de_capacidades():
    assert '<script src="/static/system_capabilities.js"></script>' in HTML
    assert "CentritoCapabilities.applyCapabilities" in HTML


def test_index_tiene_banner_y_consulta_capabilities():
    assert 'id="system-banner"' in HTML
    assert "fetch('/api/system/capabilities')" in HTML


def test_index_controles_afectados_tienen_data_cap():
    assert 'data-cap="render"' in HTML
    assert 'data-cap="auto"' in HTML
    assert 'data-cap="upload_validation"' in HTML
    assert 'data-cap="reframe"' in HTML


def test_uploadfile_gatea_por_capacidad_cacheada():
    # El drop zone llama uploadFile directo; el guard debe cubrir click Y arrastrar-soltar.
    frag = HTML[HTML.index("async function uploadFile") :]
    frag = frag[: frag.index("const prog")]
    assert "_systemCaps" in frag and "upload_validation" in frag


def test_reaplica_capacidades_tras_render_de_clips():
    # Los botones "Reencuadrar 9:16" se crean dinamicamente -> hay que re-gatearlos.
    frag = HTML[HTML.index("function renderClipsCards") :]
    frag = frag[: frag.index("\nfunction setLayoutMode")]
    assert "applyCaps()" in frag


def test_consulta_capabilities_en_try_catch():
    # El fallo al consultar NO debe romper la UI: la funcion envuelve el fetch en try/catch.
    frag = HTML[HTML.index("async function checkSystemCapabilities") :]
    frag = frag[: frag.index("\n}")]
    assert "try" in frag and "catch" in frag


# ── Comportamiento (Node) ────────────────────────────────────────────────────────
@requires_node
def test_ready_todo_habilitado_y_banner_oculto():
    out = _run(
        {
            "caps": _READY,
            "elements": [
                {"data-cap": "render"},
                {"data-cap": "auto"},
                {"data-cap": "upload_validation"},
                {"data-cap": "reframe"},
            ],
        }
    )
    assert all(e["disabled"] is False for e in out["elements"])
    assert out["banner"]["hidden"] is True


@requires_node
def test_degradado_deshabilita_afectados_y_deja_los_demas():
    out = _run(
        {
            "caps": _degradado_sin_ffmpeg(),
            "elements": [
                {"data-cap": "render"},
                {"data-cap": "reframe"},
                {"data-cap": "upload_validation"},
            ],
        }
    )
    by_cap = {e["cap"]: e for e in out["elements"]}
    assert by_cap["render"]["disabled"] is True
    assert by_cap["reframe"]["disabled"] is True
    assert by_cap["upload_validation"]["disabled"] is False  # ffprobe sigue -> no afectado


@requires_node
def test_degradado_aviso_aria_y_mensaje_saneado():
    out = _run({"caps": _degradado_sin_ffmpeg(), "elements": [{"data-cap": "render"}]})
    assert out["banner"]["hidden"] is False
    assert out["banner"]["role"] == "status"
    assert "Modo degradado" in out["banner"]["text"]
    # Sin rutas absolutas ni secretos en el aviso.
    assert ":\\" not in out["banner"]["text"] and "C:/" not in out["banner"]["text"]


@requires_node
def test_control_deshabilitado_tiene_explicacion_accesible():
    out = _run({"caps": _degradado_sin_ffmpeg(), "elements": [{"data-cap": "render"}]})
    el = out["elements"][0]
    assert el["ariaDisabled"] == "true"
    assert el["title"] and "ffmpeg" in el["title"].lower()


@requires_node
def test_caps_null_no_rompe_la_ui():
    # Fallo al consultar capabilities -> caps null: no lanza, no deshabilita, banner oculto.
    out = _run({"caps": None, "elements": [{"data-cap": "render"}]})
    assert out["elements"][0]["disabled"] is False
    assert out["banner"]["hidden"] is True
