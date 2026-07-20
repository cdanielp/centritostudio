"""Tests de wiring productivo de la trayectoria del reframe (F6 avoid_faces, BLOQUEO 1 PR #23).

Dos piezas:
- `tray_resolve.resolver_tray_csv`: helper UNICO (CLI + Studio) que resuelve el CSV
  consumible; prioriza el que queda junto al MP4 reframado; fallback legacy en transcripts/.
- `jobs.run_reframe`: el worker real pasa tray_dir=output_path.parent para que el CSV
  quede junto al MP4 con el MISMO stem, resoluble por el renderer sin logica divergente.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import jobs
import tray_resolve


def _touch(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("t,conf_asignada,face_y_asignada\n0.0,0.9,0.5\n", encoding="utf-8")
    return p


# ── resolver_tray_csv: orden de candidatos + stem ─────────────────────────────


def test_resuelve_csv_junto_al_mp4(tmp_path):
    mp4 = tmp_path / "out" / "clip_9x16.mp4"
    mp4.parent.mkdir(parents=True)
    csv = _touch(mp4.parent / "trayectoria_clip_9x16.csv")
    tr = tmp_path / "transcripts"
    tr.mkdir()
    assert tray_resolve.resolver_tray_csv(mp4, tr) == csv


def test_stem_del_csv_corresponde_al_stem_del_mp4(tmp_path):
    # trayectoria_clip_9x16.csv para clip_9x16.mp4 (contrato de nombre)
    assert tray_resolve.nombre_tray("clip_9x16") == "trayectoria_clip_9x16.csv"
    mp4 = tmp_path / "clip_9x16.mp4"
    _touch(mp4.parent / "trayectoria_clip_9x16.csv")
    # un CSV con OTRO stem no se resuelve
    _touch(mp4.parent / "trayectoria_otro.csv")
    got = tray_resolve.resolver_tray_csv(mp4, tmp_path / "no_tr")
    assert got is not None and got.name == "trayectoria_clip_9x16.csv"


def test_fallback_legacy_en_transcripts(tmp_path):
    mp4 = tmp_path / "out" / "clip.mp4"
    mp4.parent.mkdir(parents=True)
    tr = tmp_path / "transcripts"
    csv = _touch(tr / "trayectoria_clip.csv")  # solo el legacy existe
    assert tray_resolve.resolver_tray_csv(mp4, tr) == csv


def test_prioriza_junto_al_mp4_sobre_legacy(tmp_path):
    mp4 = tmp_path / "out" / "clip.mp4"
    mp4.parent.mkdir(parents=True)
    junto = _touch(mp4.parent / "trayectoria_clip.csv")
    tr = tmp_path / "transcripts"
    _touch(tr / "trayectoria_clip.csv")
    assert tray_resolve.resolver_tray_csv(mp4, tr) == junto


def test_name_distinto_del_stem_usa_legacy(tmp_path):
    # Studio pasa name != mp4.stem: el legacy usa name, no el stem del mp4
    mp4 = tmp_path / "out" / "clip_9x16.mp4"
    mp4.parent.mkdir(parents=True)
    tr = tmp_path / "transcripts"
    csv = _touch(tr / "trayectoria_video7.csv")
    assert tray_resolve.resolver_tray_csv(mp4, tr, name="video7") == csv


def test_ausente_es_none_fail_open(tmp_path):
    mp4 = tmp_path / "clip.mp4"
    assert tray_resolve.resolver_tray_csv(mp4, tmp_path / "transcripts") is None


# ── jobs.run_reframe: el worker real solicita la trayectoria ──────────────────


def test_run_reframe_pasa_tray_dir_junto_al_mp4(monkeypatch, tmp_path):
    captura = {}

    def fake_reframe_clip(clip, out, **kw):
        captura["out"] = out
        captura["kw"] = kw
        return {"n_caras": 1, "dur_s": 0.1, "output": str(out)}

    import reframe

    monkeypatch.setattr(reframe, "reframe_clip", fake_reframe_clip)
    monkeypatch.setattr(jobs, "update_job", lambda *a, **k: None)
    out = tmp_path / "salida" / "clip_9x16.mp4"
    jobs.run_reframe("j1", tmp_path / "clip.mp4", out, None, False, layout="tracking")
    # el worker pide la trayectoria en el directorio del MP4 reframado
    assert captura["kw"].get("tray_dir") == out.parent


def test_loop_completo_worker_escribe_resolver_encuentra(monkeypatch, tmp_path):
    # Cierra el lazo con nombres de PRODUCCION (output/clips + sufijo _9x16): el worker
    # escribe trayectoria_<name>_9x16.csv junto al MP4; el render de ESE clip la resuelve.
    clips = tmp_path / "output" / "clips"
    reframed = clips / "video7_9x16.mp4"

    def fake_reframe_clip(clip, out, **kw):
        # emula el serializador real: CSV en tray_dir con el stem del MP4 reframado
        td = kw["tray_dir"]
        td.mkdir(parents=True, exist_ok=True)
        (td / tray_resolve.nombre_tray(out.stem)).write_text(
            "t,conf_asignada,face_y_asignada\n0.0,0.9,0.8\n", encoding="utf-8"
        )
        return {"n_caras": 1, "dur_s": 0.1, "output": str(out)}

    import reframe

    monkeypatch.setattr(reframe, "reframe_clip", fake_reframe_clip)
    monkeypatch.setattr(jobs, "update_job", lambda *a, **k: None)
    jobs.run_reframe("j1", tmp_path / "input" / "video7.mp4", reframed, None, False)
    # el render que quema el clip reframado resuelve la trayectoria por el candidato 1
    got = tray_resolve.resolver_tray_csv(reframed, tmp_path / "transcripts", name="video7_9x16")
    assert got == clips / "trayectoria_video7_9x16.csv" and got.exists()


def test_run_reframe_stem_del_csv_seria_el_del_mp4(monkeypatch, tmp_path):
    # tray_dir + output_path.stem => trayectoria_<stem_del_mp4>.csv resoluble por el renderer
    captura = {}
    import reframe

    monkeypatch.setattr(
        reframe,
        "reframe_clip",
        lambda clip, out, **kw: (
            captura.update(out=out, tray_dir=kw.get("tray_dir"))
            or {"n_caras": 1, "dur_s": 0.1, "output": str(out)}
        ),
    )
    monkeypatch.setattr(jobs, "update_job", lambda *a, **k: None)
    out = tmp_path / "salida" / "clip_9x16.mp4"
    jobs.run_reframe("j1", tmp_path / "clip.mp4", out, None, False, layout="tracking")
    esperado = captura["tray_dir"] / tray_resolve.nombre_tray(out.stem)
    assert esperado == out.parent / "trayectoria_clip_9x16.csv"
