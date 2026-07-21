"""test_h3_models.py — Modelos de deteccion e instalador reproducible (H3, FASE 11.C).

Sin red real: `fetch` y el opener de urllib se inyectan/parchean. El downloader se prueba con
bytes sinteticos cuyo SHA256 conocemos; NO se descarga ningun modelo real.
"""

from __future__ import annotations

import hashlib

import pytest

import model_assets
import model_setup
import reframe_detect


def _asset(tmp_path, data: bytes, rel="models/fake.bin") -> model_assets.ModelAsset:
    return model_assets.ModelAsset(
        id="fake",
        rel_path=rel,
        detector="blazeface",
        required=True,
        url="https://example.com/fake.bin",
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        install_hint="setup",
    )


# ── reframe_detect: fallback y error accionable ────────────────────────────────
def test_mensaje_sin_detector_incluye_setup_y_rutas_relativas():
    msg = reframe_detect._mensaje_sin_detector()
    assert "setup_models.py" in msg
    assert model_assets.YUNET.rel_path in msg
    assert ":\\" not in msg and "C:/" not in msg  # sin rutas absolutas


def test_ambos_ausentes_lanza_detector_unavailable(monkeypatch, tmp_path):
    ausente = tmp_path / "no_existe.tflite"
    monkeypatch.setattr(reframe_detect, "ACTIVE_MODEL_PATH", ausente)
    with pytest.raises(reframe_detect.DetectorUnavailable):
        reframe_detect._crear_detector_blazeface()


def test_detector_blazeface_explicito_ausente_no_cae_a_yunet(monkeypatch, tmp_path):
    # YuNet presente, pero se pide blazeface explicito y falta -> DetectorUnavailable (no yunet)
    monkeypatch.setattr(reframe_detect, "ACTIVE_MODEL_PATH", tmp_path / "no.tflite")
    monkeypatch.setattr(reframe_detect, "YUNET_MODEL_PATH", tmp_path / "si.onnx")
    (tmp_path / "si.onnx").write_bytes(b"onnx")
    with pytest.raises(reframe_detect.DetectorUnavailable):
        reframe_detect._crear_detector("blazeface")


def test_yunet_ausente_cae_a_blazeface(monkeypatch, tmp_path):
    # YuNet ausente + BlazeFace presente -> intenta crear blazeface (llega a importar mediapipe).
    monkeypatch.setattr(reframe_detect, "YUNET_MODEL_PATH", tmp_path / "no.onnx")
    bf = tmp_path / "bf.tflite"
    bf.write_bytes(b"tflite")
    llamado = {}

    def _fake_bf(model_path=None):
        llamado["bf"] = True
        return "blaze-detector"

    monkeypatch.setattr(reframe_detect, "_crear_detector_blazeface", _fake_bf)
    assert reframe_detect._crear_detector("yunet") == "blaze-detector"
    assert llamado.get("bf") is True


# ── Downloader: hash ───────────────────────────────────────────────────────────
def test_install_model_hash_correcto_publica(tmp_path):
    data = b"modelo-de-prueba"
    asset = _asset(tmp_path, data)
    dest = model_setup.install_model(asset, fetch=lambda *a, **k: data, root=tmp_path)
    assert dest.read_bytes() == data


def test_install_model_hash_incorrecto_no_escribe(tmp_path):
    data = b"contenido"
    asset = _asset(tmp_path, data)
    with pytest.raises(model_setup.ModelSetupError):
        model_setup.install_model(asset, fetch=lambda *a, **k: b"OTRO", root=tmp_path)
    assert not asset.path(tmp_path).exists()


def test_install_model_preserva_modelo_anterior_ante_hash_malo(tmp_path):
    data = b"nuevo"
    asset = _asset(tmp_path, data)
    dest = asset.path(tmp_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"MODELO-ANTERIOR-BUENO")
    with pytest.raises(model_setup.ModelSetupError):
        model_setup.install_model(asset, fetch=lambda *a, **k: b"corrupto", root=tmp_path)
    assert dest.read_bytes() == b"MODELO-ANTERIOR-BUENO"  # intacto


def test_install_model_descarga_parcial_falla_por_hash(tmp_path):
    data = b"0123456789"
    asset = _asset(tmp_path, data)
    with pytest.raises(model_setup.ModelSetupError):
        model_setup.install_model(asset, fetch=lambda *a, **k: data[:5], root=tmp_path)
    assert not asset.path(tmp_path).exists()


def test_install_model_timeout_o_red_propaga(tmp_path):
    asset = _asset(tmp_path, b"x")

    def _boom(*a, **k):
        raise model_setup.ModelSetupError("timeout")

    with pytest.raises(model_setup.ModelSetupError):
        model_setup.install_model(asset, fetch=_boom, root=tmp_path)


# ── publish_bytes: cleanup ─────────────────────────────────────────────────────
def test_publish_bytes_cleanup_sin_temporales(monkeypatch, tmp_path):
    dest = tmp_path / "sub" / "m.bin"

    def _replace_boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(model_setup.os, "replace", _replace_boom)
    with pytest.raises(model_setup.ModelSetupError):
        model_setup.publish_bytes(dest, b"data")
    # No debe quedar ningun .part
    assert not list((tmp_path / "sub").glob("*.part"))


# ── _fetch: esquema y tope de bytes ────────────────────────────────────────────
def test_fetch_esquema_no_http_rechazado(tmp_path):
    with pytest.raises(model_setup.ModelSetupError):
        model_setup._fetch("file:///etc/passwd", timeout=1, max_bytes=100)


def test_fetch_oversize_aborta(monkeypatch):
    class _Resp:
        def __init__(self):
            self._chunks = [b"x" * 40, b"y" * 40, b"z" * 40]

        def read(self, _n):
            return self._chunks.pop(0) if self._chunks else b""

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _Opener:
        def open(self, _req, timeout=None):
            return _Resp()

    monkeypatch.setattr(model_setup.urllib.request, "build_opener", lambda *a: _Opener())
    with pytest.raises(model_setup.ModelSetupError):
        model_setup._fetch("https://example.com/x", timeout=1, max_bytes=50)


def test_redirect_a_esquema_no_web_rechazado():
    handler = model_setup._SafeRedirectHandler()
    with pytest.raises(model_setup.ModelSetupError):
        handler.redirect_request(None, None, 302, "Found", {}, "ftp://evil/model")


# ── install_all: no descarga lo ya presente ni ejecuta red innecesaria ─────────
def test_install_all_no_descarga_lo_presente(tmp_path):
    # crea ambos modelos reales-por-tamano en sus rutas
    for m in model_assets.MODELS:
        p = tmp_path / m.rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"presente")
    llamadas = {"n": 0}

    def _spy(*a, **k):
        llamadas["n"] += 1
        return b""

    res = model_setup.install_all(fetch=_spy, root=tmp_path)
    assert all(r == "ya-presente" for _id, r in res)
    assert llamadas["n"] == 0  # cero red


def test_urls_oficiales_son_https():
    for m in model_assets.MODELS:
        assert m.url.startswith("https://")
        assert len(m.sha256) == 64
