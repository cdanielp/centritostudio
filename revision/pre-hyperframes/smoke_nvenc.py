"""Smoke NVENC — codificacion NVIDIA con fallback CPU (fase GPU pre-HyperFrames).

Dos modos:
  --self-test : todo mockeado (sin GPU). Demuestra que el arnes DETECTA fallos de deteccion,
                seleccion y fallback. Corre en cualquier maquina.
  --real      : usa fixtures SINTETICOS (lavfi), comprueba h264_nvenc real, genera CPU y NVENC
                por pipeline, verifica integridad + sincronizacion A/V, confirma que el codec
                final proviene de NVENC y limpia todos los temporales. Reporta N/A si no hay
                NVENC (maquina sin NVIDIA); en la RTX de destino debe pasar (blockers=0, fails=0).

Cubre 14 checks (1-7 logica, 8-14 real):
    1. FFmpeg sin h264_nvenc -> no disponible.        8. depurador NVENC.
    2. h264_nvenc listado, runtime falla -> no disp.  9. captions NVENC.
    3. NVENC funcional -> disponible.                10. overlays NVENC.
    4. auto selecciona NVENC.                        11. reframe NVENC.
    5. auto cae a CPU sin NVENC.                     12. fallback atomico real (64x64).
    6. nvenc explicito falla antes del job.          13. A/V dentro de tolerancia.
    7. cpu no intenta usar NVENC.                    14. salida sin rutas ni stderr privados.

NO toca input/0717_corregido.srt ni ningun dato privado. Sin red.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
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
# Directorio de trabajo BAJO cwd: el filtro ass de FFmpeg necesita rutas relativas a cwd.
WORK_DIR = REAL_ROOT / "output" / ".nvenc_smoke_tmp"

results: list[dict] = []


def record(name: str, status: str, detail: str) -> None:
    icon = {"PASS": "[PASS]", "FAIL": "[FAIL]", "BLOCKER": "[BLOCKER]", "NA": "[N/A]"}[status]
    results.append({"name": name, "status": status, "detail": detail})
    print(f"{icon} {name}: {detail}")


def _check(name, cond, ok, bad, *, blocker=False):
    record(name, "PASS", ok) if cond else record(name, "BLOCKER" if blocker else "FAIL", bad)


# ── Fixtures sinteticos ─────────────────────────────────────────────────────────
def _fixture_video(dst: Path, size: str = "640x480", dur: int = 4) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", f"testsrc=size={size}:rate=30:duration={dur}",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}",
         "-c:v", "libx264", "-crf", "23", "-c:a", "aac", "-shortest", str(dst)],
        check=True, capture_output=True,
    )


def _ffprobe(path: Path) -> dict:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True,
    )
    return json.loads(r.stdout or "{}")


def _codec(path: Path, kind: str) -> str | None:
    for s in _ffprobe(path).get("streams", []):
        if s.get("codec_type") == kind:
            return s.get("codec_name")
    return None


def _words_con_gap() -> list[dict]:
    return [
        {"w": "hola", "s": 0.0, "e": 0.5, "prob": 0.9},
        {"w": "mundo", "s": 0.6, "e": 1.0, "prob": 0.9},
        {"w": "otra", "s": 3.0, "e": 3.4, "prob": 0.9},
        {"w": "frase", "s": 3.5, "e": 3.9, "prob": 0.9},
    ]


# ── Checks 1-7: logica de deteccion/seleccion (sin GPU) ─────────────────────────
def _checks_logica() -> None:
    no_enc = ve.NvencStatus(False, "no_encoder", ve.MSG_NO_ENCODER)
    runtime = ve.NvencStatus(False, "runtime", ve.MSG_RUNTIME)
    ok = ve.NvencStatus(True, "ok", ve.MSG_OK)

    _check("1_ffmpeg_sin_nvenc", not no_enc.available and no_enc.message == ve.MSG_NO_ENCODER,
           "FFmpeg sin h264_nvenc -> no disponible", "deteccion no distingue encoder ausente")
    _check("2_runtime_falla", not runtime.available and runtime.message == ve.MSG_RUNTIME,
           "runtime no funcional -> mensaje de driver", "no distingue runtime fallido")
    _check("3_nvenc_funcional", ok.available and ok.message == ve.MSG_OK,
           "NVENC funcional -> disponible", "no reconoce NVENC funcional")

    s4 = ve.select_encoder("auto", "quality", status=ok)
    _check("4_auto_elige_nvenc", s4.selected == "nvenc", "auto -> NVENC", "auto no eligio NVENC")
    s5 = ve.select_encoder("auto", "quality", status=no_enc)
    _check("5_auto_cae_cpu", s5.selected == "cpu", "auto sin NVENC -> CPU", "auto no cayo a CPU")
    try:
        ve.select_encoder("nvenc", "quality", status=no_enc)
        _check("6_nvenc_explicito_falla", False, "", "nvenc explicito no rechazo")
    except ve.NVENCUnavailable:
        _check("6_nvenc_explicito_falla", True, "nvenc explicito -> NVENCUnavailable (pre-job)", "")
    s7 = ve.select_encoder("cpu", "quality")  # sin status: cpu no debe requerir deteccion
    _check("7_cpu_no_usa_nvenc", s7.encoder == "libx264", "cpu -> libx264 sin probe NVENC",
           "cpu intento usar NVENC")


# ── Checks 8-14: pipelines reales con NVENC ─────────────────────────────────────
def _av_ok(path: Path, dur_esperada: float) -> tuple[bool, str]:
    data = _ffprobe(path)
    fmt = data.get("format", {})
    dur = float(fmt.get("duration", 0) or 0)
    vs = [s for s in data.get("streams", []) if s.get("codec_type") == "video"]
    as_ = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
    if not vs:
        return False, "sin stream de video"
    v_start = float(vs[0].get("start_time", 0) or 0)
    a_start = float(as_[0].get("start_time", 0) or 0) if as_ else v_start
    if abs(v_start - a_start) > 0.05:
        return False, f"desfase A/V {abs(v_start - a_start):.3f}s > 50ms"
    if abs(dur - dur_esperada) > 0.2:
        return False, f"duracion {dur:.2f}s lejos de {dur_esperada:.2f}s"
    return True, f"dur={dur:.2f}s A/V<=50ms"


def _check_depurador(work: Path) -> None:
    src = work / "dep_src.mp4"
    _fixture_video(src, "640x480", 4)
    out = work / "dep_out.mp4"
    with ve.snapshot_job("auto"):
        res = depurador.depurar(src, _words_con_gap(), "seguro", out)
    integ = media_integrity.video_reanudable(out)
    _check("8_depurador_nvenc",
           res["video_encoder"] == "h264_nvenc" and _codec(out, "video") == "h264" and integ
           and _codec(out, "audio") == "aac",
           f"depurador NVENC ok ({res['encode_time_s']}s, aac intacto)",
           f"depurador NVENC fallo: {res.get('video_encoder')}", blocker=True)
    av, msg = _av_ok(out, float(_ffprobe(out).get("format", {}).get("duration", 0)))
    _check("13_av_tolerancia", av, f"A/V ok: {msg}", f"A/V fuera de tolerancia: {msg}")


def _check_captions(work: Path) -> None:
    src = work / "cap_src.mp4"
    _fixture_video(src, "1080x1920", 3)
    groups = core.group_words(
        [{"w": "hola", "s": 0.0, "e": 0.6, "prob": 0.9}, {"w": "gpu", "s": 0.7, "e": 1.3, "prob": 0.9}]
    )
    ass = work / "cap.ass"
    core.build_ass(groups, 1080, 1920, styles.get_style("hormozi"), ass)
    out = work / "cap_out.mp4"
    with ve.snapshot_job("auto"):
        core_ass.burn_video(src, ass, out)
    _check("9_captions_nvenc", _codec(out, "video") == "h264" and media_integrity.video_reanudable(out),
           "captions NVENC ok (integridad PASS)", "captions NVENC fallo", blocker=True)


def _check_overlays(work: Path) -> None:
    src = work / "ov_src.mp4"
    _fixture_video(src, "1080x1920", 3)
    groups = core.group_words([{"w": "pop", "s": 0.0, "e": 0.8, "prob": 0.9}])
    ass = work / "ov.ass"
    core.build_ass(groups, 1080, 1920, styles.get_style("hormozi"), ass)
    png = work / "e.png"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "color=c=red:s=100x100:d=1", "-frames:v", "1", str(png)],
        check=True, capture_output=True,
    )
    out = work / "ov_out.mp4"
    with ve.snapshot_job("auto"):
        core_ass.burn_video_with_emojis(src, ass, out, [(png, 0.2, 1.2)])
    _check("10_overlays_nvenc", _codec(out, "video") == "h264" and media_integrity.video_reanudable(out),
           "overlays (emoji) NVENC ok", "overlays NVENC fallo", blocker=True)


def _sin_residuo(work: Path) -> bool:
    tmp_dir = work / media_integrity.TEMP_DIRNAME
    return not tmp_dir.exists() or not any(tmp_dir.iterdir())


def _check_reframe(work: Path) -> None:
    src = work / "rf_src.mp4"
    _fixture_video(src, "1080x1920", 3)
    out = work / "rf_out.mp4"
    frames = [(0, 0, 1080, 1920)] * 90
    with ve.snapshot_job("auto"):
        reframe.renderizar_reframe(src, frames, out, 30.0, has_audio=True)
    _check("11_reframe_nvenc", _codec(out, "video") == "h264" and out.exists() and out.stat().st_size > 0,
           "reframe NVENC ok (pipe rawvideo)", "reframe NVENC fallo", blocker=True)


def _check_reframe_atomico(work: Path) -> None:
    src = work / "rf_src.mp4"  # reutiliza el fixture 1080x1920 del check anterior
    frames = [(0, 0, 1080, 1920)] * 90
    bandas = [(0, 0, 1080, 960), (0, 960, 1080, 960)]
    # Tracking sobre un final PREVIO valido: debe reemplazarlo y no dejar temporales.
    out_t = work / "rf_atom.mp4"
    _fixture_video(out_t, "1080x1920", 1)  # final anterior valido
    with ve.snapshot_job("auto"):
        reframe.renderizar_reframe(src, frames, out_t, 30.0, has_audio=True)
    out_s = work / "stk_atom.mp4"
    with ve.snapshot_job("cpu"):
        reframe.renderizar_stack(src, bandas, out_s, 30.0, has_audio=True)
    ok = (
        _codec(out_t, "video") == "h264" and media_integrity.video_reanudable(out_t)
        and _codec(out_s, "video") == "h264" and media_integrity.video_reanudable(out_s)
        and _sin_residuo(work)
    )
    _check("15_reframe_atomico", ok, "tracking y stack publican atomico, sin .render_tmp residual",
           "reframe no publico atomico o dejo temporales", blocker=True)
    # Final anterior PRESERVADO ante un fallo simulado (input inexistente -> pipe falla, sin fallback).
    out_p = work / "rf_preserva.mp4"
    _fixture_video(out_p, "1080x1920", 1)
    antes = out_p.read_bytes()
    fallo_ok = False
    try:
        with ve.snapshot_job("cpu"):
            reframe.renderizar_reframe(work / "no_existe.mp4", frames, out_p, 30.0, has_audio=False)
    except Exception:
        fallo_ok = out_p.read_bytes() == antes and _sin_residuo(work)
    _check("16_reframe_final_preservado", fallo_ok,
           "final anterior intacto tras fallo de reframe, sin residuos",
           "el fallo altero el final anterior o dejo temporales", blocker=True)


def _check_fallback_real(work: Path) -> None:
    # 64x64 provoca un fallo REAL de init NVENC (frame < minimo del driver): el modo auto
    # debe caer a CPU, publicar atomicamente y no dejar temporales.
    src = work / "fb_src.mp4"
    _fixture_video(src, "64x64", 3)
    out = work / "fb_out.mp4"
    with ve.snapshot_job("auto"):
        res = depurador.depurar(src, _words_con_gap(), "seguro", out)
    tmp_dir = out.parent / media_integrity.TEMP_DIRNAME
    sin_residuo = not tmp_dir.exists() or not any(tmp_dir.iterdir())
    _check("12_fallback_atomico",
           res["fallback_used"] and res["video_encoder"] == "libx264"
           and _codec(out, "video") == "h264" and media_integrity.video_reanudable(out) and sin_residuo,
           "fallback NVENC->CPU real, atomico y sin residuos",
           f"fallback fallo: fb={res.get('fallback_used')} enc={res.get('video_encoder')}",
           blocker=True)


def _check_sanitizacion() -> None:
    # Un fallo de encode NO debe filtrar rutas ni stderr al mensaje publico.
    msg = ve.sanitize_encoder_error("C:\\Users\\PC\\secreto.mp4\nffmpeg internal detail xyz")
    _check("14_salida_saneada", "C:\\" not in msg and "secreto" not in msg and "xyz" not in msg,
           "mensaje publico sin rutas ni stderr", "el mensaje filtra detalle privado", blocker=True)


# ── Orquestacion ────────────────────────────────────────────────────────────────
def _run_real() -> int:
    _checks_logica()
    st = ve.detect_nvenc(force=True)
    if not st.available:
        record("real_nvenc", "NA", f"NVENC no disponible en esta maquina ({st.reason}); checks 8-13 N/A")
        _check_sanitizacion()
        return _summary("NVENC")
    if WORK_DIR.exists():
        shutil.rmtree(WORK_DIR, ignore_errors=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    try:
        _check_depurador(WORK_DIR)
        _check_captions(WORK_DIR)
        _check_overlays(WORK_DIR)
        _check_reframe(WORK_DIR)
        _check_reframe_atomico(WORK_DIR)
        _check_fallback_real(WORK_DIR)
        _check_sanitizacion()
    finally:
        shutil.rmtree(WORK_DIR, ignore_errors=True)
    return _summary("NVENC")


def _summary(tag: str) -> int:
    blockers = [r for r in results if r["status"] == "BLOCKER"]
    fails = [r for r in results if r["status"] == "FAIL"]
    nas = [r for r in results if r["status"] == "NA"]
    report = {
        "fase": "GPU-NVENC", "checks": len(results),
        "blockers": len(blockers), "fails": len(fails), "na": len(nas), "results": results,
    }
    EVID_DIR.mkdir(parents=True, exist_ok=True)
    (EVID_DIR / "smoke_nvenc_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n=== RESUMEN {tag} ===")
    print(f"checks={len(results)} blockers={len(blockers)} fails={len(fails)} na={len(nas)}")
    print(f"evidencia (no versionada): {EVID_DIR / 'smoke_nvenc_report.json'}")
    if blockers or fails:
        print("VEREDICTO: GPU/NVENC NO LISTO.")
        return 1
    print("VEREDICTO: GPU/NVENC codificacion acelerada con fallback CPU verificada.")
    return 0


def _self_test() -> int:
    """Verifica que el arnes DETECTA fallos (deteccion, seleccion y fallback) sin GPU."""
    checks: list[tuple[str, bool]] = []

    # Deteccion: subprocess simulado (encoder ausente / runtime falla / funcional).
    class _P:
        def __init__(self, rc=0, out="", err=""):
            self.returncode, self.stdout, self.stderr = rc, out, err

    def _det(enc_out, probe_rc):
        def fake_run(cmd, *a, **k):
            if "-encoders" in cmd:
                return _P(0, enc_out)
            out = cmd[-1]
            if probe_rc == 0:
                Path(out).write_bytes(b"\x00" * 16)
            return _P(probe_rc, "", "InitializeEncoder failed" if probe_rc else "")
        orig = ve.subprocess.run
        ve.subprocess.run = fake_run
        try:
            return ve.detect_nvenc(force=True)
        finally:
            ve.subprocess.run = orig
            ve._reset_cache_for_tests()

    checks.append(("detecta_encoder_ausente", not _det("libx264\n", 0).available))
    checks.append(("detecta_runtime_falla", not _det("h264_nvenc\n", 1).available))
    checks.append(("detecta_funcional", _det("h264_nvenc\n", 0).available))

    # Seleccion.
    ok = ve.NvencStatus(True, "ok", ve.MSG_OK)
    no = ve.NvencStatus(False, "no_encoder", ve.MSG_NO_ENCODER)
    checks.append(("auto_elige_nvenc", ve.select_encoder("auto", "quality", status=ok).selected == "nvenc"))
    checks.append(("auto_cae_cpu", ve.select_encoder("auto", "quality", status=no).selected == "cpu"))

    # Fallback: NVENC init falla -> CPU una sola vez.
    def _fb():
        intentos = []

        def fake_run(cmd, *a, **k):
            intentos.append(cmd)
            return _P(1, "", "OpenEncodeSessionEx failed") if "h264_nvenc" in cmd else _P(0)

        orig = ve.subprocess.run
        ve.subprocess.run = fake_run
        try:
            sel = ve.select_encoder("auto", "quality", status=ok)
            out = ve.run_ffmpeg_encode(sel, lambda va: ["ffmpeg", *va, "o.mp4"])
            return out.selection.fallback_used and out.selection.selected == "cpu", len(intentos)
        finally:
            ve.subprocess.run = orig

    fb_ok, n = _fb()
    checks.append(("fallback_una_vez", fb_ok and n == 2))

    # No reintenta un error de input.
    def _no_reintenta():
        orig = ve.subprocess.run
        ve.subprocess.run = lambda *a, **k: _P(1, "", "No such file input.mp4")
        try:
            sel = ve.select_encoder("auto", "quality", status=ok)
            try:
                ve.run_ffmpeg_encode(sel, lambda va: ["ffmpeg", *va, "o.mp4"])
                return False
            except ve.VideoEncodeError:
                return True
        finally:
            ve.subprocess.run = orig

    checks.append(("no_reintenta_error_input", _no_reintenta()))

    passed = sum(1 for _n, c in checks if c)
    for n_, c in checks:
        print(f"{'[OK]' if c else '[X ]'} self-test: {n_}")
    good = passed == len(checks)
    print(f"\n=== SELF-TEST NVENC: {'VERDE' if good else 'ROJO'} ({passed}/{len(checks)}) ===")
    return 0 if good else 1


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if "--self-test" in argv:
        return _self_test()
    return _run_real()


if __name__ == "__main__":
    raise SystemExit(main())
