"""Gate de piezas SELLADAS vs VISIBLES (HF-4 hotfix, TAREA 3). FFmpeg real (lavfi, sin red,
sin HyperFrames): no necesita `hf_real`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import motion_gate_visibilidad as gv

ROJO = "#FF3D3D"
VIOLETA = "#6C3AED"
ANCHO, ALTO = 320, 180


def _clip_solido(path: Path, color: str, dur_s: float) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s={ANCHO}x{ALTO}:d={dur_s}:r=10",
            str(path),
        ],
        check=True,
        timeout=60,
    )


def _sello(piezas: list[tuple[str, int, int]]) -> dict:
    return {
        "piezas": [{"plantilla": p, "t0_ms": t0, "t1_ms": t1} for p, t0, t1 in piezas],
    }


def test_pieza_visible_no_es_un_problema(tmp_path):
    mp4 = tmp_path / "clip.mp4"
    _clip_solido(mp4, ROJO, 3.0)
    sello = _sello([("hook", 0, 2500)])
    problemas = gv.piezas_declaradas_pero_invisibles(
        mp4, sello, {"hook": ROJO}, tmp_dir=tmp_path / "frames"
    )
    assert problemas == ()


def test_pieza_declarada_pero_ausente_es_un_problema(tmp_path):
    """El video entero es NEGRO (sin el acento de la pieza): exactamente el sintoma medido en
    mariosoto_clip2_corto -- el sello dice que hay una pieza y el MP4 no la muestra."""
    mp4 = tmp_path / "clip.mp4"
    _clip_solido(mp4, "black", 3.0)
    sello = _sello([("hook", 0, 2500)])
    problemas = gv.piezas_declaradas_pero_invisibles(
        mp4, sello, {"hook": ROJO}, tmp_dir=tmp_path / "frames"
    )
    assert len(problemas) == 1
    assert problemas[0].plantilla == "hook"
    assert problemas[0].pixeles_hallados < gv.UMBRAL_PIXELES_VISIBLE


def test_compara_por_pieza_no_solo_globalmente(tmp_path):
    """Dos piezas selladas, una visible (rojo) y otra invisible (falta el acento violeta): el
    gate no puede aprobar el clip completo solo porque UNA pieza si aparece."""
    mp4 = tmp_path / "clip.mp4"
    _clip_solido(mp4, ROJO, 3.0)
    sello = _sello([("hook", 0, 1000), ("lower_third", 1500, 3000)])
    problemas = gv.piezas_declaradas_pero_invisibles(
        mp4, sello, {"hook": ROJO, "lower_third": VIOLETA}, tmp_dir=tmp_path / "frames"
    )
    assert {p.plantilla for p in problemas} == {"lower_third"}


def test_plantilla_sin_acento_mapeado_se_salta(tmp_path):
    mp4 = tmp_path / "clip.mp4"
    _clip_solido(mp4, "black", 2.0)
    sello = _sello([("desconocida", 0, 1000)])
    problemas = gv.piezas_declaradas_pero_invisibles(
        mp4, sello, {"hook": ROJO}, tmp_dir=tmp_path / "frames"
    )
    assert problemas == ()


def test_contar_pixeles_acento_extrapola_por_el_muestreo(tmp_path):
    png = tmp_path / "solido.png"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c={ROJO}:s=100x100",
            "-frames:v",
            "1",
            str(png),
        ],
        check=True,
        timeout=60,
    )
    n = gv.contar_pixeles_acento(png, ROJO, muestreo=2)
    assert n == 100 * 100
