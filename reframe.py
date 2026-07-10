"""reframe.py — Reframe vertical: convierte clips 16:9 en 9:16.

Modos:
  tracking (default): face tracking EMA adaptativo + deadzone + punch-ins opcionales
  stack: bandas estaticas apiladas verticalmente (N=2 o N=3 caras)
CLI: python reframe.py <clip.mp4> [--layout tracking|stack] [--turnos ...] [--punch-in]
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import cv2

import reframe_track as rt
from reframe_detect import (
    _crear_detector,
    _detectar_trayectoria,
    _detectar_trayectorias_multi,
)

# ── Constantes ────────────────────────────────────────────────────────────────

TRANSCRIPTS_DIR = Path(__file__).parent / "transcripts"
THUMBS_DIR = Path(__file__).parent / "thumbs"

SUFFIX_9X16 = "_9x16"
SUFFIX_STACK = "_stack_9x16"
OUTPUT_W, OUTPUT_H = 1080, 1920
FACE_CLUSTER_DIST = 80  # px: umbral para agrupar caras del scan inicial
PUNCH_KW_DUR_S = 0.8  # duracion de cada punch-in en segundos
N_CORTES_WARN = 2  # mas de este numero de cortes de escena emite WARNING


# ── Precondicion de fuente ────────────────────────────────────────────────────


def _parsear_cortes_escena(stdout: str) -> list[float]:
    """Extrae timestamps de cortes del stdout del filtro scdet de FFmpeg. Puro."""
    times = []
    for line in stdout.splitlines():
        if "pts_time:" in line:
            try:
                times.append(float(line.split("pts_time:")[1].split()[0]))
            except (ValueError, IndexError):
                pass
    return times


def _filtrar_artefactos_cortes(timestamps: list[float], min_t: float = 1.0) -> list[float]:
    """Filtra el artefacto de primer frame de scdet (t < min_t). Puro."""
    return [t for t in timestamps if t >= min_t]


def _detectar_cortes_ts(video_path: Path, threshold: float = 0.3) -> list[float]:
    """Timestamps de cortes de escena reales (excluye artefacto de primer frame).

    Retorna [] si FFmpeg falla (fail-open). Threshold 0.3: NUESTRO dataset
    (cortes_dataset.md) probo que cortes reales bajan hasta 0.65 — no subir.
    """
    try:
        r = subprocess.run(
            [
                "ffmpeg",
                "-i",
                str(video_path),
                "-vf",
                f"select='gt(scene,{threshold})',metadata=print:file=-",
                "-an",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            errors="replace",
        )
        return _filtrar_artefactos_cortes(_parsear_cortes_escena(r.stdout))
    except Exception as exc:
        print(f"[reframe] AVISO: scdet fallo ({type(exc).__name__}) -- 0 cortes asumidos")
        return []


def _contar_cortes_escena(video_path: Path, threshold: float = 0.3) -> int:
    """Cuenta cortes de escena reales (wrapper de _detectar_cortes_ts)."""
    return len(_detectar_cortes_ts(video_path, threshold))


def _avisar_cortes(n: int, umbral: int = N_CORTES_WARN) -> None:
    """Emite WARNING si la fuente tiene mas cortes de escena que el umbral."""
    if n > umbral:
        print(
            f"[reframe] WARNING: fuente con {n} cortes de escena detectados: "
            "el reframe asume toma continua; resultados pueden degradarse"
        )


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


def detectar_caras_video(
    video_path: Path, muestra_frames: int = 30, detector_type: str = "yunet"
) -> list[dict]:
    """Detecta caras en los primeros muestra_frames fotogramas; guarda thumbnails.

    Devuelve lista de {'id', 'center_x', 'thumb', 'primera_vez_s'}.
    """
    THUMBS_DIR.mkdir(exist_ok=True)
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    detector = _crear_detector(detector_type)
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


# ── Calculo de secuencia de crops ────────────────────────────────────────────


def _calcular_crop_secuencia(
    sparsa: dict[int, float],
    total_frames: int,
    src_w: int,
    src_h: int,
    fps: float,
    sparsa_conf: dict[int, float] | None = None,
) -> tuple[list[tuple[int, int, int, int]], list[float], dict[int, float] | None]:
    """Convierte detecciones sparsa en crops por frame; devuelve (crops, filled, sparsa_conf)."""
    src_center = src_w / 2
    crop_w = src_h * 9 // 16
    deadzone_w = rt.DEADZONE_PCT * crop_w  # sobre crop_w, no source_w
    if not sparsa:
        print("[reframe] no se detectaron caras -- center-crop aplicado")
        cx = (src_w - crop_w) // 2
        crops = [(cx, 0, crop_w, src_h)] * total_frames
        return crops, [src_center] * total_frames, sparsa_conf
    raw = rt.interpolar_detecciones(sparsa, total_frames)
    filled = rt.manejar_cara_perdida(raw, src_center)
    targets = rt.aplicar_deadzone_secuencia(filled, deadzone_w)
    smooth = rt.ema_smooth_adaptativo(targets, fps, deadzone_w)
    crops = [rt.calcular_ventana_crop(x, src_w, src_h) for x in smooth]
    return crops, filled, sparsa_conf


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


def _exportar_trayectoria_csv(
    stem: str,
    crops: list[tuple[int, int, int, int]],
    filled: list[float],
    fps: float,
    out_dir: Path,
    sparsa_conf: dict[int, float] | None = None,
) -> Path:
    """Exporta trayectoria frame-a-frame a CSV para diagnostico de tracking.

    sparsa_conf: {frame_idx: score} para los frames donde corrio el detector;
    None o ausente => columna conf_asignada omitida (backward-compat).
    """
    import csv

    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"trayectoria_{stem}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        header = ["t", "cam_center_x", "face_x_asignada", "distancia"]
        if sparsa_conf is not None:
            header.append("conf_asignada")
        w.writerow(header)
        for fi, (x, _y, cw, _ch) in enumerate(crops):
            t = fi / fps
            cam_cx = x + cw / 2
            face_x = filled[fi] if fi < len(filled) else cam_cx
            dist = abs(cam_cx - face_x)
            row = [f"{t:.4f}", f"{cam_cx:.1f}", f"{face_x:.1f}", f"{dist:.1f}"]
            if sparsa_conf is not None:
                row.append(f"{sparsa_conf[fi]:.4f}" if fi in sparsa_conf else "")
            w.writerow(row)
    print(f"[reframe] trayectoria -> {csv_path.name}")
    return csv_path


def _calcular_crops(
    input_path: Path,
    caras: list[dict],
    turnos_list: list[dict],
    fps: float,
    total_frames: int,
    src_w: int,
    src_h: int,
    detector_type: str = "yunet",
) -> tuple[list[tuple[int, int, int, int]], list[float], dict[int, float] | None]:
    """Elige ruta single-face o multi-cara; devuelve (crops, filled_por_frame, sparsa_conf)."""
    if len(caras) >= 2 and turnos_list:
        n_t = len(turnos_list)
        print(f"[reframe] {len(caras)} caras con turnos -- conmutacion activada ({n_t} turnos)")
        sparsa_multi, conf_multi = _detectar_trayectorias_multi(
            input_path, total_frames, caras, src_w, detector_type
        )
        crops = rt.calcular_crops_por_turnos(
            sparsa_multi, turnos_list, fps, total_frames, src_w, src_h
        )
        filled = rt.reconstruir_filled_por_turnos(
            sparsa_multi, turnos_list, fps, total_frames, src_w
        )
        # Flatten conf: frame_idx -> score del cara activo en ese turno
        flat_conf = rt.aplanar_conf_por_turnos(conf_multi, turnos_list, fps, total_frames)
        return crops, filled, flat_conf
    if len(caras) >= 2:
        print(f"[reframe] {len(caras)} caras -- cara principal; asigna turnos para conmutar")
    ancla_x = caras[0]["center_x"] if caras else src_w / 2
    sparsa, sparsa_conf = _detectar_trayectoria(
        input_path, total_frames, src_w, ancla_x, detector_type
    )
    return _calcular_crop_secuencia(sparsa, total_frames, src_w, src_h, fps, sparsa_conf)


def reframe_clip(
    input_path: Path,
    output_path: Path,
    turnos: dict | None = None,
    brain_data: dict | None = None,
    punch_in: bool = False,
    tray_dir: Path | None = None,
    detector_type: str = "yunet",
    tracker: str = "escenas",
) -> dict:
    """Reencuadra clip 16:9 a 9:16.

    tracker='escenas' (default): cortes-primero + waypoints por segmento (F4.2-CORTES).
    tracker='ema': EMA adaptativo continuo (F4.1, intacto como fallback y comparacion).
    Con turnos se usa siempre la ruta EMA (turnos son de tiempo global, incompatibles
    con el re-escaneo por segmento en v1).
    """
    from core import get_video_info

    info = get_video_info(input_path)
    src_w, src_h = info["width"], info["height"]
    has_audio = bool(info.get("has_audio", True))

    cap = cv2.VideoCapture(str(input_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    if punch_in and brain_data is None:
        brain_data = _cargar_o_generar_brain(input_path)
    turnos_list = (turnos or {}).get("turnos", [])

    seg_reporte: list[dict] = []
    if tracker == "escenas" and not turnos_list:
        import reframe_escenas  # noqa: PLC0415

        cortes = _detectar_cortes_ts(input_path)
        crops, filled, sparsa_conf, seg_reporte = reframe_escenas.calcular_crops_escenas(
            input_path, fps, total_frames, src_w, src_h, cortes, detector_type
        )
        n_caras = max((s["n_caras"] for s in seg_reporte), default=0)
    else:
        if tracker == "escenas" and turnos_list:
            print("[reframe] turnos presentes -- usando tracker ema (escenas v1 no soporta turnos)")
        _avisar_cortes(_contar_cortes_escena(input_path))
        caras = detectar_caras_video(input_path, detector_type=detector_type)
        crops, filled, sparsa_conf = _calcular_crops(
            input_path, caras, turnos_list, fps, total_frames, src_w, src_h, detector_type
        )
        n_caras = len(caras)

    if punch_in and brain_data:
        crops = _aplicar_punch_ins(crops, brain_data, fps, src_w, src_h)
    if tray_dir is not None:
        _exportar_trayectoria_csv(output_path.stem, crops, filled, fps, tray_dir, sparsa_conf)
        print(f"[reframe] detector: {detector_type} | tracker: {tracker}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    elapsed = renderizar_reframe(input_path, crops, output_path, fps, has_audio)
    print(f"[reframe] {input_path.name} -> {output_path.name} en {elapsed:.1f}s")
    return {
        "output": str(output_path),
        "dur_s": round(elapsed, 2),
        "n_caras": n_caras,
        "punch_ins": _contar_punch_ins(brain_data if punch_in else None),
        "tracker": tracker,
        "segmentos": seg_reporte,
    }


# ── Stack layout ─────────────────────────────────────────────────────────────


def renderizar_stack(
    input_path: Path,
    bandas: list[tuple[int, int, int, int]],
    output_path: Path,
    fps: float,
    has_audio: bool,
) -> float:
    """Render en modo stack: N bandas estaticas apiladas verticalmente."""
    n = len(bandas)
    assert OUTPUT_H % n == 0, f"OUTPUT_H={OUTPUT_H} no divisible por n={n}"
    band_h = OUTPUT_H // n
    t0 = time.time()
    cmd = _cmd_ffmpeg_pipe(input_path, output_path, fps, has_audio)
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    cap = cv2.VideoCapture(str(input_path))
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            strips = []
            for x, y, cw, ch in bandas:
                crop = frame[y : y + ch, x : x + cw]
                interp = cv2.INTER_AREA if cw > OUTPUT_W else cv2.INTER_LANCZOS4
                strips.append(cv2.resize(crop, (OUTPUT_W, band_h), interpolation=interp))
            proc.stdin.write(cv2.vconcat(strips).tobytes())
    finally:
        cap.release()
        if proc.stdin:
            proc.stdin.close()
    _, err = proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"FFmpeg returncode {proc.returncode}: "
            + (err or b"").decode("utf-8", errors="replace")[-2000:]
        )
    return time.time() - t0


def reframe_stack_clip(input_path: Path, output_path: Path, detector_type: str = "yunet") -> dict:
    """Reencuadra en modo stack: N=2 o N=3 bandas estaticas, cero EMA/turnos."""
    from core import get_video_info

    _avisar_cortes(_contar_cortes_escena(input_path))
    info = get_video_info(input_path)
    src_w, src_h = info["width"], info["height"]
    has_audio = bool(info.get("has_audio", True))
    cap = cv2.VideoCapture(str(input_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.release()
    caras = detectar_caras_video(input_path, detector_type=detector_type)
    bandas = rt.calcular_bandas_stack(caras, src_w, src_h)  # raises ValueError si N<2 o N>3
    n = len(bandas)
    ordered = sorted(caras, key=lambda c: c["center_x"])
    for i, (x, _, cw, ch) in enumerate(bandas):
        cx = ordered[i]["center_x"]
        print(f"[reframe] stack banda {i}: cx_ancla={cx:.0f}  crop_x={x}  {cw}x{ch}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    elapsed = renderizar_stack(input_path, bandas, output_path, fps, has_audio)
    print(f"[reframe] stack {n} bandas  {input_path.name} -> {output_path.name} en {elapsed:.1f}s")
    return {"output": str(output_path), "dur_s": round(elapsed, 2), "n_caras": n, "modo": "stack"}


# ── CLI ───────────────────────────────────────────────────────────────────────


def _build_parser():
    import argparse

    p = argparse.ArgumentParser(description="Reframe vertical 16:9 -> 9:16")
    p.add_argument("input", type=Path, help="Clip MP4 de entrada")
    p.add_argument(
        "--layout",
        choices=["tracking", "stack"],
        default="tracking",
        help="tracking (default, EMA+deadzone) o stack (bandas estaticas N=2-3)",
    )
    p.add_argument("--turnos", type=Path, default=None, help="Archivo _turnos.json (tracking)")
    p.add_argument("--punch-in", action="store_true", help="Punch-ins en keywords (tracking)")
    p.add_argument("--out", type=Path, default=None, help="Ruta de salida")
    p.add_argument("--tray-dir", type=Path, default=None, help="CSV de trayectoria (tracking)")
    p.add_argument(
        "--detector",
        choices=["yunet", "blazeface"],
        default="yunet",
        help="Detector: yunet (default, mayor confianza) o blazeface (MediaPipe, fallback)",
    )
    p.add_argument(
        "--tracker",
        choices=["escenas", "ema"],
        default="escenas",
        help="escenas (default, cortes-primero + waypoints) o ema (F4.1 continuo)",
    )
    return p


if __name__ == "__main__":
    args = _build_parser().parse_args()
    if args.layout == "stack":
        output = args.out or args.input.with_stem(args.input.stem + SUFFIX_STACK)
        result = reframe_stack_clip(args.input, output)
    else:
        output = args.out or args.input.with_stem(args.input.stem + SUFFIX_9X16)
        turnos = json.loads(args.turnos.read_text(encoding="utf-8")) if args.turnos else None
        result = reframe_clip(
            args.input,
            output,
            turnos=turnos,
            punch_in=args.punch_in,
            tray_dir=args.tray_dir,
            detector_type=args.detector,
            tracker=args.tracker,
        )
    print(f"Output: {result['output']}")
