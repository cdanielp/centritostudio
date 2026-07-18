"""test_auto_v2.py — AutoConfig, compatibilidad clasica, checkpoints y E2E v2 (S37-B).

Sin red (autouse bloquea sockets), sin GPU, sin Whisper, sin DeepSeek, sin Pexels:
clipper/brain/transcripcion/reframe se mockean; los resolvers usan assets locales
sinteticos. El render FFmpeg del E2E es REAL (ASS real + burn real + A/V real).
"""

from __future__ import annotations

import builtins
import json
import subprocess
from pathlib import Path

import pytest

import auto
import auto_v2
from auto_config import PIPELINE_VERSION, AutoConfig, AutoConfigError


@pytest.fixture(autouse=True)
def _sin_red(monkeypatch):
    import socket

    def _bloqueado(*a, **k):
        raise RuntimeError("red bloqueada en tests (S37-B)")

    monkeypatch.setattr(socket.socket, "connect", _bloqueado)


# ── AutoConfig ───────────────────────────────────────────────────────────────


def test_config_default_classic():
    c = AutoConfig()
    assert c.mode == "classic" and c.fx_preset == "express"
    assert c.broll_enabled is True and c.verify_av is True


def test_config_v2_explicito():
    assert AutoConfig(mode="v2").mode == "v2"


def test_config_mode_invalido():
    with pytest.raises(AutoConfigError):
        AutoConfig(mode="turbo")


def test_config_bool_invalido():
    with pytest.raises(AutoConfigError):
        AutoConfig(broll_enabled="si")
    with pytest.raises(AutoConfigError):
        AutoConfig(verify_av=1)


def test_config_preset_invalido():
    with pytest.raises(AutoConfigError):
        AutoConfig(fx_preset="cinematic")


def test_config_target_mayor_que_max():
    with pytest.raises(AutoConfigError):
        AutoConfig(target_coverage_pct=0.5, max_coverage_pct=0.3)


def test_config_max_video_windows_v1():
    with pytest.raises(AutoConfigError):
        AutoConfig(max_video_windows=2)
    with pytest.raises(AutoConfigError):
        AutoConfig(max_video_windows=True)


def test_fingerprint_estable():
    assert AutoConfig(mode="v2").fingerprint() == AutoConfig(mode="v2").fingerprint()


def test_fingerprint_cambia_con_config():
    assert (
        AutoConfig(mode="v2").fingerprint() != AutoConfig(mode="v2", fx_preset="pro").fingerprint()
    )
    assert AutoConfig().fingerprint() != AutoConfig(mode="v2").fingerprint()


def test_fingerprint_incluye_pipeline_version():
    d = AutoConfig().to_dict()
    assert d["pipeline_version"] == PIPELINE_VERSION


def test_config_serializable_sin_secretos():
    texto = json.dumps(AutoConfig(mode="v2").to_dict())
    assert "key" not in texto.lower() and "path" not in texto.lower()


def test_config_frozen():
    c = AutoConfig()
    with pytest.raises(AttributeError):
        c.mode = "v2"


def test_broll_config_de_mapea_campos():
    c = AutoConfig(
        mode="v2",
        target_coverage_pct=0.3,
        max_coverage_pct=0.4,
        hook_protected_s=2.0,
        max_video_windows=0,
        fx_preset="premium",
    )
    b = auto_v2.broll_config_de(c)
    assert b.target_coverage_pct == 0.3 and b.max_coverage_pct == 0.4
    assert b.hook_protected_s == 2.0 and b.max_video_windows == 0
    assert b.fx_preset == "premium"


def test_broll_config_sin_fx_no_reserva_outro():
    c = AutoConfig(mode="v2", fx_preset="premium", fx_enabled=False)
    assert auto_v2.broll_config_de(c).fx_preset == "express"  # sin FX no hay outro


# ── Entorno compartido (estilo test_contrato_auto) ───────────────────────────


def _seg(**kw):
    base = {
        "seg": 0,
        "t_ini": 0.0,
        "t_fin": 10.0,
        "tipo": "single",
        "n_caras": 1,
        "n_paneos": 0,
        "c1v2": 95.0,
        "n_det_vivas": 20,
    }
    base.update(kw)
    return base


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    transcripts = tmp_path / "transcripts"
    clips_dir = tmp_path / "clips"
    paquetes = tmp_path / "paquetes"
    for d in (transcripts, clips_dir, paquetes):
        d.mkdir()
    monkeypatch.setattr(auto, "TRANSCRIPTS", transcripts)
    monkeypatch.setattr(auto, "CLIPS_DIR", clips_dir)
    monkeypatch.setattr(auto, "PAQUETES_DIR", paquetes)
    monkeypatch.setattr(auto, "ROOT", tmp_path)
    (tmp_path / "output").mkdir()
    video = tmp_path / "vid.mp4"
    video.write_bytes(b"fake")
    (transcripts / "vid_words.json").write_text(
        json.dumps({"words": [{"w": "hola", "s": 0.0, "e": 0.5, "prob": 0.9}], "language": "es"}),
        encoding="utf-8",
    )
    grupos = [{"id": 0, "start": 0.0, "end": 1.0, "text": "hola", "words": []}]
    (transcripts / "vid_clip1_corto_words.json").write_text(
        json.dumps({"words": [], "language": "es"}), encoding="utf-8"
    )
    (transcripts / "vid_clip1_corto_groups.json").write_text(json.dumps(grupos), encoding="utf-8")
    (clips_dir / "vid_clip1_corto.mp4").write_bytes(b"fake-clip")
    return {
        "video": video,
        "transcripts": transcripts,
        "clips_dir": clips_dir,
        "paquetes": paquetes,
    }


def _mock_motor_classic(monkeypatch):
    import assets_comfy
    import brain
    import clipper
    import core
    import reframe

    def fake_generar_clips(mp4, words, tipos):
        return {
            "clips": [
                {
                    "archivo": "vid_clip1_corto.mp4",
                    "titulo": "T",
                    "razon": "R",
                    "score": 88,
                    "dur_s": 30.0,
                }
            ],
            "casi": [],
            "telemetria_resumen": {"costo_usd": 0.001},
        }

    def fake_reframe(clip_path, output_path, **kw):
        output_path.write_bytes(b"fake-9x16")
        return {"output": str(output_path), "segmentos": [_seg()]}

    monkeypatch.setattr(clipper, "generar_clips", fake_generar_clips)
    monkeypatch.setattr(reframe, "reframe_clip", fake_reframe)
    monkeypatch.setattr(
        brain, "analizar_grupos", lambda g, **k: (_ for _ in ()).throw(RuntimeError("sin key"))
    )
    monkeypatch.setattr(assets_comfy, "resolver_overlays", lambda *a: [])
    monkeypatch.setattr(core, "get_video_info", lambda p: {"width": 1080, "height": 1920})
    monkeypatch.setattr(core, "build_ass", lambda *a, **k: None)

    def fake_burn(inp, ass, out, overlays, style_cfg):
        out.write_bytes(b"fake-final")
        return 1.0

    monkeypatch.setattr(core, "burn_video_with_emojis", fake_burn)


# ── Compatibilidad clasica ───────────────────────────────────────────────────


def test_classic_sin_config_ruta_historica(entorno, monkeypatch):
    _mock_motor_classic(monkeypatch)
    r = auto.ejecutar_auto(entorno["video"], "vid")
    assert r["clips"] and "pipeline_mode" not in r["meta"]
    assert "_v2_" not in r["paquete"]


def test_classic_config_explicita_identica(entorno, monkeypatch):
    _mock_motor_classic(monkeypatch)
    r = auto.ejecutar_auto(entorno["video"], "vid", config=AutoConfig())
    assert "pipeline_mode" not in r["meta"]
    assert "_v2_" not in r["paquete"]


def test_classic_no_genera_sidecars_s37(entorno, monkeypatch):
    _mock_motor_classic(monkeypatch)
    auto.ejecutar_auto(entorno["video"], "vid")
    nombres = [p.name for p in entorno["transcripts"].iterdir()]
    assert not any("broll" in n or "auto.json" in n for n in nombres)


def test_classic_no_llama_capa_v2(entorno, monkeypatch):
    _mock_motor_classic(monkeypatch)

    def bomba(*a, **k):
        raise AssertionError("classic no debe tocar la capa v2")

    monkeypatch.setattr(auto_v2, "procesar_clip_v2", bomba)
    import auto_broll

    monkeypatch.setattr(auto_broll, "resolver_plan", bomba)
    r = auto.ejecutar_auto(entorno["video"], "vid")
    assert r["clips"]


def test_classic_no_importa_pexels_ni_planner(entorno, monkeypatch):
    _mock_motor_classic(monkeypatch)
    prohibidos = {
        "broll_stock",
        "broll_video_stock",
        "broll_cutaway",
        "broll_video_cutaway",
        "broll_planner",
        "fx",
    }
    importados: set[str] = set()
    real_import = builtins.__import__

    def spy(name, *a, **k):
        importados.add(name.split(".")[0])
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", spy)
    auto.ejecutar_auto(entorno["video"], "vid")
    assert not (importados & prohibidos)


def test_classic_reporte_sin_seccion_v2(entorno, monkeypatch):
    _mock_motor_classic(monkeypatch)
    r = auto.ejecutar_auto(entorno["video"], "vid")
    paquete = Path(entorno["paquetes"]) / Path(r["paquete"]).name
    md = (paquete / "REPORTE.md").read_text(encoding="utf-8")
    assert "Modo Automatico v2" not in md


def test_reporte_golden_sin_campos_v2():
    from auto_report import _lineas_v2_paquete, generar_reporte_md

    clips = [
        {
            "archivo": "a.mp4",
            "titulo": "T",
            "dur_s": 10.0,
            "avisos": [],
            "emojis_msg": "sin overlays",
        }
    ]
    assert _lineas_v2_paquete(clips) == []
    md = generar_reporte_md("vid", clips, {"fecha": "x", "t_total_s": 1})
    assert "Modo Automatico v2" not in md


def test_reporte_con_clip_v2_agrega_seccion():
    from auto_report import _lineas_v2_paquete

    clip = {
        "pipeline_mode": "v2",
        "broll": {
            "planned": 2,
            "resolved": 2,
            "images": 1,
            "videos": 1,
            "fallbacks": 0,
            "blocked": 0,
            "omitted": 0,
            "manual_popups": 0,
            "manual_clips": 0,
            "plan_sidecar": "p.json",
            "auto_sidecar": "a.json",
            "resolved_sidecar": "r.json",
        },
        "fx": {"preset": "express", "removed": []},
        "av": {"integrity": {"status": "pass"}, "sync": {"status": "pass"}},
    }
    lineas = _lineas_v2_paquete([clip])
    texto = "\n".join(lineas)
    assert "Modo Automatico v2" in texto and "audio pass" in texto


# ── Paquetes classic/v2 separados ────────────────────────────────────────────


def test_paquete_classic_excluye_v2(entorno):
    v2_dir = entorno["paquetes"] / "vid_v2_20260718-0001"
    v2_dir.mkdir()
    d, reanudado = auto._paquete_dir("vid")
    assert reanudado is False and "_v2_" not in d.name


def test_paquete_v2_crea_marker(entorno):
    d, reanudado = auto._paquete_dir_v2("vid", "fp-1")
    assert reanudado is False and d.name.startswith("vid_v2_")
    marker = json.loads((d / "auto_v2.json").read_text(encoding="utf-8"))
    assert marker["config_fingerprint"] == "fp-1"


def test_paquete_v2_reanuda_mismo_fingerprint(entorno):
    d1, _ = auto._paquete_dir_v2("vid", "fp-1")
    d2, reanudado = auto._paquete_dir_v2("vid", "fp-1")
    assert d2 == d1 and reanudado is True


def test_paquete_v2_fingerprint_distinto_crea_nuevo(entorno):
    d1, _ = auto._paquete_dir_v2("vid", "fp-1")
    d2, reanudado = auto._paquete_dir_v2("vid", "fp-2")
    assert d2 != d1 and reanudado is False
    assert d1.exists()  # el anterior no se destruye


def test_paquete_v2_no_reanuda_classic(entorno):
    (entorno["paquetes"] / "vid_20260718-0001").mkdir()
    d, reanudado = auto._paquete_dir_v2("vid", "fp-1")
    assert reanudado is False and d.name.startswith("vid_v2_")


def test_paquete_v2_completo_no_se_reanuda(entorno):
    d1, _ = auto._paquete_dir_v2("vid", "fp-1")
    (d1 / "paquete.json").write_text("{}", encoding="utf-8")
    d2, reanudado = auto._paquete_dir_v2("vid", "fp-1")
    assert d2 != d1 and reanudado is False


# ── checkpoint_v2_valido ─────────────────────────────────────────────────────


def _info_v2(fingerprint, transcripts, final_path, stem="c1"):
    nombres = {
        "plan_sidecar": f"{stem}_broll_plan.json",
        "auto_sidecar": f"{stem}_popups.auto.json",
        "resolved_sidecar": f"{stem}_broll_resolved.json",
    }
    for n in nombres.values():
        (transcripts / n).write_text("{}", encoding="utf-8")
    # el resolved debe pertenecer al MISMO fingerprint (transcripts/ es compartido)
    (transcripts / nombres["resolved_sidecar"]).write_text(
        json.dumps({"config_fingerprint": fingerprint}), encoding="utf-8"
    )
    final_path.write_bytes(b"mp4")
    return {
        "pipeline_mode": "v2",
        "config_fingerprint": fingerprint,
        "av": {"integrity": {"status": "pass"}, "sync": {"status": "pass"}},
        "broll": nombres,
    }


def test_checkpoint_v2_valido_ok(tmp_path):
    info = _info_v2("fp", tmp_path, tmp_path / "f.mp4")
    assert auto_v2.checkpoint_v2_valido(info, "fp", tmp_path / "f.mp4", tmp_path) is True


def test_checkpoint_fingerprint_distinto(tmp_path):
    info = _info_v2("fp", tmp_path, tmp_path / "f.mp4")
    assert auto_v2.checkpoint_v2_valido(info, "otro", tmp_path / "f.mp4", tmp_path) is False


def test_checkpoint_classic_no_pasa_como_v2(tmp_path):
    info = {"archivo": "x.mp4"}  # sidecar clasico: sin pipeline_mode
    assert auto_v2.checkpoint_v2_valido(info, "fp", tmp_path / "f.mp4", tmp_path) is False


def test_checkpoint_av_fail_no_se_reutiliza(tmp_path):
    info = _info_v2("fp", tmp_path, tmp_path / "f.mp4")
    info["av"]["sync"]["status"] = "fail"
    assert auto_v2.checkpoint_v2_valido(info, "fp", tmp_path / "f.mp4", tmp_path) is False


def test_checkpoint_sidecar_faltante(tmp_path):
    info = _info_v2("fp", tmp_path, tmp_path / "f.mp4")
    (tmp_path / "c1_broll_plan.json").unlink()
    assert auto_v2.checkpoint_v2_valido(info, "fp", tmp_path / "f.mp4", tmp_path) is False


def test_checkpoint_output_faltante(tmp_path):
    info = _info_v2("fp", tmp_path, tmp_path / "f.mp4")
    (tmp_path / "f.mp4").unlink()
    assert auto_v2.checkpoint_v2_valido(info, "fp", tmp_path / "f.mp4", tmp_path) is False


def test_checkpoint_no_audio_es_valido(tmp_path):
    info = _info_v2("fp", tmp_path, tmp_path / "f.mp4")
    info["av"] = {"integrity": {"status": "no_audio"}, "sync": {"status": "no_audio"}}
    assert auto_v2.checkpoint_v2_valido(info, "fp", tmp_path / "f.mp4", tmp_path) is True


def test_checkpoint_av_skipped_valido_con_mismo_fingerprint(tmp_path):
    # verify_av=False escribe {"skipped": True}; el fingerprint incluye verify_av,
    # asi que un match de fingerprint implica la misma politica -> reutilizable.
    info = _info_v2("fp", tmp_path, tmp_path / "f.mp4")
    info["av"] = {"skipped": True}
    assert auto_v2.checkpoint_v2_valido(info, "fp", tmp_path / "f.mp4", tmp_path) is True


def test_checkpoint_resolved_de_otro_fingerprint_no_se_reutiliza(tmp_path):
    # otra corrida v2 (config distinta) sobreescribio el resolved en transcripts/
    info = _info_v2("fp", tmp_path, tmp_path / "f.mp4")
    (tmp_path / "c1_broll_resolved.json").write_text(
        json.dumps({"config_fingerprint": "otro"}), encoding="utf-8"
    )
    assert auto_v2.checkpoint_v2_valido(info, "fp", tmp_path / "f.mp4", tmp_path) is False


# ── E2E v2 sin red (render FFmpeg REAL) ──────────────────────────────────────


def _ffmpeg(*args):
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", *args], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-500:]


def _grupos_reales():
    def g(gid, start, end, texto):
        palabras = texto.split()
        paso = (end - start) / len(palabras)
        words = [
            {
                "text": w,
                "start": round(start + i * paso, 3),
                "end": round(start + (i + 1) * paso, 3),
                "line_idx": 0 if i < 3 else 1,
            }
            for i, w in enumerate(palabras)
        ]
        return {"id": gid, "start": start, "end": end, "text": texto, "words": words}

    return [
        g(0, 0.0, 3.0, "Bienvenidos al taller de cafe"),
        g(1, 3.0, 8.0, "Ahora conectamos la maquina nueva"),
        g(2, 8.0, 12.0, "El aroma llena la cocina"),
    ]


@pytest.fixture
def entorno_e2e(entorno, tmp_path, monkeypatch):
    """Entorno v2 con motores mockeados, assets locales y render real."""
    import assets_comfy
    import auto_broll
    import brain
    import clipper
    import reframe

    # El filtro ass usa rutas relativas al cwd (asi corre produccion desde la raiz del
    # repo); con ROOT en tmp el cwd debe ser tmp para que la ruta no lleve "C:".
    monkeypatch.chdir(tmp_path)

    clip_real = tmp_path / "clip_real.mp4"
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "color=c=0x224466:size=216x384:rate=30",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=330:sample_rate=44100",
        "-t",
        "12",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "30",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(clip_real),
    )
    (entorno["clips_dir"] / "vid_clip1_corto.mp4").write_bytes(clip_real.read_bytes())

    png = tmp_path / "broll_img.png"
    _ffmpeg("-f", "lavfi", "-i", "color=c=orange:size=200x200", "-frames:v", "1", str(png))
    broll_vid = tmp_path / "broll_vid.mp4"
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=216x384:rate=30",
        "-t",
        "6",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "30",
        "-pix_fmt",
        "yuv420p",
        str(broll_vid),
    )

    grupos = _grupos_reales()
    (entorno["transcripts"] / "vid_clip1_corto_groups.json").write_text(
        json.dumps(grupos, ensure_ascii=False), encoding="utf-8"
    )

    monkeypatch.setattr(
        clipper,
        "generar_clips",
        lambda *a, **k: {
            "clips": [
                {
                    "archivo": "vid_clip1_corto.mp4",
                    "titulo": "T",
                    "razon": "R",
                    "score": 88,
                    "dur_s": 12.0,
                }
            ],
            "casi": [],
            "telemetria_resumen": {"costo_usd": 0.0},
        },
    )

    def fake_reframe(clip_path, output_path, **kw):
        output_path.write_bytes(Path(clip_path).read_bytes())  # ya es 9:16 sintetico
        return {"output": str(output_path), "segmentos": [_seg(t_fin=12.0)]}

    monkeypatch.setattr(reframe, "reframe_clip", fake_reframe)
    monkeypatch.setattr(
        brain,
        "analizar_grupos",
        lambda g, **k: {
            "groups": [
                {"g": 1, "kw": 1, "emoji": None, "kw_ts": 4.0},
                {"g": 2, "kw": 1, "emoji": None, "kw_ts": 9.0},
            ]
        },
    )
    monkeypatch.setattr(assets_comfy, "resolver_overlays", lambda *a: [])
    import caption_qa

    monkeypatch.setattr(caption_qa, "qa_para_reporte", lambda stem: None)

    from types import SimpleNamespace

    from core_overlays import Popup

    def fake_img(query, t0, t1, w, h):
        asset = SimpleNamespace(
            provider="pexels", asset_id="img-1", author="A", width=200, height=200, local_path=png
        )
        popup = Popup(
            png=png,
            t0=t0,
            t1=t1,
            pos="center",
            size_pct=1.0,
            behind_text=True,
            cutaway=True,
            fit="cover",
        )
        return SimpleNamespace(popup=popup, codigo="ok", mensaje="ok", asset=asset)

    video_asset = SimpleNamespace(
        provider="pexels",
        asset_id="vid-1",
        author="B",
        width=216,
        height=384,
        duration=6,
        selected_file_id="f1",
        local_path=broll_vid,
    )
    monkeypatch.setattr(auto_broll, "_resolve_image", fake_img)
    monkeypatch.setattr(
        auto_broll,
        "_search_videos",
        lambda q, w, h: SimpleNamespace(error=None, assets=(video_asset,)),
    )
    monkeypatch.setattr(auto_broll, "_download_video", lambda a, w, h: a)
    return entorno


CFG_E2E = AutoConfig(mode="v2", target_coverage_pct=0.9, max_coverage_pct=0.95)


@pytest.fixture
def resultado_e2e(entorno_e2e):
    return auto.ejecutar_auto(entorno_e2e["video"], "vid", config=CFG_E2E)


def test_e2e_produce_mp4_9x16(resultado_e2e, entorno_e2e):
    import core

    paquete = entorno_e2e["paquetes"] / Path(resultado_e2e["paquete"]).name
    finales = list(paquete.glob("*.mp4"))
    assert len(finales) == 1
    info = core.get_video_info(finales[0])
    assert (info["width"], info["height"]) == (216, 384)  # 9:16
    assert info["has_audio"] is True


def test_e2e_paquete_v2_distinguible(resultado_e2e):
    assert "_v2_" in resultado_e2e["paquete"]


def test_e2e_sidecars_generados(resultado_e2e, entorno_e2e):
    t = entorno_e2e["transcripts"]
    assert (t / "vid_clip1_corto_9x16_broll_plan.json").exists()
    assert (t / "vid_clip1_corto_9x16_popups.auto.json").exists()
    assert (t / "vid_clip1_corto_9x16_broll_resolved.json").exists()


def test_e2e_popups_auto_imagen_y_video(resultado_e2e, entorno_e2e):
    entradas = json.loads(
        (entorno_e2e["transcripts"] / "vid_clip1_corto_9x16_popups.auto.json").read_text(
            encoding="utf-8"
        )
    )
    fuentes = sorted(e["source"] for e in entradas)
    assert fuentes == ["pexels", "pexels_video"]
    vid = next(e for e in entradas if e["source"] == "pexels_video")
    assert vid["loop"] is False and vid["mute"] is True


def test_e2e_info_v2_completo(resultado_e2e):
    info = resultado_e2e["clips"][0]
    assert info["pipeline_mode"] == "v2"
    assert info["pipeline_version"] == PIPELINE_VERSION
    assert info["config_fingerprint"] == CFG_E2E.fingerprint()
    assert info["broll"]["videos"] == 1 and info["broll"]["images"] == 1
    assert info["av"]["integrity"]["status"] == "pass"
    assert info["av"]["sync"]["status"] == "pass"


def test_e2e_av_verificado_contra_fuente(resultado_e2e):
    av = resultado_e2e["clips"][0]["av"]
    assert av["integrity"]["packet_count_source"] == av["integrity"]["packet_count_output"]
    assert av["sync"]["audio_start_delta_s"] <= 0.05


def test_e2e_reporte_incluye_seccion_v2(resultado_e2e, entorno_e2e):
    paquete = entorno_e2e["paquetes"] / Path(resultado_e2e["paquete"]).name
    md = (paquete / "REPORTE.md").read_text(encoding="utf-8")
    assert "Modo Automatico v2" in md and "audio pass" in md


def test_e2e_meta_v2(resultado_e2e):
    meta = resultado_e2e["meta"]
    assert meta["pipeline_mode"] == "v2"
    assert meta["config_fingerprint"] == CFG_E2E.fingerprint()


def test_e2e_resolved_auditable(resultado_e2e, entorno_e2e):
    resolved = json.loads(
        (entorno_e2e["transcripts"] / "vid_clip1_corto_9x16_broll_resolved.json").read_text(
            encoding="utf-8"
        )
    )
    assert resolved["mode"] == "v2" and resolved["cache_policy"] == "existing_fetcher_cache"
    assert resolved["final"]["videos"] == 1 and resolved["final"]["images"] == 1
    texto = json.dumps(resolved)
    assert "http" not in texto


def test_e2e_manual_sidecar_no_creado(resultado_e2e, entorno_e2e):
    # el pipeline v2 jamas escribe el sidecar MANUAL
    assert not (entorno_e2e["transcripts"] / "vid_clip1_corto_9x16_popups.json").exists()


def test_e2e_reanudacion_no_rerenderiza(entorno_e2e, monkeypatch):
    r1 = auto.ejecutar_auto(entorno_e2e["video"], "vid", config=CFG_E2E)
    # simular corrida interrumpida: el paquete queda incompleto (sin paquete.json)
    paquete = entorno_e2e["paquetes"] / Path(r1["paquete"]).name
    (paquete / "paquete.json").unlink()
    llamadas = []
    real = auto_v2.procesar_clip_v2

    def spy(*a, **k):
        llamadas.append(1)
        return real(*a, **k)

    monkeypatch.setattr(auto_v2, "procesar_clip_v2", spy)
    r2 = auto.ejecutar_auto(entorno_e2e["video"], "vid", config=CFG_E2E)
    assert llamadas == []  # checkpoint valido: sin re-render
    assert r2["clips"][0]["config_fingerprint"] == r1["clips"][0]["config_fingerprint"]


def test_e2e_fingerprint_distinto_rerenderiza(entorno_e2e, monkeypatch):
    auto.ejecutar_auto(entorno_e2e["video"], "vid", config=CFG_E2E)
    llamadas = []
    real = auto_v2.procesar_clip_v2

    def spy(*a, **k):
        llamadas.append(1)
        return real(*a, **k)

    monkeypatch.setattr(auto_v2, "procesar_clip_v2", spy)
    otra = AutoConfig(mode="v2", target_coverage_pct=0.5, max_coverage_pct=0.6)
    auto.ejecutar_auto(entorno_e2e["video"], "vid", config=otra)
    assert llamadas == [1]  # paquete y checkpoint nuevos


def test_e2e_broll_disabled_sin_ventanas(entorno_e2e):
    cfg = AutoConfig(mode="v2", broll_enabled=False)
    r = auto.ejecutar_auto(entorno_e2e["video"], "vid", config=cfg)
    info = r["clips"][0]
    assert info["broll"]["resolved"] == 0
    entradas = json.loads(
        (Path(auto.TRANSCRIPTS) / "vid_clip1_corto_9x16_popups.auto.json").read_text(
            encoding="utf-8"
        )
    )
    assert entradas == []
