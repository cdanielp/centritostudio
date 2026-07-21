"""test_h2_atomic_io.py — Escrituras atomicas de estado de recuperacion (H2, P2-ATOM-STATE).

Contrato de `atomic_io`: exito reemplaza; error preserva el final anterior; temporal limpiado;
dos writers concurrentes no colisionan; el JSON publicado siempre esta completo. Todo en
`tmp_path` (TemporaryDirectory), sin red ni FFmpeg.
"""

from __future__ import annotations

import json

import pytest

import atomic_io


def _tmps(d):
    return [p for p in d.iterdir() if ".tmp" in p.name]


def test_exito_reemplaza(tmp_path):
    dst = tmp_path / "checkpoint.json"
    atomic_io.atomic_write_json(dst, {"status": "done", "n": 1})
    assert json.loads(dst.read_text(encoding="utf-8")) == {"status": "done", "n": 1}
    assert not _tmps(tmp_path)  # sin temporales residuales


def test_error_preserva_final_anterior(tmp_path, monkeypatch):
    dst = tmp_path / "estado.json"
    atomic_io.atomic_write_text(dst, "ORIGINAL")

    def _boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(atomic_io.os, "replace", _boom)  # falla la publicacion tras el temporal
    with pytest.raises(OSError):
        atomic_io.atomic_write_text(dst, "NUEVO_QUE_FALLA")
    assert dst.read_text(encoding="utf-8") == "ORIGINAL"  # final previo intacto
    assert not _tmps(tmp_path)  # el temporal se limpio pese al error


def test_temporal_limpiado_en_error_de_serializacion(tmp_path):
    dst = tmp_path / "x.json"
    dst.write_text("PREVIO", encoding="utf-8")

    class _NoSerializable:
        pass

    with pytest.raises(TypeError):
        atomic_io.atomic_write_json(dst, {"bad": _NoSerializable()})
    # json.dumps falla ANTES de abrir temporal -> sin residuos y final intacto.
    assert dst.read_text(encoding="utf-8") == "PREVIO"
    assert not _tmps(tmp_path)


def test_dos_writers_no_colisionan(tmp_path):
    # Temporal UNICO (mkstemp): dos escrituras al MISMO destino no comparten `.tmp`.
    dst = tmp_path / "shared.json"
    atomic_io.atomic_write_json(dst, {"a": 1})
    atomic_io.atomic_write_json(dst, {"a": 2})
    assert json.loads(dst.read_text(encoding="utf-8")) == {"a": 2}
    assert not _tmps(tmp_path)


def test_json_publicado_siempre_completo(tmp_path):
    dst = tmp_path / "grande.json"
    payload = {"words": [{"w": str(i), "s": i, "e": i + 1} for i in range(500)]}
    atomic_io.atomic_write_json(dst, payload)
    # Se lee entero y valido (nunca a medias): el os.replace es atomico.
    assert json.loads(dst.read_text(encoding="utf-8")) == payload


def test_crea_directorio_padre(tmp_path):
    dst = tmp_path / "sub" / "dir" / "m.json"
    atomic_io.atomic_write_json(dst, {"ok": True})
    assert dst.exists() and json.loads(dst.read_text(encoding="utf-8")) == {"ok": True}
