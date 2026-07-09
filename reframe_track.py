"""reframe_track.py — Deteccion de caras y matematicas de suavizado para el reframe 9:16.

Las funciones puras (calcular_ventana_crop, ema_smooth, etc.) son deterministas y
testeables sin video ni dependencias externas. detectar_cara_frame requiere mediapipe
y es stub hasta la sesion de implementacion de F4.1.
Disenio: revision/fase-4.1/DISENO_REFRAME.md
"""

from __future__ import annotations

# ── Parametros calibrables ────────────────────────────────────────────────────
# Ver tabla en DISENO_REFRAME.md §2 para rango sensato de cada constante.

EMA_ALPHA = 0.08  # suavizado: menor = mas suave y lento, mayor = mas reactivo
DEADZONE_PCT = 0.30  # zona muerta como fraccion de source_w
DETECT_EVERY_N = 3  # detectar cara cada N fotogramas
FACE_LOST_PATIENCE = 30  # fotogramas antes de iniciar recentrado gradual
PUNCH_ZOOM = 1.12  # factor de zoom punch-in (112% = crop 11% mas estrecho)
PUNCH_TRANS_FRAMES = 4  # fotogramas de rampa entrada/salida del punch-in
RECENTER_ALPHA = 0.05  # EMA hacia centro cuando cara perdida > patience
FACE_MIN_CONFIDENCE = 0.20  # confianza minima del detector (0.5 es alto para videos 480p)


# ── Geometria de crop (matematicas puras, sin I/O) ────────────────────────────


def calcular_ventana_crop(
    face_center_x: float, source_w: int, source_h: int
) -> tuple[int, int, int, int]:
    """Devuelve (x, y, w, h) de la ventana de crop 9:16 centrada en face_center_x.

    El tracking es solo horizontal: y=0 siempre, h=source_h siempre.
    x se clampea a [0, source_w - crop_w].
    """
    crop_w = source_h * 9 // 16
    crop_h = source_h
    x = int(face_center_x - crop_w / 2)
    x = max(0, min(x, source_w - crop_w))
    return (x, 0, crop_w, crop_h)


# ── Suavizado EMA ─────────────────────────────────────────────────────────────


def ema_smooth(positions: list[float], alpha: float) -> list[float]:
    """Filtra EMA sobre la secuencia de posiciones.

    smooth[0] = positions[0]; smooth[i] = alpha*pos[i] + (1-alpha)*smooth[i-1].
    """
    if not positions:
        return []
    smooth = [positions[0]]
    for p in positions[1:]:
        smooth.append(alpha * p + (1 - alpha) * smooth[-1])
    return smooth


# ── Deadzone ──────────────────────────────────────────────────────────────────


def aplicar_deadzone(face_x: float, current_target: float, deadzone_w: float) -> float:
    """Retorna current_target si la cara sigue en la zona muerta; face_x si sale."""
    if abs(face_x - current_target) <= deadzone_w / 2:
        return current_target
    return face_x


def aplicar_deadzone_secuencia(face_centers: list[float], deadzone_w: float) -> list[float]:
    """Aplica deadzone en secuencia; el target solo cambia cuando la cara sale de la zona."""
    if not face_centers:
        return []
    targets: list[float] = [face_centers[0]]
    for fc in face_centers[1:]:
        targets.append(aplicar_deadzone(fc, targets[-1], deadzone_w))
    return targets


# ── Interpolacion entre detecciones ──────────────────────────────────────────


def interpolar_detecciones(sparsa: dict[int, float], total_frames: int) -> list[float | None]:
    """Interpola linealmente entre fotogramas detectados; None fuera del rango conocido."""
    resultado: list[float | None] = [None] * total_frames
    if not sparsa:
        return resultado
    frames_ord = sorted(sparsa)
    for fi in frames_ord:
        if 0 <= fi < total_frames:
            resultado[fi] = sparsa[fi]
    for fa, fb in zip(frames_ord, frames_ord[1:], strict=False):
        for fi in range(fa + 1, fb):
            if 0 <= fi < total_frames:
                t = (fi - fa) / (fb - fa)
                resultado[fi] = sparsa[fa] * (1 - t) + sparsa[fb] * t
    return resultado


# ── Manejo de cara perdida ────────────────────────────────────────────────────


def manejar_cara_perdida(
    raw_centers: list[float | None],
    patience: int,
    source_center_x: float,
    recenter_alpha: float = RECENTER_ALPHA,
) -> list[float]:
    """Rellena Nones: mantiene ultimo conocido patience frames; luego EMA hacia centro."""
    filled: list[float] = []
    last_known = source_center_x
    frames_perdidos = 0
    for cx in raw_centers:
        if cx is not None:
            last_known = cx
            frames_perdidos = 0
            filled.append(cx)
        else:
            frames_perdidos += 1
            if frames_perdidos <= patience:
                filled.append(last_known)
            else:
                last_known = last_known * (1 - recenter_alpha) + source_center_x * recenter_alpha
                filled.append(last_known)
    return filled


# ── Seleccion de cara activa segun turnos ─────────────────────────────────────


def cara_en_frame(frame_idx: int, fps: float, turnos: list[dict]) -> int:
    """Devuelve el cara_id activo en el frame dado segun los turnos; 0 si fuera de rango."""
    t = frame_idx / fps
    for turno in turnos:
        if turno["t_ini"] <= t < turno["t_fin"]:
            return int(turno["cara_id"])
    return 0


# ── Deteccion de caras (MediaPipe Tasks API 0.10.x) ──────────────────────────


def detectar_cara_frame(frame, detector) -> dict | None:
    """Detecta la cara mas prominente en un fotograma numpy (BGR) con MediaPipe Tasks.

    Devuelve {'center_x': float, 'center_y': float, 'bbox': [x, y, w, h]} o None.
    detector: FaceDetector creado con mediapipe.tasks.python.vision.FaceDetector.
    """
    import cv2
    import mediapipe as _mp

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_img = _mp.Image(image_format=_mp.ImageFormat.SRGB, data=rgb)
    result = detector.detect(mp_img)
    if not result.detections:
        return None
    best = max(result.detections, key=lambda d: d.categories[0].score)
    bb = best.bounding_box
    h, w = frame.shape[:2]
    x = max(0, bb.origin_x)
    y = max(0, bb.origin_y)
    bw = min(bb.width, w - x)
    bh = min(bb.height, h - y)
    return {
        "center_x": float(x + bw / 2),
        "center_y": float(y + bh / 2),
        "bbox": [x, y, bw, bh],
    }


def detectar_todas_caras_frame(frame, detector) -> list[dict]:
    """Detecta todas las caras en un fotograma numpy (BGR); devuelve lista ordenada por score desc.

    Cada elemento: {'center_x': float, 'center_y': float, 'bbox': list, 'score': float}.
    """
    import cv2
    import mediapipe as _mp

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_img = _mp.Image(image_format=_mp.ImageFormat.SRGB, data=rgb)
    result = detector.detect(mp_img)
    if not result.detections:
        return []
    dets = []
    for d in result.detections:
        bb = d.bounding_box
        h, w = frame.shape[:2]
        x = max(0, bb.origin_x)
        y = max(0, bb.origin_y)
        bw = min(bb.width, w - x)
        bh = min(bb.height, h - y)
        dets.append(
            {
                "center_x": float(x + bw / 2),
                "center_y": float(y + bh / 2),
                "bbox": [x, y, bw, bh],
                "score": d.categories[0].score,
            }
        )
    return sorted(dets, key=lambda d: d["score"], reverse=True)


# ── Crops multi-cara con conmutacion por turnos ───────────────────────────────


def calcular_crops_por_turnos(
    sparsa_multi: dict[int, dict[int, float]],
    turnos_list: list[dict],
    fps: float,
    total_frames: int,
    src_w: int,
    src_h: int,
) -> list[tuple[int, int, int, int]]:
    """Calcula crops con CORTE SECO en cada t_ini de turno. Puro math, sin I/O.

    sparsa_multi: {cara_id: {frame_idx: center_x}} desde _detectar_trayectorias_multi.
    Cada segmento aplica EMA+deadzone independientemente — no hay suavizado entre turnos.
    """
    src_center = src_w / 2
    deadzone_w = DEADZONE_PCT * src_w
    cw_def = src_h * 9 // 16
    default_crop: tuple[int, int, int, int] = ((src_w - cw_def) // 2, 0, cw_def, src_h)
    result: list[tuple[int, int, int, int] | None] = [None] * total_frames

    for i, turno in enumerate(turnos_list):
        f_ini = int(turno["t_ini"] * fps)
        next_t = turnos_list[i + 1]["t_ini"] if i + 1 < len(turnos_list) else total_frames / fps
        f_fin = min(int(next_t * fps) - 1, total_frames - 1)
        n_seg = f_fin - f_ini + 1
        if n_seg <= 0:
            continue
        cara_id = int(turno["cara_id"])
        sparsa_seg = {
            fi - f_ini: cx
            for fi, cx in sparsa_multi.get(cara_id, {}).items()
            if f_ini <= fi <= f_fin
        }
        raw = interpolar_detecciones(sparsa_seg, n_seg)
        filled = manejar_cara_perdida(raw, FACE_LOST_PATIENCE, src_center)
        targets = aplicar_deadzone_secuencia(filled, deadzone_w)
        smooth = ema_smooth(targets, EMA_ALPHA)
        for j, cx_val in enumerate(smooth):
            result[f_ini + j] = calcular_ventana_crop(cx_val, src_w, src_h)

    return [c if c is not None else default_crop for c in result]
