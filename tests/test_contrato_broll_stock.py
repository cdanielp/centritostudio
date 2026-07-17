"""Tests de contrato del fetcher de imagenes Pexels (feat/broll-pexels-images).

NINGUN test toca la red: broll_stock.requests.get se stubea siempre. Nunca se usa una
key real. Las caches de busqueda/archivo se redirigen a tmp_path para no tocar el repo.

Cobertura (25 casos del brief + 10 ordenes de variante):
config sin key, Authorization sin filtrar, query codificada, orientaciones, per_page,
parseo, cero resultados, 401, 429, timeout, JSON invalido, seleccion de variante (9
ordenes + error), descarga, escritura atomica, reuso de cache, archivo vacio, Content-Type
invalido, firma de bytes, sidecar completo/sin key, nombres estables, cache de busqueda
(hit/expira/corrupta/normalizacion), compatibilidad Windows, y sin red real.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import broll_stock as bs
import broll_stock_base as bbase

# ── Dobles de red (jamas se contacta Pexels) ──────────────────────────────────


class FakeResp:
    """Respuesta HTTP minima para stubear requests.get."""

    def __init__(self, status=200, payload=None, headers=None, content=b""):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._payload = payload
        self.headers = headers or {}
        self.content = content

    def json(self):
        if self._payload is None:
            raise ValueError("body no es JSON")
        return self._payload


def _foto(pid=101, w=1280, h=1920, src=None):
    """Objeto foto estilo Pexels."""
    return {
        "id": pid,
        "width": w,
        "height": h,
        "url": f"https://www.pexels.com/photo/{pid}/",
        "photographer": "Ana Perez",
        "photographer_url": "https://www.pexels.com/@anaperez",
        "alt": "gato en la ventana",
        "src": src
        or {
            "original": f"https://images.pexels.com/photos/{pid}/orig.jpg",
            "large2x": f"https://images.pexels.com/photos/{pid}/l2x.jpg?w=1880",
            "large": f"https://images.pexels.com/photos/{pid}/l.jpg?w=1170",
            "portrait": f"https://images.pexels.com/photos/{pid}/p.jpg?w=800&h=1200",
            "landscape": f"https://images.pexels.com/photos/{pid}/land.jpg?w=1200&h=627",
        },
    }


@pytest.fixture(autouse=True)
def _entorno_limpio(monkeypatch, tmp_path):
    """Key de prueba + caches redirigidas a tmp + red bloqueada por default."""
    monkeypatch.setenv("PEXELS_API_KEY", "test-key-123")
    monkeypatch.setattr(bbase, "CACHE_ROOT", tmp_path / "cache")
    monkeypatch.setattr(bbase, "SEARCH_CACHE_DIR", tmp_path / "cache" / "_search")

    def _boom(*a, **k):
        raise AssertionError("ningun test debe tocar la red real")

    monkeypatch.setattr(bs.requests, "get", _boom)
    return tmp_path


def _stub_get(monkeypatch, resp, capture=None):
    """Reemplaza requests.get por una funcion que registra la llamada y devuelve resp."""

    def fake_get(url, headers=None, params=None, timeout=None):
        if capture is not None:
            capture["url"] = url
            capture["headers"] = headers
            capture["params"] = params
            capture["timeout"] = timeout
            capture["llamadas"] = capture.get("llamadas", 0) + 1
        return resp

    monkeypatch.setattr(bs.requests, "get", fake_get)


# ── 1. Config: API key ausente ────────────────────────────────────────────────


def test_sin_api_key_estado_deshabilitado(monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    assert bs.tiene_api_key() is False
    assert bs.estado_pexels()["habilitado"] is False


def test_sin_api_key_buscar_lanza_tipado(monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    with pytest.raises(bs.PexelsDeshabilitado):
        bs.buscar_imagenes_pexels("gatos", usar_cache=False)


def test_sin_api_key_seguro_error_tipado(monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    r = bs.buscar_broll_seguro("gatos", usar_cache=False)
    assert r.assets == ()
    assert r.error is not None and r.error.code == "deshabilitado"


# ── 2. Request lleva Authorization y NO filtra la key ─────────────────────────


def test_request_manda_authorization_sin_filtrar(monkeypatch):
    cap = {}
    _stub_get(monkeypatch, FakeResp(200, {"photos": [_foto()]}), cap)
    bs.buscar_imagenes_pexels("gatos", usar_cache=False)
    assert cap["headers"]["Authorization"] == "test-key-123"
    assert cap["timeout"] == bs.TIMEOUT_S
    # La key jamas debe aparecer serializada en el estado ni en mensajes.
    assert "test-key-123" not in json.dumps(bs.estado_pexels())


def test_mensaje_de_error_saneado_nunca_expone_key():
    filtrado = bs._sanitizar("fallo con test-key-123 adentro")
    assert "test-key-123" not in filtrado and "***" in filtrado


# ── 3. Query codificada correctamente (via params de requests) ────────────────


def test_query_va_en_params(monkeypatch):
    cap = {}
    _stub_get(monkeypatch, FakeResp(200, {"photos": []}), cap)
    bs.buscar_imagenes_pexels("cafe de especialidad", usar_cache=False)
    assert cap["params"]["query"] == "cafe de especialidad"
    assert cap["url"] == bs.SEARCH_URL


# ── 4-5. Orientacion vertical / horizontal ────────────────────────────────────


def test_orientacion_portrait_en_params(monkeypatch):
    cap = {}
    _stub_get(monkeypatch, FakeResp(200, {"photos": []}), cap)
    bs.buscar_imagenes_pexels("montana", orientation="portrait", usar_cache=False)
    assert cap["params"]["orientation"] == "portrait"


def test_orientacion_landscape_en_params(monkeypatch):
    cap = {}
    _stub_get(monkeypatch, FakeResp(200, {"photos": []}), cap)
    bs.buscar_imagenes_pexels("montana", orientation="landscape", usar_cache=False)
    assert cap["params"]["orientation"] == "landscape"


def test_orientacion_invalida_rechazada(monkeypatch):
    _stub_get(monkeypatch, FakeResp(200, {"photos": []}))
    with pytest.raises(ValueError):
        bs.buscar_imagenes_pexels("x", orientation="diagonal", usar_cache=False)


# ── 6. Limite de per_page ─────────────────────────────────────────────────────


def test_per_page_se_limita(monkeypatch):
    cap = {}
    _stub_get(monkeypatch, FakeResp(200, {"photos": []}), cap)
    bs.buscar_imagenes_pexels("x", per_page=9999, usar_cache=False)
    assert cap["params"]["per_page"] == bs.PER_PAGE_MAX
    bs.buscar_imagenes_pexels("x", per_page=0, page=0, usar_cache=False)
    assert cap["params"]["per_page"] == bs.PER_PAGE_MIN
    assert cap["params"]["page"] == 1


def test_query_vacio_rechazado(monkeypatch):
    _stub_get(monkeypatch, FakeResp(200, {"photos": []}))
    with pytest.raises(ValueError):
        bs.buscar_imagenes_pexels("   ", usar_cache=False)


# ── 7. Parseo correcto de respuesta ───────────────────────────────────────────


def test_parseo_a_stockasset(monkeypatch):
    _stub_get(monkeypatch, FakeResp(200, {"photos": [_foto(pid=55, w=1280, h=1920)]}))
    assets = bs.buscar_imagenes_pexels("gatos", usar_cache=False)
    a = assets[0]
    assert a.provider == "pexels"
    assert a.asset_id == "55"
    assert a.orientation == "portrait"
    assert a.author == "Ana Perez"
    assert a.author_url.endswith("anaperez")
    assert a.source_url.endswith("/55/")
    assert a.alt == "gato en la ventana"
    assert a.media_type == "image"
    # Candidato sin descargar: rutas None (nunca strings vacios).
    assert a.local_path is None and a.metadata_path is None
    assert a.download_url.endswith("orig.jpg")


# ── 8. Respuesta sin resultados = exito valido ────────────────────────────────


def test_cero_resultados_no_es_error(monkeypatch):
    _stub_get(monkeypatch, FakeResp(200, {"photos": []}))
    assert bs.buscar_imagenes_pexels("noexiste", usar_cache=False) == []
    r = bs.buscar_broll_seguro("noexiste", usar_cache=False)
    assert r.error is None and r.assets == ()


# ── 9. HTTP 401 ───────────────────────────────────────────────────────────────


def test_http_401_lanza_auth(monkeypatch):
    _stub_get(monkeypatch, FakeResp(401))
    with pytest.raises(bs.PexelsAuthError):
        bs.buscar_imagenes_pexels("x", usar_cache=False)
    _stub_get(monkeypatch, FakeResp(401))
    r = bs.buscar_broll_seguro("x", usar_cache=False)
    assert r.error.code == "auth"


# ── 10. HTTP 429 (sin reintento, sin sleep) ───────────────────────────────────


def test_http_429_no_reintenta_conserva_retry_after(monkeypatch):
    cap = {}
    _stub_get(monkeypatch, FakeResp(429, headers={"Retry-After": "30"}), cap)
    dormido = {"n": 0}
    monkeypatch.setattr(time, "sleep", lambda s: dormido.__setitem__("n", dormido["n"] + 1))
    with pytest.raises(bs.PexelsRateLimit) as exc:
        bs.buscar_imagenes_pexels("x", usar_cache=False)
    assert exc.value.retry_after == 30
    assert cap["llamadas"] == 1  # un solo request, sin reintento
    assert dormido["n"] == 0  # jamas durmio


def test_http_429_seguro_permite_continuar(monkeypatch):
    _stub_get(monkeypatch, FakeResp(429, headers={"Retry-After": "12"}))
    r = bs.buscar_broll_seguro("x", usar_cache=False)
    assert r.error.code == "rate_limit"
    assert r.error.retry_after == 12
    assert r.assets == ()


def test_seguro_propaga_errores_de_programacion(monkeypatch):
    # buscar_broll_seguro solo atrapa PexelsError; un RuntimeError interno debe PROPAGARSE.
    def _boom(*a, **k):
        raise RuntimeError("bug interno, no operativo")

    monkeypatch.setattr(bs, "_buscar_con_rate", _boom)
    with pytest.raises(RuntimeError):
        bs.buscar_broll_seguro("gatos", usar_cache=False)


# ── 11. Timeout ───────────────────────────────────────────────────────────────


def test_timeout_lanza_tipado(monkeypatch):
    def _timeout(*a, **k):
        raise bs.requests.Timeout("lento")

    monkeypatch.setattr(bs.requests, "get", _timeout)
    with pytest.raises(bs.PexelsTimeout):
        bs.buscar_imagenes_pexels("x", usar_cache=False)
    r = bs.buscar_broll_seguro("x", usar_cache=False)
    assert r.error.code == "timeout"


# ── 12. JSON invalido ─────────────────────────────────────────────────────────


def test_json_invalido_lanza_tipado(monkeypatch):
    _stub_get(monkeypatch, FakeResp(200, payload=None))  # .json() lanza ValueError
    with pytest.raises(bs.PexelsRespuestaInvalida):
        bs.buscar_imagenes_pexels("x", usar_cache=False)


def test_json_sin_photos_lanza_tipado(monkeypatch):
    _stub_get(monkeypatch, FakeResp(200, {"otra_cosa": 1}))
    with pytest.raises(bs.PexelsRespuestaInvalida):
        bs.buscar_imagenes_pexels("x", usar_cache=False)


# ── 13-15 + ordenes de variante (10 casos deterministas) ──────────────────────

_SRC_COMPLETO = {
    "large2x": "u_l2x",
    "original": "u_orig",
    "large": "u_large",
    "portrait": "u_port",
    "landscape": "u_land",
}


def test_variante_1_contain_large2x():
    sel = bs.seleccionar_variante(_SRC_COMPLETO, destino="vertical", fit="contain")
    assert sel.nombre == "large2x" and sel.url == "u_l2x" and sel.motivo


def test_variante_2_contain_cae_a_original():
    src = {k: v for k, v in _SRC_COMPLETO.items() if k != "large2x"}
    sel = bs.seleccionar_variante(src, destino="vertical", fit="contain")
    assert sel.nombre == "original"


def test_variante_3_contain_cae_a_large():
    src = {"large": "u_large", "portrait": "u_port"}
    sel = bs.seleccionar_variante(src, destino="vertical", fit="contain")
    assert sel.nombre == "large"


def test_variante_4_cover_vertical_large2x():
    sel = bs.seleccionar_variante(_SRC_COMPLETO, destino="vertical", fit="cover")
    assert sel.nombre == "large2x"


def test_variante_5_cover_vertical_cae_a_original():
    src = {k: v for k, v in _SRC_COMPLETO.items() if k != "large2x"}
    sel = bs.seleccionar_variante(src, destino="vertical", fit="cover")
    assert sel.nombre == "original"


def test_variante_6_cover_vertical_cae_a_portrait():
    src = {"portrait": "u_port", "landscape": "u_land", "large": "u_large"}
    sel = bs.seleccionar_variante(src, destino="vertical", fit="cover")
    assert sel.nombre == "portrait"


def test_variante_7_cover_horizontal_large2x():
    sel = bs.seleccionar_variante(_SRC_COMPLETO, destino="horizontal", fit="cover")
    assert sel.nombre == "large2x"


def test_variante_8_cover_horizontal_cae_a_original():
    src = {k: v for k, v in _SRC_COMPLETO.items() if k != "large2x"}
    sel = bs.seleccionar_variante(src, destino="horizontal", fit="cover")
    assert sel.nombre == "original"


def test_variante_9_cover_horizontal_cae_a_landscape():
    src = {"portrait": "u_port", "landscape": "u_land", "large": "u_large"}
    sel = bs.seleccionar_variante(src, destino="horizontal", fit="cover")
    assert sel.nombre == "landscape"


def test_variante_10_sin_variantes_error_tipado():
    with pytest.raises(bs.PexelsSinVariante):
        bs.seleccionar_variante({"medium": "x", "small": "y"}, destino="vertical", fit="cover")


def test_variante_fit_o_destino_invalido():
    with pytest.raises(ValueError):
        bs.seleccionar_variante(_SRC_COMPLETO, destino="vertical", fit="raro")
    with pytest.raises(ValueError):
        bs.seleccionar_variante(_SRC_COMPLETO, destino="diagonal", fit="cover")


# ── Firmas de bytes de imagenes (para descargas de prueba) ────────────────────

_JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
_WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 32
_NO_IMG = b"<html>no soy imagen</html>"


def _stub_download(monkeypatch, content, headers=None, status=200):
    resp = FakeResp(status, headers=headers or {"Content-Type": "image/jpeg"}, content=content)

    def fake_get(url, headers=None, params=None, timeout=None):
        return resp

    monkeypatch.setattr(bs.requests, "get", fake_get)


def _stub_download_count(monkeypatch, content, headers=None):
    """Como _stub_download pero cuenta cuantas descargas se hicieron (cap['n'])."""
    resp = FakeResp(200, headers=headers or {"Content-Type": "image/jpeg"}, content=content)
    cap = {"n": 0}

    def fake_get(url, headers=None, params=None, timeout=None):
        cap["n"] += 1
        return resp

    monkeypatch.setattr(bs.requests, "get", fake_get)
    return cap


def _asset_para_descarga(pid=77):
    return bs._asset_desde_foto(_foto(pid=pid), "gatos")


def _asset_sin_top(pid=200):
    """Asset cuyo src NO tiene large2x ni original: fuerza los fallbacks orientados."""
    src = {"large": f"u_large_{pid}", "portrait": f"u_port_{pid}", "landscape": f"u_land_{pid}"}
    return bs._asset_desde_foto(_foto(pid=pid, src=src), "gatos")


# ── 16. Descarga correcta + 21/22. Sidecar completo/sin key ───────────────────


def test_descarga_correcta_y_sidecar(monkeypatch, tmp_path):
    _stub_download(monkeypatch, _JPG)
    a = _asset_para_descarga(pid=77)
    out = bs.descargar_asset(a, cache_dir=tmp_path, destino="vertical", fit="cover")
    assert out.local_path is not None and out.local_path.exists()
    assert out.local_path.read_bytes() == _JPG
    assert out.metadata_path is not None and out.metadata_path.exists()
    # download_url quedo en la variante elegida (large2x por resolucion).
    assert out.download_url.endswith("l2x.jpg?w=1880")
    assert out.selected_variant == "large2x"
    assert out.selection_reason and "large2x" in out.selection_reason
    side = json.loads(out.metadata_path.read_text(encoding="utf-8"))
    for campo in (
        "provider",
        "provider_url",
        "asset_id",
        "query",
        "author",
        "author_url",
        "source_url",
        "attribution_text",
        "downloaded_utc",
        "last_used_utc",
        "sidecar_version",
        "width",
        "height",
        "selected_variant",
        "selection_reason",
        "download_url",
    ):
        assert campo in side
    assert side["selected_variant"] == "large2x"
    assert side["download_url"] == out.download_url
    assert side["provider_url"] == bbase.PROVIDER_URL
    assert side["attribution_text"] == "Photo by Ana Perez on Pexels"
    assert side["licencia"]["uso_comercial"] is True
    assert side["licencia"]["uso_en_datasets_o_entrenamiento_ia"] is False
    # El sidecar JAMAS contiene la API key.
    assert "test-key-123" not in out.metadata_path.read_text(encoding="utf-8")


# ── 17. Escritura atomica (no quedan .tmp) ────────────────────────────────────


def test_escritura_atomica_sin_temporales(monkeypatch, tmp_path):
    _stub_download(monkeypatch, _PNG)
    bs.descargar_asset(_asset_para_descarga(pid=88), cache_dir=tmp_path)
    assert list(tmp_path.glob("*.tmp")) == []
    assert (tmp_path / "pexels_88_large2x.png").exists()


# ── 18. Reuso de cache (no re-descarga) ───────────────────────────────────────


def test_reuso_de_cache_no_redescarga(monkeypatch, tmp_path):
    _stub_download(monkeypatch, _JPG)
    a = _asset_para_descarga(pid=99)
    bs.descargar_asset(a, cache_dir=tmp_path)

    def _boom(*args, **kwargs):
        raise AssertionError("no debe descargar de nuevo si ya esta cacheado")

    monkeypatch.setattr(bs.requests, "get", _boom)
    out = bs.descargar_asset(a, cache_dir=tmp_path)
    assert out.local_path == tmp_path / "pexels_99_large2x.jpg"
    assert out.metadata_path == tmp_path / "pexels_99_large2x.json"


def test_sidecar_faltante_no_es_cache_hit_redescarga(monkeypatch, tmp_path):
    cap = _stub_download_count(monkeypatch, _JPG)
    a = _asset_para_descarga(pid=111)
    out = bs.descargar_asset(a, cache_dir=tmp_path)
    assert cap["n"] == 1
    out.metadata_path.unlink()  # imagen queda, sidecar desaparece -> NO es cache hit
    reparado = bs.descargar_asset(a, cache_dir=tmp_path)
    assert cap["n"] == 2  # sin sidecar valido se vuelve a descargar
    assert reparado.metadata_path.exists()
    side = json.loads(reparado.metadata_path.read_text(encoding="utf-8"))
    assert side["asset_id"] == "111"


# ── 19. Archivo vacio rechazado ───────────────────────────────────────────────


def test_descarga_vacia_rechazada(monkeypatch, tmp_path):
    _stub_download(monkeypatch, b"")
    with pytest.raises(bs.PexelsDescargaError):
        bs.descargar_asset(_asset_para_descarga(), cache_dir=tmp_path)
    assert list(tmp_path.glob("pexels_*")) == []


# ── 20. Content-Type invalido / contenido no imagen ───────────────────────────


def test_content_type_no_imagen_rechazado(monkeypatch, tmp_path):
    _stub_download(monkeypatch, _JPG, headers={"Content-Type": "text/html"})
    with pytest.raises(bs.PexelsDescargaError):
        bs.descargar_asset(_asset_para_descarga(), cache_dir=tmp_path)


def test_content_type_ausente_usa_firma_de_bytes(monkeypatch, tmp_path):
    # Sin Content-Type: la firma decide la extension (webp aqui).
    _stub_download(monkeypatch, _WEBP, headers={})
    out = bs.descargar_asset(_asset_para_descarga(pid=123), cache_dir=tmp_path)
    assert out.local_path.suffix == ".webp"


def test_contenido_no_reconocido_rechazado(monkeypatch, tmp_path):
    _stub_download(monkeypatch, _NO_IMG, headers={})
    with pytest.raises(bs.PexelsDescargaError):
        bs.descargar_asset(_asset_para_descarga(), cache_dir=tmp_path)


# ── 23. Nombres de archivo estables (incluyen la variante) + Windows-safe ─────


def test_nombre_estable_por_provider_id_y_variante():
    a = _asset_para_descarga(pid=555)
    s1 = bbase._stem_cache(a, "large2x")
    s2 = bbase._stem_cache(a, "large2x")
    assert s1 == s2 == "pexels_555_large2x"  # determinista
    assert bbase._stem_cache(a, "portrait") != s1  # otra variante -> otro nombre
    # Sin separadores de ruta ni caracteres invalidos en Windows.
    assert not any(c in s1 for c in '\\/:*?"<>|')


# ── Identidad de cache por variante (bug de colision corregido) ───────────────


def test_mismo_id_variante_distinta_genera_archivos_distintos(monkeypatch, tmp_path):
    _stub_download(monkeypatch, _JPG)
    a = _asset_sin_top(pid=301)
    v = bs.descargar_asset(a, cache_dir=tmp_path, destino="vertical", fit="cover")
    h = bs.descargar_asset(a, cache_dir=tmp_path, destino="horizontal", fit="cover")
    assert v.selected_variant == "portrait" and h.selected_variant == "landscape"
    assert v.local_path.name == "pexels_301_portrait.jpg"
    assert h.local_path.name == "pexels_301_landscape.jpg"
    assert v.local_path != h.local_path
    assert v.local_path.exists() and h.local_path.exists()
    assert v.metadata_path.name == "pexels_301_portrait.json"


def test_fallbacks_orientados_no_colisionan(monkeypatch, tmp_path):
    # contain->large, cover vertical->portrait, cover horizontal->landscape: 3 archivos distintos.
    _stub_download(monkeypatch, _JPG)
    a = _asset_sin_top(pid=302)
    c = bs.descargar_asset(a, cache_dir=tmp_path, destino="vertical", fit="contain")
    v = bs.descargar_asset(a, cache_dir=tmp_path, destino="vertical", fit="cover")
    h = bs.descargar_asset(a, cache_dir=tmp_path, destino="horizontal", fit="cover")
    variantes = {c.selected_variant, v.selected_variant, h.selected_variant}
    assert variantes == {"large", "portrait", "landscape"}
    rutas = {c.local_path, v.local_path, h.local_path}
    assert len(rutas) == 3  # ninguna colision
    assert all(p.exists() for p in rutas)


def test_misma_variante_reutiliza_cache(monkeypatch, tmp_path):
    cap = _stub_download_count(monkeypatch, _JPG)
    a = _asset_para_descarga(pid=303)
    bs.descargar_asset(a, cache_dir=tmp_path, destino="vertical", fit="cover")
    bs.descargar_asset(a, cache_dir=tmp_path, destino="vertical", fit="cover")
    assert cap["n"] == 1  # segunda vez = cache hit, no re-descarga


def test_sidecar_variante_distinta_no_es_cache_hit(monkeypatch, tmp_path):
    cap = _stub_download_count(monkeypatch, _JPG)
    a = _asset_para_descarga(pid=400)
    bs.descargar_asset(a, cache_dir=tmp_path)  # variante large2x, n==1
    sc = tmp_path / "pexels_400_large2x.json"
    obj = json.loads(sc.read_text(encoding="utf-8"))
    obj["selected_variant"] = "portrait"  # sidecar dice otra variante
    sc.write_text(json.dumps(obj), encoding="utf-8")
    bs.descargar_asset(a, cache_dir=tmp_path)
    assert cap["n"] == 2  # desajuste de variante -> NO hit, re-descarga
    assert json.loads(sc.read_text(encoding="utf-8"))["selected_variant"] == "large2x"


def test_sidecar_download_url_distinta_no_es_cache_hit(monkeypatch, tmp_path):
    cap = _stub_download_count(monkeypatch, _JPG)
    a = _asset_para_descarga(pid=401)
    bs.descargar_asset(a, cache_dir=tmp_path)  # n==1
    sc = tmp_path / "pexels_401_large2x.json"
    obj = json.loads(sc.read_text(encoding="utf-8"))
    obj["download_url"] = "https://images.pexels.com/otra/url.jpg"
    sc.write_text(json.dumps(obj), encoding="utf-8")
    bs.descargar_asset(a, cache_dir=tmp_path)
    assert cap["n"] == 2  # url distinta -> NO hit, re-descarga


def test_cache_hit_refresca_sidecar_preserva_downloaded(monkeypatch, tmp_path):
    cap = _stub_download_count(monkeypatch, _JPG)
    a = bs._asset_desde_foto(_foto(pid=500), "gatos")
    bs.descargar_asset(a, cache_dir=tmp_path, ahora_utc="2020-01-01T00:00:00Z")
    assert cap["n"] == 1
    sc = tmp_path / "pexels_500_large2x.json"
    obj0 = json.loads(sc.read_text(encoding="utf-8"))
    assert obj0["downloaded_utc"] == "2020-01-01T00:00:00Z"
    assert obj0["last_used_utc"] == "2020-01-01T00:00:00Z"
    assert obj0["query"] == "gatos"
    # Mismo asset + misma variante + query distinta -> cache hit (no re-descarga).
    a2 = bs._asset_desde_foto(_foto(pid=500), "perros")
    bs.descargar_asset(a2, cache_dir=tmp_path, ahora_utc="2021-06-15T12:00:00Z")
    assert cap["n"] == 1  # NO re-descargo
    obj1 = json.loads(sc.read_text(encoding="utf-8"))
    assert obj1["downloaded_utc"] == "2020-01-01T00:00:00Z"  # intacto, nunca se reinicia
    assert obj1["last_used_utc"] == "2021-06-15T12:00:00Z"  # actualizado
    assert obj1["query"] == "perros"  # query mas reciente
    assert obj1["selection_reason"] and "large2x" in obj1["selection_reason"]  # motivo actual


# ── 24. Compatibilidad Windows (rutas via pathlib, no separadores fijos) ──────


def test_rutas_usan_pathlib(monkeypatch, tmp_path):
    _stub_download(monkeypatch, _JPG)
    out = bs.descargar_asset(_asset_para_descarga(pid=42), cache_dir=tmp_path)
    assert isinstance(out.local_path, Path)
    assert out.local_path.parent == tmp_path


# ── Cache de busqueda: hit / expira / corrupta / normalizacion ────────────────


def test_cache_busqueda_hit_evita_request(monkeypatch):
    cap = {}
    _stub_get(monkeypatch, FakeResp(200, {"photos": [_foto(pid=1)]}), cap)
    bs.buscar_imagenes_pexels("gatos", usar_cache=True)
    assert cap["llamadas"] == 1

    def _boom(*a, **k):
        raise AssertionError("cache hit debe evitar el request")

    monkeypatch.setattr(bs.requests, "get", _boom)
    assets = bs.buscar_imagenes_pexels("gatos", usar_cache=True)
    assert len(assets) == 1 and assets[0].asset_id == "1"


def test_cache_busqueda_expira_provoca_request(monkeypatch):
    clave = bbase._clave_cache_busqueda("gatos", None, 10, 1)
    viejo = time.time() - (bbase.SEARCH_CACHE_TTL_S + 100)
    bbase._escribir_cache_busqueda(clave, [_foto(pid=9)], ahora_epoch=viejo)
    cap = {}
    _stub_get(monkeypatch, FakeResp(200, {"photos": [_foto(pid=2)]}), cap)
    assets = bs.buscar_imagenes_pexels("gatos", usar_cache=True)
    assert cap["llamadas"] == 1  # cache vencida -> si pide a la API
    assert assets[0].asset_id == "2"


def test_cache_busqueda_corrupta_no_finge_exito(monkeypatch):
    clave = bbase._clave_cache_busqueda("gatos", None, 10, 1)
    bbase.SEARCH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    bbase._search_cache_path(clave).write_text("{no es json valido", encoding="utf-8")
    cap = {}
    _stub_get(monkeypatch, FakeResp(200, {"photos": [_foto(pid=3)]}), cap)
    assets = bs.buscar_imagenes_pexels("gatos", usar_cache=True)
    assert cap["llamadas"] == 1  # corrupta -> renueva via request
    assert assets[0].asset_id == "3"


def test_cache_busqueda_normalizacion_misma_clave():
    a = bbase._clave_cache_busqueda("  Gatos   Monteses ", "portrait", 10, 1)
    b = bbase._clave_cache_busqueda("gatos monteses", "portrait", 10, 1)
    assert a == b


# ── 25. Ninguna prueba usa red real (verificado por el fixture autouse) ───────


def test_red_bloqueada_por_default():
    # El fixture autouse ya reemplaza requests.get por un boom; confirmamos el contrato.
    with pytest.raises(AssertionError):
        bs.requests.get("https://api.pexels.com/v1/search")
