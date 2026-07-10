"""reframe_detect.py — Deteccion de cara y trayectoria para el reframe 9:16.

Contiene las funciones con I/O de video (OpenCV + MediaPipe) separadas de la
orquestacion principal. Importado exclusivamente por reframe.py.
"""

from __future__ import annotations

from pathlib import Path

import cv2
from mediapipe.tasks import python as _mp_python
from mediapipe.tasks.python import vision as _mp_vision

import reframe_track as rt

MODEL_PATH_SHORT = Path(__file__).parent / "models" / "blaze_face_short_range.tflite"
MODEL_PATH_FULL = Path(__file__).parent / "models" / "blaze_face_full_range.tflite"

# Detector activo: cambiar a MODEL_PATH_FULL si la comparativa lo adopta
ACTIVE_MODEL_PATH = MODEL_PATH_SHORT


def _crear_detector(model_path: Path | None = None):
    """Crea un FaceDetector MediaPipe Tasks en modo IMAGE."""
    path = model_path or ACTIVE_MODEL_PATH
    if not path.exists():
        raise FileNotFoundError(f"Modelo MediaPipe no encontrado: {path}")
    base = _mp_python.BaseOptions(model_asset_path=str(path))
    opts = _mp_vision.FaceDetectorOptions(
        base_options=base,
        running_mode=_mp_vision.RunningMode.IMAGE,
        min_detection_confidence=rt.FACE_MIN_CONFIDENCE,
    )
    return _mp_vision.FaceDetector.create_from_options(opts)


def _detectar_trayectoria(
    video_path: Path, total_frames: int, src_w: int, ancla_x: float
) -> tuple[dict[int, float], dict[int, float]]:
    """Detecta center_x de la cara principal usando ancla estatica.

    Devuelve (sparsa, sparsa_conf) donde sparsa_conf[frame_idx] = score MediaPipe.
    Solo acepta detecciones dentro de GATE_ANCLA_PCT x src_w del ancla.
    """
    gate_ancla_w = rt.GATE_ANCLA_PCT * src_w
    cap = cv2.VideoCapture(str(video_path))
    detector = _crear_detector()
    sparsa: dict[int, float] = {}
    sparsa_conf: dict[int, float] = {}
    n_det = n_sin = n_gated = 0
    try:
        for fi in range(total_frames):
            ret, frame = cap.read()
            if not ret:
                break
            if fi % rt.DETECT_EVERY_N != 0:
                continue
            det = rt.detectar_cara_frame(frame, detector)
            if det is None:
                n_sin += 1
                continue
            new_x = det["center_x"]
            if abs(new_x - ancla_x) > gate_ancla_w:
                n_gated += 1
                continue
            sparsa[fi] = new_x
            sparsa_conf[fi] = det["score"]
            n_det += 1
    finally:
        cap.release()
        detector.close()
    if n_gated:
        print(f"[reframe] {n_gated} detecciones fuera del ancla (>{gate_ancla_w:.0f}px)")
    if n_sin > n_det:
        print(f"[reframe] cara perdida en {n_sin}/{n_det + n_sin} detecciones, manteniendo ultima")
    return sparsa, sparsa_conf


def _asignar_detecciones_a_caras(
    all_dets: list[dict],
    caras: list[dict],
    sparsa: dict[int, dict[int, float]],
    sparsa_conf: dict[int, dict[int, float]],
    fi: int,
    gate_ancla_w: float,
) -> None:
    """Asigna detecciones a tracks por ancla estatica; exclusiva por frame (greedy).

    Actualiza sparsa y sparsa_conf in-place.
    """
    pares = []
    for di, det in enumerate(all_dets):
        cx = det["center_x"]
        for cara in caras:
            dist = abs(cx - cara["center_x"])
            if dist <= gate_ancla_w:
                pares.append((dist, cara["id"], di, cx, det["score"]))
    asignados_cara: set[int] = set()
    asignados_det: set[int] = set()
    for _dist, cara_id, di, cx, score in sorted(pares):
        if cara_id in asignados_cara or di in asignados_det:
            continue
        sparsa[cara_id][fi] = cx
        sparsa_conf[cara_id][fi] = score
        asignados_cara.add(cara_id)
        asignados_det.add(di)


def _detectar_trayectorias_multi(
    video_path: Path, total_frames: int, caras: list[dict], src_w: int
) -> tuple[dict[int, dict[int, float]], dict[int, dict[int, float]]]:
    """Detecta center_x por cara cada DETECT_EVERY_N frames con ancla estatica.

    Devuelve (sparsa_multi, conf_multi) donde:
      sparsa_multi[cara_id][frame_idx] = center_x
      conf_multi[cara_id][frame_idx]   = score
    """
    gate_ancla_w = rt.GATE_ANCLA_PCT * src_w
    cap = cv2.VideoCapture(str(video_path))
    detector = _crear_detector()
    sparsa: dict[int, dict[int, float]] = {c["id"]: {} for c in caras}
    sparsa_conf: dict[int, dict[int, float]] = {c["id"]: {} for c in caras}
    try:
        for fi in range(total_frames):
            ret, frame = cap.read()
            if not ret:
                break
            if fi % rt.DETECT_EVERY_N != 0:
                continue
            all_dets = rt.detectar_todas_caras_frame(frame, detector)
            if all_dets:
                _asignar_detecciones_a_caras(all_dets, caras, sparsa, sparsa_conf, fi, gate_ancla_w)
    finally:
        cap.release()
        detector.close()
    return sparsa, sparsa_conf
