"""test_h3_preflight.py — Diagnostico central de entorno (H3, FASE 11.A).

Todo con dependencias INYECTADAS (version, ejecutable, which, import_probe, rutas de modelos):
sin tocar el entorno real, sin red, sin abrir puertos.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import model_assets
import system_preflight as sp

SUP = sp.SUPPORTED_PYTHON  # (3, 12)


def _which_todo(_n):
    return "C:/fake/bin/tool.exe"


def _which_nada(_n):
    return None


def _root_con_modelos(tmp_path: Path, *, yunet: bool, blazeface: bool) -> Path:
    """Crea un root sintetico con (o sin) cada modelo en su ruta relativa."""
    for d in sp.ESSENTIAL_DIRS:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    if yunet:
        p = tmp_path / model_assets.YUNET.rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"onnx-fake")
    if blazeface:
        p = tmp_path / model_assets.BLAZEFACE_SHORT.rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"tflite-fake")
    return tmp_path


def _report(
    tmp_path,
    *,
    version=None,
    executable=None,
    venv_dir=None,
    which=_which_todo,
    import_probe=lambda _m: True,
    yunet=True,
    blazeface=True,
    port=None,
    port_in_use=None,
):
    root = _root_con_modelos(tmp_path, yunet=yunet, blazeface=blazeface)
    venv_dir = venv_dir if venv_dir is not None else (root / "venv")
    executable = executable if executable is not None else str(venv_dir / "Scripts" / "python.exe")
    version = version if version is not None else (SUP[0], SUP[1], 5)
    return sp.check_environment(
        version=version,
        executable=executable,
        venv_dir=venv_dir,
        which=which,
        import_probe=import_probe,
        root=root,
        port=port,
        port_in_use=port_in_use,
    )


def _check(report, cid):
    return next(c for c in report["checks"] if c["id"] == cid)


# ── Python ─────────────────────────────────────────────────────────────────────
def test_python_soportado_exacto_ok(tmp_path):
    r = _report(tmp_path, version=(SUP[0], SUP[1], 10))
    assert _check(r, "python")["status"] == "ok"


def test_python_mismo_minor_distinto_patch_ok(tmp_path):
    r = _report(tmp_path, version=(SUP[0], SUP[1], 0))
    assert _check(r, "python")["status"] == "ok"


def test_python_no_soportado_bloquea(tmp_path):
    r = _report(tmp_path, version=(SUP[0], SUP[1] - 1, 9))
    assert _check(r, "python")["status"] == "error"
    assert r["status"] == "blocked"
    assert "py -3.12" in _check(r, "python")["action"]


# ── venv ───────────────────────────────────────────────────────────────────────
def test_venv_correcto_ok(tmp_path):
    r = _report(tmp_path)
    assert _check(r, "venv")["status"] == "ok"


def test_fuera_de_venv_bloquea(tmp_path):
    r = _report(tmp_path, executable="C:/Python312/python.exe")
    assert _check(r, "venv")["status"] == "error"
    assert r["status"] == "blocked"


# ── ffmpeg / ffprobe ───────────────────────────────────────────────────────────
def test_ffmpeg_ffprobe_disponibles_ready(tmp_path):
    r = _report(tmp_path, which=_which_todo)
    assert r["status"] == "ready"
    assert r["capabilities"]["render"]["available"] is True


def test_falta_ffmpeg_degradado_no_bloquea(tmp_path):
    r = _report(tmp_path, which=lambda n: None if n == "ffmpeg" else "x")
    assert _check(r, "ffmpeg")["status"] == "warning"
    assert r["status"] == "degraded"
    assert r["capabilities"]["render"]["available"] is False
    assert r["capabilities"]["upload_validation"]["available"] is True  # ffprobe sigue


def test_falta_ffprobe_degradado(tmp_path):
    r = _report(tmp_path, which=lambda n: None if n == "ffprobe" else "x")
    assert _check(r, "ffprobe")["status"] == "warning"
    assert r["status"] == "degraded"
    assert r["capabilities"]["upload_validation"]["available"] is False


# ── modelos ────────────────────────────────────────────────────────────────────
def test_falta_yunet_pero_existe_blazeface_reframe_disponible(tmp_path):
    r = _report(tmp_path, yunet=False, blazeface=True)
    assert _check(r, "model_yunet")["status"] == "warning"
    assert r["capabilities"]["reframe"]["available"] is True
    assert r["capabilities"]["detector_blazeface"]["available"] is True


def test_falta_blazeface_pero_existe_yunet_reframe_disponible(tmp_path):
    r = _report(tmp_path, yunet=True, blazeface=False)
    assert r["capabilities"]["reframe"]["available"] is True


def test_faltan_ambos_reframe_no_disponible_pero_no_bloquea(tmp_path):
    r = _report(tmp_path, yunet=False, blazeface=False)
    assert r["capabilities"]["reframe"]["available"] is False
    assert r["status"] == "degraded"  # NUNCA blocked por modelos


# ── imports criticos ───────────────────────────────────────────────────────────
def test_import_critico_ausente_bloquea(tmp_path):
    r = _report(tmp_path, import_probe=lambda m: m != "uvicorn")
    assert _check(r, "imports")["status"] == "error"
    assert r["status"] == "blocked"


# ── ready / degraded / blocked ─────────────────────────────────────────────────
def test_todo_ok_ready(tmp_path):
    assert _report(tmp_path)["status"] == "ready"


# ── puerto ─────────────────────────────────────────────────────────────────────
def test_puerto_ocupado_es_warning_no_bloquea(tmp_path):
    r = _report(tmp_path, port=("127.0.0.1", 8787), port_in_use=lambda h, p: True)
    assert _check(r, "port")["status"] == "warning"
    assert r["status"] == "degraded"  # puerto no es fatal


def test_puerto_libre_ok(tmp_path):
    r = _report(tmp_path, port=("127.0.0.1", 8787), port_in_use=lambda h, p: False)
    assert _check(r, "port")["status"] == "ok"


# ── Privacidad: rutas relativas, sin secretos ni paths absolutos ───────────────
def test_salida_publica_sin_paths_absolutos_ni_secretos(tmp_path):
    r = _report(
        tmp_path,
        yunet=False,
        blazeface=False,
        which=lambda n: None,
        executable="C:/Python312/python.exe",
        version=(SUP[0], SUP[1] - 1, 0),
    )
    blob = json.dumps(r, ensure_ascii=False)
    # No debe filtrar la ruta absoluta del root sintetico ni el ejecutable absoluto.
    assert str(tmp_path) not in blob
    assert "C:/Python312/python.exe" not in blob and "C:\\Python312" not in blob
    # Rutas de modelos SIEMPRE relativas.
    assert model_assets.YUNET.rel_path in blob
    assert not any(":" in c["message"][:3] for c in r["checks"])  # sin "C:\\..." al inicio


def test_strict_local_falla_si_falta_capacidad(tmp_path):
    r = _report(tmp_path, which=lambda n: None)  # sin ffmpeg/ffprobe
    ok, motivos = sp._strict_local_ok(r)
    assert ok is False and motivos


def test_strict_local_ok_entorno_completo(tmp_path):
    r = _report(tmp_path)
    ok, motivos = sp._strict_local_ok(r)
    assert ok is True and motivos == []


@pytest.mark.parametrize("cid", ["python", "venv", "imports", "ffmpeg", "ffprobe"])
def test_cada_check_tiene_contrato(tmp_path, cid):
    c = _check(_report(tmp_path), cid)
    assert set(c) == {"id", "status", "required_for", "message", "action"}
    assert c["status"] in ("ok", "warning", "error")
