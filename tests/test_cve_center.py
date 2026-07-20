"""Tests de la marca [center] conectada al render (F6 esencial, PASO D).

Prioridad de posicion (pre-firmada):
    marca manual [center]  ->  decision explicita del preset  ->  avoid_faces  ->  default
- `[center]` nunca aparece en el texto final (voto #34).
- Centra el caption del grupo correspondiente; compatible con phrase spans.
- Conflictos resueltos determinismamente. Sin regresion transcript/SRT.
"""

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import core_ass
import cve


def _grupo(
    palabras: list[str], g_id: int = 0, texto: str | None = None, start: float = 0.0
) -> dict:
    words = [
        {"text": p, "start": start + i * 0.5, "end": start + i * 0.5 + 0.4, "line_idx": 0}
        for i, p in enumerate(palabras)
    ]
    return {
        "id": g_id,
        "start": start,
        "end": start + len(palabras) * 0.5,
        "text": texto if texto is not None else " ".join(palabras),
        "words": words,
    }


def _csv(tmp_path: Path, y: float) -> Path:
    p = tmp_path / "trayectoria_test.csv"
    p.write_text(
        "t,cam_center_x,face_x_asignada,distancia,conf_asignada,face_y_asignada\n"
        f"0.0000,500.0,500.0,0.0,0.900,{y:.3f}\n"
        f"0.5000,500.0,500.0,0.0,0.900,{y:.3f}\n",
        encoding="utf-8",
    )
    return p


# ── [center] conectada al render ──────────────────────────────────────────────


def test_center_mark_pone_caption_pos_center():
    g = _grupo(["la", "frase", "principal"], texto="[center]la frase principal")
    plan = cve.resolve_preset("clean_podcast")
    out, _plan, _aviso = cve.aplicar_preset([g], plan, None, 1080, 1920)
    assert out[0]["caption_pos"] == "center"


def test_center_no_aparece_en_el_texto():
    g = _grupo(["la", "frase", "principal"], texto="[center]la frase principal")
    plan = cve.resolve_preset("clean_podcast")
    out, _plan, _aviso = cve.aplicar_preset([g], plan, None, 1080, 1920)
    assert [w["text"] for w in out[0]["words"]] == ["la", "frase", "principal"]
    assert "center" not in out[0]["text"] and "[" not in out[0]["text"]


def test_center_cerrado_no_aparece_en_ass(tmp_path):
    g = _grupo(["titulo", "grande"], texto="[center]titulo grande[/center]")
    plan = cve.resolve_preset("clean_podcast")
    out, _plan, _aviso = cve.aplicar_preset([g], plan, None, 1080, 1920)
    ass = tmp_path / "center.ass"
    core_ass.build_ass(out, 1080, 1920, plan.style_cfg, ass)
    contenido = ass.read_text(encoding="utf-8")
    assert "[center]" not in contenido and "[/center]" not in contenido
    assert "\\an5" in contenido  # centrado real


# ── Prioridad: manual gana a avoid_faces y a preset ───────────────────────────


def test_center_manual_gana_a_avoid_faces(tmp_path):
    # cara abajo: sin center, avoid moveria a top; el [center] manual manda -> center
    csv = _csv(tmp_path, 0.85)
    g = _grupo(["la", "clave"], texto="[center]la clave")
    plan = cve.resolve_preset("clean_podcast")  # avoid_faces True
    out, _plan, _aviso = cve.aplicar_preset([g], plan, None, 1080, 1920, None, csv)
    assert out[0]["caption_pos"] == "center"


def test_sin_center_avoid_faces_si_mueve(tmp_path):
    # control: mismo CSV sin [center] -> avoid mueve bottom->top (cara abajo)
    csv = _csv(tmp_path, 0.85)
    g = _grupo(["la", "clave"])
    plan = cve.resolve_preset("clean_podcast")
    out, _plan, _aviso = cve.aplicar_preset([g], plan, None, 1080, 1920, None, csv)
    assert out[0]["caption_pos"] == "top"


def test_center_manual_gana_a_preset_top():
    g = _grupo(["la", "clave"], texto="[center]la clave")
    plan = replace(cve.resolve_preset("clean_podcast"), position="top")
    out, _plan, _aviso = cve.aplicar_preset([g], plan, None, 1080, 1920)
    assert out[0]["caption_pos"] == "center"  # manual gana al preset


# ── Compatibilidad con phrase spans ───────────────────────────────────────────


def test_center_compatible_con_span():
    g = _grupo(["la", "frase", "clave"], texto="[center][strong]la frase clave[/strong]")
    plan = cve.resolve_preset("keyword_punch")
    out, _plan, _aviso = cve.aplicar_preset([g], plan, None, 1080, 1920)
    assert out[0]["caption_pos"] == "center"
    assert all(w.get("is_keyword") for w in out[0]["words"])  # span marca cada palabra


# ── Determinismo y no regresion ───────────────────────────────────────────────


def test_center_determinista():
    g = _grupo(["la", "clave"], texto="[center]la clave")
    plan = cve.resolve_preset("clean_podcast")
    a, _p, _a = cve.aplicar_preset([g], plan, None, 1080, 1920)
    b, _p2, _a2 = cve.aplicar_preset(
        [_grupo(["la", "clave"], texto="[center]la clave")], plan, None, 1080, 1920
    )
    assert a[0]["caption_pos"] == b[0]["caption_pos"] == "center"


def test_sin_center_no_pone_caption_pos():
    g = _grupo(["texto", "normal", "sin", "marca"])
    plan = cve.resolve_preset("clean_podcast")
    out, _plan, _aviso = cve.aplicar_preset([g], plan, None, 1080, 1920)
    assert "caption_pos" not in out[0]  # ruta historica byte-identica


def test_center_solo_afecta_su_grupo():
    g0 = _grupo(["centra", "esto"], 0, texto="[center]centra esto")
    g1 = _grupo(["esto", "no"], 1)
    plan = cve.resolve_preset("clean_podcast")
    out, _plan, _aviso = cve.aplicar_preset([g0, g1], plan, None, 1080, 1920)
    assert out[0]["caption_pos"] == "center"
    assert "caption_pos" not in out[1]
