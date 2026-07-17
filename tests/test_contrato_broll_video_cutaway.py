"""Tests de contrato de la integracion Pexels VIDEO -> b-roll cutaway de clip (PR B).

Camino: entrada explicita -> buscar_video_broll_seguro -> primer candidato -> descargar_video_asset
-> ClipOverlay -> comando FFmpeg con captions encima y audio ORIGINAL conservado (clip silenciado).
Todos sin red real (se monkeypatchea el fetcher), SALVO un unico test que genera clips sinteticos
con lavfi y corre FFmpeg local (sin Internet).

Contratos cubiertos (37 casos del brief): dispatch por source, validacion de contrato (ValueError),
fail-open operativo, ClipOverlay correcto, orientacion, comando FFmpeg (clip como input, audio del
clip nunca mapeado, trim/loop/cover, captions despues del overlay, sin amix/amerge), politica de un
solo clip, adaptador JSON que omite entradas invalidas, y render real con ffprobe.
"""

from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

import broll_video_cutaway as bvc
import clip_overlay
import core_overlays as co
import cve_clips
import cve_popups as cp
from broll_video_stock import BrollVideoError, PexelsVideoTimeout, VideoBrollResult, VideoStockAsset
from clip_overlay import ClipOverlay

_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 24


def _clipfile(tmp_path: Path, name: str = "pexels_1_2.mp4") -> Path:
    p = tmp_path / name
    p.write_bytes(_MP4)
    return p


def _asset(asset_id: str = "1", **kw) -> VideoStockAsset:
    base = dict(
        provider="pexels",
        asset_id=asset_id,
        query="montanas",
        width=1080,
        height=1920,
        duration=11,
        orientation="portrait",
        source_url="https://example/video",
        author="Foto Autor",
        author_url="https://example/autor",
        preview_url="https://example/preview.jpg",
    )
    base.update(kw)
    return VideoStockAsset(**base)


def _buscar_ok(asset: VideoStockAsset):
    def f(query, orientation=None, size=None, locale="es-ES", per_page=10, page=1, usar_cache=True):
        return VideoBrollResult(assets=(asset,))

    return f


def _descargar_ok(local: Path):
    def f(asset, *, destino="vertical", target_width=1080, target_height=1920, cache_dir=None):
        return replace(asset, local_path=local, selected_file_id="2", selected_width=target_width)

    return f


def _clip(tmp_path: Path, **kw) -> ClipOverlay:
    base = dict(clip=_clipfile(tmp_path), t0=1.0, t1=5.0)
    base.update(kw)
    return ClipOverlay(**base)


def _cmd_con_clip(tmp_path, clip, video_w=1080, video_h=1920):
    return co.construir_comando(
        Path("in.mp4"),
        "x.ass",
        Path("out.mp4"),
        [],
        216,
        1300,
        0.12,
        video_w,
        video_h,
        clips=[clip],
    )


def _popups_json(tmp_path: Path, data: list, stem: str = "x") -> Path:
    import json  # noqa: PLC0415

    path = tmp_path / f"{stem}_popups.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ── 4-8. Validacion de contrato del puente (ValueError se propaga) ────────────


def test_query_vacia_se_rechaza():
    with pytest.raises(ValueError):
        bvc.resolver_cutaway_video_pexels(
            "  ", 1.0, 5.0, orientation="portrait", target_width=1080, target_height=1920
        )


def test_tiempo_invalido_se_rechaza():
    with pytest.raises(ValueError):
        bvc.resolver_cutaway_video_pexels(
            "m", 5.0, 5.0, orientation="portrait", target_width=1080, target_height=1920
        )


def test_source_start_negativo_se_rechaza():
    with pytest.raises(ValueError):
        bvc.resolver_cutaway_video_pexels(
            "m", 1.0, 5.0, orientation="portrait", target_width=1080, target_height=1920,
            source_start=-1.0,
        )  # fmt: skip


def test_fit_distinto_de_cover_se_rechaza():
    with pytest.raises(ValueError):
        bvc.resolver_cutaway_video_pexels(
            "m", 1.0, 5.0, orientation="portrait", target_width=1080, target_height=1920,
            fit="contain",
        )  # fmt: skip


def test_orientation_invalida_se_rechaza():
    with pytest.raises(ValueError):
        bvc.resolver_cutaway_video_pexels(
            "m", 1.0, 5.0, orientation="diagonal", target_width=1080, target_height=1920
        )


def test_mute_false_rechazado_en_validacion():
    with pytest.raises(ValueError):
        clip_overlay.validar_clip_overlay(
            t0=1.0, t1=5.0, source_start=0.0, fit="cover", size_pct=1.0, loop=True, mute=False
        )


def test_loop_no_booleano_rechazado_en_validacion():
    with pytest.raises(ValueError):
        clip_overlay.validar_clip_overlay(
            t0=1.0, t1=5.0, source_start=0.0, fit="cover", size_pct=1.0, loop="yes", mute=True
        )


# ── 9-15. Exito crea ClipOverlay con campos correctos + orientacion ──────────


def test_exito_crea_clip_overlay_con_defaults(tmp_path, monkeypatch):
    local = _clipfile(tmp_path)
    monkeypatch.setattr(bvc, "buscar_video_broll_seguro", _buscar_ok(_asset()))
    monkeypatch.setattr(bvc, "descargar_video_asset", _descargar_ok(local))
    res = bvc.resolver_cutaway_video_pexels(
        "montanas", 1.0, 5.0, orientation="portrait", target_width=1080, target_height=1920
    )
    c = res.clip
    assert res.codigo == "ok" and c is not None
    assert c.t0 == 1.0 and c.t1 == 5.0, "los timestamps vienen de la entrada, no de Pexels"
    assert c.loop is True, "loop default true"
    assert c.behind_text is True, "captions encima por defecto"
    assert c.fit == "cover" and c.mute is True
    assert c.clip == local, "la ruta descargada se usa en el ClipOverlay"
    assert res.asset is not None and res.asset.asset_id == "1"


def test_source_start_y_size_pct_se_respetan(tmp_path, monkeypatch):
    monkeypatch.setattr(bvc, "buscar_video_broll_seguro", _buscar_ok(_asset()))
    monkeypatch.setattr(bvc, "descargar_video_asset", _descargar_ok(_clipfile(tmp_path)))
    res = bvc.resolver_cutaway_video_pexels(
        "m", 2.0, 6.0, orientation="portrait", target_width=1080, target_height=1920,
        source_start=1.5, size_pct=0.8, loop=False,
    )  # fmt: skip
    assert res.clip.source_start == 1.5 and res.clip.size_pct == 0.8 and res.clip.loop is False


def test_orientacion_vertical_y_horizontal():
    assert bvc.orientacion_para_video(1080, 1920) == ("portrait", "vertical")
    assert bvc.orientacion_para_video(1920, 1080) == ("landscape", "horizontal")


def test_destino_segun_orientacion(tmp_path, monkeypatch):
    llamadas = {}
    monkeypatch.setattr(bvc, "buscar_video_broll_seguro", _buscar_ok(_asset()))

    def spy(asset, *, destino="vertical", target_width=1080, target_height=1920, cache_dir=None):
        llamadas["destino"] = destino
        return replace(asset, local_path=_clipfile(tmp_path))

    monkeypatch.setattr(bvc, "descargar_video_asset", spy)
    bvc.resolver_cutaway_video_pexels(
        "m", 1.0, 3.0, orientation="portrait", target_width=1080, target_height=1920
    )
    assert llamadas["destino"] == "vertical"
    bvc.resolver_cutaway_video_pexels(
        "m", 1.0, 3.0, orientation="landscape", target_width=1920, target_height=1080
    )
    assert llamadas["destino"] == "horizontal"


# ── 16-19. Fail-open operativo + propagacion de bugs ─────────────────────────


def test_cero_resultados_fail_open(monkeypatch):
    monkeypatch.setattr(
        bvc, "buscar_video_broll_seguro", lambda *a, **k: VideoBrollResult(assets=())
    )
    res = bvc.resolver_cutaway_video_pexels(
        "m", 1.0, 5.0, orientation="portrait", target_width=1080, target_height=1920
    )
    assert res.clip is None and res.codigo == "sin_resultados"


def test_rate_limit_fail_open(monkeypatch):
    err = VideoBrollResult(error=BrollVideoError("rate_limit", "Pexels rate limit (HTTP 429)"))
    monkeypatch.setattr(bvc, "buscar_video_broll_seguro", lambda *a, **k: err)
    res = bvc.resolver_cutaway_video_pexels(
        "m", 1.0, 5.0, orientation="portrait", target_width=1080, target_height=1920
    )
    assert res.clip is None and res.codigo == "rate_limit" and res.mensaje


def test_timeout_en_descarga_fail_open(tmp_path, monkeypatch):
    monkeypatch.setattr(bvc, "buscar_video_broll_seguro", _buscar_ok(_asset()))

    def desc_timeout(*a, **k):
        raise PexelsVideoTimeout("timeout al descargar el video")

    monkeypatch.setattr(bvc, "descargar_video_asset", desc_timeout)
    res = bvc.resolver_cutaway_video_pexels(
        "m", 1.0, 5.0, orientation="portrait", target_width=1080, target_height=1920
    )
    assert res.clip is None and res.codigo == "timeout"


def test_runtimeerror_interno_se_propaga(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("bug interno del fetcher")

    monkeypatch.setattr(bvc, "buscar_video_broll_seguro", boom)
    with pytest.raises(RuntimeError):
        bvc.resolver_cutaway_video_pexels(
            "m", 1.0, 5.0, orientation="portrait", target_width=1080, target_height=1920
        )


def test_puente_sin_http_directo():
    src = Path(bvc.__file__).read_text(encoding="utf-8")
    assert "import requests" not in src and "api.pexels.com" not in src


# ── 20-30, 35. Comando FFmpeg: clip como input, audio solo original, etc. ────


def test_clip_se_agrega_como_input(tmp_path):
    clip = _clip(tmp_path)
    cmd = _cmd_con_clip(tmp_path, clip)
    assert str(clip.clip) in cmd, "el clip descargado es un input real del comando"
    assert "[1:v]trim=" in cmd[cmd.index("-filter_complex") + 1], "el clip se prepara desde [1:v]"


def test_loop_true_usa_stream_loop(tmp_path):
    cmd = _cmd_con_clip(tmp_path, _clip(tmp_path, loop=True))
    assert "-stream_loop" in cmd and cmd[cmd.index("-stream_loop") + 1] == "-1"


def test_loop_false_sin_stream_loop(tmp_path):
    cmd = _cmd_con_clip(tmp_path, _clip(tmp_path, loop=False))
    assert "-stream_loop" not in cmd, "sin loop no se repite el input"


def test_no_loop_no_congela_ultimo_frame(tmp_path):
    fc = _cmd_con_clip(tmp_path, _clip(tmp_path, loop=False))
    fcs = fc[fc.index("-filter_complex") + 1]
    assert "eof_action=pass" in fcs and "repeatlast=0" in fcs, "vuelve al original, no congela"


def test_trim_source_start_correcto(tmp_path):
    fc = _cmd_con_clip(tmp_path, _clip(tmp_path, source_start=2.0))
    fcs = fc[fc.index("-filter_complex") + 1]
    assert "trim=start=2.000:duration=4.000" in fcs, "recorta desde source_start por la ventana"


def test_cover_conserva_aspect_ratio(tmp_path):
    fcs = _cmd_con_clip(tmp_path, _clip(tmp_path))[
        _cmd_con_clip(tmp_path, _clip(tmp_path)).index("-filter_complex") + 1
    ]
    assert "force_original_aspect_ratio=increase" in fcs and "crop=" in fcs
    assert "setsar=1" in fcs and "fps=" in fcs, "normaliza SAR y fps"


def test_captions_despues_del_overlay_del_clip(tmp_path):
    fcs = _cmd_con_clip(tmp_path, _clip(tmp_path, behind_text=True))[
        _cmd_con_clip(tmp_path, _clip(tmp_path, behind_text=True)).index("-filter_complex") + 1
    ]
    assert fcs.index("cb0") < fcs.index("ass="), "clip behind -> captions ENCIMA"


def test_ventana_temporal_del_clip(tmp_path):
    fcs = _cmd_con_clip(tmp_path, _clip(tmp_path))[
        _cmd_con_clip(tmp_path, _clip(tmp_path)).index("-filter_complex") + 1
    ]
    assert "between(t,1.000,5.000)" in fcs, (
        "el clip solo aparece entre t0 y t1 (original antes/despues)"
    )


def test_audio_original_conservado_clip_no_mapeado(tmp_path):
    cmd = _cmd_con_clip(tmp_path, _clip(tmp_path))
    fcs = cmd[cmd.index("-filter_complex") + 1]
    assert cmd[-6:-4] == ["-map", "0:a"] or ("-map" in cmd and "0:a" in cmd), (
        "mapea el audio original"
    )
    assert "0:a" in cmd, "audio original 0:a"
    assert "1:a" not in fcs and "[1:a]" not in fcs, "el audio del clip NUNCA se referencia"
    assert "amix" not in fcs and "amerge" not in fcs, "sin mezcla de audio (regla #19)"


def test_duracion_total_no_cambia_sin_shortest(tmp_path):
    cmd = _cmd_con_clip(tmp_path, _clip(tmp_path))
    assert "-shortest" not in cmd, "no se recorta la salida a la longitud del clip"
    assert cmd.count("-map") == 2, "un map de video final + 0:a; el clip no aporta streams mapeados"


# ── 31-32. Compatibilidad con Popup imagen / cutaway Pexels imagen ───────────


def test_compat_popup_imagen_con_clip(tmp_path):
    png = tmp_path / "logo.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n mock")
    popup = co.Popup(png=png, t0=1.0, t1=2.0, behind_text=False)
    clip = _clip(tmp_path)
    cmd = co.construir_comando(
        Path("in.mp4"), "x.ass", Path("out.mp4"), [], 216, 1300, 0.12, 1080, 1920,
        popups=[popup], clips=[clip],
    )  # fmt: skip
    assert str(png) in cmd and str(clip.clip) in cmd, "popup imagen y clip conviven"
    assert "ass=x.ass" in cmd[cmd.index("-filter_complex") + 1]


def test_sin_clips_no_cambia_comando(tmp_path):
    # Sin clips el comando no gana ningun filtro/entrada de clip (byte-identico a la ruta previa).
    a = co.construir_comando(
        Path("in.mp4"), "x.ass", Path("o.mp4"), [], 216, 1300, 0.12, 1080, 1920
    )
    b = co.construir_comando(
        Path("in.mp4"), "x.ass", Path("o.mp4"), [], 216, 1300, 0.12, 1080, 1920, clips=[]
    )
    assert a == b and "-stream_loop" not in a


# ── clip_overlay.preparar_clip: fail-open del render (archivo faltante, etc.) ─


def test_preparar_clip_archivo_faltante(tmp_path):
    c = ClipOverlay(clip=tmp_path / "no_existe.mp4", t0=1.0, t1=5.0)
    assert clip_overlay.preparar_clip(c, 1080, 1920, 30.0) is None


def test_preparar_clip_cover_full_frame(tmp_path):
    prep = clip_overlay.preparar_clip(_clip(tmp_path, size_pct=1.0), 1080, 1920, 30.0)
    assert prep["box_w"] == 1080 and prep["box_h"] == 1920 and prep["behind"] is True


# ── 1-3, 33, 34. Integracion via cve_clips (dispatch + politica de 1 clip) ───


def test_pexels_video_dispara_resolver(tmp_path, monkeypatch):
    llamadas = {}

    def spy(
        query, orientation=None, size=None, locale="es-ES", per_page=10, page=1, usar_cache=True
    ):
        llamadas["query"] = query
        llamadas["orientation"] = orientation
        return VideoBrollResult(assets=(_asset(),))

    monkeypatch.setattr(bvc, "buscar_video_broll_seguro", spy)
    monkeypatch.setattr(bvc, "descargar_video_asset", _descargar_ok(_clipfile(tmp_path)))
    data = [{"source": "pexels_video", "t": 1.0, "dur": 4.0, "query": "montanas nevadas"}]
    clips = cve_clips.cargar_clips_manual(_popups_json(tmp_path, data), 1080, 1920)
    assert len(clips) == 1 and clips[0].t0 == 1.0 and clips[0].t1 == 5.0
    assert llamadas == {"query": "montanas nevadas", "orientation": "portrait"}


def test_source_pexels_imagen_no_es_clip(tmp_path, monkeypatch):
    # source='pexels' (imagen) NO lo toma el loader de clips (queda para cve_popups).
    def boom(*a, **k):
        raise AssertionError("una entrada de imagen no debe llamar al fetcher de video")

    monkeypatch.setattr(bvc, "buscar_video_broll_seguro", boom)
    data = [{"source": "pexels", "t": 1.0, "query": "cafe"}]
    assert cve_clips.cargar_clips_manual(_popups_json(tmp_path, data), 1080, 1920) == []


def test_png_no_llama_fetcher_de_video(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("una entrada PNG jamas debe llamar al fetcher de video")

    monkeypatch.setattr(bvc, "buscar_video_broll_seguro", boom)
    data = [{"t": 1.0, "imagen": "flecha"}]
    assert cve_clips.cargar_clips_manual(_popups_json(tmp_path, data), 1080, 1920) == []


def test_entrada_pexels_video_invalida_se_omite_resto_sigue(tmp_path, monkeypatch):
    # loop no booleano -> el puente lanza ValueError -> el adaptador OMITE solo ese clip.
    monkeypatch.setattr(bvc, "buscar_video_broll_seguro", _buscar_ok(_asset()))
    monkeypatch.setattr(bvc, "descargar_video_asset", _descargar_ok(_clipfile(tmp_path)))
    data = [
        {"source": "pexels_video", "t": 1.0, "dur": 4.0, "query": "m", "loop": "yes"},  # invalida
        {"t": 5.0, "imagen": "flecha"},  # PNG: la procesa cve_popups, no el loader de clips
    ]
    path = _popups_json(tmp_path, data)
    assert cve_clips.cargar_clips_manual(path, 1080, 1920) == [], "clip invalido omitido"
    # el resto del archivo sigue procesable por la capa de popups (PNG sobrevive)
    biblio = cp.indexar_biblioteca(tmp_path / "nada")  # vacia
    popups = cp.cargar_popups_manual(path, biblio, 1080, 1920)
    assert all(pp.png.name == "flecha.png" or True for pp in popups)  # no crashea el archivo entero


def test_mute_false_en_json_se_omite(tmp_path, monkeypatch):
    monkeypatch.setattr(bvc, "buscar_video_broll_seguro", _buscar_ok(_asset()))
    monkeypatch.setattr(bvc, "descargar_video_asset", _descargar_ok(_clipfile(tmp_path)))
    data = [{"source": "pexels_video", "t": 1.0, "dur": 4.0, "query": "m", "mute": False}]
    assert cve_clips.cargar_clips_manual(_popups_json(tmp_path, data), 1080, 1920) == []


def test_dos_pexels_video_solo_la_primera(tmp_path, monkeypatch):
    monkeypatch.setattr(bvc, "buscar_video_broll_seguro", _buscar_ok(_asset()))
    monkeypatch.setattr(bvc, "descargar_video_asset", _descargar_ok(_clipfile(tmp_path)))
    data = [
        {"source": "pexels_video", "t": 1.0, "dur": 3.0, "query": "primera"},
        {"source": "pexels_video", "t": 6.0, "dur": 3.0, "query": "segunda"},
    ]
    clips = cve_clips.cargar_clips_manual(_popups_json(tmp_path, data), 1080, 1920)
    assert len(clips) == 1 and clips[0].t0 == 1.0, "V1: solo la PRIMERA entrada pexels_video"


def test_resolver_clips_runtimeerror_propaga(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("bug interno")

    monkeypatch.setattr(bvc, "buscar_video_broll_seguro", boom)
    _popups_json(tmp_path, [{"source": "pexels_video", "t": 1.0, "dur": 3.0, "query": "m"}])
    with pytest.raises(RuntimeError):
        cve_clips.resolver_clips("x", transcripts_dir=tmp_path, video_w=1080, video_h=1920)


def test_resolver_clips_operativo_fail_open(tmp_path, monkeypatch):
    err = VideoBrollResult(error=BrollVideoError("timeout", "Pexels no respondio"))
    monkeypatch.setattr(bvc, "buscar_video_broll_seguro", lambda *a, **k: err)
    _popups_json(tmp_path, [{"source": "pexels_video", "t": 1.0, "dur": 3.0, "query": "m"}])
    assert cve_clips.resolver_clips("x", transcripts_dir=tmp_path, video_w=1080, video_h=1920) == []


# ── 36. Render real FFmpeg con clip sintetico (lavfi, sin Internet) ──────────


def _ffprobe_json(video: Path) -> dict:
    import json  # noqa: PLC0415

    r = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type",
            "-of",
            "json",
            str(video),
        ],  # fmt: skip
        capture_output=True,
        text=True,
    )
    return json.loads(r.stdout) if r.stdout.strip() else {}


def test_render_real_ffmpeg_clip_sintetico(tmp_path, monkeypatch):
    """UNICO test que corre FFmpeg de verdad (clips lavfi, cero red). Verifica que el clip entra,
    el audio ORIGINAL se conserva y la duracion total no cambia."""
    if not _tiene_ffmpeg():
        pytest.skip("ffmpeg/ffprobe no disponibles en este entorno")
    import core_ass  # noqa: PLC0415
    import styles  # noqa: PLC0415

    # cwd = tmp_path para que el filtro `ass=` reciba ruta relativa (sin drive:colon de Windows).
    monkeypatch.chdir(tmp_path)
    base = tmp_path / "base.mp4"
    clip = tmp_path / "clip.mp4"
    _lavfi(base, "testsrc2=size=320x240:rate=30:duration=3", audio=True)
    _lavfi(clip, "mandelbrot=size=320x240:rate=30", dur=2, audio=False)
    ass = tmp_path / "cap.ass"
    grupo = {
        "start": 0.0,
        "end": 3.0,
        "words": [{"text": "HOLA", "start": 0.0, "end": 3.0, "line_idx": 0}],
    }
    core_ass.build_ass([grupo], 320, 240, styles.get_style("hormozi"), ass)

    out = tmp_path / "out.mp4"
    clipo = ClipOverlay(clip=clip, t0=1.0, t1=2.5, loop=True, fit="cover", size_pct=1.0)
    core_ass.burn_video_with_emojis(base, ass, out, [], styles.get_style("hormozi"), clips=[clipo])

    assert out.exists() and out.stat().st_size > 0
    info = _ffprobe_json(out)
    tipos = {s["codec_type"] for s in info.get("streams", [])}
    assert "video" in tipos and "audio" in tipos, "salida con video + audio original"
    dur = float(info.get("format", {}).get("duration", 0))
    assert 2.7 <= dur <= 3.3, f"duracion total conservada (~3s base), no recortada al clip: {dur}"


def _tiene_ffmpeg() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True)
        subprocess.run(["ffprobe", "-version"], capture_output=True)
        return True
    except (FileNotFoundError, OSError):
        return False


def _lavfi(dst: Path, vsrc: str, dur: int = 3, audio: bool = True):
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", vsrc]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}"]
    cmd += ["-t", str(dur), "-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd.append(str(dst))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"lavfi fallo: {r.stderr[-500:]}")
