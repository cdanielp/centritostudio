"""HF-4 Formato dual en Modo Automatico v2: `procesar_clip_v2` con broll real (FFmpeg real,
Pexels/brain mockeados como espias) para probar, de punta a punta y no solo por unidad, que
una corrida "ambos" reencuadra UNA vez, llama al brain UNA vez, consulta los fetchers de
broll UNA vez por cue (nunca una vez por formato), y produce dos MP4 + dos juegos de sidecars
sin colision.

Fuente HORIZONTAL a proposito (a diferencia de `entorno_e2e` en test_auto_v2.py, que usa un
clip ya "9:16-shaped" porque el mock de reframe solo copia bytes): sin una fuente horizontal,
`auto_formato.formatos_pedidos("16:9", ...)` omite la pierna 16:9 (sin ruta de reencuadre
vertical->horizontal) y el test no ejercitaria nada nuevo.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_auto_v2 import _ffmpeg, _grupos_reales, _seg, entorno  # noqa: F401 (fixture reexport)

import auto
from auto_config import AutoConfig


@pytest.fixture
def entorno_e2e_horizontal(entorno, tmp_path, monkeypatch):  # noqa: F811 (fixture reexport)
    import assets_comfy
    import auto_broll
    import brain
    import clipper
    import reframe

    monkeypatch.chdir(tmp_path)

    clip_real = tmp_path / "clip_real.mp4"
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "color=c=0x224466:size=384x216:rate=30",
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

    llamadas = {"reframe": 0, "brain": 0, "resolve_image": 0, "search_videos": 0}

    def fake_reframe(clip_path, output_path, **kw):
        llamadas["reframe"] += 1
        # copia real 384x216 -> "9x16.mp4": las dimensiones no importan para este test, solo
        # el CONTEO de llamadas (una fuente horizontal real con reencuadre real es el objetivo
        # de la corrida hf_real de evidencia, no de este test rapido).
        output_path.write_bytes(Path(clip_path).read_bytes())
        return {"output": str(output_path), "segmentos": [_seg(t_fin=12.0)]}

    monkeypatch.setattr(reframe, "reframe_clip", fake_reframe)

    def fake_analizar(g, **k):
        llamadas["brain"] += 1
        return {"groups": [{"g": 1, "kw": 1, "emoji": None, "kw_ts": 4.0}]}

    monkeypatch.setattr(brain, "analizar_grupos", fake_analizar)
    monkeypatch.setattr(assets_comfy, "resolver_overlays", lambda *a: [])

    import caption_qa

    monkeypatch.setattr(caption_qa, "qa_para_reporte", lambda stem, words_path=None: None)

    def fake_img(query, t0, t1, w, h):
        llamadas["resolve_image"] += 1
        asset = SimpleNamespace(
            provider="pexels", asset_id="img-1", author="A", width=200, height=200, local_path=png
        )
        from core_overlays import Popup

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

    def fake_search_videos(q, w, h):
        llamadas["search_videos"] += 1
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
        return SimpleNamespace(error=None, assets=(video_asset,))

    monkeypatch.setattr(auto_broll, "_resolve_image", fake_img)
    monkeypatch.setattr(auto_broll, "_search_videos", fake_search_videos)
    monkeypatch.setattr(auto_broll, "_download_video", lambda a, w, h: a)

    entorno["llamadas"] = llamadas
    return entorno


CFG_AMBOS = AutoConfig(mode="v2", formato="ambos", target_coverage_pct=0.9, max_coverage_pct=0.95)
CFG_16X9 = AutoConfig(mode="v2", formato="16:9", target_coverage_pct=0.9, max_coverage_pct=0.95)


def test_ambos_produce_dos_mp4(entorno_e2e_horizontal):
    r = auto.ejecutar_auto(entorno_e2e_horizontal["video"], "vid", config=CFG_AMBOS)
    paquete = entorno_e2e_horizontal["paquetes"] / Path(r["paquete"]).name
    finales = sorted(p.name for p in paquete.glob("*_hormozi.mp4"))
    assert finales == ["vid_clip1_corto_16x9_hormozi.mp4", "vid_clip1_corto_9x16_hormozi.mp4"]
    assert len(r["clips"]) == 2


def test_ambos_reencuadra_una_sola_vez(entorno_e2e_horizontal):
    auto.ejecutar_auto(entorno_e2e_horizontal["video"], "vid", config=CFG_AMBOS)
    assert entorno_e2e_horizontal["llamadas"]["reframe"] == 1


def test_ambos_llama_al_brain_una_sola_vez(entorno_e2e_horizontal):
    auto.ejecutar_auto(entorno_e2e_horizontal["video"], "vid", config=CFG_AMBOS)
    assert entorno_e2e_horizontal["llamadas"]["brain"] == 1


def test_ambos_consulta_pexels_una_sola_vez_por_cue_no_por_formato(entorno_e2e_horizontal):
    """Referencia: una corrida SOLO 9:16 con la misma config/cobertura pide N imagenes y M
    videos. Una corrida "ambos" debe pedir EXACTAMENTE las mismas N y M -- nunca 2N/2M."""
    r_916 = auto.ejecutar_auto(entorno_e2e_horizontal["video"], "vid", config=CFG_AMBOS)
    llamadas_ambos = dict(entorno_e2e_horizontal["llamadas"])
    assert r_916["clips"]

    assert llamadas_ambos["resolve_image"] + llamadas_ambos["search_videos"] >= 1
    # el numero exacto depende del planner de b-roll (no es el foco aqui); el foco es que
    # "ambos" no dobla lo que pediria un solo formato con la MISMA cobertura -- se verifica
    # comparando contra una corrida 9:16 sola sobre un paquete nuevo (config distinta).
    cfg_916_sola = AutoConfig(
        mode="v2", formato="9:16", target_coverage_pct=0.9, max_coverage_pct=0.95
    )
    entorno_e2e_horizontal["llamadas"]["resolve_image"] = 0
    entorno_e2e_horizontal["llamadas"]["search_videos"] = 0
    auto.ejecutar_auto(entorno_e2e_horizontal["video"], "vid", config=cfg_916_sola)
    llamadas_916_sola = dict(entorno_e2e_horizontal["llamadas"])
    assert llamadas_ambos["resolve_image"] == llamadas_916_sola["resolve_image"]
    assert llamadas_ambos["search_videos"] == llamadas_916_sola["search_videos"]


def test_ambos_escribe_sidecares_de_broll_solo_para_la_primaria(entorno_e2e_horizontal):
    """El broll se resuelve una vez, bajo el nombre de la pierna primaria (9:16): no hay un
    segundo juego de sidecars de broll para el 16:9, porque son los MISMOS datos reusados."""
    auto.ejecutar_auto(entorno_e2e_horizontal["video"], "vid", config=CFG_AMBOS)
    t = entorno_e2e_horizontal["transcripts"]
    assert (t / "vid_clip1_corto_9x16_broll_plan.json").exists()
    assert not (t / "vid_clip1_corto_16x9_broll_plan.json").exists()


def test_16x9_solo_no_reencuadra(entorno_e2e_horizontal):
    auto.ejecutar_auto(entorno_e2e_horizontal["video"], "vid", config=CFG_16X9)
    assert entorno_e2e_horizontal["llamadas"]["reframe"] == 0


def test_16x9_solo_produce_un_mp4_con_sufijo_16x9(entorno_e2e_horizontal):
    r = auto.ejecutar_auto(entorno_e2e_horizontal["video"], "vid", config=CFG_16X9)
    assert len(r["clips"]) == 1
    assert r["clips"][0]["archivo"] == "vid_clip1_corto_16x9_hormozi.mp4"


def test_meta_formato_ambos(entorno_e2e_horizontal):
    r = auto.ejecutar_auto(entorno_e2e_horizontal["video"], "vid", config=CFG_AMBOS)
    assert r["meta"]["formato"] == "ambos"


# ── Letreros: el sello de la pierna sin reencuadre usa SU PROPIO nombre ──────
#
# Bug real detectado en la corrida de evidencia real (hf_real): la pierna 16:9 quema desde la
# fuente compartida (sin reencuadrar), y sellar su plan bajo el nombre de ESA fuente compartida
# (sin sufijo de formato) dejaba el sidecar bajo un nombre que el editor nunca pide y que
# ademas podria colisionar con cualquier otro consumidor de la fuente. `clip_identidad` en
# auto_v2.procesar_clip_v2 separa "de donde se quema" de "bajo que nombre se sella".


def test_ambos_con_letreros_sella_el_16x9_bajo_su_propio_nombre_no_el_de_la_fuente(
    entorno_e2e_horizontal, monkeypatch
):
    import motion_capa
    import motion_plan as mp

    llamadas_clip_mp4 = []
    # plan NO vacio y NO None: si la primaria devolviera plan=None, _capa_motion_otro_formato
    # cortaria ANTES de llamar a clips_de_motion (fail-open de "sin plan primario, sin pierna
    # extra") y el espia solo veria la llamada primaria, sin probar nada del bug real.
    plan_falso = mp.PlanMotion(orientacion="vertical", piezas=())

    def espia(**kw):
        llamadas_clip_mp4.append(Path(kw["clip_mp4"]).stem if kw.get("clip_mp4") else None)
        return motion_capa.ResultadoMotion((), {"enabled": True, "plan": None}, plan=plan_falso)

    monkeypatch.setattr(motion_capa, "clips_de_motion", espia)
    cfg = AutoConfig(
        mode="v2",
        formato="ambos",
        motion_enabled=True,
        motion_nombre="K",
        motion_textos_llm=False,
        target_coverage_pct=0.9,
        max_coverage_pct=0.95,
    )
    auto.ejecutar_auto(entorno_e2e_horizontal["video"], "vid", config=cfg)

    assert llamadas_clip_mp4 == ["vid_clip1_corto_9x16", "vid_clip1_corto_16x9"]
    # nunca el stem de la fuente compartida sin sufijo: eso pisaria/perderia el sello
    assert "vid_clip1_corto" not in llamadas_clip_mp4
