"""reframe.py — Reframe vertical: convierte clips 16:9 en 9:16 con face tracking.

Disenio: revision/fase-4.1/DISENO_REFRAME.md
Orden del pipeline: clipper -> reframe (9:16 + punch-ins) -> captions.
CLI: python reframe.py output/clips/clip.mp4 [--turnos transcripts/clip_turnos.json] [--punch-in]
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import cv2
from mediapipe.tasks import python as _mp_python
from mediapipe.tasks.python import vision as _mp_vision

import reframe_track as rt

# ── Constantes ────────────────────────────────────────────────────────────────

TRANSCRIPTS_DIR = Path(__file__).parent / "transcripts"
THUMBS_DIR = Path(__file__).parent / "thumbs"
MODEL_PATH = Path(__file__).parent / "models" / "blaze_face_short_range.tflite"

SUFFIX_9X16 = "_9x16"
OUTPUT_W, OUTPUT_H = 1080, 1920
FACE_CLUSTER_DIST = 80  # px: umbral para agrupar caras del scan inicial
PUNCH_KW_DUR_S = 0.8  # duracion de cada punch-in en segundos


# ── Detector MediaPipe ────────────────────────────────────────────────────────


def _crear_detector():
    """Crea un FaceDetector MediaPipe Tasks en modo IMAGE."""
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"Modelo MediaPipe no encontrado: {MODEL_PATH}")
    base = _mp_python.BaseOptions(model_asset_path=str(MODEL_PATH))
    opts = _mp_vision.FaceDetectorOptions(
        base_options=base,
        running_mode=_mp_vision.RunningMode.IMAGE,
        min_detection_confidence=rt.FACE_MIN_CONFIDENCE,
    )
    return _mp_vision.FaceDetector.create_from_options(opts)


# ── Deteccion inicial de caras ────────────────────────────────────────────────


def _registrar_cara_nueva(
    det: dict, frame, caras: list[dict], stem: str, idx: int, fps: float
) -> None:
    """Registra una deteccion si su center_x no solapa con caras ya conocidas."""
    cx = det["center_x"]
    if any(abs(c["center_x"] - cx) < FACE_CLUSTER_DIST for c in caras):
        return
    cara_id = len(caras)
    thumb_path = THUMBS_DIR / f"{stem}_cara{cara_id}.jpg"
    extraer_thumb_cara(frame, det["bbox"], thumb_path)
    caras.append(
        {
            "id": cara_id,
            "center_x": cx,
            "thumb": f"thumbs/{stem}_cara{cara_id}.jpg",
            "primera_vez_s": round(idx / fps, 3),
        }
    )


def detectar_caras_video(video_path: Path, muestra_frames: int = 30) -> list[dict]:
    """Detecta caras en los primeros muestra_frames fotogramas; guarda thumbnails.

    Devuelve lista de {'id', 'center_x', 'thumb', 'primera_vez_s'}.
    """
    THUMBS_DIR.mkdir(exist_ok=True)
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    detector = _crear_detector()
    caras: list[dict] = []
    stem = video_path.stem
    try:
        for idx in range(muestra_frames):
            ret, frame = cap.read()
            if not ret:
                break
            for det in rt.detectar_todas_caras_frame(frame, detector):
                _registrar_cara_nueva(det, frame, caras, stem, idx, fps)
    finally:
        cap.release()
        detector.close()
    return caras


def extraer_thumb_cara(frame, bbox: list[int], out_path: Path) -> Path:
    """Recorta el bounding box de una cara y lo guarda como thumbnail JPEG."""
    x, y, w, h = bbox
    pad = max(10, int(min(w, h) * 0.15))
    x0, y0 = max(0, x - pad), max(0, y - pad)
    x1 = min(frame.shape[1], x + w + pad)
    y1 = min(frame.shape[0], y + h + pad)
    crop = frame[y0:y1, x0:x1]
    if crop.size > 0:
        cv2.imwrite(str(out_path), crop)
    return out_path


# ── Deteccion de trayectoria ──────────────────────────────────────────────────


def _detectar_trayectoria(video_path: Path, total_frames: int) -> dict[int, float]:
    """Detecta center_x de la cara principal cada DETECT_EVERY_N frames."""
    cap = cv2.VideoCapture(str(video_path))
    detector = _crear_detector()
    sparsa: dict[int, float] = {}
    n_det = n_sin = 0
    try:
        for fi in range(total_frames):
            ret, frame = cap.read()
            if not ret:
                break
            if fi % rt.DETECT_EVERY_N != 0:
                continue
            det = rt.detectar_cara_frame(frame, detector)
            if det is not None:
                sparsa[fi] = det["center_x"]
                n_det += 1
            else:
                n_sin += 1
    finally:
        cap.release()
        detector.close()
    if n_sin > n_det:
        print(f"[reframe] cara perdida en {n_sin}/{n_det + n_sin} detecciones, recentrando")
    return sparsa


def _asignar_detecciones_a_caras(
    all_dets: list[dict], caras: list[dict], sparsa: dict[int, dict[int, float]], fi: int
) -> None:
    """Para cada cara conocida, asigna la deteccion mas cercana si esta dentro del rango."""
    for cara in caras:
        ref = cara["center_x"]
        best = min(all_dets, key=lambda d: abs(d["center_x"] - ref))
        if abs(best["center_x"] - ref) < FACE_CLUSTER_DIST * 2:
            sparsa[cara["id"]][fi] = best["center_x"]


def _detectar_trayectorias_multi(
    video_path: Path, total_frames: int, caras: list[dict]
) -> dict[int, dict[int, float]]:
    """Detecta, por cara, el center_x cada DETECT_EVERY_N frames.

    Devuelve {cara_id: {frame_idx: center_x}}.
    """
    cap = cv2.VideoCapture(str(video_path))
    detector = _crear_detector()
    sparsa: dict[int, dict[int, float]] = {c["id"]: {} for c in caras}
    try:
        for fi in range(total_frames):
            ret, frame = cap.read()
            if not ret:
                break
            if fi % rt.DETECT_EVERY_N != 0:
                continue
            all_dets = rt.detectar_todas_caras_frame(frame, detector)
            if all_dets:
                _asignar_detecciones_a_caras(all_dets, caras, sparsa, fi)
    finally:
        cap.release()
        detector.close()
    return sparsa


# ── Calculo de secuencia de crops ────────────────────────────────────────────


def _calcular_crop_secuencia(
    sparsa: dict[int, float], total_frames: int, src_w: int, src_h: int
) -> list[tuple[int, int, int, int]]:
    """Convierte detecciones sparsa en lista de (x, y, w, h) por frame."""
    src_center = src_w / 2
    deadzone_w = rt.DEADZONE_PCT * src_w
    if not sparsa:
        print("[reframe] no se detectaron caras -- center-crop aplicado")
        cw = src_h * 9 // 16
        cx = (src_w - cw) // 2
        return [(cx, 0, cw, src_h)] * total_frames
    raw = rt.interpolar_detecciones(sparsa, total_frames)
    filled = rt.manejar_cara_perdida(raw, rt.FACE_LOST_PATIENCE, src_center)
    targets = rt.aplicar_deadzone_secuencia(filled, deadzone_w)
    smooth = rt.ema_smooth(targets, rt.EMA_ALPHA)
    return [rt.calcular_ventana_crop(x, src_w, src_h) for x in smooth]


# ── Punch-ins en keywords ─────────────────────────────────────────────────────


def _punch_crop_w(offset: int, span: int, normal_w: int, punch_w: int, trans: int) -> int:
    """Calcula el ancho de crop con rampa de entrada/salida para punch-in."""
    if offset < trans:
        return int(normal_w - (offset / max(trans, 1)) * (normal_w - punch_w))
    if offset > span - trans:
        return int(normal_w - (max(0, span - offset) / max(trans, 1)) * (normal_w - punch_w))
    return punch_w


def _aplicar_punch_ins(
    crops: list[tuple[int, int, int, int]],
    brain_data: dict,
    fps: float,
    src_w: int,
    src_h: int,
) -> list[tuple[int, int, int, int]]:
    """Aplica zoom temporal en frames de keyword del brain (opt-in --punch-in)."""
    kw_times = [
        (g["kw_ts"], g["kw_ts"] + PUNCH_KW_DUR_S)
        for g in (brain_data or {}).get("groups", [])
        if g.get("kw_ts") is not None
    ]
    if not kw_times:
        return crops
    normal_w = src_h * 9 // 16
    punch_w = int(normal_w / rt.PUNCH_ZOOM)
    trans = rt.PUNCH_TRANS_FRAMES
    result = list(crops)
    for t_ini, t_fin in kw_times:
        f_ini = int(t_ini * fps)
        f_fin = min(int(t_fin * fps), len(result) - 1)
        span = max(f_fin - f_ini, 1)
        for fi in range(f_ini, f_fin + 1):
            if fi >= len(result):
                break
            x, y, w, _ = result[fi]
            cw = _punch_crop_w(fi - f_ini, span, normal_w, punch_w, trans)
            new_x = max(0, min(x + w // 2 - cw // 2, src_w - cw))
            result[fi] = (new_x, y, cw, src_h)
    return result


# ── Render ────────────────────────────────────────────────────────────────────


def _cmd_ffmpeg_pipe(input_path: Path, output_path: Path, fps: float, has_audio: bool) -> list[str]:
    """Construye el comando FFmpeg para el pipe OpenCV (bgr24) -> MP4 yuv420p."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24"]
    cmd += ["-s", f"{OUTPUT_W}x{OUTPUT_H}", "-r", str(fps), "-i", "pipe:0"]
    ai = ["-i", str(input_path), "-map", "0:v", "-map", "1:a"] if has_audio else ["-map", "0:v"]
    cmd += ai + ["-c:v", "libx264", "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p"]
    if has_audio:
        cmd += ["-c:a", "copy"]
    cmd += ["-movflags", "+faststart", str(output_path)]
    return cmd


def renderizar_reframe(
    input_path: Path,
    crop_frames: list[tuple[int, int, int, int]],
    output_path: Path,
    fps: float,
    has_audio: bool = True,
) -> float:
    """Lee frames con OpenCV, aplica crops, escala 1080x1920 (LANCZOS4), pipe a FFmpeg."""
    t0 = time.time()
    cmd = _cmd_ffmpeg_pipe(input_path, output_path, fps, has_audio)
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    cap = cv2.VideoCapture(str(input_path))
    try:
        for cx, cy, cw, ch in crop_frames:
            ret, frame = cap.read()
            if not ret:
                break
            cropped = frame[cy : cy + ch, cx : cx + cw]
            resized = cv2.resize(cropped, (OUTPUT_W, OUTPUT_H), interpolation=cv2.INTER_LANCZOS4)
            proc.stdin.write(resized.tobytes())
    finally:
        cap.release()
        if proc.stdin:
            proc.stdin.close()
    _, stderr_bytes = proc.communicate()
    if proc.returncode != 0:
        tail = (stderr_bytes or b"").decode("utf-8", errors="replace")[-2000:]
        raise RuntimeError(f"FFmpeg returncode {proc.returncode}: {tail}")
    return time.time() - t0


def _cargar_o_generar_brain(clip_path: Path) -> dict | None:
    """Carga {clip}_brain.json si existe; si no, llama brain.py UNA vez y persiste."""
    brain_path = TRANSCRIPTS_DIR / f"{clip_path.stem}.brain.json"
    grp_path = TRANSCRIPTS_DIR / f"{clip_path.stem}_groups.json"
    if brain_path.exists():
        print("[reframe] brain reutilizado")
        return json.loads(brain_path.read_text(encoding="utf-8"))
    if not grp_path.exists():
        print("[reframe] sin groups.json para brain -- punch-ins desactivados")
        return None
    try:
        import brain as brain_mod  # noqa: PLC0415

        grupos = json.loads(grp_path.read_text(encoding="utf-8"))
        data = brain_mod.analizar_grupos(grupos, contexto=clip_path.stem, video_name=clip_path.stem)
        brain_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print("[reframe] brain generado")
        return data
    except Exception as exc:
        print(f"[reframe] brain fallido: {type(exc).__name__} -- punch-ins desactivados")
        return None


# ── Orquestacion principal ────────────────────────────────────────────────────


def _contar_punch_ins(brain_data: dict | None) -> int:
    """Cuenta keywords con timestamp en brain_data."""
    return sum(1 for g in (brain_data or {}).get("groups", []) if g.get("kw_ts") is not None)


def _calcular_crops(
    input_path: Path,
    caras: list[dict],
    turnos_list: list[dict],
    fps: float,
    total_frames: int,
    src_w: int,
    src_h: int,
) -> list[tuple[int, int, int, int]]:
    """Elige ruta single-face o multi-cara y devuelve la secuencia de crops."""
    if len(caras) >= 2 and turnos_list:
        n_t = len(turnos_list)
        print(f"[reframe] {len(caras)} caras con turnos -- conmutacion activada ({n_t} turnos)")
        sparsa_multi = _detectar_trayectorias_multi(input_path, total_frames, caras)
        return rt.calcular_crops_por_turnos(
            sparsa_multi, turnos_list, fps, total_frames, src_w, src_h
        )
    if len(caras) >= 2:
        print(f"[reframe] {len(caras)} caras -- cara principal; asigna turnos para conmutar")
    sparsa = _detectar_trayectoria(input_path, total_frames)
    return _calcular_crop_secuencia(sparsa, total_frames, src_w, src_h)


def reframe_clip(
    input_path: Path,
    output_path: Path,
    turnos: dict | None = None,
    brain_data: dict | None = None,
    punch_in: bool = False,
) -> dict:
    """Reencuadra clip 16:9 a 9:16 con face tracking EMA+deadzone y conmutacion por turnos."""
    from core import get_video_info

    info = get_video_info(input_path)
    src_w, src_h = info["width"], info["height"]
    has_audio = bool(info.get("has_audio", True))

    cap = cv2.VideoCapture(str(input_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    caras = detectar_caras_video(input_path)
    if punch_in and brain_data is None:
        brain_data = _cargar_o_generar_brain(input_path)
    turnos_list = (turnos or {}).get("turnos", [])
    crops = _calcular_crops(input_path, caras, turnos_list, fps, total_frames, src_w, src_h)
    if punch_in and brain_data:
        crops = _aplicar_punch_ins(crops, brain_data, fps, src_w, src_h)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    elapsed = renderizar_reframe(input_path, crops, output_path, fps, has_audio)
    print(f"[reframe] {input_path.name} -> {output_path.name} en {elapsed:.1f}s")
    return {
        "output": str(output_path),
        "dur_s": round(elapsed, 2),
        "n_caras": len(caras),
        "punch_ins": _contar_punch_ins(brain_data if punch_in else None),
    }


# ── CLI ───────────────────────────────────────────────────────────────────────


def _build_parser():
    import argparse

    p = argparse.ArgumentParser(description="Reframe vertical 16:9 -> 9:16 con face tracking")
    p.add_argument("input", type=Path, help="Clip MP4 de entrada")
    p.add_argument("--turnos", type=Path, default=None, help="Archivo _turnos.json")
    p.add_argument("--punch-in", action="store_true", help="Activar punch-ins en keywords")
    p.add_argument("--out", type=Path, default=None, help="Ruta de salida")
    return p


if __name__ == "__main__":
    args = _build_parser().parse_args()
    output = args.out or args.input.with_stem(args.input.stem + SUFFIX_9X16)
    turnos = json.loads(args.turnos.read_text(encoding="utf-8")) if args.turnos else None
    result = reframe_clip(args.input, output, turnos=turnos, punch_in=args.punch_in)
    print(f"Output: {result['output']}")
