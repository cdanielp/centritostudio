"""test_ui_auto_failed_clips.py — Política de tarjetas de clip fallido en Auto (S36-C2B, P2).

Un clip con `status="error"` NUNCA es publicable: ni en classic ni en v2 (con o sin SRT) debe
mostrar descarga, botón de Editor, ruta ni estado "Listo". Se ejecuta el JS REAL de
`static/index.html` en un sandbox `vm` de Node (sin Playwright) vía `ui_render_harness.cjs`.
Si Node no está disponible, los tests conductuales se saltan (skip declarado, no oculta bugs).
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
        encoding="utf-8",  # node emite UTF-8; no dejar que Windows decodifique en cp1252
        timeout=60,
    )
    assert proc.returncode == 0, f"harness fallo: {proc.stderr}"
    out = json.loads(proc.stdout)
    assert not out["initerr"], f"init error: {out['initerr']}"
    return out


def _card(clip: dict, *, v2: bool, i: int = 0, pkg: str = "demo_pkg") -> str:
    out = _run({"fn": "clip", "clip": clip, "i": i, "pkgId": pkg, "v2": v2})
    assert not out["err"], f"render error: {out['err']}"
    return json.loads(out["ret"])["html"]


_OK_V2 = {
    "titulo": "Bien",
    "archivo": "ok.mp4",
    "score": 90,
    "dur_s": 5.0,
    "broll": {},
    "fx": {},
    "av": {},
    "pipeline_mode": "v2",
}
_OK_CLASSIC = {
    "titulo": "Bien",
    "archivo": "ok.mp4",
    "score": 88,
    "dur_s": 5.0,
    "emojis_msg": "2 emojis",
}
_ERR = {"titulo": "Malo", "archivo": "boom.mp4", "status": "error", "dur_s": 4.0}


def _assert_safe_failed(html: str) -> None:
    """Una tarjeta de fallo nunca expone descarga, Editor, ruta/output ni estado Listo."""
    assert "Falló el render" in html
    assert "Descargar" not in html and "download" not in html
    assert "Editor" not in html  # ni "Abrir paquete en Editor" ni "Abrir en el Editor"
    assert "boom.mp4" not in html  # sin output/ruta del clip fallido
    assert "/api/paquetes/" not in html
    assert "Listo" not in html


# ─── Contrato estático: política compartida antes de decidir pipeline ──────────
def test_existe_dispatcher_de_politica_unica():
    assert "function renderAutoClip(" in HTML
    # renderAutoResult enruta por el dispatcher, no por v2?v2card:classiccard directo.
    assert "renderAutoClip(c" in HTML
    assert "v2 ? renderAutoV2Clip(c,i,pkgId) : renderAutoClassicClip(c,i,pkgId)" not in HTML


def test_dispatcher_chequea_error_antes_de_pipeline():
    # El check de error debe ocurrir dentro del dispatcher (política única).
    frag = HTML[HTML.index("function renderAutoClip(") :]
    frag = frag[: frag.index("\n}") + 2]
    assert "status === 'error'" in frag and "renderAutoFailedClip" in frag


# ─── Conductual: v2 + error (con y sin SRT) ─────────────────────────────────────
@requires_node
def test_v2_srt_clip_error_es_tarjeta_segura():
    clip = dict(_ERR, caption_source="srt", pipeline_mode="v2")
    _assert_safe_failed(_card(clip, v2=True))


@requires_node
def test_v2_transcript_clip_error_misma_politica_segura():
    clip = dict(_ERR, pipeline_mode="v2")  # sin SRT
    _assert_safe_failed(_card(clip, v2=True))


@requires_node
def test_classic_clip_error_sigue_seguro():
    _assert_safe_failed(_card(_ERR, v2=False))


# ─── Conductual: clips exitosos conservan sus acciones ─────────────────────────
@requires_node
def test_v2_exitoso_conserva_editor_y_descarga():
    html = _card(_OK_V2, v2=True)
    assert "AUTO V2" in html
    assert "Abrir paquete en Editor" in html
    assert "Descargar" in html and "ok.mp4" in html


@requires_node
def test_classic_exitoso_conserva_descarga():
    html = _card(_OK_CLASSIC, v2=False)
    assert "Descargar" in html and "ok.mp4" in html
    assert "Falló el render" not in html


# ─── Integración: renderAutoResult v2 con fallo parcial ────────────────────────
@requires_node
def test_result_v2_parcial_aisla_el_fallido_y_ofrece_reanudar():
    result = {
        "resumen": "2 clips; 1 falló.",
        "paquete": "output/paquetes/demo_v2_20260720",
        "meta": {"pipeline_mode": "v2"},
        "clips": [dict(_OK_V2), dict(_ERR)],
    }
    out = _run({"fn": "result", "result": result})
    assert not out["err"], out["err"]
    clips = out["clips"]
    assert "Falló el render" in clips  # el fallido se muestra como error (bug: iba a v2 normal)
    # El fallido NO es descargable: su archivo no aparece; el exitoso sí.
    assert "boom.mp4" not in clips and "ok.mp4" in clips
    # Solo el clip exitoso ofrece Editor (1 sola vez).
    assert clips.count("Abrir paquete en Editor") == 1
    # Permanece disponible la reanudación de fallidos.
    assert "Reanudar clips fallidos" in out["resume"]


@requires_node
def test_result_v2_todo_ok_sin_boton_reanudar():
    result = {
        "resumen": "2 clips OK.",
        "paquete": "output/paquetes/demo_v2_20260720",
        "meta": {"pipeline_mode": "v2"},
        "clips": [dict(_OK_V2), dict(_OK_V2, archivo="ok2.mp4")],
    }
    out = _run({"fn": "result", "result": result})
    assert not out["err"], out["err"]
    assert "Falló el render" not in out["clips"]
    assert "Reanudar clips fallidos" not in out["resume"]
