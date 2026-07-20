"""Tests de center_y en la ruta multi-cara con turnos (F6 avoid_faces v2, BLOQUEO 2 PR #23).

La conmutacion por turnos debe conservar el center_y de la MISMA deteccion que aporto
center_x y score, aplanarlo a la cara activa del turno y serializarlo normalizado 0..1.
Se inyecta la salida del detector existente (dicts {center_x, center_y, bbox, score}) y una
captura de video falsa — sin GPU, sin red, sin segunda pasada, sin crear otro detector.
"""

from __future__ import annotations

import csv as _csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import reframe
import reframe_detect as rd
import reframe_track as rt

SRC_W, SRC_H, FPS = 1080, 1920, 30.0


def _det(cx: float, cy: float, score: float = 0.9) -> dict:
    return {"center_x": cx, "center_y": cy, "bbox": [cx - 40, cy - 60, 80, 120], "score": score}


# ── _asignar_detecciones_a_caras: exclusiva + conserva center_y de la misma deteccion ──


def test_asignacion_conserva_center_y_de_la_misma_deteccion():
    caras = [{"id": 0, "center_x": 300.0}, {"id": 1, "center_x": 800.0}]
    dets = [_det(300.0, 200.0, 0.9), _det(800.0, 1500.0, 0.8)]
    sparsa = {0: {}, 1: {}}
    conf = {0: {}, 1: {}}
    cy = {0: {}, 1: {}}
    rd._asignar_detecciones_a_caras(dets, caras, sparsa, conf, 3, 200.0, cy)
    # cada cara recibe center_x/score/center_y de SU deteccion (misma fila)
    assert sparsa[0][3] == 300.0 and conf[0][3] == 0.9 and cy[0][3] == 200.0
    assert sparsa[1][3] == 800.0 and conf[1][3] == 0.8 and cy[1][3] == 1500.0


def test_dos_caras_no_comparten_una_deteccion():
    # Una sola deteccion, dos caras dentro del gate: solo la mas cercana la recibe
    caras = [{"id": 0, "center_x": 500.0}, {"id": 1, "center_x": 560.0}]
    dets = [_det(505.0, 400.0, 0.9)]
    sparsa = {0: {}, 1: {}}
    conf = {0: {}, 1: {}}
    cy = {0: {}, 1: {}}
    rd._asignar_detecciones_a_caras(dets, caras, sparsa, conf, 0, 200.0, cy)
    asignadas = [cid for cid in (0, 1) if 0 in cy[cid]]
    assert asignadas == [0]  # cara 0 (dist 5) gana; cara 1 queda vacia
    assert 0 not in cy[1]


def test_asignacion_sin_sparsa_cy_no_rompe():
    # Retrocompat: sin el dict cy (None) la asignacion sigue funcionando
    caras = [{"id": 0, "center_x": 300.0}]
    sparsa, conf = {0: {}}, {0: {}}
    rd._asignar_detecciones_a_caras([_det(300.0, 200.0)], caras, sparsa, conf, 0, 200.0, None)
    assert sparsa[0][0] == 300.0 and conf[0][0] == 0.9


# ── aplanar_cy_por_turnos: cara activa del turno + cambio de track vertical ────

_TURNOS = [
    {"t_ini": 0.0, "t_fin": 1.0, "cara_id": 0},  # f 0..29 a 30fps
    {"t_ini": 1.0, "t_fin": 2.0, "cara_id": 1},  # f 30..59
]
_CY_MULTI = {
    0: {0: 200.0, 3: 210.0, 27: 220.0},  # cara 0 arriba
    1: {30: 1600.0, 33: 1620.0},  # cara 1 abajo
}


def test_aplanar_cy_usa_cara_activa_del_turno():
    r = rt.aplanar_cy_por_turnos(_CY_MULTI, _TURNOS, 30.0, 60)
    assert r[0] == 200.0 and r[3] == 210.0 and r[27] == 220.0  # turno 0 -> cara 0
    assert r[30] == 1600.0 and r[33] == 1620.0  # turno 1 -> cara 1


def test_cambio_de_turno_cambia_track_vertical():
    r = rt.aplanar_cy_por_turnos(_CY_MULTI, _TURNOS, 30.0, 60)
    # el ultimo frame del turno 0 (cara arriba) y el primero del turno 1 (cara abajo) difieren
    assert r[27] < 300 and r[30] > 1500


def test_aplanar_cy_deteccion_ausente_deja_celda_vacia():
    r = rt.aplanar_cy_por_turnos(_CY_MULTI, _TURNOS, 30.0, 60)
    assert 1 not in r and 15 not in r  # frames sin deteccion no aparecen


def test_aplanar_cy_detector_sin_resultados_no_rompe():
    assert rt.aplanar_cy_por_turnos({0: {}, 1: {}}, _TURNOS, 30.0, 60) == {}


def test_aplanar_cy_misma_segmentacion_que_conf():
    # cy y conf deben cubrir EXACTAMENTE los mismos frames (misma deteccion)
    conf_multi = {0: {0: 0.5, 3: 0.6, 27: 0.7}, 1: {30: 0.8, 33: 0.9}}
    fc = rt.aplanar_conf_por_turnos(conf_multi, _TURNOS, 30.0, 60)
    fcy = rt.aplanar_cy_por_turnos(_CY_MULTI, _TURNOS, 30.0, 60)
    assert set(fc) == set(fcy)


# ── Serializador: flat_cy normalizado y clampeado 0..1 en el CSV ──────────────


def test_flat_cy_serializado_normaliza_y_clampa(tmp_path):
    # center_y en px (incluso fuera de rango) -> columna face_y_asignada en [0,1]
    crops = [(0, 0, 1080, SRC_H)] * 6
    filled = [540.0] * 6
    flat_cy = {0: 200.0, 3: float(SRC_H + 500)}  # segundo fuera de rango -> clamp a 1.0
    reframe._exportar_trayectoria_csv(
        "demo",
        crops,
        filled,
        FPS,
        tmp_path,
        sparsa_conf={0: 0.9, 3: 0.8},
        sparsa_cy=flat_cy,
        src_h=SRC_H,
    )
    with open(tmp_path / "trayectoria_demo.csv", encoding="utf-8") as f:
        rows = list(_csv.DictReader(f))
    vivas = [r for r in rows if r["face_y_asignada"].strip()]
    vals = [float(r["face_y_asignada"]) for r in vivas]
    assert all(0.0 <= v <= 1.0 for v in vals)
    assert abs(vals[0] - round(200.0 / SRC_H, 3)) < 1e-6 and vals[1] == 1.0


# ── _detectar_trayectorias_multi: 3-tupla real con detector y captura inyectados ──


class _FakeCap:
    def __init__(self, n):
        self._n = n
        self._i = 0

    def read(self):
        if self._i >= self._n:
            return False, None
        self._i += 1
        return True, object()

    def release(self):
        pass


class _FakeDetector:
    def __init__(self, dets):
        self._dets = dets
        self.detect_calls = 0

    def detect_all(self, _frame):
        self.detect_calls += 1
        return list(self._dets)

    def close(self):
        pass


def test_detectar_trayectorias_multi_devuelve_cy(monkeypatch):
    caras = [{"id": 0, "center_x": 300.0}, {"id": 1, "center_x": 800.0}]
    dets = [_det(300.0, 200.0, 0.9), _det(800.0, 1500.0, 0.8)]
    fake = _FakeDetector(dets)
    monkeypatch.setattr(rd.cv2, "VideoCapture", lambda _p: _FakeCap(6))
    monkeypatch.setattr(rd, "_crear_detector", lambda *_a, **_k: fake)
    sparsa, conf, cy = rd._detectar_trayectorias_multi(Path("x.mp4"), 6, caras, SRC_W)
    # tres estructuras, misma forma; cy[cara][frame] es el center_y de esa cara
    assert set(sparsa) == set(conf) == set(cy) == {0, 1}
    assert cy[0] and cy[1]
    assert all(cy[0][fi] == 200.0 for fi in cy[0])
    assert all(cy[1][fi] == 1500.0 for fi in cy[1])
    # un solo detector (no segunda pasada): se detecta 1 vez por frame muestreado (fi 0,3)
    assert fake.detect_calls == 2


def test_detectar_trayectorias_multi_detector_vacio_no_rompe(monkeypatch):
    caras = [{"id": 0, "center_x": 300.0}, {"id": 1, "center_x": 800.0}]
    fake = _FakeDetector([])
    monkeypatch.setattr(rd.cv2, "VideoCapture", lambda _p: _FakeCap(6))
    monkeypatch.setattr(rd, "_crear_detector", lambda *_a, **_k: fake)
    sparsa, conf, cy = rd._detectar_trayectorias_multi(Path("x.mp4"), 6, caras, SRC_W)
    assert cy == {0: {}, 1: {}} and sparsa == {0: {}, 1: {}}
