"""Enriquecimiento read-only del Editor con diagnosticos Auto v2."""

import json
import os

import pytest

import paquete_editor as pe

FP = "a" * 64


def _clip(**overrides):
    clip = {
        "archivo": "demo.mp4",
        "titulo": "Demo",
        "razon": "Sintetico",
        "score": 90,
        "dur_s": 12.0,
        "avisos": [],
        "pipeline_mode": "v2",
        "pipeline_version": 2,
        "config_fingerprint": FP,
        "brain_ok": True,
        "broll": {
            "planned": 4,
            "resolved": 3,
            "images": 2,
            "videos": 1,
            "fallbacks": 1,
            "blocked": 1,
            "omitted": 1,
            "manual_popups": 1,
            "manual_clips": 0,
            "resolved_sidecar": "demo_broll_resolved.json",
        },
        "fx": {
            "enabled": True,
            "preset": "express",
            "before": {"punch": 2, "flash": 1, "scanner": 0, "logo": 0},
            "after": {"punch": 1, "flash": 1, "scanner": 0, "logo": 0},
            "removed": [{"code": "punch_removed_cutaway", "cutaway": [3, 5]}],
            "warnings": ["warning sintetico"],
        },
        "av": {
            "integrity": {"status": "pass", "payload_sha256": "secreto-hash"},
            "sync": {"status": "pass", "av_end_drift_s": 0.031, "allowed_end_drift_s": 0.12},
        },
    }
    clip.update(overrides)
    return clip


def _decision(media="image", status="resolved", start=3.0, end=5.0, query="cafe tostado"):
    return {
        "window_id": "broll-1",
        "final_media_type": media,
        "status": status,
        "start_s": start,
        "end_s": end,
        "query": query,
        "asset": {"asset_id": "privado", "source_url": "https://pexels.invalid/x"},
    }


def _resolved(path, decisions, fingerprint=FP):
    path.write_text(
        json.dumps({"version": 1, "config_fingerprint": fingerprint, "decisions": decisions}),
        encoding="utf-8",
    )


def test_classic_conserva_campos_historicos_y_no_paneles_v2(tmp_path):
    (tmp_path / "classic.mp4").write_bytes(b"mp4")
    classic = _clip(archivo="classic.mp4")
    for key in (
        "pipeline_mode",
        "pipeline_version",
        "config_fingerprint",
        "brain_ok",
        "broll",
        "fx",
        "av",
    ):
        classic.pop(key, None)
    out = pe.enriquecer_clip(classic, "pkg", tmp_path, tmp_path)
    assert out["archivo"] == "classic.mp4" and out["titulo"] == "Demo"
    assert (
        out["pipeline_mode"] is None
        and out["broll"] is None
        and out["fx"] is None
        and out["av"] is None
    )


def test_v2_expone_solo_resumen_saneado(tmp_path):
    (tmp_path / "demo.mp4").write_bytes(b"mp4")
    _resolved(tmp_path / "demo_broll_resolved.json", [_decision()])
    meta = {"config": {"broll_enabled": True}}
    out = pe.enriquecer_clip(_clip(), "pkg", tmp_path, tmp_path, meta)
    assert out["pipeline_mode"] == "v2" and out["pipeline_version"] == 2 and out["brain_ok"] is True
    assert out["broll"]["planned"] == 4 and out["broll"]["enabled"] is True
    assert out["fx"]["removed"] == 1 and out["fx"]["before"]["punch"] == 2
    assert out["av"] == {
        "integrity": "pass",
        "sync": "pass",
        "drift_s": 0.031,
        "allowed_drift_s": 0.12,
    }
    texto = json.dumps(out).lower()
    assert "secreto-hash" not in texto and "asset_id" not in texto and "pexels.invalid" not in texto
    assert "resolved_sidecar" not in texto


@pytest.mark.parametrize(
    ("decision", "tipo", "status"),
    [
        (_decision("image", "resolved"), "broll_image", "resolved"),
        (_decision("video", "resolved", 5, 8), "broll_video", "resolved"),
        (_decision("image", "fallback", 8, 10), "broll_image", "fallback"),
    ],
)
def test_resolved_valido_produce_markers(tmp_path, decision, tipo, status):
    _resolved(tmp_path / "demo_broll_resolved.json", [decision])
    markers = pe.markers_broll_resueltos(_clip(), tmp_path)
    assert markers == [
        {
            "tipo": tipo,
            "t": decision["start_s"],
            "t_fin": decision["end_s"],
            "texto": "cafe tostado",
            "status": status,
        }
    ]


@pytest.mark.parametrize("status", ["blocked", "omitted", "disabled", "empty"])
def test_estados_no_renderizados_no_producen_marker(tmp_path, status):
    _resolved(tmp_path / "demo_broll_resolved.json", [_decision(None, status)])
    assert pe.markers_broll_resueltos(_clip(), tmp_path) == []


def test_classic_no_genera_marker_v2_aunque_tenga_campos_accidentales(tmp_path):
    clip = _clip()
    clip["pipeline_mode"] = "classic"
    _resolved(tmp_path / "demo_broll_resolved.json", [_decision()])
    assert pe.markers_broll_resueltos(clip, tmp_path) == []


def test_resumen_v2_no_inventa_conteos_ausentes():
    clip = {"pipeline_mode": "v2", "broll": {}, "fx": {}, "av": {}}
    assert pe.resumen_broll_seguro(clip)["planned"] is None
    assert pe.resumen_fx_seguro(clip)["removed"] is None


def test_markers_ordenados_y_fuera_de_duracion_descartado(tmp_path):
    decisions = [
        _decision("video", "resolved", 7, 9),
        _decision("image", "resolved", 2, 4),
        _decision("image", "resolved", 11, 13),
    ]
    _resolved(tmp_path / "demo_broll_resolved.json", decisions)
    markers = pe.markers_broll_resueltos(_clip(), tmp_path)
    assert [m["t"] for m in markers] == [2.0, 7.0]
    assert all("t_fin" in m for m in markers)


@pytest.mark.parametrize("case", ["mismatch", "broken", "missing", "traversal"])
def test_resolved_invalido_es_fail_open(tmp_path, case):
    clip = _clip()
    path = tmp_path / "demo_broll_resolved.json"
    if case == "mismatch":
        _resolved(path, [_decision()], fingerprint="b" * 64)
    elif case == "broken":
        path.write_text("{", encoding="utf-8")
    elif case == "traversal":
        clip["broll"]["resolved_sidecar"] = "../fuera.json"
    assert pe.markers_broll_resueltos(clip, tmp_path) == []


def test_query_url_se_sanea_como_texto_generico(tmp_path):
    _resolved(tmp_path / "demo_broll_resolved.json", [_decision(query="https://pexels.invalid/x")])
    marker = pe.markers_broll_resueltos(_clip(), tmp_path)[0]
    assert marker["texto"] == "B-roll image" and "http" not in json.dumps(marker)


def test_campos_v2_malformados_degradan_sin_romper():
    clip = _clip(fx={"before": "mal", "after": [], "warnings": "mal"}, av={"sync": "mal"})
    assert pe.resumen_fx_seguro(clip)["before"] == {
        "punch": None,
        "flash": None,
        "scanner": None,
        "logo": None,
    }
    assert pe.resumen_av_seguro(clip)["sync"] == "unknown"
    assert pe.resumen_broll_seguro(clip, meta="mal")["enabled"] is None


def test_symlink_fuera_rechazado_si_plataforma_lo_permite(tmp_path):
    outside = tmp_path.parent / "outside-resolved.json"
    _resolved(outside, [_decision()])
    link = tmp_path / "demo_broll_resolved.json"
    try:
        os.symlink(outside, link)
    except OSError:
        pytest.skip("symlink no disponible sin privilegios en este Windows")
    assert pe.markers_broll_resueltos(_clip(), tmp_path) == []
