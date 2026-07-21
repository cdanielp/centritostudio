"""test_nvenc_encoder.py — Deteccion, seleccion, argumentos y fallback del encoder (FASE 12).

Sin FFmpeg real y sin GPU: la deteccion se prueba con subprocess mockeado (inyeccion), la
seleccion con NvencStatus inyectado y los argumentos son puros. Cero skips, cero red.
"""

from __future__ import annotations

import subprocess

import pytest

import video_encoder as ve


class _FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture(autouse=True)
def _reset_encoder_state():
    """Cada test parte de cache limpia y modo por defecto auto (aislamiento)."""
    ve._reset_cache_for_tests()
    ve.set_default_mode("auto")
    yield
    ve._reset_cache_for_tests()
    ve.set_default_mode("auto")


# ── A. Deteccion ────────────────────────────────────────────────────────────────
def _patch_run(monkeypatch, encoders_proc, probe_proc=None):
    """Simula subprocess.run: 1a llamada = -encoders, 2a = micro-probe."""
    llamadas = {"n": 0}

    def fake_run(cmd, *a, **k):
        llamadas["n"] += 1
        if "-encoders" in cmd:
            if isinstance(encoders_proc, Exception):
                raise encoders_proc
            return encoders_proc
        if isinstance(probe_proc, Exception):
            raise probe_proc
        return probe_proc

    monkeypatch.setattr(ve.subprocess, "run", fake_run)
    return llamadas


def test_deteccion_ffmpeg_ausente(monkeypatch):
    _patch_run(monkeypatch, OSError("no ffmpeg"))
    st = ve.detect_nvenc(force=True)
    assert not st.available and st.reason == "no_ffmpeg"
    assert st.message == ve.MSG_NO_FFMPEG


def test_deteccion_encoder_ausente(monkeypatch):
    _patch_run(monkeypatch, _FakeProc(0, "V..... libx264\nV..... libvpx\n"))
    st = ve.detect_nvenc(force=True)
    assert not st.available and st.reason == "no_encoder"
    assert st.message == ve.MSG_NO_ENCODER


def test_deteccion_encoder_listado_runtime_falla(monkeypatch):
    _patch_run(
        monkeypatch,
        _FakeProc(0, "V..... h264_nvenc\n"),
        _FakeProc(1, "", "InitializeEncoder failed"),
    )
    st = ve.detect_nvenc(force=True)
    assert not st.available and st.reason == "runtime"
    assert st.message == ve.MSG_RUNTIME


def test_deteccion_runtime_probe_correcto(monkeypatch, tmp_path):
    # El probe escribe a un temporal del sistema; simulamos exito con un archivo real no vacio.
    def fake_run(cmd, *a, **k):
        if "-encoders" in cmd:
            return _FakeProc(0, "V..... h264_nvenc\n")
        out = cmd[-1]
        from pathlib import Path

        Path(out).write_bytes(b"\x00" * 32)
        return _FakeProc(0)

    monkeypatch.setattr(ve.subprocess, "run", fake_run)
    st = ve.detect_nvenc(force=True)
    assert st.available and st.reason == "ok" and st.message == ve.MSG_OK


def test_deteccion_timeout_encoders(monkeypatch):
    _patch_run(monkeypatch, subprocess.TimeoutExpired("ffmpeg", 20))
    st = ve.detect_nvenc(force=True)
    assert not st.available and st.reason == "no_encoder"


def test_deteccion_cache_no_reejecuta(monkeypatch):
    llamadas = _patch_run(monkeypatch, _FakeProc(0, "no nvenc aqui\n"))
    ve.detect_nvenc(force=True)
    n1 = llamadas["n"]
    ve.detect_nvenc()  # sin force -> cache
    assert llamadas["n"] == n1


def test_deteccion_refresh_reejecuta(monkeypatch):
    llamadas = _patch_run(monkeypatch, _FakeProc(0, "no nvenc\n"))
    ve.detect_nvenc(force=True)
    n1 = llamadas["n"]
    ve.refresh_nvenc()
    assert llamadas["n"] > n1


def test_probe_limpia_temporal(monkeypatch):
    creados = []

    def fake_run(cmd, *a, **k):
        if "-encoders" in cmd:
            return _FakeProc(0, "h264_nvenc\n")
        creados.append(cmd[-1])
        return _FakeProc(1, "", "boom")  # falla -> igual debe limpiar

    monkeypatch.setattr(ve.subprocess, "run", fake_run)
    ve.detect_nvenc(force=True)
    from pathlib import Path

    assert creados, "el probe debio intentar escribir un temporal"
    assert not Path(creados[0]).parent.exists() or not Path(creados[0]).exists()


# ── B. Seleccion ────────────────────────────────────────────────────────────────
_OK = ve.NvencStatus(True, "ok", ve.MSG_OK)
_NO = ve.NvencStatus(False, "no_encoder", ve.MSG_NO_ENCODER)


def test_seleccion_auto_con_nvenc():
    sel = ve.select_encoder("auto", "quality", status=_OK)
    assert sel.selected == "nvenc" and sel.encoder == "h264_nvenc" and not sel.fallback_used


def test_seleccion_auto_sin_nvenc_cae_cpu():
    sel = ve.select_encoder("auto", "quality", status=_NO)
    assert sel.selected == "cpu" and sel.encoder == "libx264"


def test_seleccion_nvenc_explicito_disponible():
    sel = ve.select_encoder("nvenc", "fast", status=_OK)
    assert sel.selected == "nvenc"


def test_seleccion_nvenc_explicito_ausente_lanza():
    with pytest.raises(ve.NVENCUnavailable):
        ve.select_encoder("nvenc", "quality", status=_NO)


def test_seleccion_cpu_no_consulta_status():
    # status None + cpu: no debe requerir deteccion (no lanza aunque no haya status)
    sel = ve.select_encoder("cpu", "quality")
    assert sel.selected == "cpu"


def test_variable_entorno_invalida_cae_auto(monkeypatch):
    monkeypatch.setenv(ve.ENV_VAR, "turbogpu")
    assert ve._mode_from_env() == ve.EncoderMode.AUTO


def test_coerce_mode_invalido_lanza():
    with pytest.raises(ve.EncoderConfigurationError):
        ve.coerce_mode("gpu")


# ── C. Argumentos (byte-identicos a los historicos) ─────────────────────────────
def test_cpu_quality_byte_identico():
    sel = ve.select_encoder("cpu", "quality")
    assert ve.build_video_args(sel) == ["-c:v", "libx264", "-preset", "medium", "-crf", "18"]


def test_cpu_fast_byte_identico():
    sel = ve.select_encoder("cpu", "fast")
    assert ve.build_video_args(sel) == ["-c:v", "libx264", "-crf", "18", "-preset", "fast"]


def test_nvenc_quality_args():
    sel = ve.select_encoder("nvenc", "quality", status=_OK)
    args = ve.build_video_args(sel)
    assert args[:2] == ["-c:v", "h264_nvenc"]
    assert "-preset" in args and args[args.index("-preset") + 1] == "p5"
    assert args[-2:] == ["-pix_fmt", "yuv420p"]
    assert "-cq" in args and args[args.index("-cq") + 1] == "18"


def test_nvenc_fast_preset_p4():
    sel = ve.select_encoder("nvenc", "fast", status=_OK)
    args = ve.build_video_args(sel)
    assert args[args.index("-preset") + 1] == "p4"


def test_build_args_encoder_no_permitido():
    mal = ve.EncoderSelection("auto", "gpu", "encoder_raro", "quality", "x")
    with pytest.raises(ve.EncoderConfigurationError):
        ve.build_video_args(mal)


def test_args_no_usan_shell():
    # Los argumentos son SIEMPRE una lista de tokens (nunca un string para shell).
    sel = ve.select_encoder("nvenc", "quality", status=_OK)
    assert isinstance(ve.build_video_args(sel), list)
    assert all(isinstance(t, str) and " " not in t for t in ve.build_video_args(sel))


# ── E. Fallback ─────────────────────────────────────────────────────────────────
def _build_cmd(vargs):
    return ["ffmpeg", "-y", *vargs, "out.mp4"]


def test_fallback_solo_auto_una_vez(monkeypatch):
    sel = ve.select_encoder("auto", "quality", status=_OK)  # nvenc
    intentos = []

    def fake_run(cmd, *a, **k):
        intentos.append(cmd)
        if "h264_nvenc" in cmd:
            return _FakeProc(1, "", "OpenEncodeSessionEx failed")
        return _FakeProc(0)  # cpu OK

    monkeypatch.setattr(ve.subprocess, "run", fake_run)
    limpieza = []
    out = ve.run_ffmpeg_encode(sel, _build_cmd, cleanup=lambda: limpieza.append(1))
    assert out.selection.selected == "cpu" and out.selection.fallback_used
    assert sum(1 for c in intentos if "h264_nvenc" in c) == 1  # NVENC una sola vez
    assert sum(1 for c in intentos if "libx264" in c) == 1  # CPU una sola vez
    assert limpieza == [1]  # limpio el parcial NVENC antes del reintento


def test_fallback_no_reintenta_error_de_input(monkeypatch):
    sel = ve.select_encoder("auto", "quality", status=_OK)
    intentos = []

    def fake_run(cmd, *a, **k):
        intentos.append(cmd)
        return _FakeProc(1, "", "No such file or directory: input.mp4")

    monkeypatch.setattr(ve.subprocess, "run", fake_run)
    with pytest.raises(ve.VideoEncodeError):
        ve.run_ffmpeg_encode(sel, _build_cmd)
    assert len(intentos) == 1  # NO reintenta un error de input


def test_fallback_no_ocurre_en_modo_cpu(monkeypatch):
    sel = ve.select_encoder("cpu", "quality")

    def fake_run(cmd, *a, **k):
        return _FakeProc(1, "", "InitializeEncoder failed")

    monkeypatch.setattr(ve.subprocess, "run", fake_run)
    with pytest.raises(ve.VideoEncodeError):
        ve.run_ffmpeg_encode(sel, _build_cmd)


def test_fallback_no_ocurre_en_nvenc_explicito(monkeypatch):
    sel = ve.select_encoder("nvenc", "quality", status=_OK)
    intentos = []

    def fake_run(cmd, *a, **k):
        intentos.append(cmd)
        return _FakeProc(1, "", "InitializeEncoder failed")

    monkeypatch.setattr(ve.subprocess, "run", fake_run)
    with pytest.raises(ve.VideoEncodeError):
        ve.run_ffmpeg_encode(sel, _build_cmd)
    assert len(intentos) == 1  # nvenc explicito no cae silenciosamente a CPU


def test_run_encode_exito_reporta_seleccion(monkeypatch):
    sel = ve.select_encoder("auto", "quality", status=_OK)
    monkeypatch.setattr(ve.subprocess, "run", lambda *a, **k: _FakeProc(0))
    out = ve.run_ffmpeg_encode(sel, _build_cmd)
    assert out.selection.selected == "nvenc" and not out.selection.fallback_used


def test_is_nvenc_init_failure_clasifica():
    assert ve.is_nvenc_init_failure("InitializeEncoder failed: invalid param")
    assert ve.is_nvenc_init_failure("No capable devices found")
    assert not ve.is_nvenc_init_failure("No such file input.mp4")
    assert not ve.is_nvenc_init_failure("Error parsing ass filter")


def test_sanitize_no_filtra_stderr():
    msg = ve.sanitize_encoder_error("C:\\Users\\PC\\secreto\nffmpeg internal error")
    assert "C:\\" not in msg and "secreto" not in msg


# ── Telemetria y snapshot ───────────────────────────────────────────────────────
def test_telemetria_saneada():
    sel = ve.select_encoder("auto", "quality", status=_OK)
    t = ve.selection_telemetry(sel, 3.14159)
    assert t == {
        "video_encoder": "h264_nvenc",
        "encoder_mode": "auto",
        "fallback_used": False,
        "encode_time_s": 3.14,
    }


def test_snapshot_es_inmutable_ante_cambio_de_default():
    ve.set_default_mode("cpu")
    with ve.snapshot_job():  # captura cpu
        ve.set_default_mode("nvenc")  # cambia el default a mitad del "job"
        assert ve.active_mode() == ve.EncoderMode.CPU  # el snapshot NO cambia
    assert ve.active_mode() == ve.EncoderMode.NVENC  # fuera del job, el nuevo default


def test_con_snapshot_decorador():
    ve.set_default_mode("cpu")

    @ve.con_snapshot
    def worker():
        return ve.active_mode()

    assert worker() == ve.EncoderMode.CPU
