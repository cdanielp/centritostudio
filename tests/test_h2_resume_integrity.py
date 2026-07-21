"""test_h2_resume_integrity.py — Validacion profunda de outputs en resume (H2, P1-OUT-3).

`media_integrity.video_reanudable` es el gate fail-closed que usan los 4 predicados de resume. Un
MP4 inexistente / 0-byte / truncado / sin stream / con duracion 0/NaN/Inf -> NO se reutiliza (se
re-renderiza). ffprobe se mockea (patron H1); is_file()/st_size>0 son REALES. Se verifica ademas
que el gate esta CABLEADO en `_clip_incompleto`, la reutilizacion classic y el checkpoint v2, y
que un clip invalido no obliga a reprocesar los clips sanos.
"""

from __future__ import annotations

import json
import types

import media_integrity as mi

VIDEO_OK = {"streams": [{"codec_type": "video", "duration": "3.0"}], "format": {"duration": "3.0"}}
SIN_VIDEO = {"streams": [{"codec_type": "audio"}], "format": {"duration": "3.0"}}
DUR_CERO = {"streams": [{"codec_type": "video"}], "format": {"duration": "0"}}
DUR_NAN = {"streams": [{"codec_type": "video", "duration": "nan"}], "format": {"duration": "inf"}}


def _ffprobe(payload, returncode=0):
    def _run(_cmd, **_kw):
        return types.SimpleNamespace(returncode=returncode, stdout=json.dumps(payload), stderr="")

    return _run


def _mp4(tmp_path, data=b"REALMP4DATA", name="c.mp4"):
    p = tmp_path / name
    p.write_bytes(data)
    return p


# ── video_reanudable: contrato fail-closed ────────────────────────────────────
def test_valido_es_reanudable(tmp_path, monkeypatch):
    monkeypatch.setattr(mi.subprocess, "run", _ffprobe(VIDEO_OK))
    assert mi.video_reanudable(_mp4(tmp_path)) is True


def test_inexistente_no_reanudable(tmp_path):
    assert mi.video_reanudable(tmp_path / "no-existe.mp4") is False


def test_cero_bytes_no_reanudable(tmp_path, monkeypatch):
    monkeypatch.setattr(mi.subprocess, "run", _ffprobe(VIDEO_OK))
    assert mi.video_reanudable(_mp4(tmp_path, data=b"")) is False


def test_truncado_no_reanudable(tmp_path, monkeypatch):
    # No vacio pero ffprobe lo rechaza (returncode != 0) -> truncado -> no reanudable.
    monkeypatch.setattr(mi.subprocess, "run", _ffprobe({}, returncode=1))
    assert mi.video_reanudable(_mp4(tmp_path, data=b"trunc")) is False


def test_sin_stream_de_video_no_reanudable(tmp_path, monkeypatch):
    monkeypatch.setattr(mi.subprocess, "run", _ffprobe(SIN_VIDEO))
    assert mi.video_reanudable(_mp4(tmp_path)) is False


def test_duracion_cero_no_reanudable(tmp_path, monkeypatch):
    monkeypatch.setattr(mi.subprocess, "run", _ffprobe(DUR_CERO))
    assert mi.video_reanudable(_mp4(tmp_path)) is False


def test_duracion_nan_inf_no_reanudable(tmp_path, monkeypatch):
    monkeypatch.setattr(mi.subprocess, "run", _ffprobe(DUR_NAN))
    assert mi.video_reanudable(_mp4(tmp_path)) is False


def test_no_borra_el_archivo(tmp_path, monkeypatch):
    # Un MP4 invalido NO se borra (politica: no destruir sin un render valido).
    monkeypatch.setattr(mi.subprocess, "run", _ffprobe(SIN_VIDEO))
    p = _mp4(tmp_path)
    assert mi.video_reanudable(p) is False
    assert p.exists()


# ── Cableado en los predicados de auto ────────────────────────────────────────
def test_clip_incompleto_usa_el_gate(tmp_path, monkeypatch):
    import auto

    paquete = tmp_path
    final = paquete / "clip_9x16_hormozi.mp4"
    final.write_bytes(b"data")
    sidecar = final.with_name(final.stem + ".info.json")
    sidecar.write_text(json.dumps({"archivo": final.name, "status": "done"}), encoding="utf-8")
    info = {"archivo": final.name, "status": "done"}

    # MP4 valido + checkpoint valido -> NO incompleto (se conserva).
    monkeypatch.setattr(auto, "video_reanudable", lambda _p: True)
    assert auto._clip_incompleto(info, paquete) is False
    # checkpoint done + MP4 invalido -> incompleto (se re-renderiza).
    monkeypatch.setattr(auto, "video_reanudable", lambda _p: False)
    assert auto._clip_incompleto(info, paquete) is True


def test_checkpoint_v2_requiere_video_reanudable(tmp_path, monkeypatch):
    import auto_v2

    final = tmp_path / "c_9x16_hormozi.mp4"
    final.write_bytes(b"data")
    trans = tmp_path / "t"
    trans.mkdir()
    for s in ("plan", "auto", "resolved"):
        (trans / f"{s}.json").write_text(json.dumps({"config_fingerprint": "fp"}), encoding="utf-8")
    info = {
        "pipeline_mode": "v2",
        "config_fingerprint": "fp",
        "av": {"skipped": True},
        "broll": {
            "plan_sidecar": "plan.json",
            "auto_sidecar": "auto.json",
            "resolved_sidecar": "resolved.json",
        },
    }
    monkeypatch.setattr(auto_v2, "video_reanudable", lambda _p: True)
    assert auto_v2.checkpoint_v2_valido(info, "fp", final, trans) is True
    # MP4 invalido -> el checkpoint v2 no se reutiliza aunque todo lo demas cuadre.
    monkeypatch.setattr(auto_v2, "video_reanudable", lambda _p: False)
    assert auto_v2.checkpoint_v2_valido(info, "fp", final, trans) is False


def test_clip_invalido_no_obliga_a_reprocesar_los_sanos(tmp_path, monkeypatch):
    # _clip_incompleto se evalua por clip: uno invalido no contamina a los validos.
    import auto

    paquete = tmp_path
    sano = paquete / "sano_9x16_hormozi.mp4"
    malo = paquete / "malo_9x16_hormozi.mp4"
    for f in (sano, malo):
        f.write_bytes(b"data")
        f.with_name(f.stem + ".info.json").write_text(
            json.dumps({"archivo": f.name, "status": "done"}), encoding="utf-8"
        )
    monkeypatch.setattr(auto, "video_reanudable", lambda p: "sano" in str(p))
    assert auto._clip_incompleto({"archivo": sano.name, "status": "done"}, paquete) is False
    assert auto._clip_incompleto({"archivo": malo.name, "status": "done"}, paquete) is True
