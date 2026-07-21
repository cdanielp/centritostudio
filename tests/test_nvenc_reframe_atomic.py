"""test_nvenc_reframe_atomic.py — Publicacion atomica de reframe tracking/stack (fase GPU).

Sin FFmpeg real: se mockea el pipe (`_pipe_a_ffmpeg`/`_pipe_stack`) y `verificar_video` con un
stub de tamano. Verifica que FFmpeg nunca escribe al nombre final, que cada intento usa un
temporal UNICO en `.render_tmp`, que el final anterior se conserva ante fallos y que no quedan
temporales. Cubre los 13 checks obligatorios del correctivo.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import media_integrity
import reframe
import video_encoder as ve

_OK = ve.NvencStatus(True, "ok", ve.MSG_OK)
_INIT_FAIL = "InitializeEncoder failed: invalid param"
_INPUT_ERR = "No such file or directory: input.mp4"


@pytest.fixture(autouse=True)
def _reset():
    ve._reset_cache_for_tests()
    ve.set_default_mode("auto")
    yield
    ve._reset_cache_for_tests()
    ve.set_default_mode("auto")


class _FakePipe:
    """Sustituye el pipe real: registra cmds/targets, escribe al target solo si rc==0."""

    def __init__(self, rc_seq, stderr_seq, write=True):
        self.rc_seq = list(rc_seq)
        self.stderr_seq = list(stderr_seq)
        self.write = write
        self.cmds: list[list[str]] = []
        self.targets: list[Path] = []

    def __call__(self, cmd, *rest):
        self.cmds.append(cmd)
        target = Path(cmd[-1])
        self.targets.append(target)
        rc = self.rc_seq.pop(0)
        stderr = self.stderr_seq.pop(0)
        if self.write and rc == 0:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"NEWDATA" * 20)
        return rc, stderr, 0.1


def _verificar_size(path):
    p = Path(path)
    if not p.is_file() or p.stat().st_size == 0:
        raise media_integrity.MediaIntegrityError("no publicable")


@pytest.fixture
def env(monkeypatch):
    """NVENC disponible (mock), verificar_video = chequeo de tamano (sin ffprobe real)."""
    monkeypatch.setattr(ve, "detect_nvenc", lambda **k: _OK)
    monkeypatch.setattr(media_integrity, "verificar_video", _verificar_size)
    return monkeypatch


def _run_tracking(fake, out):
    return reframe.renderizar_reframe(Path("in.mp4"), [(0, 0, 1080, 1920)] * 3, out, 30.0, True)


def _run_stack(fake, out):
    return reframe.renderizar_stack(
        Path("in.mp4"), [(0, 0, 1080, 960), (0, 960, 1080, 960)], out, 30.0, True
    )


# ── 1-2: FFmpeg no escribe al final antes de validar ────────────────────────────
def test_1_tracking_no_escribe_al_final_antes_de_validar(env, tmp_path):
    out = tmp_path / "rf.mp4"
    fake = _FakePipe([0], [""])
    env.setattr(reframe, "_pipe_a_ffmpeg", fake)
    _run_tracking(fake, out)
    # El pipe recibio un temporal en .render_tmp, NUNCA el nombre final.
    assert fake.targets[0] != out
    assert fake.targets[0].parent.name == media_integrity.TEMP_DIRNAME
    assert out.exists()  # publicado tras verificar


def test_2_stack_no_escribe_al_final_antes_de_validar(env, tmp_path):
    out = tmp_path / "stk.mp4"
    fake = _FakePipe([0], [""])
    env.setattr(reframe, "_pipe_stack", fake)
    _run_stack(fake, out)
    assert fake.targets[0] != out
    assert fake.targets[0].parent.name == media_integrity.TEMP_DIRNAME


# ── 3-4: el final anterior sobrevive a fallos ───────────────────────────────────
def test_3_final_anterior_sobrevive_fallo_nvenc(env, tmp_path):
    out = tmp_path / "rf.mp4"
    out.write_bytes(b"OLD-VALID")
    # NVENC falla con error NO de init -> sin fallback -> RuntimeError; final intacto.
    fake = _FakePipe([1], [_INPUT_ERR], write=False)
    env.setattr(reframe, "_pipe_a_ffmpeg", fake)
    with pytest.raises(RuntimeError):
        _run_tracking(fake, out)
    assert out.read_bytes() == b"OLD-VALID"
    assert len(fake.targets) == 1  # no reintento


def test_4_final_anterior_sobrevive_nvenc_y_cpu(env, tmp_path):
    out = tmp_path / "rf.mp4"
    out.write_bytes(b"OLD-VALID")
    # auto: NVENC init falla -> fallback CPU tambien falla -> final intacto.
    fake = _FakePipe([1, 1], [_INIT_FAIL, _INPUT_ERR], write=False)
    env.setattr(reframe, "_pipe_a_ffmpeg", fake)
    with pytest.raises(RuntimeError):
        _run_tracking(fake, out)
    assert out.read_bytes() == b"OLD-VALID"
    assert len(fake.targets) == 2  # NVENC + CPU


# ── 5-6: el final se reemplaza tras verificar ───────────────────────────────────
def test_5_exito_nvenc_reemplaza_tras_verificar(env, tmp_path):
    out = tmp_path / "rf.mp4"
    out.write_bytes(b"OLD")
    fake = _FakePipe([0], [""])
    env.setattr(reframe, "_pipe_a_ffmpeg", fake)
    _run_tracking(fake, out)
    assert out.read_bytes().startswith(b"NEWDATA")  # publicado el nuevo
    assert "h264_nvenc" in fake.cmds[0]


def test_6_fallback_cpu_reemplaza_tras_verificar(env, tmp_path):
    out = tmp_path / "rf.mp4"
    out.write_bytes(b"OLD")
    fake = _FakePipe([1, 0], [_INIT_FAIL, ""])  # NVENC init falla, CPU ok
    env.setattr(reframe, "_pipe_a_ffmpeg", fake)
    _run_tracking(fake, out)
    assert out.read_bytes().startswith(b"NEWDATA")
    assert "h264_nvenc" in fake.cmds[0] and "libx264" in fake.cmds[1]


# ── 7: temporales distintos por intento ─────────────────────────────────────────
def test_7_intentos_usan_temporales_distintos(env, tmp_path):
    out = tmp_path / "rf.mp4"
    fake = _FakePipe([1, 0], [_INIT_FAIL, ""])
    env.setattr(reframe, "_pipe_a_ffmpeg", fake)
    _run_tracking(fake, out)
    assert fake.targets[0] != fake.targets[1]  # temporal NVENC != temporal CPU


# ── 8-9: temporales fallidos se eliminan ────────────────────────────────────────
def test_8_temporal_nvenc_fallido_se_elimina(env, tmp_path):
    out = tmp_path / "rf.mp4"
    fake = _FakePipe([1, 0], [_INIT_FAIL, ""])
    env.setattr(reframe, "_pipe_a_ffmpeg", fake)
    _run_tracking(fake, out)
    assert not fake.targets[0].exists()  # el temp NVENC fallido no queda
    tmpdir = tmp_path / media_integrity.TEMP_DIRNAME
    assert not tmpdir.exists() or not any(tmpdir.iterdir())


def test_9_temporal_cpu_fallido_se_elimina(env, tmp_path):
    out = tmp_path / "rf.mp4"
    fake = _FakePipe([1, 1], [_INIT_FAIL, _INPUT_ERR], write=False)
    env.setattr(reframe, "_pipe_a_ffmpeg", fake)
    with pytest.raises(RuntimeError):
        _run_tracking(fake, out)
    tmpdir = tmp_path / media_integrity.TEMP_DIRNAME
    assert not tmpdir.exists() or not any(tmpdir.iterdir())


# ── 10-12: reglas de fallback/probe ─────────────────────────────────────────────
def test_10_error_no_init_no_reintenta(env, tmp_path):
    out = tmp_path / "rf.mp4"
    fake = _FakePipe([1], [_INPUT_ERR], write=False)
    env.setattr(reframe, "_pipe_a_ffmpeg", fake)
    with pytest.raises(RuntimeError):
        _run_tracking(fake, out)
    assert len(fake.targets) == 1


def test_11_nvenc_explicito_no_reintenta(env, tmp_path):
    ve.set_default_mode("nvenc")
    out = tmp_path / "rf.mp4"
    fake = _FakePipe([1], [_INIT_FAIL], write=False)
    env.setattr(reframe, "_pipe_a_ffmpeg", fake)
    with pytest.raises(RuntimeError):
        _run_tracking(fake, out)
    assert len(fake.targets) == 1  # nvenc explicito NO cae a CPU


def test_12_cpu_no_ejecuta_probe_nvenc(monkeypatch, tmp_path):
    ve.set_default_mode("cpu")
    monkeypatch.setattr(media_integrity, "verificar_video", _verificar_size)

    def _boom(**k):
        raise AssertionError("cpu no debe invocar detect_nvenc")

    monkeypatch.setattr(ve, "detect_nvenc", _boom)
    out = tmp_path / "rf.mp4"
    fake = _FakePipe([0], [""])
    monkeypatch.setattr(reframe, "_pipe_a_ffmpeg", fake)
    _run_tracking(fake, out)
    assert "libx264" in fake.cmds[0] and "h264_nvenc" not in fake.cmds[0]


# ── 13: comandos, audio, FPS, faststart preservados ─────────────────────────────
def test_13_tracking_y_stack_conservan_comando(env, tmp_path):
    out = tmp_path / "rf.mp4"
    ft = _FakePipe([0], [""])
    env.setattr(reframe, "_pipe_a_ffmpeg", ft)
    _run_tracking(ft, out)
    cmd = ft.cmds[0]
    assert "+faststart" in cmd and cmd[cmd.index("-c:a") + 1] == "copy"
    assert cmd[cmd.index("-r") + 1] == "30.0"  # FPS
    assert f"{reframe.OUTPUT_W}x{reframe.OUTPUT_H}" in cmd  # resolucion del pipe

    out2 = tmp_path / "stk.mp4"
    fs = _FakePipe([0], [""])
    env.setattr(reframe, "_pipe_stack", fs)
    _run_stack(fs, out2)
    cmd2 = fs.cmds[0]
    assert "+faststart" in cmd2 and cmd2[cmd2.index("-c:a") + 1] == "copy"
