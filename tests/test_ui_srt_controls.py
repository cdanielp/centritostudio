"""test_ui_srt_controls.py — Política de controles incompatibles con SRT en Render (S36-C2B).

Con Fuente de captions = SRT, los cues definen agrupación y texto oficial: Palabras por grupo,
Énfasis IA y Caption QA se deshabilitan de verdad (atributo disabled) y se restauran al default
seguro; esos parámetros NO se envían. Estilo/Preset/Intensidad/Emojis y las acciones SRT siguen
disponibles. Volver a Transcript reactiva los controles sin reponer valores previos inválidos.

Se ejecuta el JS REAL de `static/index.html` en un sandbox `vm` de Node (`ui_render_harness.cjs`).
Si Node no está disponible, se saltan (skip declarado, no oculta bugs).
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
    return data


def _controls(steps, pre=None) -> dict:
    return json.loads(_run({"fn": "controls", "steps": steps, "pre": pre or {}})["out"])


def _render_url(source: str, pre=None) -> str:
    return json.loads(_run({"fn": "render_params", "source": source, "pre": pre or {}})["out"])[
        "url"
    ]


# ─── Contrato estático ─────────────────────────────────────────────────────────
def test_existe_politica_y_texto_explicativo():
    assert "_setRenderIncompatible(" in HTML
    assert "Énfasis IA y Caption QA no están disponibles." in HTML
    assert 'id="render-srt-incompat"' in HTML


# ─── SRT deshabilita y limpia los controles incompatibles ──────────────────────
@requires_node
def test_srt_deshabilita_palabras_por_grupo():
    st = _controls(["srt"], pre={"wpg": "3"})
    assert st["wpg_disabled"] is True
    assert st["wpg_value"] == ""  # restaurado al default seguro
    assert st["field_wpg_dis"] is True


@requires_node
def test_srt_deshabilita_y_desmarca_enfasis():
    st = _controls(["srt"], pre={"emphasis": True})
    assert st["emph_disabled"] is True and st["emph_checked"] is False
    assert st["row_emph_dis"] is True


@requires_node
def test_srt_deshabilita_y_desmarca_caption_qa():
    st = _controls(["srt"], pre={"qa": True})
    assert st["qa_disabled"] is True and st["qa_checked"] is False
    assert st["row_qa_dis"] is True


@requires_node
def test_srt_muestra_texto_explicativo():
    assert _controls(["srt"])["note_hidden"] is False
    assert _controls(["transcript"])["note_hidden"] is True  # solo con SRT


@requires_node
def test_srt_no_deshabilita_estilo_preset_intensidad_emojis():
    st = _controls(["srt"])
    assert st["style_disabled"] is False
    assert st["preset_disabled"] is False
    assert st["intensidad_disabled"] is False
    assert st["emojis_disabled"] is False


# ─── SRT no envía los parámetros incompatibles ─────────────────────────────────
@requires_node
def test_srt_no_envia_parametros_incompatibles():
    url = _render_url("srt", pre={"emphasis": True, "qa": True, "wpg": "3"})
    assert "caption_source=srt" in url
    assert "words_per_group" not in url
    assert "use_emphasis" not in url
    assert "caption_qa" not in url


# ─── Transcript conserva el comportamiento histórico ───────────────────────────
@requires_node
def test_volver_a_transcript_reactiva_controles():
    st = _controls(["srt", "transcript"], pre={"emphasis": True, "qa": True, "wpg": "3"})
    assert st["wpg_disabled"] is False
    assert st["emph_disabled"] is False
    assert st["qa_disabled"] is False
    assert (
        st["field_wpg_dis"] is False and st["row_emph_dis"] is False and st["row_qa_dis"] is False
    )
    assert st["note_hidden"] is True


@requires_node
def test_volver_a_transcript_no_repone_valores_invalidos():
    # SRT limpió wpg y desmarcó los checkboxes; al volver a Transcript siguen en default seguro.
    st = _controls(["srt", "transcript"], pre={"emphasis": True, "qa": True, "wpg": "3"})
    assert st["wpg_value"] == ""
    assert st["emph_checked"] is False and st["qa_checked"] is False


@requires_node
def test_transcript_envia_parametros_historicos():
    url = _render_url("transcript", pre={"emphasis": True, "qa": True, "wpg": "2"})
    assert "caption_source=srt" not in url
    assert "words_per_group=2" in url
    assert "use_emphasis=true" in url
    assert "caption_qa=alertas" in url
