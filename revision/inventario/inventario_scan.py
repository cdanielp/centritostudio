"""Inventario de fuentes s26: ffprobe + cortes de escena + scan YuNet.

Reutiliza el detector de cortes del proyecto (_parsear_cortes_escena +
_filtrar_artefactos_cortes, threshold 0.3) y YuNetDetector para el scan
de caras en 6-8 frames repartidos por la duracion.

Salida: revision/inventario/scan_raw.json (consumido para fuentes.md).
Consola: solo ASCII (regla #2).
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402

from reframe import _filtrar_artefactos_cortes, _parsear_cortes_escena  # noqa: E402
from reframe_detect import YuNetDetector  # noqa: E402

VIDEOS = [
    "tacosjuan.mp4",
    "reel01.mp4",
    "reel02.mp4",
    "reel03.mp4",
    "pruebaedicionvideoyo.mov",
    "pruebaparaedicion.mov",
    "2c1b8978-5e83-42a0-879f-868a70794bc7_0.mov",
    "videolargo.mov",
    "pruebapodcast2personas.mp4",
    "prueba2personasenmedio.mov",
    "podcast_test_60s.mp4",
    "stack_test_estatico.mp4",
]


def ffprobe_info(path: Path) -> dict:
    r = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,avg_frame_rate",
            "-show_entries", "format=duration",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode:
        raise RuntimeError(f"ffprobe fallo para {path.name}: {r.stderr[-2000:]}")
    data = json.loads(r.stdout)
    st = data["streams"][0]
    num, den = st["avg_frame_rate"].split("/")
    fps = float(num) / float(den) if float(den) else 0.0
    w, h = st["width"], st["height"]
    return {
        "width": w,
        "height": h,
        "fps": round(fps, 2),
        "duration_s": round(float(data["format"]["duration"]), 1),
        "orientacion": "vertical" if h > w else ("horizontal" if w > h else "cuadrado"),
    }


def detectar_cortes(path: Path, timeout_s: int = 900) -> list[float] | None:
    """Detector del proyecto con timeout ampliado para fuentes largas."""
    try:
        r = subprocess.run(
            [
                "ffmpeg", "-i", str(path),
                "-vf", "select='gt(scene,0.3)',metadata=print:file=-",
                "-an", "-f", "null", "-",
            ],
            capture_output=True, text=True, timeout=timeout_s, errors="replace",
        )
        return _filtrar_artefactos_cortes(_parsear_cortes_escena(r.stdout))
    except Exception as exc:
        print(f"  AVISO scdet fallo: {type(exc).__name__}")
        return None


def scan_caras(path: Path, duracion_s: float, n_frames: int = 7) -> list[dict]:
    det = YuNetDetector()
    cap = cv2.VideoCapture(str(path))
    frames_out = []
    try:
        for i in range(n_frames):
            t = duracion_s * (i + 0.5) / n_frames
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ret, frame = cap.read()
            if not ret:
                continue
            h_frame = frame.shape[0]
            caras = [
                {
                    "score": round(d["score"], 3),
                    "alto_rel": round(d["bbox"][3] / h_frame, 3),
                    "cx_rel": round(d["center_x"] / frame.shape[1], 3),
                    "cy_rel": round(d["center_y"] / h_frame, 3),
                }
                for d in det.detect_all(frame)
            ]
            frames_out.append({"t_s": round(t, 1), "n_caras": len(caras), "caras": caras})
    finally:
        cap.release()
        det.close()
    return frames_out


def main() -> None:
    out = {}
    for name in VIDEOS:
        path = ROOT / "input" / name
        if not path.exists():
            print(f"[skip] {name} no existe")
            continue
        print(f"[scan] {name}")
        info = ffprobe_info(path)
        print(f"  {info['width']}x{info['height']} @{info['fps']}fps {info['duration_s']}s")
        cortes = detectar_cortes(path)
        n_cortes = len(cortes) if cortes is not None else -1
        print(f"  cortes: {n_cortes}")
        caras = scan_caras(path, info["duration_s"])
        resumen = [f["n_caras"] for f in caras]
        print(f"  caras por frame: {resumen}")
        out[name] = {
            "info": info,
            "n_cortes": n_cortes,
            "cortes_ts": cortes[:20] if cortes else cortes,
            "scan_caras": caras,
        }
        # guardar incremental por si algo truena a mitad
        raw = ROOT / "revision" / "inventario" / "scan_raw.json"
        raw.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("[ok] scan_raw.json escrito")


if __name__ == "__main__":
    main()
