"""reframe_escenas.py — Modo escenas del reframe 9:16 (F4.2-CORTES).

Pipeline cortes-primero: los cortes de escena delimitan segmentos; cada segmento
se clasifica con UN frame representativo (single/multi/none) y se trackea DENTRO
del segmento. Los tracks se REINICIAN en cada corte: cada segmento es una llamada
independiente a funciones puras de reframe_track — cero estado cruzando fronteras.

Diseno: PREGUNTAS.md #26 / DECISIONES.md D15 (credito proyecto de referencia;
reimplementacion propia). Importado exclusivamente por reframe.py.
"""

from __future__ import annotations

from pathlib import Path

import cv2

import reframe_track as rt
from reframe_detect import _crear_detector


def _clasificar_segmentos_video(
    input_path: Path, segs: list[tuple[int, int]], detector
) -> list[dict]:
    """Por segmento: frame representativo en el punto medio -> caras -> tipo."""
    cap = cv2.VideoCapture(str(input_path))
    infos: list[dict] = []
    try:
        for f_ini, f_fin in segs:
            f_rep = (f_ini + f_fin) // 2
            cap.set(cv2.CAP_PROP_POS_FRAMES, f_rep)
            ret, frame = cap.read()
            caras = rt.detectar_todas_caras_frame(frame, detector) if ret else []
            infos.append(
                {
                    "f_ini": f_ini,
                    "f_fin": f_fin,
                    "f_rep": f_rep,
                    "tipo": rt.clasificar_segmento(len(caras)),
                    "caras": caras,
                }
            )
    finally:
        cap.release()
    return infos


def _muestrear_escenas(
    input_path: Path, seg_infos: list[dict], fps: float, detector
) -> dict[int, list[dict]]:
    """Un pase secuencial; detecta caras en los frames de muestreo de cada segmento.

    single: cada MUESTREO_ESCENAS_S; multi: cada DETECT_EVERY_N frames; none: nada.
    Devuelve {frame_idx: [detecciones]}.
    """
    paso_single = max(int(rt.MUESTREO_ESCENAS_S * fps), 1)
    detectar_en: set[int] = set()
    for si in seg_infos:
        if si["tipo"] == "single":
            detectar_en.update(range(si["f_ini"], si["f_fin"], paso_single))
        elif si["tipo"] == "multi":
            detectar_en.update(range(si["f_ini"], si["f_fin"], rt.DETECT_EVERY_N))
    dets_por_frame: dict[int, list[dict]] = {}
    if not detectar_en:
        return dets_por_frame
    ultimo = max(detectar_en)
    cap = cv2.VideoCapture(str(input_path))
    try:
        for fi in range(ultimo + 1):
            ret, frame = cap.read()
            if not ret:
                break
            if fi in detectar_en:
                dets = rt.detectar_todas_caras_frame(frame, detector)
                if dets:
                    dets_por_frame[fi] = dets
    finally:
        cap.release()
    return dets_por_frame


def _seg_single(
    si: dict, dets: dict[int, list[dict]], fps: float, src_w: int, src_h: int
) -> tuple[list[tuple[int, int, int, int]], list[float], dict[int, float], int]:
    """Segmento single: waypoints + paneo interpolado. Devuelve (crops, filled, conf, n_paneos)."""
    crop_w = src_h * 9 // 16
    dz_w = rt.DEADZONE_PCT_ESCENAS * crop_w
    ancla = si["caras"][0]["center_x"]
    gate = rt.GATE_ANCLA_PCT * src_w
    samples: list[tuple[float, float | None]] = []
    conf: dict[int, float] = {}
    filled_sparsa: dict[int, float] = {}
    for fi in sorted(dets):
        if not (si["f_ini"] <= fi < si["f_fin"]):
            continue
        cands = [d for d in dets[fi] if abs(d["center_x"] - ancla) <= gate]
        if cands:
            best = max(cands, key=lambda d: d["score"])
            samples.append((fi / fps, best["center_x"]))
            conf[fi] = best["score"]
            filled_sparsa[fi] = best["center_x"]
        else:
            samples.append((fi / fps, None))
    t_frames = [fi / fps for fi in range(si["f_ini"], si["f_fin"])]
    xs, n_paneos = rt.xs_segmento_single(samples, t_frames, dz_w, ancla)
    crops = [rt.calcular_ventana_crop(x, src_w, src_h) for x in xs]
    # filled: posicion real de la cara (hold entre muestras) para CSV/C1v2
    n_seg = si["f_fin"] - si["f_ini"]
    raw = rt.interpolar_detecciones(
        {fi - si["f_ini"]: cx for fi, cx in filled_sparsa.items()}, n_seg
    )
    filled = rt.manejar_cara_perdida(raw, ancla)
    return crops, filled, conf, n_paneos


def _seg_multi(
    si: dict, dets: dict[int, list[dict]], fps: float, src_w: int, src_h: int
) -> tuple[list[tuple[int, int, int, int]], list[float], dict[int, float]]:
    """Segmento multi: ancla re-escaneada en este segmento, EMA scoped.

    v1: sigue UNICAMENTE la cara principal (mayor score) del frame representativo
    del segmento; caras que entran a mitad del segmento no generan track propio.
    EMA adaptativo + deadzone existentes con estado local al segmento.
    """
    crop_w = src_h * 9 // 16
    deadzone_w = rt.DEADZONE_PCT * crop_w
    ancla = si["caras"][0]["center_x"]  # detect_all ordena por score desc
    gate = rt.GATE_ANCLA_PCT * src_w
    sparsa_local: dict[int, float] = {}
    conf: dict[int, float] = {}
    for fi in sorted(dets):
        if not (si["f_ini"] <= fi < si["f_fin"]):
            continue
        cands = [d for d in dets[fi] if abs(d["center_x"] - ancla) <= gate]
        if cands:
            best = max(cands, key=lambda d: d["score"])
            sparsa_local[fi - si["f_ini"]] = best["center_x"]
            conf[fi] = best["score"]
    n_seg = si["f_fin"] - si["f_ini"]
    if not sparsa_local:
        crops_fijos = [rt.calcular_ventana_crop(ancla, src_w, src_h)] * n_seg
        return crops_fijos, [ancla] * n_seg, conf
    raw = rt.interpolar_detecciones(sparsa_local, n_seg)
    filled = rt.manejar_cara_perdida(raw, ancla)
    targets = rt.aplicar_deadzone_secuencia(filled, deadzone_w)
    smooth = rt.ema_smooth_adaptativo(targets, fps, deadzone_w)
    crops = [rt.calcular_ventana_crop(x, src_w, src_h) for x in smooth]
    return crops, filled, conf


def _c1v2_segmento(
    crops: list[tuple[int, int, int, int]],
    filled: list[float],
    conf: dict[int, float],
    f_ini: int,
) -> tuple[float | None, int]:
    """C1v2 del segmento: % de detecciones VIVAS con |cam - cara| <= 80px.

    Devuelve (pct | None si no hubo detecciones vivas, n_vivas).
    """
    n_pass = n_live = 0
    for fi_global in conf:
        j = fi_global - f_ini
        if not (0 <= j < len(crops)):
            continue
        x, _y, cw, _ch = crops[j]
        cam_cx = x + cw / 2
        n_live += 1
        if abs(cam_cx - filled[j]) <= 80:
            n_pass += 1
    return (100.0 * n_pass / n_live if n_live else None), n_live


def _reporte_segmento(
    si: dict, idx: int, fps: float, n_paneos: int, c1v2: float | None, n_live: int
) -> dict:
    """Construye la entrada de reporte del segmento y la imprime."""
    t_ini, t_fin = si["f_ini"] / fps, si["f_fin"] / fps
    c1_str = f"{c1v2:.1f}%" if c1v2 is not None else "n/a"
    print(
        f"[reframe]   seg {idx}: {t_ini:.1f}-{t_fin:.1f}s {si['tipo']} "
        f"({len(si['caras'])} cara(s)) paneos={n_paneos} C1v2={c1_str} vivas={n_live}"
    )
    return {
        "seg": idx,
        "t_ini": round(t_ini, 2),
        "t_fin": round(t_fin, 2),
        "tipo": si["tipo"],
        "n_caras": len(si["caras"]),
        "n_paneos": n_paneos,
        "c1v2": round(c1v2, 1) if c1v2 is not None else None,
        "n_det_vivas": n_live,
    }


def calcular_crops_escenas(
    input_path: Path,
    fps: float,
    total_frames: int,
    src_w: int,
    src_h: int,
    cortes_ts: list[float],
    detector_type: str = "yunet",
) -> tuple[list[tuple[int, int, int, int]], list[float], dict[int, float], list[dict]]:
    """Pipeline cortes-primero: segmentos -> clasificar -> trackear POR segmento.

    Devuelve (crops, filled, conf_global, reporte_segmentos).
    """
    segs = rt.segmentos_desde_cortes(cortes_ts, fps, total_frames)
    print(f"[reframe] modo escenas: {len(cortes_ts)} corte(s) -> {len(segs)} segmento(s)")

    detector = _crear_detector(detector_type)
    try:
        seg_infos = _clasificar_segmentos_video(input_path, segs, detector)
        dets = _muestrear_escenas(input_path, seg_infos, fps, detector)
    finally:
        detector.close()

    crop_w = src_h * 9 // 16
    crops: list[tuple[int, int, int, int]] = []
    filled: list[float] = []
    conf_global: dict[int, float] = {}
    reporte: list[dict] = []

    for idx, si in enumerate(seg_infos):
        n_seg = si["f_fin"] - si["f_ini"]
        n_paneos = 0
        if si["tipo"] == "single":
            c, f, cf, n_paneos = _seg_single(si, dets, fps, src_w, src_h)
        elif si["tipo"] == "multi":
            c, f, cf = _seg_multi(si, dets, fps, src_w, src_h)
        else:  # none: crop estatico centrado, sin tracking
            cx = (src_w - crop_w) // 2
            c = [(cx, 0, crop_w, src_h)] * n_seg
            f = [src_w / 2] * n_seg
            cf = {}
        crops.extend(c)
        filled.extend(f)
        conf_global.update(cf)
        c1v2, n_live = _c1v2_segmento(c, f, cf, si["f_ini"])
        reporte.append(_reporte_segmento(si, idx, fps, n_paneos, c1v2, n_live))

    # Rellenar cola si CAP_PROP_FRAME_COUNT reporto mas frames que los segmentos
    while len(crops) < total_frames:
        crops.append(crops[-1] if crops else ((src_w - crop_w) // 2, 0, crop_w, src_h))
        filled.append(filled[-1] if filled else src_w / 2)

    return crops, filled, conf_global, reporte
