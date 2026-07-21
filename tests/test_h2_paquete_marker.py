"""test_h2_paquete_marker.py — Paquete classic reanudable seguro por marker (H2, P2-PAQUETE-DIR).

`auto._paquete_dir` ya NO reanuda cualquier dir `{name}_*` sin `paquete.json`: exige un marker
`auto_classic.json` legible con schema+pipeline_mode=classic y procedencia del video EXACTO, ser
hijo directo de PAQUETES_DIR, y no tener `paquete.json` final. Un dir manual sin marker, corrupto,
de otro video o v2/SRT -> se crea un paquete NUEVO (sin borrar el viejo). Fixtures en tmp_path.
"""

from __future__ import annotations

import json

import pytest

import auto
import auto_classic_provenance as acp


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    paquetes = tmp_path / "paquetes"
    paquetes.mkdir()
    monkeypatch.setattr(auto, "PAQUETES_DIR", paquetes)
    video = tmp_path / "vid.mp4"
    video.write_bytes(b"abcdef")
    return {"paquetes": paquetes, "video": video}


def _marker(video, *, pipeline_mode="classic", schema=acp.SCHEMA_VERSION, video_prov=None):
    return {
        "schema_version": schema,
        "pipeline_mode": pipeline_mode,
        "video": video_prov
        if video_prov is not None
        else acp.build_provenance(video, lang="es", model="auto"),
        "created_at": "20260101-000000",
        "run_id": "r",
    }


def _crear(paquetes, name, marker=None, *, paquete_json=False):
    d = paquetes / name
    d.mkdir()
    if marker is not None:
        (d / "auto_classic.json").write_text(json.dumps(marker), encoding="utf-8")
    if paquete_json:
        (d / "paquete.json").write_text(json.dumps({"clips": []}), encoding="utf-8")
    return d


def test_marker_valido_reanuda(entorno):
    prev = _crear(entorno["paquetes"], "vid_20260101-0000", _marker(entorno["video"]))
    d, reanudado = auto._paquete_dir("vid", entorno["video"])
    assert reanudado is True and d == prev


def test_directorio_sin_marker_no_reanuda(entorno):
    _crear(entorno["paquetes"], "vid_20260101-0000", marker=None)  # dir manual sin marker
    d, reanudado = auto._paquete_dir("vid", entorno["video"])
    assert reanudado is False and d.name != "vid_20260101-0000"


def test_marker_corrupto_no_reanuda(entorno):
    d0 = _crear(entorno["paquetes"], "vid_20260101-0000")
    (d0 / "auto_classic.json").write_text("{no json", encoding="utf-8")
    d, reanudado = auto._paquete_dir("vid", entorno["video"])
    assert reanudado is False


def test_marker_de_otro_video_no_reanuda(entorno, tmp_path):
    otro = tmp_path / "otro.mp4"
    otro.write_bytes(b"XYZ-diferente")
    _crear(entorno["paquetes"], "vid_20260101-0000", _marker(otro))
    d, reanudado = auto._paquete_dir("vid", entorno["video"])
    assert reanudado is False


def test_marker_v2_no_reanuda_como_classic(entorno):
    # Un marker con pipeline_mode v2 nunca se reanuda por la ruta classic.
    _crear(entorno["paquetes"], "vid_20260101-0000", _marker(entorno["video"], pipeline_mode="v2"))
    d, reanudado = auto._paquete_dir("vid", entorno["video"])
    assert reanudado is False


def test_paquete_v2_dir_excluido(entorno):
    # Los dirs {name}_v2_* jamas los considera la ruta classic.
    (entorno["paquetes"] / "vid_v2_20260101-0000").mkdir()
    d, reanudado = auto._paquete_dir("vid", entorno["video"])
    assert reanudado is False and "_v2_" not in d.name


def test_completado_con_paquete_json_no_reanuda(entorno):
    _crear(entorno["paquetes"], "vid_20260101-0000", _marker(entorno["video"]), paquete_json=True)
    d, reanudado = auto._paquete_dir("vid", entorno["video"])
    assert reanudado is False  # ya completado -> no se reabre


def test_marker_valido_pero_otro_stem_no_se_confunde(entorno):
    # Un paquete de "otrovid" no debe reanudarse para "vid" (glob por nombre).
    _crear(entorno["paquetes"], "otrovid_20260101-0000", _marker(entorno["video"]))
    d, reanudado = auto._paquete_dir("vid", entorno["video"])
    assert reanudado is False


def test_crea_marker_al_crear_paquete_nuevo(entorno):
    d, reanudado = auto._paquete_dir("vid", entorno["video"])
    assert reanudado is False
    marker = json.loads((d / "auto_classic.json").read_text(encoding="utf-8"))
    assert marker["pipeline_mode"] == "classic"
    assert marker["schema_version"] == acp.SCHEMA_VERSION
    assert "run_id" in marker and "created_at" in marker
    assert acp.matches(marker["video"], entorno["video"], lang="es", model="auto")


def test_dos_corridas_no_comparten_directorio(entorno, monkeypatch):
    # Mismo timestamp (segundos) -> el sufijo unico evita colision entre dos corridas.
    monkeypatch.setattr(auto.time, "strftime", lambda _f: "20260101-000000")
    d1, _ = auto._paquete_dir("vid", entorno["video"])
    # d1 ya tiene marker+ (sin paquete.json) -> seria "reanudable"; para forzar creacion de un
    # segundo dir, se marca d1 como completado.
    (d1 / "paquete.json").write_text("{}", encoding="utf-8")
    d2, _ = auto._paquete_dir("vid", entorno["video"])
    assert d1 != d2 and d2.name.startswith("vid_20260101-000000")
