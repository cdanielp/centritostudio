"""reframe_detect.py — Deteccion de cara y trayectoria para el reframe 9:16.

Contiene las funciones con I/O de video (OpenCV + MediaPipe/YuNet) separadas de la
orquestacion principal. Importado exclusivamente por reframe.py.

Detectores disponibles:
  yunet    (default): cv2.FaceDetectorYN con modelo ONNX — alta confianza en 480p/1080p.
             Umbral 0.75 validado contra busto decorativo y punos en nuestro video.
             Downscale automatico a YUNET_MAX_INPUT_W si el frame es muy ancho.
  blazeface (fallback): MediaPipe FaceDetector short-range .tflite.
             Activar con --detector blazeface. Confianza baja (~0.40) en 480p.
"""

from __future__ import annotations

from pathlib import Path

import cv2

import reframe_track as rt

# ── Rutas de modelos ──────────────────────────────────────────────────────────

MODEL_PATH_SHORT = Path(__file__).parent / "models" / "blaze_face_short_range.tflite"
MODEL_PATH_FULL = Path(__file__).parent / "models" / "blaze_face_full_range.tflite"
YUNET_MODEL_PATH = (
    Path(__file__).parent / "referencia" / "yunet" / "face_detection_yunet_2023mar.onnx"
)

# ── Constantes YuNet ──────────────────────────────────────────────────────────

YUNET_SCORE_THRESHOLD = (
    0.75  # validado contra busto(0.65-0.69) y punos(0.73) en prueba2personasenmedio.mov
)
YUNET_MAX_INPUT_W = 1920  # downscale frames mas anchos para mantener precision
YUNET_FACE_MAX_AREA_FRAC = 0.02056  # filtro de area: derivado de proyecto referencia

ACTIVE_MODEL_PATH = (
    MODEL_PATH_SHORT  # BlazeFace (para compatibilidad con flag --detector blazeface)
)


# ── Detector YuNet ────────────────────────────────────────────────────────────


class YuNetDetector:
    """Wrapper de cv2.FaceDetectorYN con cache de input_size y downscale automatico.

    Interfaz: close() + detect_all(frame) -> list[dict] compatible con
    detectar_todas_caras_frame en reframe_track.py.
    """

    def __init__(
        self,
        model_path: Path = YUNET_MODEL_PATH,
        score_threshold: float = YUNET_SCORE_THRESHOLD,
        max_input_w: int = YUNET_MAX_INPUT_W,
        face_max_area_frac: float = YUNET_FACE_MAX_AREA_FRAC,
    ) -> None:
        self._model_path = model_path
        self._score_threshold = score_threshold
        self._max_input_w = max_input_w
        self._face_max_area_frac = face_max_area_frac
        self._det: cv2.FaceDetectorYN | None = None
        self._input_size: tuple[int, int] | None = None

    def _get_det(self, w: int, h: int) -> cv2.FaceDetectorYN:
        if self._input_size != (w, h) or self._det is None:
            self._det = cv2.FaceDetectorYN_create(
                str(self._model_path),
                "",
                (w, h),
                score_threshold=self._score_threshold,
                nms_threshold=0.3,
                top_k=5000,
            )
            self._det.setInputSize((w, h))
            self._input_size = (w, h)
        return self._det

    def detect_all(self, frame) -> list[dict]:
        """Detecta todas las caras. Devuelve lista ordenada por score desc.

        Cada elemento: {'center_x', 'center_y', 'bbox': [x,y,w,h], 'score'}.
        Coordenadas en el espacio del frame original (antes del downscale).
        """
        h_orig, w_orig = frame.shape[:2]

        # Downscale si el frame es mas ancho que el umbral
        if w_orig > self._max_input_w:
            scale = self._max_input_w / w_orig
            w_in = self._max_input_w
            h_in = int(h_orig * scale)
            frame_in = cv2.resize(frame, (w_in, h_in))
        else:
            scale = 1.0
            w_in, h_in = w_orig, h_orig
            frame_in = frame

        det = self._get_det(w_in, h_in)
        _, faces = det.detect(frame_in)
        if faces is None:
            return []

        results = []
        for f in faces:
            x_d, y_d, fw_d, fh_d = f[0:4].astype(int).tolist()
            score = float(f[14])
            # Filtro de area sobre las coords DETECCION (frame downscaleado)
            area_frac = (fw_d * fh_d) / (w_in * h_in)
            if area_frac > self._face_max_area_frac:
                continue
            # Proyectar coordenadas al espacio del frame original
            inv = 1.0 / scale
            x = x_d * inv
            y = y_d * inv
            fw = fw_d * inv
            fh = fh_d * inv
            results.append(
                {
                    "center_x": x + fw / 2,
                    "center_y": y + fh / 2,
                    "bbox": [int(x), int(y), int(fw), int(fh)],
                    "score": score,
                }
            )
        return sorted(results, key=lambda d: -d["score"])

    def close(self) -> None:
        self._det = None


# ── Detector BlazeFace (fallback) ─────────────────────────────────────────────


def _crear_detector_blazeface(model_path: Path | None = None):
    """Crea un FaceDetector MediaPipe Tasks en modo IMAGE (BlazeFace)."""
    from mediapipe.tasks import python as _mp_python  # noqa: PLC0415
    from mediapipe.tasks.python import vision as _mp_vision  # noqa: PLC0415

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


# ── Factory publica ────────────────────────────────────────────────────────────


def _crear_detector(
    detector_type: str = "yunet",
    model_path: Path | None = None,
):
    """Crea el detector segun el tipo pedido.

    detector_type: 'yunet' (default) | 'blazeface'
    model_path: override de ruta del modelo (BlazeFace solamente).
    """
    if detector_type == "yunet":
        yn_path = YUNET_MODEL_PATH
        if not yn_path.exists():
            print(f"[reframe] YuNet no encontrado en {yn_path} -- fallback a BlazeFace")
            return _crear_detector_blazeface(model_path)
        return YuNetDetector(model_path=yn_path)
    return _crear_detector_blazeface(model_path)


# ── Trayectoria (funciones de alto nivel usadas por reframe.py) ───────────────


def _detectar_trayectoria(
    video_path: Path,
    total_frames: int,
    src_w: int,
    ancla_x: float,
    detector_type: str = "yunet",
) -> tuple[dict[int, float], dict[int, float]]:
    """Detecta center_x de la cara principal usando ancla estatica.

    Devuelve (sparsa, sparsa_conf) donde sparsa_conf[frame_idx] = score.
    Solo acepta detecciones dentro de GATE_ANCLA_PCT x src_w del ancla.
    """
    gate_ancla_w = rt.GATE_ANCLA_PCT * src_w
    cap = cv2.VideoCapture(str(video_path))
    detector = _crear_detector(detector_type)
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
            det_list = rt.detectar_todas_caras_frame(frame, detector)
            if not det_list:
                n_sin += 1
                continue
            best = det_list[0]
            new_x = best["center_x"]
            if abs(new_x - ancla_x) > gate_ancla_w:
                n_gated += 1
                continue
            sparsa[fi] = new_x
            sparsa_conf[fi] = best["score"]
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
    video_path: Path,
    total_frames: int,
    caras: list[dict],
    src_w: int,
    detector_type: str = "yunet",
) -> tuple[dict[int, dict[int, float]], dict[int, dict[int, float]]]:
    """Detecta center_x por cara cada DETECT_EVERY_N frames con ancla estatica.

    Devuelve (sparsa_multi, conf_multi) donde:
      sparsa_multi[cara_id][frame_idx] = center_x
      conf_multi[cara_id][frame_idx]   = score
    """
    gate_ancla_w = rt.GATE_ANCLA_PCT * src_w
    cap = cv2.VideoCapture(str(video_path))
    detector = _crear_detector(detector_type)
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
