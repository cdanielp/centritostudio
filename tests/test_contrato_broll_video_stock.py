"""Tests de contrato del fetcher de VIDEOS Pexels (feat/broll-pexels-video-fetcher, PR A).

NINGUN test toca la red: broll_video_stock.requests.get se stubea siempre. Nunca se usa una key
real. Las caches de busqueda/archivo se redirigen a tmp_path para no tocar el repo.

Cubre los 40 casos del brief: config sin key, Authorization sin fuga, endpoint /v1/videos/search,
query+locale, orientaciones, size NO por defecto, per_page, parseo (Video/duration/user/
video_files), cero resultados, 401/403/429 (sin retry)/timeout/JSON invalido, exclusion HLS/m3u8/
dimensiones nulas, seleccion 1080x1920 y 1920x1080, evita 4K, fallback a mayor, desempate
determinista, nombre por video_id+file_id, descarga atomica, reuso de cache, variante distinta,
archivo vacio, HTML rechazado, MP4 ftyp, sidecar completo/sin key, cache hit/expira/corrupta,
RuntimeError propaga, y sin red real.
"""

from __future__ import annotations

import json
import time

import pytest

import broll_video_stock as bs
import broll_video_stock_base as bbase

# ── Dobles de red (jamas se contacta Pexels) ──────────────────────────────────

# MP4 sintetico valido: box 'ftyp' al inicio (bytes[4:8]). Suficiente para la firma.
_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 24
_HTML = b"<!DOCTYPE html><html>no soy un video</html>"


class FakeResp:
    """Respuesta HTTP minima para stubear la BUSQUEDA (requests.get con json())."""

    def __init__(self, status=200, payload=None, headers=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("body no es JSON")
        return self._payload


class FakeStream:
    """Respuesta HTTP minima para stubear la DESCARGA (streaming: iter_content + close)."""

    def __init__(self, status=200, headers=None, content=b""):
        self.status_code = status
        self.headers = headers or {"Content-Type": "video/mp4"}
        self._content = content

    def iter_content(self, chunk_size):
        for i in range(0, len(self._content), max(chunk_size, 1)):
            yield self._content[i : i + chunk_size]

    def close(self):
        pass


def _vf(fid, w, h, quality="hd", file_type="video/mp4", link=None):
    """video_file crudo estilo Pexels."""
    return {
        "id": fid,
        "quality": quality,
        "file_type": file_type,
        "width": w,
        "height": h,
        "fps": 30.0,
        "link": link if link is not None else f"https://player.vimeo.com/external/{fid}.mp4",
    }


def _video(vid=555, w=1080, h=1920, files=None, duration=17):
    """Objeto Video estilo Pexels."""
    return {
        "id": vid,
        "width": w,
        "height": h,
        "url": f"https://www.pexels.com/video/{vid}/",
        "image": f"https://images.pexels.com/videos/{vid}/preview.jpg",
        "duration": duration,
        "user": {"id": 9, "name": "Ana Perez", "url": "https://www.pexels.com/@anaperez"},
        "video_files": files
        if files is not None
        else [
            _vf(1, 2160, 3840),
            _vf(2, 1080, 1920),
            _vf(3, 540, 960),
        ],
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
    """Reemplaza requests.get (BUSQUEDA) registrando la llamada."""

    def fake_get(url, headers=None, params=None, timeout=None, **kw):
        if capture is not None:
            capture.update(url=url, headers=headers, params=params, timeout=timeout)
            capture["llamadas"] = capture.get("llamadas", 0) + 1
        return resp

    monkeypatch.setattr(bs.requests, "get", fake_get)


def _stub_download(monkeypatch, content, headers=None, status=200):
    resp = FakeStream(status, headers=headers or {"Content-Type": "video/mp4"}, content=content)

    def fake_get(url, stream=None, timeout=None, **kw):
        return resp

    monkeypatch.setattr(bs.requests, "get", fake_get)


def _stub_download_count(monkeypatch, content, headers=None):
    resp = FakeStream(200, headers=headers or {"Content-Type": "video/mp4"}, content=content)
    cap = {"n": 0}

    def fake_get(url, stream=None, timeout=None, **kw):
        cap["n"] += 1
        return resp

    monkeypatch.setattr(bs.requests, "get", fake_get)
    return cap


def _asset(vid=555, **kw):
    return bs._asset_desde_video(_video(vid=vid, **kw), "montanas nevadas")


# ── 1. Config: API key ausente ────────────────────────────────────────────────


def test_sin_api_key_estado_deshabilitado(monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    assert bs.tiene_api_key() is False
    assert bs.estado_pexels_video()["habilitado"] is False


def test_sin_api_key_buscar_lanza_tipado(monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    with pytest.raises(bs.PexelsVideoDeshabilitado):
        bs.buscar_videos_pexels("montanas", usar_cache=False)


def test_sin_api_key_seguro_error_tipado(monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    r = bs.buscar_video_broll_seguro("montanas", usar_cache=False)
    assert r.assets == ()
    assert r.error is not None and r.error.code == "deshabilitado"


# ── 2. Authorization sin fuga ─────────────────────────────────────────────────


def test_request_manda_authorization_sin_filtrar(monkeypatch):
    cap = {}
    _stub_get(monkeypatch, FakeResp(200, {"videos": [_video()]}), cap)
    bs.buscar_videos_pexels("montanas", usar_cache=False)
    assert cap["headers"]["Authorization"] == "test-key-123"
    assert cap["timeout"] == bs.TIMEOUT_S
    assert "test-key-123" not in json.dumps(bs.estado_pexels_video())


def test_mensaje_de_error_saneado_nunca_expone_key():
    filtrado = bs._sanitizar("fallo con test-key-123 adentro")
    assert "test-key-123" not in filtrado and "***" in filtrado


# ── 3-4. Endpoint, query y locale ─────────────────────────────────────────────


def test_endpoint_videos_search_y_query_locale(monkeypatch):
    cap = {}
    _stub_get(monkeypatch, FakeResp(200, {"videos": []}), cap)
    bs.buscar_videos_pexels("montanas nevadas", usar_cache=False)
    assert cap["url"] == bs.SEARCH_URL == "https://api.pexels.com/v1/videos/search"
    assert cap["params"]["query"] == "montanas nevadas"
    assert cap["params"]["locale"] == "es-ES"  # locale default se envia


# ── 5-6. Orientacion ──────────────────────────────────────────────────────────


def test_orientacion_portrait_en_params(monkeypatch):
    cap = {}
    _stub_get(monkeypatch, FakeResp(200, {"videos": []}), cap)
    bs.buscar_videos_pexels("x", orientation="portrait", usar_cache=False)
    assert cap["params"]["orientation"] == "portrait"


def test_orientacion_landscape_en_params(monkeypatch):
    cap = {}
    _stub_get(monkeypatch, FakeResp(200, {"videos": []}), cap)
    bs.buscar_videos_pexels("x", orientation="landscape", usar_cache=False)
    assert cap["params"]["orientation"] == "landscape"


def test_orientacion_invalida_rechazada(monkeypatch):
    _stub_get(monkeypatch, FakeResp(200, {"videos": []}))
    with pytest.raises(ValueError):
        bs.buscar_videos_pexels("x", orientation="diagonal", usar_cache=False)


# ── 7. size NO se envia por defecto (size=None) ───────────────────────────────


def test_size_no_se_envia_por_defecto(monkeypatch):
    cap = {}
    _stub_get(monkeypatch, FakeResp(200, {"videos": []}), cap)
    bs.buscar_videos_pexels("x", usar_cache=False)
    assert "size" not in cap["params"], "por defecto la resolucion la decide el selector"


def test_size_se_envia_si_se_pide(monkeypatch):
    cap = {}
    _stub_get(monkeypatch, FakeResp(200, {"videos": []}), cap)
    bs.buscar_videos_pexels("x", size="medium", usar_cache=False)
    assert cap["params"]["size"] == "medium"


def test_size_invalido_rechazado(monkeypatch):
    _stub_get(monkeypatch, FakeResp(200, {"videos": []}))
    with pytest.raises(ValueError):
        bs.buscar_videos_pexels("x", size="8k", usar_cache=False)


# ── 8. per_page limitado ──────────────────────────────────────────────────────


def test_per_page_se_limita(monkeypatch):
    cap = {}
    _stub_get(monkeypatch, FakeResp(200, {"videos": []}), cap)
    bs.buscar_videos_pexels("x", per_page=9999, usar_cache=False)
    assert cap["params"]["per_page"] == bs.PER_PAGE_MAX
    bs.buscar_videos_pexels("x", per_page=0, page=0, usar_cache=False)
    assert cap["params"]["per_page"] == bs.PER_PAGE_MIN
    assert cap["params"]["page"] == 1


def test_query_vacio_rechazado(monkeypatch):
    _stub_get(monkeypatch, FakeResp(200, {"videos": []}))
    with pytest.raises(ValueError):
        bs.buscar_videos_pexels("   ", usar_cache=False)


# ── 9-12. Parseo de Video / duration / user / video_files ─────────────────────


def test_parseo_a_video_stock_asset(monkeypatch):
    _stub_get(monkeypatch, FakeResp(200, {"videos": [_video(vid=77, w=1080, h=1920)]}))
    assets = bs.buscar_videos_pexels("montanas", usar_cache=False)
    a = assets[0]
    assert a.provider == "pexels" and a.asset_id == "77"
    assert a.media_type == "video"
    assert a.width == 1080 and a.height == 1920 and a.orientation == "portrait"
    assert a.duration == 17  # parseo de duration
    assert a.author == "Ana Perez"  # parseo de user.name
    assert a.author_url.endswith("anaperez")  # parseo de user.url
    assert a.preview_url.endswith("preview.jpg")  # image
    assert a.source_url.endswith("/77/")
    assert len(a.video_files) == 3  # parseo de video_files
    assert a.video_files[0].file_id == "1" and a.video_files[0].file_type == "video/mp4"
    assert a.local_path is None and a.metadata_path is None
    assert a.selected_file_id is None


def test_user_ausente_no_rompe(monkeypatch):
    v = _video(vid=88)
    del v["user"]
    _stub_get(monkeypatch, FakeResp(200, {"videos": [v]}))
    a = bs.buscar_videos_pexels("x", usar_cache=False)[0]
    assert a.author == "" and a.author_url == ""


# ── 13. Cero resultados = exito valido ────────────────────────────────────────


def test_cero_resultados_no_es_error(monkeypatch):
    _stub_get(monkeypatch, FakeResp(200, {"videos": []}))
    assert bs.buscar_videos_pexels("noexiste", usar_cache=False) == []
    r = bs.buscar_video_broll_seguro("noexiste", usar_cache=False)
    assert r.error is None and r.assets == ()


# ── 14-15. HTTP 401 / 403 ─────────────────────────────────────────────────────


def test_http_401_lanza_auth(monkeypatch):
    _stub_get(monkeypatch, FakeResp(401))
    with pytest.raises(bs.PexelsVideoAuthError):
        bs.buscar_videos_pexels("x", usar_cache=False)


def test_http_403_seguro_codigo_auth(monkeypatch):
    _stub_get(monkeypatch, FakeResp(403))
    r = bs.buscar_video_broll_seguro("x", usar_cache=False)
    assert r.error.code == "auth"


# ── 16. HTTP 429 sin retry ────────────────────────────────────────────────────


def test_http_429_no_reintenta_conserva_retry_after(monkeypatch):
    cap = {}
    _stub_get(monkeypatch, FakeResp(429, headers={"Retry-After": "30"}), cap)
    dormido = {"n": 0}
    monkeypatch.setattr(time, "sleep", lambda s: dormido.__setitem__("n", dormido["n"] + 1))
    with pytest.raises(bs.PexelsVideoRateLimit) as exc:
        bs.buscar_videos_pexels("x", usar_cache=False)
    assert exc.value.retry_after == 30
    assert cap["llamadas"] == 1  # un solo request
    assert dormido["n"] == 0  # jamas durmio


def test_http_429_seguro_permite_continuar(monkeypatch):
    _stub_get(monkeypatch, FakeResp(429, headers={"Retry-After": "12"}))
    r = bs.buscar_video_broll_seguro("x", usar_cache=False)
    assert r.error.code == "rate_limit" and r.error.retry_after == 12


# ── 39. RuntimeError se propaga (no lo atrapa el fail-open) ────────────────────


def test_seguro_propaga_errores_de_programacion(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("bug interno, no operativo")

    monkeypatch.setattr(bs, "_buscar_con_rate", _boom)
    with pytest.raises(RuntimeError):
        bs.buscar_video_broll_seguro("montanas", usar_cache=False)


# ── 17. Timeout ───────────────────────────────────────────────────────────────


def test_timeout_lanza_tipado(monkeypatch):
    def _timeout(*a, **k):
        raise bs.requests.Timeout("lento")

    monkeypatch.setattr(bs.requests, "get", _timeout)
    with pytest.raises(bs.PexelsVideoTimeout):
        bs.buscar_videos_pexels("x", usar_cache=False)
    r = bs.buscar_video_broll_seguro("x", usar_cache=False)
    assert r.error.code == "timeout"


# ── 18. JSON invalido ─────────────────────────────────────────────────────────


def test_json_invalido_lanza_tipado(monkeypatch):
    _stub_get(monkeypatch, FakeResp(200, payload=None))
    with pytest.raises(bs.PexelsVideoRespuestaInvalida):
        bs.buscar_videos_pexels("x", usar_cache=False)


def test_json_sin_videos_lanza_tipado(monkeypatch):
    _stub_get(monkeypatch, FakeResp(200, {"otra_cosa": 1}))
    with pytest.raises(bs.PexelsVideoRespuestaInvalida):
        bs.buscar_videos_pexels("x", usar_cache=False)


# ── 19-21. Seleccion: exclusion HLS / m3u8 / dimensiones nulas ────────────────


def test_seleccion_excluye_hls():
    files = (
        bs.VideoFileCandidate("10", "hls", "video/mp4", 1080, 1920, "https://x/hls.mp4"),
        bs.VideoFileCandidate("11", "hd", "video/mp4", 1080, 1920, "https://x/ok.mp4"),
    )
    sel = bs.seleccionar_variante_video(
        files, destino="vertical", target_width=1080, target_height=1920
    )
    assert sel.file_id == "11"


def test_seleccion_excluye_m3u8():
    files = (
        bs.VideoFileCandidate("12", "hd", "video/mp4", 1080, 1920, "https://x/stream.m3u8"),
        bs.VideoFileCandidate("13", "hd", "video/mp4", 1080, 1920, "https://x/ok.mp4"),
    )
    sel = bs.seleccionar_variante_video(
        files, destino="vertical", target_width=1080, target_height=1920
    )
    assert sel.file_id == "13"


def test_seleccion_excluye_file_type_no_mp4():
    files = (
        bs.VideoFileCandidate("14", "hd", "application/x-mpegURL", 1080, 1920, "https://x/a"),
        bs.VideoFileCandidate("15", "hd", "video/mp4", 1080, 1920, "https://x/ok.mp4"),
    )
    sel = bs.seleccionar_variante_video(
        files, destino="vertical", target_width=1080, target_height=1920
    )
    assert sel.file_id == "15"


def test_seleccion_excluye_dimensiones_nulas():
    files = (
        bs.VideoFileCandidate("16", "hd", "video/mp4", 0, 0, "https://x/nula.mp4"),
        bs.VideoFileCandidate("17", "hd", "video/mp4", 1080, 1920, "https://x/ok.mp4"),
    )
    sel = bs.seleccionar_variante_video(
        files, destino="vertical", target_width=1080, target_height=1920
    )
    assert sel.file_id == "17"


def test_seleccion_sin_candidato_valido_lanza():
    files = (bs.VideoFileCandidate("18", "hls", "application/x-mpegURL", 0, 0, ""),)
    with pytest.raises(bs.PexelsVideoSinVariante):
        bs.seleccionar_variante_video(
            files, destino="vertical", target_width=1080, target_height=1920
        )


def test_seleccion_destino_invalido_o_target_cero():
    files = (bs.VideoFileCandidate("19", "hd", "video/mp4", 1080, 1920, "https://x/ok.mp4"),)
    with pytest.raises(ValueError):
        bs.seleccionar_variante_video(
            files, destino="diagonal", target_width=1080, target_height=1920
        )
    with pytest.raises(ValueError):
        bs.seleccionar_variante_video(files, destino="vertical", target_width=0, target_height=1920)


# ── 22-23. Seleccion exacta 1080x1920 / 1920x1080 ─────────────────────────────


def test_seleccion_exacta_1080x1920():
    files = (
        bs.VideoFileCandidate("1", "uhd", "video/mp4", 2160, 3840, "https://x/4k.mp4"),
        bs.VideoFileCandidate("2", "hd", "video/mp4", 1080, 1920, "https://x/fhd.mp4"),
        bs.VideoFileCandidate("3", "sd", "video/mp4", 540, 960, "https://x/sd.mp4"),
    )
    sel = bs.seleccionar_variante_video(
        files, destino="vertical", target_width=1080, target_height=1920
    )
    assert (sel.width, sel.height, sel.file_id) == (1080, 1920, "2")


def test_seleccion_exacta_1920x1080():
    files = (
        bs.VideoFileCandidate("a", "uhd", "video/mp4", 4096, 2160, "https://x/4k.mp4"),
        bs.VideoFileCandidate("b", "hd", "video/mp4", 1920, 1080, "https://x/fhd.mp4"),
    )
    sel = bs.seleccionar_variante_video(
        files, destino="horizontal", target_width=1920, target_height=1080
    )
    assert (sel.width, sel.height, sel.file_id) == (1920, 1080, "b")


# ── 24. Evita 4K si Full HD basta ─────────────────────────────────────────────


def test_evita_4k_si_full_hd_basta():
    files = (
        bs.VideoFileCandidate("1", "uhd", "video/mp4", 2160, 3840, "https://x/4k.mp4"),
        bs.VideoFileCandidate("2", "hd", "video/mp4", 1080, 1920, "https://x/fhd.mp4"),
    )
    sel = bs.seleccionar_variante_video(
        files, destino="vertical", target_width=1080, target_height=1920
    )
    assert sel.width == 1080, "con Full HD suficiente NO se baja el 4K"


# ── 25. Fallback a mayor disponible si ninguno alcanza ────────────────────────


def test_fallback_mayor_si_ninguno_alcanza():
    files = (
        bs.VideoFileCandidate("1", "sd", "video/mp4", 720, 1280, "https://x/720.mp4"),
        bs.VideoFileCandidate("2", "sd", "video/mp4", 540, 960, "https://x/540.mp4"),
    )
    sel = bs.seleccionar_variante_video(
        files, destino="vertical", target_width=1080, target_height=1920
    )
    assert (sel.width, sel.height) == (720, 1280), "ninguno alcanza -> el de mayor area"


# ── Prioriza orientacion que coincide con el destino ──────────────────────────


def test_seleccion_prioriza_orientacion_del_destino():
    files = (
        bs.VideoFileCandidate("1", "uhd", "video/mp4", 3840, 2160, "https://x/land4k.mp4"),
        bs.VideoFileCandidate("2", "sd", "video/mp4", 720, 1280, "https://x/port.mp4"),
    )
    sel = bs.seleccionar_variante_video(
        files, destino="vertical", target_width=1080, target_height=1920
    )
    assert sel.file_id == "2", "portrait gana aunque el landscape tenga mas resolucion"


# ── 26. Desempate determinista (misma area -> file_id menor) ──────────────────


def test_desempate_determinista_por_file_id():
    files = (
        bs.VideoFileCandidate("50", "hd", "video/mp4", 1080, 1920, "https://x/a.mp4"),
        bs.VideoFileCandidate("20", "hd", "video/mp4", 1080, 1920, "https://x/b.mp4"),
    )
    sel = bs.seleccionar_variante_video(
        files, destino="vertical", target_width=1080, target_height=1920
    )
    assert sel.file_id == "20", "misma area y AR -> gana el file_id menor (determinista)"


# ── 27-28. Descarga atomica + nombre por video_id+file_id ─────────────────────


def test_descarga_atomica_nombre_por_video_id_y_file_id(monkeypatch, tmp_path):
    _stub_download(monkeypatch, _MP4)
    a = _asset(vid=333)
    out = bs.descargar_video_asset(
        a, destino="vertical", target_width=1080, target_height=1920, cache_dir=tmp_path
    )
    assert out.local_path == tmp_path / "pexels_333_2.mp4"  # video_id 333 + file_id 2 (1080x1920)
    assert out.local_path.read_bytes() == _MP4
    assert list(tmp_path.glob("*.tmp")) == []  # atomico: sin temporales
    assert out.selected_file_id == "2" and out.selected_width == 1080


# ── 34-35. Sidecar completo / sin key ─────────────────────────────────────────


def test_sidecar_completo_y_sin_key(monkeypatch, tmp_path):
    _stub_download(monkeypatch, _MP4)
    a = _asset(vid=444)
    out = bs.descargar_video_asset(
        a, destino="vertical", target_width=1080, target_height=1920, cache_dir=tmp_path
    )
    side = json.loads(out.metadata_path.read_text(encoding="utf-8"))
    for campo in (
        "sidecar_version", "provider", "provider_url", "asset_id", "video_file_id", "query",
        "author", "author_url", "attribution_text", "source_url", "preview_url", "duration",
        "width", "height", "selected_width", "selected_height", "selected_quality",
        "selected_file_type", "download_url", "selection_reason", "downloaded_utc",
        "last_used_utc", "local_file",
    ):  # fmt: skip
        assert campo in side, f"falta {campo} en el sidecar"
    assert side["video_file_id"] == "2"
    assert side["attribution_text"] == "Video by Ana Perez on Pexels"
    assert side["selected_file_type"] == "video/mp4"
    assert side["local_file"] == "pexels_444_2.mp4"
    assert side["licencia"]["uso_comercial"] is True
    assert "test-key-123" not in out.metadata_path.read_text(encoding="utf-8")


# ── 29. Reuso de cache (no re-descarga) ───────────────────────────────────────


def test_reuso_de_cache_no_redescarga(monkeypatch, tmp_path):
    cap = _stub_download_count(monkeypatch, _MP4)
    a = _asset(vid=555)
    bs.descargar_video_asset(
        a, destino="vertical", target_width=1080, target_height=1920, cache_dir=tmp_path
    )
    assert cap["n"] == 1
    out = bs.descargar_video_asset(
        a, destino="vertical", target_width=1080, target_height=1920, cache_dir=tmp_path
    )
    assert cap["n"] == 1  # segunda vez = cache hit
    assert out.local_path == tmp_path / "pexels_555_2.mp4"


def test_sidecar_faltante_no_es_cache_hit_redescarga(monkeypatch, tmp_path):
    cap = _stub_download_count(monkeypatch, _MP4)
    a = _asset(vid=666)
    out = bs.descargar_video_asset(
        a, destino="vertical", target_width=1080, target_height=1920, cache_dir=tmp_path
    )
    assert cap["n"] == 1
    out.metadata_path.unlink()  # sidecar desaparece -> NO es cache hit
    bs.descargar_video_asset(
        a, destino="vertical", target_width=1080, target_height=1920, cache_dir=tmp_path
    )
    assert cap["n"] == 2


def test_cache_hit_download_url_distinta_redescarga(monkeypatch, tmp_path):
    cap = _stub_download_count(monkeypatch, _MP4)
    a = _asset(vid=777)
    bs.descargar_video_asset(
        a, destino="vertical", target_width=1080, target_height=1920, cache_dir=tmp_path
    )
    sc = tmp_path / "pexels_777_2.json"
    obj = json.loads(sc.read_text(encoding="utf-8"))
    obj["download_url"] = "https://otro/enlace.mp4"
    sc.write_text(json.dumps(obj), encoding="utf-8")
    bs.descargar_video_asset(
        a, destino="vertical", target_width=1080, target_height=1920, cache_dir=tmp_path
    )
    assert cap["n"] == 2  # url distinta -> re-descarga


# ── 30. Variante distinta genera archivo distinto ─────────────────────────────


def test_variante_distinta_genera_archivo_distinto(monkeypatch, tmp_path):
    _stub_download(monkeypatch, _MP4)
    files = [_vf(100, 1080, 1920), _vf(200, 1920, 1080)]  # portrait id100 + landscape id200
    a = bs._asset_desde_video(_video(vid=888, files=files), "x")
    v = bs.descargar_video_asset(
        a, destino="vertical", target_width=1080, target_height=1920, cache_dir=tmp_path
    )
    h = bs.descargar_video_asset(
        a, destino="horizontal", target_width=1920, target_height=1080, cache_dir=tmp_path
    )
    assert v.selected_file_id == "100" and h.selected_file_id == "200"
    assert v.local_path.name == "pexels_888_100.mp4"
    assert h.local_path.name == "pexels_888_200.mp4"
    assert v.local_path != h.local_path and v.local_path.exists() and h.local_path.exists()


# ── 31-33. Archivo vacio / HTML rechazado / MP4 ftyp aceptado ─────────────────


def test_descarga_vacia_rechazada(monkeypatch, tmp_path):
    _stub_download(monkeypatch, b"")
    with pytest.raises(bs.PexelsVideoDescargaError):
        bs.descargar_video_asset(
            _asset(), destino="vertical", target_width=1080, target_height=1920, cache_dir=tmp_path
        )
    assert list(tmp_path.glob("pexels_*.mp4")) == []


def test_html_renombrado_rechazado_por_firma(monkeypatch, tmp_path):
    # Content-Type octet-stream (no lo delata) pero la firma ftyp lo rechaza.
    _stub_download(monkeypatch, _HTML, headers={"Content-Type": "application/octet-stream"})
    with pytest.raises(bs.PexelsVideoDescargaError):
        bs.descargar_video_asset(
            _asset(), destino="vertical", target_width=1080, target_height=1920, cache_dir=tmp_path
        )


def test_content_type_html_rechazado(monkeypatch, tmp_path):
    _stub_download(monkeypatch, _MP4, headers={"Content-Type": "text/html"})
    with pytest.raises(bs.PexelsVideoDescargaError):
        bs.descargar_video_asset(
            _asset(), destino="vertical", target_width=1080, target_height=1920, cache_dir=tmp_path
        )


def test_mp4_ftyp_aceptado(monkeypatch, tmp_path):
    _stub_download(monkeypatch, _MP4, headers={})  # sin Content-Type: la firma decide
    out = bs.descargar_video_asset(
        _asset(vid=999),
        destino="vertical",
        target_width=1080,
        target_height=1920,
        cache_dir=tmp_path,
    )
    assert out.local_path.suffix == ".mp4" and out.local_path.read_bytes() == _MP4


# ── 36-38. Cache de busqueda: hit / expira / corrupta ─────────────────────────


def test_cache_busqueda_hit_evita_request(monkeypatch):
    cap = {}
    _stub_get(monkeypatch, FakeResp(200, {"videos": [_video(vid=1)]}), cap)
    bs.buscar_videos_pexels("montanas", usar_cache=True)
    assert cap["llamadas"] == 1

    def _boom(*a, **k):
        raise AssertionError("cache hit debe evitar el request")

    monkeypatch.setattr(bs.requests, "get", _boom)
    assets = bs.buscar_videos_pexels("montanas", usar_cache=True)
    assert len(assets) == 1 and assets[0].asset_id == "1"


def test_cache_busqueda_expira_provoca_request(monkeypatch):
    clave = bbase._clave_cache_busqueda("montanas", None, None, "es-ES", 10, 1)
    viejo = time.time() - (bbase.SEARCH_CACHE_TTL_S + 100)
    bbase._escribir_cache_busqueda(clave, [_video(vid=9)], ahora_epoch=viejo)
    cap = {}
    _stub_get(monkeypatch, FakeResp(200, {"videos": [_video(vid=2)]}), cap)
    assets = bs.buscar_videos_pexels("montanas", usar_cache=True)
    assert cap["llamadas"] == 1 and assets[0].asset_id == "2"


def test_cache_busqueda_corrupta_no_finge_exito(monkeypatch):
    clave = bbase._clave_cache_busqueda("montanas", None, None, "es-ES", 10, 1)
    bbase.SEARCH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    bbase._search_cache_path(clave).write_text("{no es json", encoding="utf-8")
    cap = {}
    _stub_get(monkeypatch, FakeResp(200, {"videos": [_video(vid=3)]}), cap)
    assets = bs.buscar_videos_pexels("montanas", usar_cache=True)
    assert cap["llamadas"] == 1 and assets[0].asset_id == "3"


def test_cache_busqueda_incluye_size_en_identidad():
    a = bbase._clave_cache_busqueda("m", "portrait", None, "es-ES", 10, 1)
    b = bbase._clave_cache_busqueda("m", "portrait", "large", "es-ES", 10, 1)
    assert a != b, "size distinto -> clave de cache distinta"


# ── 40. Ninguna prueba usa red real ───────────────────────────────────────────


def test_red_bloqueada_por_default():
    with pytest.raises(AssertionError):
        bs.requests.get("https://api.pexels.com/v1/videos/search")
