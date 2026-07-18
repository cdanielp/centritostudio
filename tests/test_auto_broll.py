"""test_auto_broll.py — Resolucion automatica de b-roll v2 (S37-B, #47a/b/c/f).

Sin red: los resolvers de Pexels se sustituyen por fakes locales (module-level
monkeypatch); un autouse bloquea sockets por si algo intentara conectarse.
"""

from __future__ import annotations

import base64
import json
from types import SimpleNamespace

import pytest

import auto_broll
from auto_broll import (
    COD_BROLL_DISABLED,
    COD_FALLBACK_FAILED,
    COD_IMAGE_SEARCH_OMIT,
    COD_MANUAL_PRECEDENCE,
    COD_MANUAL_VIDEO_SLOT,
    COD_PLANNER_EMPTY,
    COD_RESOLVED_IMAGE,
    COD_RESOLVED_VIDEO,
    COD_VIDEO_DOWNLOAD_FB,
    COD_VIDEO_NO_COVER,
    COD_VIDEO_SEARCH_FB,
    ResolucionBroll,
    entradas_popups_auto,
    escribir_json_atomico,
    intervalos_manual,
    resolver_plan,
)
from broll_plan_types import BrollSignal, BrollWindow
from clip_overlay import ClipOverlay
from core_overlays import Popup

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


@pytest.fixture(autouse=True)
def _sin_red(monkeypatch):
    """Ningun test de esta suite puede tocar la red (falla duro si lo intenta)."""
    import socket

    def _bloqueado(*a, **k):
        raise RuntimeError("red bloqueada en tests (S37-B)")

    monkeypatch.setattr(socket.socket, "connect", _bloqueado)


# ── Helpers sinteticos ───────────────────────────────────────────────────────


def mk_window(wid, start, end, media="image", query="cafe artesanal"):
    sig = BrollSignal(0, 0, 0, query.split()[0], start, f"texto con {query}")
    return BrollWindow(
        window_id=wid,
        start_s=start,
        end_s=end,
        duration_s=round(end - start, 3),
        media_type=media,
        query=query,
        reason="test",
        signal=sig,
    )


def mk_plan(*windows):
    return SimpleNamespace(windows=tuple(windows))


def fake_image_asset(tmp_path, name="pexels_img_1.png"):
    p = tmp_path / name
    p.write_bytes(PNG_1PX)
    return SimpleNamespace(
        provider="pexels",
        asset_id="img-1",
        author="Autor Uno",
        width=1080,
        height=1920,
        local_path=p,
    )


def fake_video_asset(tmp_path, duration, name="pexels_vid_1.mp4", asset_id="vid-1"):
    p = tmp_path / name
    p.write_bytes(b"fake-mp4")
    return SimpleNamespace(
        provider="pexels",
        asset_id=asset_id,
        author="Autor Dos",
        width=1080,
        height=1920,
        duration=duration,
        selected_file_id="f1",
        local_path=p,
    )


def resolver_img_ok(tmp_path):
    def _fn(query, t0, t1, w, h):
        asset = fake_image_asset(tmp_path)
        popup = Popup(
            png=asset.local_path,
            t0=t0,
            t1=t1,
            pos="center",
            size_pct=1.0,
            behind_text=True,
            cutaway=True,
            fit="cover",
        )
        return SimpleNamespace(popup=popup, codigo="ok", mensaje="ok", asset=asset)

    return _fn


def resolver_img_fail(codigo="sin_resultados"):
    def _fn(query, t0, t1, w, h):
        return SimpleNamespace(popup=None, codigo=codigo, mensaje=f"fallo {codigo}", asset=None)

    return _fn


def search_ok(tmp_path, durations=(6,)):
    assets = tuple(
        fake_video_asset(tmp_path, d, name=f"v{i}.mp4", asset_id=f"vid-{i}")
        for i, d in enumerate(durations)
    )

    def _fn(query, w, h):
        return SimpleNamespace(error=None, assets=assets)

    return _fn


def search_error():
    def _fn(query, w, h):
        return SimpleNamespace(error=SimpleNamespace(code="timeout", message="timeout"), assets=())

    return _fn


def download_ok():
    def _fn(asset, w, h):
        return asset

    return _fn


def download_error():
    from broll_video_stock import PexelsVideoDescargaError

    def _fn(asset, w, h):
        raise PexelsVideoDescargaError("descarga fallo")

    return _fn


def manual_popup(t0, t1, tmp_path):
    p = tmp_path / "manual.png"
    p.write_bytes(PNG_1PX)
    return Popup(png=p, t0=t0, t1=t1)


def manual_clip(t0, t1, tmp_path):
    p = tmp_path / "manual_clip.mp4"
    p.write_bytes(b"fake")
    return ClipOverlay(clip=p, t0=t0, t1=t1)


# ── Plan vacio / desactivado ─────────────────────────────────────────────────


def test_disabled_produce_decision_unica():
    res = resolver_plan(mk_plan(), [], [], 1080, 1920, broll_enabled=False)
    assert res.auto_popups == () and res.auto_clips == ()
    assert res.decisiones[0]["code"] == COD_BROLL_DISABLED


def test_plan_vacio_produce_planner_empty():
    res = resolver_plan(mk_plan(), [], [], 1080, 1920)
    assert res.decisiones[0]["code"] == COD_PLANNER_EMPTY


# ── Imagen ───────────────────────────────────────────────────────────────────


def test_imagen_resuelta(tmp_path):
    w = mk_window("broll-0001", 4.0, 7.5)
    res = resolver_plan(mk_plan(w), [], [], 1080, 1920, resolve_image_fn=resolver_img_ok(tmp_path))
    assert len(res.auto_popups) == 1
    d = res.decisiones[0]
    assert d["code"] == COD_RESOLVED_IMAGE and d["status"] == "resolved"
    assert d["final_media_type"] == "image"


def test_imagen_query_y_timestamps_exactos(tmp_path):
    llamadas = []

    def spy(query, t0, t1, w, h):
        llamadas.append((query, t0, t1))
        return resolver_img_ok(tmp_path)(query, t0, t1, w, h)

    win = mk_window("broll-0001", 4.25, 7.75, query="granos cafe tostado")
    resolver_plan(mk_plan(win), [], [], 1080, 1920, resolve_image_fn=spy)
    assert llamadas == [("granos cafe tostado", 4.25, 7.75)]


def test_imagen_popup_cover_behind_text(tmp_path):
    w = mk_window("broll-0001", 4.0, 7.5)
    res = resolver_plan(mk_plan(w), [], [], 1080, 1920, resolve_image_fn=resolver_img_ok(tmp_path))
    p = res.auto_popups[0]
    assert p.cutaway is True and p.fit == "cover" and p.behind_text is True
    assert p.t0 == 4.0 and p.t1 == 7.5


def test_imagen_asset_metadata_segura(tmp_path):
    w = mk_window("broll-0001", 4.0, 7.5)
    res = resolver_plan(mk_plan(w), [], [], 1080, 1920, resolve_image_fn=resolver_img_ok(tmp_path))
    asset = res.decisiones[0]["asset"]
    assert asset["asset_id"] == "img-1" and asset["author"] == "Autor Uno"
    assert asset["local_basename"] == "pexels_img_1.png"
    texto = json.dumps(asset)
    assert "http" not in texto and str(tmp_path) not in texto


def test_imagen_error_operativo_omitida():
    w = mk_window("broll-0001", 4.0, 7.5)
    res = resolver_plan(
        mk_plan(w), [], [], 1080, 1920, resolve_image_fn=resolver_img_fail("timeout")
    )
    assert res.auto_popups == ()
    d = res.decisiones[0]
    assert d["code"] == COD_IMAGE_SEARCH_OMIT and d["status"] == "omitted"


def test_imagen_error_descarga_codigo_distinto():
    w = mk_window("broll-0001", 4.0, 7.5)
    res = resolver_plan(
        mk_plan(w), [], [], 1080, 1920, resolve_image_fn=resolver_img_fail("descarga")
    )
    assert res.decisiones[0]["code"] == "image_download_omitted"


def test_imagen_valueerror_de_contrato_propaga():
    def roto(query, t0, t1, w, h):
        raise ValueError("query vacia")

    w = mk_window("broll-0001", 4.0, 7.5)
    with pytest.raises(ValueError):
        resolver_plan(mk_plan(w), [], [], 1080, 1920, resolve_image_fn=roto)


# ── Video ────────────────────────────────────────────────────────────────────


def test_video_selecciona_primer_candidato_que_cubre(tmp_path):
    w = mk_window("broll-0001", 4.0, 8.5, media="video")  # dur 4.5
    res = resolver_plan(
        mk_plan(w),
        [],
        [],
        1080,
        1920,
        search_video_fn=search_ok(tmp_path, durations=(3, 5, 9)),
        download_video_fn=download_ok(),
    )
    assert len(res.auto_clips) == 1
    assert res.decisiones[0]["code"] == COD_RESOLVED_VIDEO
    assert res.decisiones[0]["asset"]["asset_id"] == "vid-1"  # primero con dur >= 4.5


def test_video_clip_overlay_contrato_v1(tmp_path):
    w = mk_window("broll-0001", 4.0, 8.5, media="video")
    res = resolver_plan(
        mk_plan(w),
        [],
        [],
        1080,
        1920,
        search_video_fn=search_ok(tmp_path, durations=(6,)),
        download_video_fn=download_ok(),
    )
    c = res.auto_clips[0]
    assert c.loop is False and c.mute is True and c.source_start == 0.0
    assert c.fit == "cover" and c.size_pct == 1.0 and c.behind_text is True
    assert c.t0 == 4.0 and c.t1 == 8.5


def test_video_sin_candidato_suficiente_fallback_imagen(tmp_path):
    w = mk_window("broll-0001", 4.0, 8.5, media="video")
    res = resolver_plan(
        mk_plan(w),
        [],
        [],
        1080,
        1920,
        resolve_image_fn=resolver_img_ok(tmp_path),
        search_video_fn=search_ok(tmp_path, durations=(2, 3)),  # ninguno cubre 4.5
        download_video_fn=download_ok(),
    )
    assert res.auto_clips == () and len(res.auto_popups) == 1
    d = res.decisiones[0]
    assert d["status"] == "fallback" and d["final_media_type"] == "image"
    assert COD_VIDEO_NO_COVER in d["steps"] and d["code"] == COD_VIDEO_NO_COVER


def test_video_error_busqueda_fallback_imagen(tmp_path):
    w = mk_window("broll-0001", 4.0, 8.5, media="video")
    res = resolver_plan(
        mk_plan(w),
        [],
        [],
        1080,
        1920,
        resolve_image_fn=resolver_img_ok(tmp_path),
        search_video_fn=search_error(),
    )
    assert len(res.auto_popups) == 1
    assert res.decisiones[0]["code"] == COD_VIDEO_SEARCH_FB


def test_video_error_descarga_fallback_imagen(tmp_path):
    w = mk_window("broll-0001", 4.0, 8.5, media="video")
    res = resolver_plan(
        mk_plan(w),
        [],
        [],
        1080,
        1920,
        resolve_image_fn=resolver_img_ok(tmp_path),
        search_video_fn=search_ok(tmp_path, durations=(6,)),
        download_video_fn=download_error(),
    )
    assert len(res.auto_popups) == 1
    assert res.decisiones[0]["code"] == COD_VIDEO_DOWNLOAD_FB


def test_fallback_imagen_tambien_falla_omitida(tmp_path):
    w = mk_window("broll-0001", 4.0, 8.5, media="video")
    res = resolver_plan(
        mk_plan(w),
        [],
        [],
        1080,
        1920,
        resolve_image_fn=resolver_img_fail("timeout"),
        search_video_fn=search_error(),
    )
    assert res.auto_popups == () and res.auto_clips == ()
    d = res.decisiones[0]
    assert d["code"] == COD_FALLBACK_FAILED and d["status"] == "omitted"
    assert COD_VIDEO_SEARCH_FB in d["steps"]


def test_maximo_un_video_automatico(tmp_path):
    w1 = mk_window("broll-0001", 4.0, 8.5, media="video", query="uno corre")
    w2 = mk_window("broll-0002", 10.0, 14.5, media="video", query="dos salta")
    res = resolver_plan(
        mk_plan(w1, w2),
        [],
        [],
        1080,
        1920,
        resolve_image_fn=resolver_img_ok(tmp_path),
        search_video_fn=search_ok(tmp_path, durations=(9,)),
        download_video_fn=download_ok(),
    )
    assert len(res.auto_clips) == 1
    # el segundo se degrada a imagen por slot ocupado
    assert res.decisiones[1]["final_media_type"] == "image"
    assert COD_MANUAL_VIDEO_SLOT in res.decisiones[1]["steps"]


# ── Precedencia manual (#47b) ────────────────────────────────────────────────


def test_manual_popup_bloquea_auto(tmp_path):
    llamado = []

    def spy(query, t0, t1, w, h):
        llamado.append(query)
        return resolver_img_ok(tmp_path)(query, t0, t1, w, h)

    w = mk_window("broll-0001", 4.0, 7.5)
    manual = [manual_popup(5.0, 6.0, tmp_path)]
    res = resolver_plan(mk_plan(w), manual, [], 1080, 1920, resolve_image_fn=spy)
    assert res.auto_popups == ()
    assert res.decisiones[0]["code"] == COD_MANUAL_PRECEDENCE
    assert llamado == []  # no se descarga el asset bloqueado


def test_manual_clip_bloquea_auto_video(tmp_path):
    w = mk_window("broll-0001", 4.0, 8.5, media="video")
    manual = [manual_clip(5.0, 7.0, tmp_path)]
    res = resolver_plan(mk_plan(w), [], manual, 1080, 1920)
    assert res.decisiones[0]["code"] == COD_MANUAL_PRECEDENCE


def test_manual_clip_ocupa_slot_video_fuera_de_ventana(tmp_path):
    # clip manual en 20-24 NO traslapa la ventana 4-8.5, pero ocupa el slot de video
    w = mk_window("broll-0001", 4.0, 8.5, media="video")
    manual = [manual_clip(20.0, 24.0, tmp_path)]
    res = resolver_plan(
        mk_plan(w), [], manual, 1080, 1920, resolve_image_fn=resolver_img_ok(tmp_path)
    )
    assert res.auto_clips == () and len(res.auto_popups) == 1
    assert COD_MANUAL_VIDEO_SLOT in res.decisiones[0]["steps"]


def test_tocar_borde_no_bloquea(tmp_path):
    w = mk_window("broll-0001", 4.0, 7.5)
    manual = [manual_popup(7.5, 9.0, tmp_path)]  # empieza exactamente donde termina
    res = resolver_plan(
        mk_plan(w), manual, [], 1080, 1920, resolve_image_fn=resolver_img_ok(tmp_path)
    )
    assert len(res.auto_popups) == 1


def test_manual_fuera_de_ventana_no_bloquea(tmp_path):
    w = mk_window("broll-0001", 4.0, 7.5)
    manual = [manual_popup(10.0, 12.0, tmp_path)]
    res = resolver_plan(
        mk_plan(w), manual, [], 1080, 1920, resolve_image_fn=resolver_img_ok(tmp_path)
    )
    assert len(res.auto_popups) == 1


def test_intervalos_manual_ordenados(tmp_path):
    manual_p = [manual_popup(8.0, 9.0, tmp_path)]
    manual_c = [manual_clip(2.0, 4.0, tmp_path)]
    assert intervalos_manual(manual_p, manual_c) == [(2.0, 4.0), (8.0, 9.0)]


def test_manual_no_se_modifica_en_disco(tmp_path, monkeypatch):
    import cve_popups

    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    biblioteca = tmp_path / "biblio"
    biblioteca.mkdir()
    (biblioteca / "logo.png").write_bytes(PNG_1PX)
    monkeypatch.setattr(cve_popups, "BIBLIOTECA_DIR", biblioteca)
    sidecar = transcripts / "demo_popups.json"
    sidecar.write_text(json.dumps([{"imagen": "logo", "t": 5.0, "dur": 2.0}]), encoding="utf-8")
    bytes_antes = sidecar.read_bytes()
    popups, clips = auto_broll.cargar_manual("demo", transcripts, 1080, 1920)
    assert len(popups) == 1 and clips == []
    assert sidecar.read_bytes() == bytes_antes  # hash identico: jamas se toca


def test_manual_json_invalido_fail_open(tmp_path):
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    (transcripts / "demo_popups.json").write_text("{no es lista", encoding="utf-8")
    popups, clips = auto_broll.cargar_manual("demo", transcripts, 1080, 1920)
    assert popups == [] and clips == []


def test_manual_ausente_fail_open(tmp_path):
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    popups, clips = auto_broll.cargar_manual("demo", transcripts, 1080, 1920)
    assert popups == [] and clips == []


# ── Materializacion (#47c) ───────────────────────────────────────────────────


def _resolucion_demo(tmp_path):
    w1 = mk_window("broll-0001", 4.0, 7.5)
    w2 = mk_window("broll-0002", 9.0, 13.5, media="video", query="camina rio")
    return resolver_plan(
        mk_plan(w1, w2),
        [],
        [],
        1080,
        1920,
        resolve_image_fn=resolver_img_ok(tmp_path),
        search_video_fn=search_ok(tmp_path, durations=(9,)),
        download_video_fn=download_ok(),
    )


def test_popups_auto_lista_compatible(tmp_path):
    res = _resolucion_demo(tmp_path)
    entradas = entradas_popups_auto(res.decisiones)
    assert isinstance(entradas, list) and len(entradas) == 2
    img = next(e for e in entradas if e["source"] == "pexels")
    vid = next(e for e in entradas if e["source"] == "pexels_video")
    assert img["t"] == 4.0 and img["dur"] == 3.5 and img["fit"] == "cover"
    assert img["planner_window_id"] == "broll-0001"
    assert vid["loop"] is False and vid["mute"] is True and vid["source_start"] == 0.0


def test_popups_auto_fallback_usa_source_final(tmp_path):
    w = mk_window("broll-0001", 4.0, 8.5, media="video")
    res = resolver_plan(
        mk_plan(w),
        [],
        [],
        1080,
        1920,
        resolve_image_fn=resolver_img_ok(tmp_path),
        search_video_fn=search_ok(tmp_path, durations=(2,)),
        download_video_fn=download_ok(),
    )
    entradas = entradas_popups_auto(res.decisiones)
    assert len(entradas) == 1 and entradas[0]["source"] == "pexels"  # tipo FINAL real


def test_popups_auto_omitida_no_aparece():
    w = mk_window("broll-0001", 4.0, 7.5)
    res = resolver_plan(mk_plan(w), [], [], 1080, 1920, resolve_image_fn=resolver_img_fail())
    assert entradas_popups_auto(res.decisiones) == []


def test_popups_auto_bloqueada_no_aparece(tmp_path):
    w = mk_window("broll-0001", 4.0, 7.5)
    manual = [manual_popup(5.0, 6.0, tmp_path)]
    res = resolver_plan(mk_plan(w), manual, [], 1080, 1920)
    assert entradas_popups_auto(res.decisiones) == []


def test_escritura_atomica_utf8_newline(tmp_path):
    destino = tmp_path / "x_popups.auto.json"
    escribir_json_atomico(destino, [{"query": "cafe con acento: máquina ñoña"}])
    texto = destino.read_text(encoding="utf-8")
    assert texto.endswith("\n") and "máquina" in texto
    assert list(tmp_path.iterdir()) == [destino]  # sin temporales residuales


def test_escritura_sobrescribe_en_reanudacion(tmp_path):
    destino = tmp_path / "x.json"
    escribir_json_atomico(destino, {"v": 1})
    escribir_json_atomico(destino, {"v": 2})
    assert json.loads(destino.read_text(encoding="utf-8")) == {"v": 2}


def test_resolved_estructura_y_conteos(tmp_path):
    res = _resolucion_demo(tmp_path)
    clip_meta = {"duration_s": 20.0, "width": 1080, "height": 1920, "fps": 30.0}
    plan_dict = {"version": 1, "windows": [1, 2]}
    audit = auto_broll.construir_resolved(plan_dict, res, [], [], clip_meta, "fp-abc")
    assert audit["version"] == 1 and audit["mode"] == "v2"
    assert audit["config_fingerprint"] == "fp-abc"
    assert audit["cache_policy"] == "existing_fetcher_cache"
    assert audit["requested_windows"] == 2 and audit["resolved"] == 2
    assert audit["final"]["images"] == 1 and audit["final"]["videos"] == 1
    assert audit["final"]["coverage_s"] == 8.0
    assert audit["final"]["coverage_pct"] == 0.4


def test_resolved_sin_secretos_ni_rutas(tmp_path):
    res = _resolucion_demo(tmp_path)
    audit = auto_broll.construir_resolved(
        {"version": 1, "windows": []},
        res,
        [],
        [],
        {"duration_s": 20.0, "width": 1080, "height": 1920, "fps": 30.0},
        "fp",
    )
    texto = json.dumps(audit, ensure_ascii=False)
    assert "http" not in texto and "PEXELS" not in texto
    assert str(tmp_path).replace("\\", "\\\\") not in texto and str(tmp_path) not in texto


def test_resolved_serializable(tmp_path):
    res = _resolucion_demo(tmp_path)
    audit = auto_broll.construir_resolved(
        {"version": 1, "windows": []},
        res,
        [],
        [],
        {"duration_s": 20.0, "width": 1080, "height": 1920, "fps": 30.0},
        "fp",
    )
    assert json.loads(json.dumps(audit, ensure_ascii=False)) == audit


def test_resolucion_es_frozen(tmp_path):
    res = _resolucion_demo(tmp_path)
    assert isinstance(res, ResolucionBroll)
    with pytest.raises(AttributeError):
        res.auto_popups = ()


# ── write_broll_plan endurecido (temp unico) ─────────────────────────────────


def test_write_broll_plan_temp_unico(tmp_path, monkeypatch):
    """Dos escrituras concurrentes no comparten el nombre del temporal (mkstemp)."""
    from broll_plan_io import write_broll_plan
    from broll_plan_types import BrollConfig
    from broll_planner import plan_broll

    plan = plan_broll([], {"groups": []}, 10.0, BrollConfig())
    destino = tmp_path / "p_broll_plan.json"
    nombres = []
    import tempfile as tf

    real_mkstemp = tf.mkstemp

    def spy(*a, **k):
        fd, name = real_mkstemp(*a, **k)
        nombres.append(name)
        return fd, name

    monkeypatch.setattr("broll_plan_io.tempfile.mkstemp", spy)
    write_broll_plan(plan, destino)
    write_broll_plan(plan, destino, overwrite=True)
    assert len(nombres) == 2 and nombres[0] != nombres[1]
    assert list(tmp_path.iterdir()) == [destino]  # temporales limpiados


def test_write_broll_plan_no_overwrite_intacto(tmp_path):
    from broll_plan_io import write_broll_plan
    from broll_plan_types import BrollConfig, BrollInputError
    from broll_planner import plan_broll

    plan = plan_broll([], {"groups": []}, 10.0, BrollConfig())
    destino = tmp_path / "p_broll_plan.json"
    write_broll_plan(plan, destino)
    with pytest.raises(BrollInputError):
        write_broll_plan(plan, destino)
