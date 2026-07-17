"""Tests de contrato de la integracion Pexels -> b-roll cutaway (feat/broll-pexels-cutaway).

Cubre el camino: entrada explicita -> buscar_broll_seguro -> primer candidato -> descargar_asset
-> Popup(cutaway=True) -> orden de overlays con captions encima. TODOS sin red real: se
monkeypatchea `broll_cutaway.buscar_broll_seguro` / `broll_cutaway.descargar_asset`, asi el
fetcher se reutiliza sin tocar HTTP. Contratos:
- source='pexels' valida dispara busqueda; una entrada PNG NO toca Pexels.
- Validacion de contrato (query vacia, t1<=t0, fit/size_pct/orientation) -> ValueError.
- Exito -> Popup cutaway con t0/t1/fit/size_pct/behind_text correctos; behind_text default True.
- Orientacion 9:16 -> portrait/vertical; 16:9 -> landscape/horizontal.
- Fail-open operativo: sin_resultados, rate_limit, timeout -> sin Popup, codigo visible.
- Errores de programacion (RuntimeError) se PROPAGAN.
- Se reutiliza descargar_asset; el modulo puente NO habla HTTP (sin red por diseno).
- La ruta descargada termina en el Popup y este entra al mismo orden de overlays; captions encima.
- Compatibilidad con el cutaway PNG anterior intacta.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

import broll_cutaway as bc
import core_overlays as co
import cve_popups as cp
from broll_stock import BrollError, BrollResult, PexelsTimeout, StockAsset

PNG_BYTES = b"\x89PNG\r\n\x1a\n mock"  # firma PNG valida (suficiente para exists()/firma)


def _png(tmp_path: Path, name: str = "pexels_123_large2x.jpg") -> Path:
    p = tmp_path / name
    p.write_bytes(PNG_BYTES)
    return p


def _asset(asset_id: str = "123", **kw) -> StockAsset:
    base = dict(
        provider="pexels",
        asset_id=asset_id,
        query="cafe",
        width=800,
        height=1200,
        orientation="portrait",
        download_url="https://example/orig.jpg",
        source_url="https://example/photo",
        author="Foto Autor",
        author_url="https://example/autor",
        alt="",
        src={"large2x": "https://example/large2x.jpg"},
    )
    base.update(kw)
    return StockAsset(**base)


def _buscar_ok(asset: StockAsset):
    def f(query, orientation=None, per_page=10, page=1, usar_cache=True):
        return BrollResult(assets=(asset,))

    return f


def _descargar_ok(local: Path):
    def f(asset, cache_dir=None, destino="vertical", fit="cover"):
        return replace(asset, local_path=local, selected_variant="large2x")

    return f


def _popups_json(tmp_path: Path, data: list) -> Path:
    path = tmp_path / "x_popups.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _biblioteca(tmp_path: Path, nombres: list[str]):
    d = tmp_path / "biblioteca"
    d.mkdir()
    for n in nombres:
        (d / n).write_bytes(PNG_BYTES)
    return cp.indexar_biblioteca(d)


# ── 1 / 2: disparo de busqueda vs entrada PNG que no toca Pexels ──────────────


def test_pexels_valido_dispara_busqueda(tmp_path, monkeypatch):
    llamadas = {}

    def spy(query, orientation=None, per_page=10, page=1, usar_cache=True):
        llamadas["query"] = query
        llamadas["orientation"] = orientation
        return BrollResult(assets=(_asset(),))

    monkeypatch.setattr(bc, "buscar_broll_seguro", spy)
    monkeypatch.setattr(bc, "descargar_asset", _descargar_ok(_png(tmp_path)))
    res = bc.resolver_cutaway_pexels("cafe mexicano", 1.0, 4.0, orientation="portrait")
    assert res.codigo == "ok"
    assert llamadas == {"query": "cafe mexicano", "orientation": "portrait"}


def test_entrada_png_no_llama_pexels(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("una entrada PNG jamas debe llamar a Pexels")

    monkeypatch.setattr(bc, "buscar_broll_seguro", boom)
    biblio = _biblioteca(tmp_path, ["flecha.png"])
    path = _popups_json(tmp_path, [{"t": 1.0, "imagen": "flecha"}])
    popups = cp.cargar_popups_manual(path, biblio, video_w=1080, video_h=1920)
    assert len(popups) == 1 and popups[0].cutaway is False


# ── 3 / 4 / 5: validacion de contrato (ValueError, se propaga) ───────────────


def test_query_vacia_se_rechaza():
    with pytest.raises(ValueError):
        bc.resolver_cutaway_pexels("   ", 1.0, 2.0, orientation="portrait")


def test_t1_menor_igual_t0_se_rechaza():
    with pytest.raises(ValueError):
        bc.resolver_cutaway_pexels("cafe", 2.0, 2.0, orientation="portrait")


def test_fit_invalido_se_rechaza():
    with pytest.raises(ValueError):
        bc.resolver_cutaway_pexels("cafe", 1.0, 2.0, orientation="portrait", fit="diagonal")


def test_size_pct_fuera_de_rango_se_rechaza():
    with pytest.raises(ValueError):
        bc.resolver_cutaway_pexels("cafe", 1.0, 2.0, orientation="portrait", size_pct=1.5)


def test_orientation_invalida_se_rechaza():
    with pytest.raises(ValueError):
        bc.resolver_cutaway_pexels("cafe", 1.0, 2.0, orientation="diagonal")


# ── 6-11: exito crea Popup cutaway con campos correctos ──────────────────────


def test_exito_crea_popup_cutaway_con_defaults(tmp_path, monkeypatch):
    local = _png(tmp_path)
    monkeypatch.setattr(bc, "buscar_broll_seguro", _buscar_ok(_asset()))
    monkeypatch.setattr(bc, "descargar_asset", _descargar_ok(local))
    res = bc.resolver_cutaway_pexels("cafe", 1.0, 4.0, orientation="portrait")
    p = res.popup
    assert p is not None and p.cutaway is True
    assert p.t0 == 1.0 and p.t1 == 4.0, "los timestamps vienen de la entrada, no de Pexels"
    assert p.fit == "cover", "fit default"
    assert p.size_pct == 1.0, "size_pct default"
    assert p.behind_text is True, "b-roll cutaway Pexels: captions encima por defecto"
    assert res.asset is not None and res.asset.asset_id == "123", "metadata segura para evidencia"


def test_popup_respeta_fit_y_size_pct(tmp_path, monkeypatch):
    monkeypatch.setattr(bc, "buscar_broll_seguro", _buscar_ok(_asset()))
    monkeypatch.setattr(bc, "descargar_asset", _descargar_ok(_png(tmp_path)))
    res = bc.resolver_cutaway_pexels(
        "cafe", 0.0, 2.0, orientation="portrait", fit="contain", size_pct=0.75
    )
    assert res.popup.fit == "contain" and res.popup.size_pct == 0.75


def test_behind_text_explicito_false_se_respeta(tmp_path, monkeypatch):
    monkeypatch.setattr(bc, "buscar_broll_seguro", _buscar_ok(_asset()))
    monkeypatch.setattr(bc, "descargar_asset", _descargar_ok(_png(tmp_path)))
    res = bc.resolver_cutaway_pexels("cafe", 0.0, 2.0, orientation="portrait", behind_text=False)
    assert res.popup.behind_text is False


# ── 12 / 13: mapeo de orientacion ────────────────────────────────────────────


def test_orientacion_vertical_9x16():
    assert bc.orientacion_para_video(1080, 1920) == ("portrait", "vertical")


def test_orientacion_horizontal_16x9():
    assert bc.orientacion_para_video(1920, 1080) == ("landscape", "horizontal")


def test_orientacion_cuadrado_cae_a_horizontal():
    assert bc.orientacion_para_video(1000, 1000) == ("landscape", "horizontal")


def test_resolver_pasa_destino_segun_orientacion(tmp_path, monkeypatch):
    llamadas = {}
    monkeypatch.setattr(bc, "buscar_broll_seguro", _buscar_ok(_asset()))

    def spy(asset, cache_dir=None, destino="vertical", fit="cover"):
        llamadas["destino"] = destino
        return replace(asset, local_path=_png(tmp_path))

    monkeypatch.setattr(bc, "descargar_asset", spy)
    bc.resolver_cutaway_pexels("cafe", 1.0, 3.0, orientation="portrait")
    assert llamadas["destino"] == "vertical"
    bc.resolver_cutaway_pexels("cafe", 1.0, 3.0, orientation="landscape")
    assert llamadas["destino"] == "horizontal"


# ── 14 / 15 / 16: fail-open operativo (sin Popup, codigo visible) ────────────


def test_cero_resultados_omite_sin_derribar(monkeypatch):
    monkeypatch.setattr(bc, "buscar_broll_seguro", lambda *a, **k: BrollResult(assets=()))
    res = bc.resolver_cutaway_pexels("cafe", 1.0, 2.0, orientation="portrait")
    assert res.popup is None and res.codigo == "sin_resultados"


def test_rate_limit_omite_con_error_visible(monkeypatch):
    err = BrollResult(error=BrollError("rate_limit", "Pexels rate limit (HTTP 429)"))
    monkeypatch.setattr(bc, "buscar_broll_seguro", lambda *a, **k: err)
    res = bc.resolver_cutaway_pexels("cafe", 1.0, 2.0, orientation="portrait")
    assert res.popup is None and res.codigo == "rate_limit" and res.mensaje


def test_timeout_en_descarga_omite(tmp_path, monkeypatch):
    monkeypatch.setattr(bc, "buscar_broll_seguro", _buscar_ok(_asset()))

    def desc_timeout(*a, **k):
        raise PexelsTimeout("timeout al descargar la imagen")

    monkeypatch.setattr(bc, "descargar_asset", desc_timeout)
    res = bc.resolver_cutaway_pexels("cafe", 1.0, 2.0, orientation="portrait")
    assert res.popup is None and res.codigo == "timeout"


# ── 17 / 18: key ausente no rompe; errores de programacion se propagan ───────


def test_key_ausente_no_rompe_render_no_pexels(tmp_path, monkeypatch):
    deshab = BrollResult(error=BrollError("deshabilitado", "PEXELS_API_KEY ausente"))
    monkeypatch.setattr(bc, "buscar_broll_seguro", lambda *a, **k: deshab)
    biblio = _biblioteca(tmp_path, ["flecha.png"])
    data = [
        {"source": "pexels", "t": 1.0, "dur": 2.0, "query": "cafe"},  # se omite (sin key)
        {"t": 5.0, "imagen": "flecha"},  # render PNG sobrevive
    ]
    popups = cp.cargar_popups_manual(_popups_json(tmp_path, data), biblio, 1080, 1920)
    assert len(popups) == 1 and popups[0].png.name == "flecha.png"


def test_runtimeerror_interno_se_propaga(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("bug interno del fetcher")

    monkeypatch.setattr(bc, "buscar_broll_seguro", boom)
    with pytest.raises(RuntimeError):
        bc.resolver_cutaway_pexels("cafe", 1.0, 2.0, orientation="portrait")


# ── 19 / 24: reutiliza descargar_asset y NO habla HTTP (sin red por diseno) ──


def test_reutiliza_descargar_asset(tmp_path, monkeypatch):
    usado = {}
    monkeypatch.setattr(bc, "buscar_broll_seguro", _buscar_ok(_asset()))

    def spy(asset, cache_dir=None, destino="vertical", fit="cover"):
        usado["si"] = True
        return replace(asset, local_path=_png(tmp_path))

    monkeypatch.setattr(bc, "descargar_asset", spy)
    bc.resolver_cutaway_pexels("cafe", 1.0, 3.0, orientation="portrait")
    assert usado.get("si") is True


def test_modulo_puente_sin_http_directo():
    src = Path(bc.__file__).read_text(encoding="utf-8")
    assert "import requests" not in src, "el puente reutiliza el fetcher, no habla HTTP"
    assert "api.pexels.com" not in src and "requests.get" not in src


# ── 20 / 21 / 22: ruta en el Popup + orden de overlays + captions encima ─────


def test_ruta_descargada_termina_en_popup(tmp_path, monkeypatch):
    local = _png(tmp_path)
    monkeypatch.setattr(bc, "buscar_broll_seguro", _buscar_ok(_asset()))
    monkeypatch.setattr(bc, "descargar_asset", _descargar_ok(local))
    res = bc.resolver_cutaway_pexels("cafe", 1.0, 3.0, orientation="portrait")
    assert res.popup.png == local


def test_popup_pexels_entra_al_orden_de_overlays_con_captions_encima(tmp_path, monkeypatch):
    local = _png(tmp_path)
    monkeypatch.setattr(bc, "buscar_broll_seguro", _buscar_ok(_asset()))
    monkeypatch.setattr(bc, "descargar_asset", _descargar_ok(local))
    res = bc.resolver_cutaway_pexels("cafe", 1.0, 3.0, orientation="portrait")  # behind default
    cmd = co.construir_comando(
        Path("in.mp4"), "x.ass", Path("out.mp4"), [], 216, 1300, 0.12, 1080, 1920, [res.popup]
    )
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "ass=x.ass" in fc, "los captions ASS siguen en el filter graph"
    assert fc.index("pb0") < fc.index("ass="), "cutaway behind -> captions ENCIMA"
    assert str(local) in cmd, "el PNG descargado es un input real del comando"


# ── 23: compatibilidad con el cutaway PNG anterior ───────────────────────────


def test_compat_cutaway_png_anterior_intacto(tmp_path):
    biblio = _biblioteca(tmp_path, ["broll.png"])
    data = [{"t": 1.0, "imagen": "broll", "dur": 2.0, "cutaway": True}]
    popups = cp.cargar_popups_manual(_popups_json(tmp_path, data), biblio, 1080, 1920)
    assert len(popups) == 1
    assert popups[0].cutaway is True and popups[0].behind_text is True
    assert popups[0].size_pct == co.CUTAWAY_SIZE_PCT


# ── Integracion via cve_popups (dispatch por source, sin red) ────────────────


def test_integracion_entrada_pexels_crea_cutaway(tmp_path, monkeypatch):
    local = _png(tmp_path)
    monkeypatch.setattr(bc, "buscar_broll_seguro", _buscar_ok(_asset()))
    monkeypatch.setattr(bc, "descargar_asset", _descargar_ok(local))
    data = [{"source": "pexels", "t": 1.0, "dur": 3.0, "query": "cafe mexicano", "fit": "cover"}]
    popups = cp.cargar_popups_manual(_popups_json(tmp_path, data), {}, 1080, 1920)
    assert len(popups) == 1
    p = popups[0]
    assert p.cutaway is True and p.behind_text is True and p.fit == "cover"
    assert p.t0 == 1.0 and p.t1 == 4.0 and p.png == local


def test_integracion_pexels_sin_dimensiones_omite(tmp_path, monkeypatch):
    monkeypatch.setattr(
        bc, "buscar_broll_seguro", lambda *a, **k: (_ for _ in ()).throw(AssertionError())
    )
    data = [{"source": "pexels", "t": 1.0, "query": "cafe"}]
    popups = cp.cargar_popups_manual(_popups_json(tmp_path, data), {})  # sin video_w/video_h
    assert popups == [], "sin dimensiones el b-roll pexels se omite (fail-open), no rompe"


def test_integracion_source_desconocido_omite(tmp_path):
    data = [{"source": "unsplash", "t": 1.0, "query": "cafe"}]
    popups = cp.cargar_popups_manual(_popups_json(tmp_path, data), {}, 1080, 1920)
    assert popups == []


# ── Flujo completo: programacion propaga, operativo fail-open (a traves de resolver_popups) ──


def test_flujo_completo_runtimeerror_propaga_por_resolver_popups(tmp_path, monkeypatch):
    """entrada source='pexels' -> dependencia interna lanza RuntimeError -> resolver_popups
    TAMBIEN lanza RuntimeError (no lo convierte en []). No se ocultan bugs (D29)."""

    def boom(*a, **k):
        raise RuntimeError("bug interno del fetcher")

    monkeypatch.setattr(bc, "buscar_broll_seguro", boom)
    _popups_json(tmp_path, [{"source": "pexels", "t": 1.0, "dur": 2.0, "query": "cafe"}])
    with pytest.raises(RuntimeError):
        cp.resolver_popups(
            [],
            "x",
            transcripts_dir=tmp_path,
            biblioteca_dir=tmp_path / "nada",
            video_w=1080,
            video_h=1920,
        )


def test_flujo_completo_operativo_pexels_sigue_fail_open_en_resolver_popups(tmp_path, monkeypatch):
    """Los errores OPERATIVOS conocidos (aqui timeout) siguen siendo fail-open a traves del
    camino real: resolver_popups devuelve [], el render nunca cae."""
    err = BrollResult(error=BrollError("timeout", "Pexels no respondio a tiempo"))
    monkeypatch.setattr(bc, "buscar_broll_seguro", lambda *a, **k: err)
    _popups_json(tmp_path, [{"source": "pexels", "t": 1.0, "dur": 2.0, "query": "cafe"}])
    popups = cp.resolver_popups(
        [],
        "x",
        transcripts_dir=tmp_path,
        biblioteca_dir=tmp_path / "nada",
        video_w=1080,
        video_h=1920,
    )
    assert popups == []
