"""test_clipper_srt.py — Round-trip SRT del clipper (S36-B, D36B-8/9).

Sin red, sin GPU, sin FFmpeg real (se mockean el LLM y el corte). El clipper corta igual
que siempre y, con SRT fuente, genera un SRT rebasado contra el clip.start REAL. La fuente
nunca se modifica. Solo texto SINTETICO.
"""

from __future__ import annotations

import json
from pathlib import Path

import clipper
import clipper_brain
from srt_import import load_srt, parse_srt_text
from srt_slice import slice_srt


def _words(n: int = 60, step: float = 0.5):
    return [
        {"w": f"w{i}", "s": round(i * step, 3), "e": round(i * step + 0.4, 3), "prob": 1.0}
        for i in range(n)
    ]


def _srt_doc_30s():
    bloques = []
    for i in range(6):
        s, e = i * 5, i * 5 + 5
        bloques.append(f"{i + 1}\n00:00:{s:02d},000 --> 00:00:{e:02d},000\nfrase numero {i + 1}\n")
    return parse_srt_text("\n".join(bloques), source_name="fuente.srt")


def _mock_llm(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setattr(
        clipper_brain,
        "segmentar_transcript",
        lambda frases, contexto, tipos="ambos": (
            [{"f_ini": 0, "f_fin": len(frases) - 1, "tipo": "corto", "tema": "t"}],
            [{"etapa": "segmentacion", "provider": "mock"}],
        ),
    )
    monkeypatch.setattr(
        clipper_brain,
        "puntuar_candidatos",
        lambda cands: (
            [
                {
                    "c": 0,
                    "hook": 80,
                    "autocontenido": 80,
                    "densidad": 80,
                    "cierre": 80,
                    "titulo": "T",
                    "razon": "R",
                }
            ],
            [{"etapa": "scoring", "provider": "mock"}],
        ),
    )


def _mock_dirs_and_cut(monkeypatch, tmp_path):
    clips_dir = tmp_path / "clips"
    tr_dir = tmp_path / "transcripts"
    clips_dir.mkdir()
    tr_dir.mkdir()
    monkeypatch.setattr(clipper, "CLIPS_DIR", clips_dir)
    monkeypatch.setattr(clipper, "TRANSCRIPTS_DIR", tr_dir)
    monkeypatch.setattr(clipper, "cortar_clip", lambda v, s, e, out: Path(out).write_text("mp4"))
    return clips_dir, tr_dir


# ============================== exportar_srt_clip (unidad) ==============================


def test_exportar_srt_clip_rebase_contra_clip_start(tmp_path, monkeypatch):
    monkeypatch.setattr(clipper, "TRANSCRIPTS_DIR", tmp_path)
    doc = _srt_doc_30s()
    # clip [10s, 20s): cubre cues 3 y 4; rebasa contra 10s (no contra la primera palabra)
    meta = clipper.exportar_srt_clip(doc, 10.0, 20.0, "clipX")
    assert meta["n_cues"] == 2
    assert meta["start_ms_source"] == 10000 and meta["end_ms_source"] == 20000
    derived = load_srt(tmp_path / "clipX.srt")
    assert derived.cues[0].start_ms == 0  # rebasado a t=0
    assert [c.index for c in derived.cues] == [1, 2]  # reindexado desde 1


def test_exportar_srt_clip_padding_reflejado(tmp_path, monkeypatch):
    monkeypatch.setattr(clipper, "TRANSCRIPTS_DIR", tmp_path)
    doc = _srt_doc_30s()
    # start con padding 4.8s: el primer cue (0-5) cruza el inicio y arranca en t=0
    meta = clipper.exportar_srt_clip(doc, 4.8, 10.0, "clipP")
    derived = load_srt(tmp_path / "clipP.srt")
    assert meta["rebased"] is True
    assert derived.cues[0].start_ms == 0  # 5000-4800 = 200? no: cruza inicio -> 0
    assert derived.cues[0].end_ms == 200  # cue 0-5s recortado a [4.8,5) rebasado


def test_exportar_srt_clip_sin_cues(tmp_path, monkeypatch):
    monkeypatch.setattr(clipper, "TRANSCRIPTS_DIR", tmp_path)
    meta = clipper.exportar_srt_clip(_srt_doc_30s(), 100.0, 110.0, "vacio")
    assert meta["n_cues"] == 0 and meta["file"] is None
    assert not (tmp_path / "vacio.srt").exists()


def test_exportar_srt_clip_ms_enteros(tmp_path, monkeypatch):
    monkeypatch.setattr(clipper, "TRANSCRIPTS_DIR", tmp_path)
    meta = clipper.exportar_srt_clip(_srt_doc_30s(), 2.001, 12.4996, "clipR")
    assert isinstance(meta["start_ms_source"], int) and isinstance(meta["end_ms_source"], int)
    assert meta["start_ms_source"] == 2001 and meta["end_ms_source"] == 12500


def test_dos_clips_generan_srt_distintos(tmp_path, monkeypatch):
    monkeypatch.setattr(clipper, "TRANSCRIPTS_DIR", tmp_path)
    doc = _srt_doc_30s()
    clipper.exportar_srt_clip(doc, 0.0, 10.0, "clipA")
    clipper.exportar_srt_clip(doc, 20.0, 30.0, "clipB")
    a = (tmp_path / "clipA.srt").read_text(encoding="utf-8")
    b = (tmp_path / "clipB.srt").read_text(encoding="utf-8")
    assert a != b and "frase numero 1" in a and "frase numero 6" in b


def test_exportar_srt_clip_fuente_intacta(tmp_path, monkeypatch):
    monkeypatch.setattr(clipper, "TRANSCRIPTS_DIR", tmp_path)
    doc = _srt_doc_30s()
    antes = [(c.index, c.start_ms, c.end_ms, c.lines) for c in doc.cues]
    clipper.exportar_srt_clip(doc, 5.0, 15.0, "clipC")
    assert [(c.index, c.start_ms, c.end_ms, c.lines) for c in doc.cues] == antes


def test_exportar_srt_clip_atomic_sin_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(clipper, "TRANSCRIPTS_DIR", tmp_path)
    clipper.exportar_srt_clip(_srt_doc_30s(), 0.0, 10.0, "clipT")
    assert not (tmp_path / "clipT.srt.tmp").exists()


def test_exportar_srt_clip_solo_basenames(tmp_path, monkeypatch):
    monkeypatch.setattr(clipper, "TRANSCRIPTS_DIR", tmp_path)
    meta = clipper.exportar_srt_clip(_srt_doc_30s(), 0.0, 10.0, "clipN")
    assert "/" not in meta["file"] and "\\" not in meta["file"]
    contract = json.loads((tmp_path / "clipN_srt.json").read_text(encoding="utf-8"))
    assert "\\" not in json.dumps(contract["source"])  # sin rutas absolutas


# ============================== generar_clips (integracion mockeada) ==============================


def test_generar_clips_sin_srt_identico(tmp_path, monkeypatch):
    _mock_llm(monkeypatch)
    _mock_dirs_and_cut(monkeypatch, tmp_path)
    res = clipper.generar_clips(Path("v.mp4"), _words(), "cortos")
    assert res["error"] is None and len(res["clips"]) == 1
    assert "srt" not in res["clips"][0]  # sin SRT fuente, no hay metadata SRT


def test_generar_clips_con_srt_genera_metadata(tmp_path, monkeypatch):
    _mock_llm(monkeypatch)
    clips_dir, tr_dir = _mock_dirs_and_cut(monkeypatch, tmp_path)
    res = clipper.generar_clips(Path("v.mp4"), _words(), "cortos", srt_document=_srt_doc_30s())
    assert len(res["clips"]) == 1
    srt_meta = res["clips"][0]["srt"]
    assert srt_meta["n_cues"] >= 1 and srt_meta["rebased"] is True
    assert (tr_dir / srt_meta["file"]).exists()
    assert len(srt_meta["source_sha256"]) == 64


def test_generar_clips_srt_falla_no_borra_mp4(tmp_path, monkeypatch):
    _mock_llm(monkeypatch)
    clips_dir, _tr = _mock_dirs_and_cut(monkeypatch, tmp_path)

    def _boom(*a, **k):
        raise RuntimeError("fallo sintetico")

    monkeypatch.setattr(clipper, "exportar_srt_clip", _boom)
    res = clipper.generar_clips(Path("v.mp4"), _words(), "cortos", srt_document=_srt_doc_30s())
    assert len(res["clips"]) == 1  # el clip sobrevive
    assert "srt" not in res["clips"][0]
    mp4 = clips_dir / res["clips"][0]["archivo"]
    assert mp4.exists()  # el MP4 ya cortado no desaparece


def test_generar_clips_srt_fuente_intacta(tmp_path, monkeypatch):
    _mock_llm(monkeypatch)
    _mock_dirs_and_cut(monkeypatch, tmp_path)
    doc = _srt_doc_30s()
    antes = [(c.index, c.start_ms, c.end_ms, c.lines) for c in doc.cues]
    clipper.generar_clips(Path("v.mp4"), _words(), "cortos", srt_document=doc)
    assert [(c.index, c.start_ms, c.end_ms, c.lines) for c in doc.cues] == antes


def test_generar_clips_clips_json_incluye_srt(tmp_path, monkeypatch):
    _mock_llm(monkeypatch)
    clips_dir, _tr = _mock_dirs_and_cut(monkeypatch, tmp_path)
    clipper.generar_clips(Path("mistem.mp4"), _words(), "cortos", srt_document=_srt_doc_30s())
    data = json.loads((clips_dir / "mistem_clips.json").read_text(encoding="utf-8"))
    assert "srt" in data["clips"][0]


def test_slice_coincide_con_exportar(tmp_path, monkeypatch):
    # el SRT derivado del clip == slice_srt directo del intervalo (contrato compartido)
    monkeypatch.setattr(clipper, "TRANSCRIPTS_DIR", tmp_path)
    doc = _srt_doc_30s()
    clipper.exportar_srt_clip(doc, 10.0, 20.0, "clipS")
    directo = slice_srt(doc, 10000, 20000, rebase=True, reindex=True)
    derived = load_srt(tmp_path / "clipS.srt")
    assert [(c.start_ms, c.end_ms, c.lines) for c in derived.cues] == [
        (c.start_ms, c.end_ms, c.lines) for c in directo.cues
    ]
