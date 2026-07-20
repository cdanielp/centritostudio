"""Tests de producción REAL de face_y_asignada (F6, TAREA 3/4 del PR #23).

No fabrican solo el CSV final: ejercitan el PRODUCTOR real del track por segmento
(`reframe_escenas._seg_single`, que elige la cara asignada del detector) y el
SERIALIZADOR real (`reframe._exportar_trayectoria_csv`), y luego el consumo real en
`cve.zona_cara_en_rango` → `resolver_posicion_captions` → caption_pos.

Se INYECTA la salida del detector existente (dicts {center_x, center_y, bbox, score})
antes de serializar — no se agrega otro detector ni una segunda pasada. Sin red, sin GPU.
"""

from __future__ import annotations

import csv as _csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import cve
import reframe
import reframe_escenas

SRC_W, SRC_H, FPS = 1080, 1920, 30.0


def _det(cx: float, cy: float, score: float = 0.9) -> dict:
    """Detección con la MISMA forma que produce reframe_track.detectar_todas_caras_frame."""
    return {"center_x": cx, "center_y": cy, "bbox": [cx - 40, cy - 60, 80, 120], "score": score}


def _si(n: int = 10, ancla: float = 540.0) -> dict:
    return {"f_ini": 0, "f_fin": n, "tipo": "single", "caras": [_det(ancla, SRC_H / 2)]}


def _producir_csv(tmp_path: Path, cy_px: float | None, n: int = 6) -> Path:
    """Corre el productor REAL (_seg_single) + serializador REAL con detección inyectada."""
    dets = {}
    if cy_px is not None:
        for fi in range(0, n, 3):  # detecciones cada 3 frames (como DETECT_EVERY_N)
            dets[fi] = [_det(540.0, cy_px)]
    crops, filled, conf, cy, _n = reframe_escenas._seg_single(_si(n), dets, FPS, SRC_W, SRC_H)
    reframe._exportar_trayectoria_csv(
        "demo", crops, filled, FPS, tmp_path, sparsa_conf=conf, sparsa_cy=cy, src_h=SRC_H
    )
    return tmp_path / "trayectoria_demo.csv"


# ── Productor real: _seg_single captura center_y de la cara asignada ──────────


def test_seg_single_captura_center_y_de_la_cara_asignada():
    dets = {0: [_det(540.0, 300.0)], 3: [_det(540.0, 320.0)]}
    _c, _f, conf, cy, _n = reframe_escenas._seg_single(_si(6), dets, FPS, SRC_W, SRC_H)
    assert set(cy) == set(conf)  # misma detección que conf_asignada
    assert cy[0] == 300.0 and cy[3] == 320.0  # center_y crudo de la cara asignada


# ── Serializador real: columna face_y_asignada normalizada 0..1 ───────────────


def test_csv_contiene_face_y_normalizada(tmp_path):
    csv_path = _producir_csv(tmp_path, cy_px=384.0)  # 384/1920 = 0.2
    with open(csv_path, encoding="utf-8") as f:
        rows = list(_csv.DictReader(f))
    assert "face_y_asignada" in rows[0]
    vivas = [r for r in rows if r["conf_asignada"].strip()]
    assert vivas and all(abs(float(r["face_y_asignada"]) - 0.2) < 1e-6 for r in vivas)
    # frames sin detección viva: face_y vacío (misma detección que conf)
    muertas = [r for r in rows if not r["conf_asignada"].strip()]
    assert all(r["face_y_asignada"].strip() == "" for r in muertas)


def test_csv_legacy_sin_columna_cuando_no_hay_cy(tmp_path):
    dets = {0: [_det(540.0, 300.0)]}
    crops, filled, conf, _cy, _n = reframe_escenas._seg_single(_si(4), dets, FPS, SRC_W, SRC_H)
    reframe._exportar_trayectoria_csv("demo", crops, filled, FPS, tmp_path, sparsa_conf=conf)
    with open(tmp_path / "trayectoria_demo.csv", encoding="utf-8") as f:
        cols = next(_csv.reader(f))
    assert "face_y_asignada" not in cols  # compat CSV legacy


def test_csv_coordenadas_limite_clamp(tmp_path):
    csv_top = _producir_csv(tmp_path, cy_px=0.0)
    with open(csv_top, encoding="utf-8") as f:
        vivas = [r for r in _csv.DictReader(f) if r["conf_asignada"].strip()]
    assert all(0.0 <= float(r["face_y_asignada"]) <= 1.0 for r in vivas)


# ── Flujo REAL end-to-end: productor → serializador → cve → caption_pos ────────


def _zona_y_pos(tmp_path, cy_px, base="bottom"):
    from dataclasses import replace

    csv_path = _producir_csv(tmp_path, cy_px)
    zona = cve.zona_cara_en_rango(csv_path, 0.0, 10.0)
    plan = replace(cve.resolve_preset("clean_podcast"), position=base)
    g = {"id": 0, "start": 0.0, "end": 0.15, "text": "hola", "words": []}
    out = cve.resolver_posicion_captions([g], plan, csv_path)
    return zona, out[0].get("caption_pos")


def test_e2e_cara_inferior_sube_caption(tmp_path):
    zona, pos = _zona_y_pos(tmp_path, cy_px=SRC_H * 0.85)
    assert zona == "bottom" and pos == "top"


def test_e2e_cara_superior_con_base_top_baja_caption(tmp_path):
    zona, pos = _zona_y_pos(tmp_path, cy_px=SRC_H * 0.15, base="top")
    assert zona == "top" and pos == "bottom"


def test_e2e_cara_central_con_base_center_alterna(tmp_path):
    zona, pos = _zona_y_pos(tmp_path, cy_px=SRC_H * 0.5, base="center")
    assert zona == "center" and pos == "bottom"


def test_e2e_sin_cara_conserva_base(tmp_path):
    zona, pos = _zona_y_pos(tmp_path, cy_px=None)
    assert zona is None and pos in (None, "bottom")


def test_e2e_multiples_muestras_promedia(tmp_path):
    # Varias muestras en el intervalo -> zona por promedio (todas abajo -> bottom)
    zona, pos = _zona_y_pos(tmp_path, cy_px=SRC_H * 0.9)
    assert zona == "bottom" and pos == "top"


def test_e2e_valor_corrupto_fail_open(tmp_path):
    csv_path = _producir_csv(tmp_path, cy_px=SRC_H * 0.85)
    # corromper el valor de face_y en la primera fila viva
    txt = csv_path.read_text(encoding="utf-8").replace("0.850", "NaNoNo")
    csv_path.write_text(txt, encoding="utf-8")
    # no debe romper: zona None o un valor válido; nunca excepción
    zona = cve.zona_cara_en_rango(csv_path, 0.0, 10.0)
    assert zona in (None, "top", "center", "bottom")


def test_e2e_marca_center_manual_gana(tmp_path):
    csv_path = _producir_csv(tmp_path, cy_px=SRC_H * 0.85)  # cara abajo
    plan = cve.resolve_preset("clean_podcast")
    g = {"id": 0, "start": 0.0, "end": 0.15, "text": "clave", "words": [], "center": True}
    out = cve.resolver_posicion_captions([g], plan, csv_path)
    assert out[0]["caption_pos"] == "center"  # marca manual gana a avoid_faces
