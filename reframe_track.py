"""reframe_track.py — Deteccion de caras y matematicas de suavizado para el reframe 9:16.

Las funciones puras (calcular_ventana_crop, ema_smooth, etc.) son deterministas y
testeables sin video ni dependencias externas. detectar_cara_frame requiere mediapipe
y es stub hasta la sesion de implementacion de F4.1.
Disenio: revision/fase-4.1/DISENO_REFRAME.md
"""

from __future__ import annotations

# ── Parametros calibrables ────────────────────────────────────────────────────
# Ver tabla en DISENO_REFRAME.md §2 para rango sensato de cada constante.

EMA_ALPHA = 0.08  # alias de ALPHA_BASE_LENTO (backward-compat)
ALPHA_BASE_LENTO = 0.08   # tau ~0.41s a 30fps: reposo y movimientos suaves
ALPHA_BASE_RAPIDO = 0.28  # tau ~0.11s a 30fps; equivale al alpha efectivo de s13 @60fps
                           # (1-(1-0.08)^2 = 0.1536 ≈ 1-(1-0.28)^0.5 = 0.1515)
RAMP_LENTO_FACTOR = 1.0   # umbral_lento  = deadzone_half × 1.0 (borde de la deadzone)
RAMP_RAPIDO_FACTOR = 3.0  # umbral_rapido = deadzone_half × 3.0 (3x el borde)
                           # => podcast 1920x1080: umbral_lento=76px  umbral_rapido=228px
                           # => videolargo 854x480: umbral_lento=34px  umbral_rapido=101px

DEADZONE_PCT = 0.25  # zona muerta como fraccion de CROP_W (corregido s12; era 0.30 de source_w)
DETECT_EVERY_N = 3  # detectar cara cada N fotogramas
GATE_ANCLA_PCT = 0.15  # radio del ancla: deteccion >15% source_w del ancla => ignorar
PUNCH_ZOOM = 1.12  # factor de zoom punch-in (112% = crop 11% mas estrecho)
PUNCH_TRANS_FRAMES = 4  # fotogramas de rampa entrada/salida del punch-in
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


def calcular_alpha_fps(alpha_base: float, fps: float, fps_ref: float = 30.0) -> float:
    """Alpha EMA efectivo normalizado por fps: comportamiento identico en 30 y 60fps.

    Derivacion: tau (segundos) = constante => alpha = 1-(1-alpha_ref)^(fps_ref/fps).
    A 60fps hay mas frames/s, cada frame mueve menos para el mismo tau real.
    """
    return 1 - (1 - alpha_base) ** (fps_ref / fps)


def calcular_alpha_adaptativo(
    error_px: float, deadzone_w: float, fps: float, fps_ref: float = 30.0
) -> float:
    """Alpha EMA adaptativo segun el error camara->target por frame.

    Regimenes:
      - Lento (ALPHA_BASE_LENTO):  error <= deadzone_half * RAMP_LENTO_FACTOR  (borde deadzone)
      - Rapido (ALPHA_BASE_RAPIDO): error >= deadzone_half * RAMP_RAPIDO_FACTOR (3x borde)
      - Intermedio: rampa lineal entre ambos umbrales.

    Invariante: error <= deadzone_w/2 SIEMPRE produce ALPHA_BASE_LENTO (reposo garantizado).
    Ambas bases pasan por calcular_alpha_fps (^(fps_ref/fps)).
    """
    dz_half = deadzone_w / 2
    umbral_lento = dz_half * RAMP_LENTO_FACTOR
    umbral_rapido = dz_half * RAMP_RAPIDO_FACTOR
    if error_px <= umbral_lento:
        alpha_base = ALPHA_BASE_LENTO
    elif error_px >= umbral_rapido:
        alpha_base = ALPHA_BASE_RAPIDO
    else:
        t = (error_px - umbral_lento) / (umbral_rapido - umbral_lento)
        alpha_base = ALPHA_BASE_LENTO + t * (ALPHA_BASE_RAPIDO - ALPHA_BASE_LENTO)
    return calcular_alpha_fps(alpha_base, fps, fps_ref)


def ema_smooth_adaptativo(
    positions: list[float], fps: float, deadzone_w: float
) -> list[float]:
    """EMA con alpha adaptativo por frame segun |target - camara_anterior|."""
    if not positions:
        return []
    smooth = [positions[0]]
    for p in positions[1:]:
        error = abs(p - smooth[-1])
        alpha = calcular_alpha_adaptativo(error, deadzone_w, fps)
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
    source_center_x: float,
) -> list[float]:
    """Rellena Nones manteniendo la ultima posicion conocida (hold indefinido).

    El recentrado al source_center_x solo aplica como valor inicial; si jamas se
    detecto cara en el video, el caller retorna center-crop sin llamar esta funcion.
    """
    filled: list[float] = []
    last_known = source_center_x
    for cx in raw_centers:
        if cx is not None:
            last_known = cx
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

    Devuelve {'center_x': float, 'center_y': float, 'bbox': [x, y, w, h], 'score': float} o None.
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
        "score": float(best.categories[0].score),
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
    cw_def = src_h * 9 // 16
    deadzone_w = DEADZONE_PCT * cw_def  # sobre crop_w, no source_w
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
        filled = manejar_cara_perdida(raw, src_center)
        targets = aplicar_deadzone_secuencia(filled, deadzone_w)
        smooth = ema_smooth_adaptativo(targets, fps, deadzone_w)
        for j, cx_val in enumerate(smooth):
            result[f_ini + j] = calcular_ventana_crop(cx_val, src_w, src_h)

    return [c if c is not None else default_crop for c in result]


def aplanar_conf_por_turnos(
    conf_multi: dict[int, dict[int, float]],
    turnos_list: list[dict],
    fps: float,
    total_frames: int,
) -> dict[int, float]:
    """Aplana conf_multi al cara activo por turno. Puro math, sin I/O.

    Devuelve {frame_idx: score} para los frames donde corrio el detector
    y la deteccion fue asignada al cara activo en ese turno.
    """
    result: dict[int, float] = {}
    for i, turno in enumerate(turnos_list):
        f_ini = int(turno["t_ini"] * fps)
        next_t = turnos_list[i + 1]["t_ini"] if i + 1 < len(turnos_list) else total_frames / fps
        f_fin = min(int(next_t * fps) - 1, total_frames - 1)
        cara_id = int(turno["cara_id"])
        for fi, score in conf_multi.get(cara_id, {}).items():
            if f_ini <= fi <= f_fin:
                result[fi] = score
    return result


def reconstruir_filled_por_turnos(
    sparsa_multi: dict[int, dict[int, float]],
    turnos_list: list[dict],
    fps: float,
    total_frames: int,
    src_w: int,
) -> list[float]:
    """Devuelve filled (interpolar+hold) por frame para CSV de trayectoria.

    Misma segmentacion que calcular_crops_por_turnos pero sin EMA/deadzone/crop.
    """
    src_center = src_w / 2
    result: list[float] = [src_center] * total_frames
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
        filled_seg = manejar_cara_perdida(raw, src_center)
        for j, fx in enumerate(filled_seg):
            result[f_ini + j] = fx
    return result
