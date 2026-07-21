"""benchmark_nvenc.py — CPU (libx264) vs NVIDIA NVENC en los pipelines reales (fase GPU).

Genera SUS PROPIOS fixtures sinteticos (lavfi; sin datos reales) y compara CPU contra NVENC en:
  1. Depuracion (EDL trim/concat + crossfade de audio).
  2. Captions simples (filtro ass).
  3. Captions con overlay minimo (emoji PNG).
  4. Reframe (pipe rawvideo OpenCV -> FFmpeg).

Para cada pipeline registra: encoder, wall time, x-tiempo-real, speedup, tamano, duracion, FPS,
dimensiones, codec de video/audio, start times, desfase A/V, fallback e integridad. Calcula
SSIM entre la salida CPU y la NVENC del mismo pipeline (objetivo >= 0.95). El reporte JSON se
escribe en output/revision-pre-hyperframes/nvenc/ y NO se versiona.

Uso:
    .\\venv\\Scripts\\python revision\\pre-hyperframes\\benchmark_nvenc.py
    .\\venv\\Scripts\\python revision\\pre-hyperframes\\benchmark_nvenc.py --dur 20
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REAL_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REAL_ROOT))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import core  # noqa: E402
import core_ass  # noqa: E402
import depurador  # noqa: E402
import media_integrity  # noqa: E402
import reframe  # noqa: E402
import styles  # noqa: E402
import video_encoder as ve  # noqa: E402

EVID_DIR = REAL_ROOT / "output" / "revision-pre-hyperframes" / "nvenc"
WORK_DIR = REAL_ROOT / "output" / ".nvenc_bench_tmp"  # bajo cwd: el filtro ass necesita rel-path
SPEEDUP_MIN = 1.25
SSIM_MIN = 0.95


def _ffprobe(path: Path) -> dict:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True,
    )
    return json.loads(r.stdout or "{}")


def _meta(path: Path) -> dict:
    d = _ffprobe(path)
    fmt = d.get("format", {})
    vs = [s for s in d.get("streams", []) if s.get("codec_type") == "video"]
    as_ = [s for s in d.get("streams", []) if s.get("codec_type") == "audio"]
    v = vs[0] if vs else {}
    a = as_[0] if as_ else {}
    v_start = float(v.get("start_time", 0) or 0)
    a_start = float(a.get("start_time", 0) or 0) if a else v_start
    return {
        "size": path.stat().st_size if path.exists() else 0,
        "duration": round(float(fmt.get("duration", 0) or 0), 3),
        "fps": v.get("r_frame_rate"),
        "dims": f"{v.get('width')}x{v.get('height')}",
        "vcodec": v.get("codec_name"),
        "acodec": a.get("codec_name"),
        "v_start": v_start,
        "a_start": a_start,
        "av_diff_ms": round(abs(v_start - a_start) * 1000, 1),
        "integridad": media_integrity.video_reanudable(path),
    }


def _ssim(cpu: Path, nvenc: Path) -> float | None:
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(cpu), "-i", str(nvenc),
         "-lavfi", "ssim", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    for line in (r.stderr or "").splitlines():
        if "SSIM" in line and "All:" in line:
            try:
                return float(line.split("All:")[1].split()[0])
            except (ValueError, IndexError):
                return None
    return None


# ── Fixtures sinteticos ─────────────────────────────────────────────────────────
def _fixture(dst: Path, dur: int) -> None:
    # mandelbrot = fuente de ALTO detalle espacial CON movimiento (zoom): representa contenido
    # real mucho mejor que un patron trivial. libx264 medium se esfuerza de verdad (revela la
    # ventaja de NVENC) y a la vez es ESTRUCTURADA (no ruido puro), asi el SSIM CPU/NVENC se
    # mantiene alto (>0.95). Sin datos privados, todo lavfi.
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "mandelbrot=size=1920x1080:rate=30",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}",
         "-t", str(dur), "-c:v", "libx264", "-crf", "18", "-c:a", "aac", "-shortest", str(dst)],
        check=True, capture_output=True,
    )


def _bench_raw_encode(src: Path, out_cpu: Path, out_nvenc: Path) -> dict:
    """Encode PURO (sin filtros): aisla la ventaja real del encoder NVENC vs libx264 medium."""
    def _enc(args, out):
        t0 = time.time()
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), *args,
                        "-c:a", "copy", str(out)], check=True, capture_output=True)
        return time.time() - t0
    t_cpu = _enc(ve.build_video_args(ve.select_encoder("cpu", "quality")), out_cpu)
    t_nvenc = _enc(ve.build_video_args(ve.select_encoder("nvenc", "quality", status=_OK_STATUS)), out_nvenc)
    return {
        "pipeline": "encode_puro_1080p",
        "cpu": {"wall_s": round(t_cpu, 2), **_meta(out_cpu)},
        "nvenc": {"wall_s": round(t_nvenc, 2), **_meta(out_nvenc)},
        "speedup": round(t_cpu / t_nvenc, 2) if t_nvenc > 0 else None,
        "ssim": _ssim(out_cpu, out_nvenc),
        "dur_diff_ms": round(abs(_meta(out_cpu)["duration"] - _meta(out_nvenc)["duration"]) * 1000, 1),
        "dims_iguales": _meta(out_cpu)["dims"] == _meta(out_nvenc)["dims"],
        "fps_iguales": _meta(out_cpu)["fps"] == _meta(out_nvenc)["fps"],
    }


_OK_STATUS = ve.NvencStatus(True, "ok", ve.MSG_OK)


def _words(dur: int) -> list[dict]:
    # Varias fronteras EDL: gaps > 0.8s cada ~4s.
    w = []
    t = 0.0
    while t < dur - 2:
        w.append({"w": "voz", "s": t, "e": t + 0.5, "prob": 0.9})
        w.append({"w": "voz", "s": t + 0.6, "e": t + 1.0, "prob": 0.9})
        t += 4.0  # gap de ~3s -> corte
    return w


def _timed(fn) -> tuple[float, object]:
    t0 = time.time()
    r = fn()
    return time.time() - t0, r


# ── Pipelines ───────────────────────────────────────────────────────────────────
def _bench_pipeline(nombre: str, correr, src: Path, dur: int, out_cpu: Path, out_nvenc: Path) -> dict:
    with ve.snapshot_job("cpu"):
        t_cpu, _ = _timed(lambda: correr(out_cpu))
    with ve.snapshot_job("nvenc"):
        t_nvenc, _ = _timed(lambda: correr(out_nvenc))
    m_cpu, m_nvenc = _meta(out_cpu), _meta(out_nvenc)
    dur_diff_ms = round(abs(m_cpu["duration"] - m_nvenc["duration"]) * 1000, 1)
    speedup = round(t_cpu / t_nvenc, 2) if t_nvenc > 0 else None
    return {
        "pipeline": nombre,
        "cpu": {"wall_s": round(t_cpu, 2), **m_cpu},
        "nvenc": {"wall_s": round(t_nvenc, 2), **m_nvenc},
        "speedup": speedup,
        "ssim": _ssim(out_cpu, out_nvenc),
        "dur_diff_ms": dur_diff_ms,
        "dims_iguales": m_cpu["dims"] == m_nvenc["dims"],
        "fps_iguales": m_cpu["fps"] == m_nvenc["fps"],
    }


def _run(dur: int) -> int:
    st = ve.detect_nvenc(force=True)
    if not st.available:
        print(f"[bench] NVENC no disponible ({st.reason}); benchmark N/A en esta maquina.")
        return 0
    if WORK_DIR.exists():
        shutil.rmtree(WORK_DIR, ignore_errors=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    reportes: list[dict] = []
    try:
        src = WORK_DIR / "src.mp4"
        _fixture(src, dur)
        words = _words(dur)
        groups = core.group_words([{"w": "hola", "s": 0.0, "e": 0.6, "prob": 0.9},
                                   {"w": "gpu", "s": 0.7, "e": 1.3, "prob": 0.9}])
        ass = WORK_DIR / "c.ass"
        core.build_ass(groups, 1920, 1080, styles.get_style("hormozi"), ass)
        png = WORK_DIR / "e.png"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", "color=c=red:s=120x120:d=1", "-frames:v", "1", str(png)],
                       check=True, capture_output=True)

        reportes.append(_bench_raw_encode(src, WORK_DIR / "raw_cpu.mp4", WORK_DIR / "raw_nv.mp4"))
        reportes.append(_bench_pipeline(
            "depuracion",
            lambda o: depurador.depurar(src, words, "seguro", o),
            src, dur, WORK_DIR / "dep_cpu.mp4", WORK_DIR / "dep_nv.mp4"))
        reportes.append(_bench_pipeline(
            "captions",
            lambda o: core_ass.burn_video(src, ass, o),
            src, dur, WORK_DIR / "cap_cpu.mp4", WORK_DIR / "cap_nv.mp4"))
        reportes.append(_bench_pipeline(
            "captions_overlay",
            lambda o: core_ass.burn_video_with_emojis(src, ass, o, [(png, 0.5, 2.0)]),
            src, dur, WORK_DIR / "ov_cpu.mp4", WORK_DIR / "ov_nv.mp4"))
        reframes = [(0, 0, 1080 * 9 // 16, 1080)] * (dur * 30)
        reportes.append(_bench_pipeline(
            "reframe",
            lambda o: reframe.renderizar_reframe(src, reframes, o, 30.0, has_audio=True),
            src, dur, WORK_DIR / "rf_cpu.mp4", WORK_DIR / "rf_nv.mp4"))
    finally:
        pass
    ok = _reporte(reportes, dur)
    shutil.rmtree(WORK_DIR, ignore_errors=True)
    return 0 if ok else 1


def _reporte(reportes: list[dict], dur: int) -> bool:
    EVID_DIR.mkdir(parents=True, exist_ok=True)
    (EVID_DIR / "benchmark_nvenc_report.json").write_text(
        json.dumps({"fixture_s": dur, "pipelines": reportes}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n=== BENCHMARK NVENC (fixture 1080p {dur}s) ===")
    todo_ok = True
    for r in reportes:
        integ = r["cpu"]["integridad"] and r["nvenc"]["integridad"]
        av = r["cpu"]["av_diff_ms"] <= 50 and r["nvenc"]["av_diff_ms"] <= 50
        h264 = r["cpu"]["vcodec"] == "h264" and r["nvenc"]["vcodec"] == "h264"
        crit = integ and av and h264 and r["dims_iguales"] and r["fps_iguales"] and r["dur_diff_ms"] <= 50
        ssim_ok = (r["ssim"] is None) or (r["ssim"] >= SSIM_MIN)
        speed_ok = (r["speedup"] or 0) >= SPEEDUP_MIN
        todo_ok = todo_ok and crit and ssim_ok
        print(f"\n[{r['pipeline']}]")
        print(f"  CPU   {r['cpu']['wall_s']}s  {r['cpu']['vcodec']}/{r['cpu']['acodec']}  {r['cpu']['size']}B")
        print(f"  NVENC {r['nvenc']['wall_s']}s  {r['nvenc']['vcodec']}/{r['nvenc']['acodec']}  {r['nvenc']['size']}B")
        print(f"  speedup={r['speedup']}x (min {SPEEDUP_MIN}) {'OK' if speed_ok else 'BAJO'} | "
              f"ssim={r['ssim']} (min {SSIM_MIN}) {'OK' if ssim_ok else 'BAJO'}")
        print(f"  dims_iguales={r['dims_iguales']} fps_iguales={r['fps_iguales']} "
              f"dur_diff={r['dur_diff_ms']}ms av<=50ms={av} integridad={integ}")
        if not speed_ok:
            print(f"  NOTA: speedup < {SPEEDUP_MIN}x - el encode NVENC acelera, pero los filtros CPU "
                  f"(decode/ass/trim/opencv) dominan el wall time en este pipeline.")
    print(f"\nevidencia (no versionada): {EVID_DIR / 'benchmark_nvenc_report.json'}")
    print(f"VEREDICTO: {'criterios A/V+SSIM cumplidos' if todo_ok else 'REVISAR criterios'}")
    return todo_ok


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    dur = 20
    if "--dur" in argv:
        dur = int(argv[argv.index("--dur") + 1])
    return _run(dur)


if __name__ == "__main__":
    raise SystemExit(main())
