"""Auditoría del modo y del offset efectivamente usados (S41).

Exponer los controles obliga a poder responder después "¿con qué se rindió esto?". El sidecar
de alineación y el resumen público que devuelve el job tienen que decir QUÉ modo se usó, QUÉ
umbral por cue y QUÉ offset se aplicó — no lo que se pidió, sino lo que acabó corriendo.

Se prueba sobre la ruta compartida por la CLI y el worker (`preparar_desde_srt`) y sobre el
resumen del runtime del Studio.
"""

from __future__ import annotations

import json

import pytest

import srt_align
import srt_caption

_SRT = "1\n00:00:00,000 --> 00:00:04,000\nuno dos tres cuatro\n"
_WORDS = [
    {"w": "uno", "s": 0.0, "e": 0.5, "prob": 1.0},
    {"w": "cuatro", "s": 3.0, "e": 3.5, "prob": 1.0},
]


@pytest.fixture
def srt_file(tmp_path):
    p = tmp_path / "s.srt"
    p.write_text(_SRT, encoding="utf-8")
    return p


def _payload(srt_file, **kw) -> dict:
    _g, _r, payload = srt_caption.preparar_desde_srt(srt_file, _WORDS, **kw)
    return payload


# ─── El sidecar dice con qué se rindió ─────────────────────────────────────────


def test_el_sidecar_reporta_modo_umbral_y_offset_aplicado(srt_file):
    payload = _payload(srt_file, modo_parcial=True, offset_ms=250)
    assert payload["offset"]["modo_parcial"] is True
    assert payload["offset"]["aplicado_ms"] == 250
    assert payload["summary"]["min_coverage"] == srt_align.MIN_COVERAGE_PARCIAL
    assert payload["summary"]["word_partial"] == 1


def test_el_sidecar_del_modo_historico_tambien_se_declara(srt_file):
    """No basta con reportar cuando se activa algo: el modo viejo también queda por escrito."""
    payload = _payload(srt_file)
    assert payload["offset"]["modo_parcial"] is False
    assert payload["offset"]["aplicado_ms"] == 0
    assert payload["summary"]["min_coverage"] == srt_align.DEFAULT_MIN_COVERAGE
    assert payload["summary"]["word_partial"] == 0


def test_el_sidecar_publica_la_propuesta_aunque_no_se_aplique(srt_file):
    """Lo aplicado y lo propuesto son campos DISTINTOS: confundirlos es lo que arriesga D45."""
    payload = _payload(srt_file, modo_parcial=True)
    assert payload["offset"]["aplicado_ms"] == 0
    assert "propuesta" in payload["offset"]


def test_el_umbral_explicito_queda_registrado(srt_file):
    payload = _payload(srt_file, modo_parcial=True, min_coverage=0.9)
    assert payload["summary"]["min_coverage"] == 0.9


def test_el_sidecar_es_serializable_y_sin_rutas(srt_file, tmp_path):
    payload = _payload(srt_file, modo_parcial=True, offset_ms=100)
    destino = tmp_path / "out" / "demo_srt_alignment.json"
    srt_caption.escribir_sidecar(payload, destino)
    crudo = destino.read_text(encoding="utf-8")
    assert json.loads(crudo)["offset"]["aplicado_ms"] == 100
    assert str(tmp_path) not in crudo


# ─── El resumen que devuelve el job dice lo mismo ──────────────────────────────


def test_el_resumen_publico_del_worker_reporta_modo_y_offset(tmp_path):
    """Es lo que la UI recibe al terminar el render: tiene que poder auditarse sin abrir disco."""
    import studio_srt_runtime as rt
    from tests.test_studio_srt_runtime import _associate, _resolve  # noqa: PLC0415

    storage, manifests = _associate(tmp_path, data=_SRT.encode("utf-8"), dur=4000)
    (manifests / "demo_words.json").write_text(json.dumps({"words": _WORDS}), encoding="utf-8")
    prepared = rt.prepare_selected_srt_groups(
        _resolve(storage, manifests),
        words_path=manifests / "demo_words.json",
        video_duration_ms=4000,
        alignment_sidecar_path=manifests / "demo_srt_alignment.json",
        offset_ms=120,
        modo_parcial=True,
    )
    s = prepared.summary
    assert s["modo_parcial"] is True
    assert s["offset_ms"] == 120
    assert s["min_coverage"] == srt_align.MIN_COVERAGE_PARCIAL
    assert s["word_partial"] == 1
    # La propuesta viaja aparte de lo aplicado, para que la UI pueda ofrecerla sin confundirlas.
    assert "offset_propuesto" in s
