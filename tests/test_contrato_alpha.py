"""Tests de contrato Alpha 0.1 (S34): splits sin cambio de comportamiento + QA en Studio.

Contratos verificados:
- El split de caption.py NO rompe la CLI publica (mismos flags, mismos defaults).
- jobs.py y auto.py re-exportan lo movido (consumidores intactos).
- qa_para_studio: modo alertas no toca los groups; auto_seguro reagrupa desde los
  words corregidos; fail-open sin words.json.
- El endpoint de render valida caption_qa con error accionable.
- La documentacion de Alpha para testers existe (checklist incluido).
"""

from __future__ import annotations

import json
from pathlib import Path

RAIZ = Path(__file__).parent.parent


# ── split B1: CLI publica intacta ────────────────────────────────────────────


def test_split_cli_publica_intacta():
    from caption_args import build_parser

    args = build_parser().parse_args(["video.mp4"])
    assert args.style == "hormozi"
    assert args.model == "auto"
    assert args.caption_qa is False
    assert args.caption_qa_mode == "alertas"
    args = build_parser().parse_args(
        [
            "video.mp4",
            "--caption-qa",
            "--caption-qa-mode",
            "auto_seguro",
            "--guion",
            "g.txt",
            "--preset",
            "keyword_punch",
            "--densidad",
            "baja",
        ]
    )
    assert args.caption_qa is True and args.caption_qa_mode == "auto_seguro"
    assert args.guion == "g.txt" and args.preset == "keyword_punch"


def test_qa_opts_de_args():
    from caption_args import build_parser, qa_opts_de_args

    sin = build_parser().parse_args(["v.mp4"])
    assert qa_opts_de_args(sin) is None, "sin --caption-qa la capa queda apagada (regla 15)"
    con = build_parser().parse_args(["v.mp4", "--caption-qa"])
    opts = qa_opts_de_args(con)
    assert opts == {"modo": "alertas", "guion": None, "glosario": None, "llm": False}


def test_jobs_reexporta_run_render():
    import jobs
    import jobs_render

    assert jobs.run_render is jobs_render.run_render


def test_auto_reexporta_reporte():
    import auto
    import auto_report

    assert auto.generar_reporte_md is auto_report.generar_reporte_md
    assert auto.avisos_de_segmentos is auto_report.avisos_de_segmentos
    assert auto.resumen_paquete is auto_report.resumen_paquete
    assert auto.C1V2_AVISO == auto_report.C1V2_AVISO


# ── B2: Caption QA en el Studio ──────────────────────────────────────────────


def _words_confeti() -> list[dict]:
    return [
        {"w": "usamos", "s": 0.5, "e": 0.9, "prob": 0.97},
        {"w": "confeti", "s": 1.0, "e": 1.4, "prob": 0.42},
        {"w": "UI", "s": 1.5, "e": 1.9, "prob": 0.40},
        {"w": "hoy", "s": 2.0, "e": 2.3, "prob": 0.98},
    ]


def _preparar_words(tmp_path, monkeypatch, name="demo"):
    import caption_qa as cq

    monkeypatch.setattr(cq, "TRANSCRIPTS", tmp_path)
    (tmp_path / f"{name}_words.json").write_text(
        json.dumps({"words": _words_confeti(), "language": "es"}), encoding="utf-8"
    )
    return cq


def test_qa_para_studio_alertas_no_toca_groups(tmp_path, monkeypatch):
    cq = _preparar_words(tmp_path, monkeypatch)
    groups = [{"id": 0, "text": "lo que sea", "words": []}]
    salida, resumen = cq.qa_para_studio("demo", "alertas", None, groups)
    assert salida is groups, "modo alertas devuelve LOS MISMOS groups"
    assert resumen["n_alertas"] == 1 and resumen["aplicadas"] == 0
    assert (tmp_path / "demo_caption_alerts.json").exists()


def test_qa_para_studio_auto_seguro_reagrupa(tmp_path, monkeypatch):
    cq = _preparar_words(tmp_path, monkeypatch)
    groups = [{"id": 0, "text": "original", "words": []}]
    salida, resumen = cq.qa_para_studio("demo", "auto_seguro", None, groups)
    assert resumen["aplicadas"] == 1
    textos = [w["text"] for g in salida for w in g["words"]]
    assert "ComfyUI" in textos, "los groups nuevos traen la correccion quemable"


def test_qa_para_studio_fail_open_sin_words(tmp_path, monkeypatch):
    cq = _preparar_words(tmp_path, monkeypatch)
    groups = [{"id": 0}]
    salida, resumen = cq.qa_para_studio("no_existe", "alertas", None, groups)
    assert salida is groups and resumen is None


def test_endpoint_render_valida_caption_qa():
    from fastapi import HTTPException

    import app as studio

    try:
        studio.start_render("cualquiera", caption_qa="turbo")
        raise AssertionError("debio lanzar HTTPException 400")
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "alertas" in exc.detail and "auto_seguro" in exc.detail, "error accionable"


# ── B3: docs Alpha para testers ──────────────────────────────────────────────


def test_docs_alpha_existen():
    doc = RAIZ / "docs" / "ALPHA_TESTERS.md"
    assert doc.exists(), "falta la guia de testers (s34 B3)"
    texto = doc.read_text(encoding="utf-8")
    for seccion in ("Checklist", "Modo Autom", "REPORTE.md", "Caption QA", "output"):
        assert seccion in texto, f"la guia no cubre: {seccion}"
