"""HF-4 Paso 2/3: el Modo Automatico classic (auto._procesar_clip) con Formato dual.

Mismo patron de mocks que test_contrato_auto.py (capa delgada, sin FFmpeg/GPU real), pero con
`core.get_video_info` consciente de la ruta: la fuente es horizontal (1920x1080, lo que entrega
el clipper) y el reencuadre produce vertical (1080x1920), para poder ejercitar de verdad la
decision de reencuadre condicional en vez de caer siempre en la omision por fuente vertical.
"""

from __future__ import annotations

import json

import pytest
from conftest import words_con_procedencia

from auto_config import AutoConfig

HORIZONTAL = {"width": 1920, "height": 1080, "duration": 30.0}
VERTICAL = {"width": 1080, "height": 1920, "duration": 30.0}


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    import auto

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
        json.dumps(
            words_con_procedencia(
                video, {"words": [{"w": "hola", "s": 0.0, "e": 0.5, "prob": 0.9}], "language": "es"}
            )
        ),
        encoding="utf-8",
    )
    grupos = [{"id": 0, "start": 0.0, "end": 1.0, "text": "hola", "words": []}]
    (transcripts / "vid_clip1_corto_words.json").write_text(
        json.dumps({"words": [], "language": "es"}), encoding="utf-8"
    )
    (transcripts / "vid_clip1_corto_groups.json").write_text(json.dumps(grupos), encoding="utf-8")
    (clips_dir / "vid_clip1_corto.mp4").write_bytes(b"fake-clip")
    return {"video": video, "transcripts": transcripts, "clips_dir": clips_dir}


def _mock_motor(monkeypatch, llamadas):
    """Mockea el motor: fuente horizontal, reencuadre produce vertical (path-aware)."""
    import assets_comfy
    import brain
    import clipper
    import core
    import reframe

    def fake_generar_clips(mp4, words, tipos):
        llamadas.append(("clipper.generar_clips", tipos))
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

    def fake_reframe_clip(clip_path, output_path, **kw):
        llamadas.append(("reframe.reframe_clip", str(output_path.name), kw.get("tracker")))
        output_path.write_bytes(b"fake-9x16")
        return {"output": str(output_path), "n_caras": 2, "segmentos": []}

    def fake_get_video_info(p):
        return dict(VERTICAL if "_9x16" in p.name else HORIZONTAL)

    def fake_analizar(grupos, **kw):
        llamadas.append(("brain.analizar_grupos", kw.get("video_name")))
        return {"groups": [{"g": 0, "kw": 0, "emoji": None, "kw_ts": 0.0}]}

    def fake_overlays(groups_path, brain_path):
        llamadas.append(("assets_comfy.resolver_overlays", groups_path.name))
        return []

    def fake_burn(inp, ass, out, overlays, style_cfg):
        llamadas.append(("core.burn_video_with_emojis", inp.name, out.name))
        out.write_bytes(b"fake-final")
        return 1.0

    monkeypatch.setattr(clipper, "generar_clips", fake_generar_clips)
    monkeypatch.setattr(reframe, "reframe_clip", fake_reframe_clip)
    monkeypatch.setattr(brain, "analizar_grupos", fake_analizar)
    monkeypatch.setattr(assets_comfy, "resolver_overlays", fake_overlays)
    monkeypatch.setattr(core, "get_video_info", fake_get_video_info)
    monkeypatch.setattr(core, "build_ass", lambda *a, **k: None)
    monkeypatch.setattr(core, "burn_video_with_emojis", fake_burn)


# ── Invariante (b): formato="9:16" reproduce EXACTAMENTE la ruta historica ───


def test_formato_9x16_llama_reframe_una_vez_igual_que_sin_config(entorno, monkeypatch):
    import auto

    llamadas = []
    _mock_motor(monkeypatch, llamadas)
    result = auto.ejecutar_auto(
        entorno["video"], "vid", config=AutoConfig(mode="classic", formato="9:16")
    )

    reframes = [ll for ll in llamadas if ll[0] == "reframe.reframe_clip"]
    assert reframes == [("reframe.reframe_clip", "vid_clip1_corto_9x16.mp4", "escenas")]
    assert len(result["clips"]) == 1
    assert result["clips"][0]["archivo"] == "vid_clip1_corto_9x16_hormozi.mp4"
    assert "formato" not in result["meta"]  # el default nunca toca meta


# ── Formato nuevo: 16:9 sin reencuadre ────────────────────────────────────────


def test_formato_16x9_no_llama_a_reframe(entorno, monkeypatch):
    import auto

    llamadas = []
    _mock_motor(monkeypatch, llamadas)
    result = auto.ejecutar_auto(
        entorno["video"], "vid", config=AutoConfig(mode="classic", formato="16:9")
    )

    assert [ll for ll in llamadas if ll[0] == "reframe.reframe_clip"] == []
    assert len(result["clips"]) == 1
    assert result["clips"][0]["archivo"] == "vid_clip1_corto_16x9_hormozi.mp4"
    assert result["meta"]["formato"] == "16:9"


# ── Ambos: dos salidas, un solo brain, un sello por formato ──────────────────


def test_formato_ambos_produce_dos_clips_y_llama_a_reframe_una_sola_vez(entorno, monkeypatch):
    import auto

    llamadas = []
    _mock_motor(monkeypatch, llamadas)
    result = auto.ejecutar_auto(
        entorno["video"], "vid", config=AutoConfig(mode="classic", formato="ambos")
    )

    reframes = [ll for ll in llamadas if ll[0] == "reframe.reframe_clip"]
    assert len(reframes) == 1, "el reencuadre debe correr UNA vez, no una por formato"

    archivos = sorted(c["archivo"] for c in result["clips"])
    assert archivos == ["vid_clip1_corto_16x9_hormozi.mp4", "vid_clip1_corto_9x16_hormozi.mp4"]
    assert result["meta"]["formato"] == "ambos"


def test_formato_ambos_llama_al_brain_una_sola_vez(entorno, monkeypatch):
    """El texto/keyword del brain no depende del formato: se pide una vez y se reusa."""
    import auto

    llamadas = []
    _mock_motor(monkeypatch, llamadas)
    auto.ejecutar_auto(entorno["video"], "vid", config=AutoConfig(mode="classic", formato="ambos"))

    brains = [ll for ll in llamadas if ll[0] == "brain.analizar_grupos"]
    assert len(brains) == 1, f"brain.analizar_grupos se llamo {len(brains)} veces, se esperaba 1"


def test_formato_ambos_escribe_dos_sidecares_de_checkpoint_distintos(entorno, monkeypatch):
    import auto

    llamadas = []
    _mock_motor(monkeypatch, llamadas)
    result = auto.ejecutar_auto(
        entorno["video"], "vid", config=AutoConfig(mode="classic", formato="ambos")
    )
    paquete = auto.PAQUETES_DIR / result["paquete"].split("/")[-1]
    sidecars = sorted(p.name for p in paquete.glob("*.info.json"))
    assert sidecars == [
        "vid_clip1_corto_16x9_hormozi.info.json",
        "vid_clip1_corto_9x16_hormozi.info.json",
    ]


def test_formato_16x9_sobre_fuente_vertical_se_omite_sin_reventar(entorno, monkeypatch):
    """Este repo solo reencuadra HACIA 9:16: pedir 16:9 sobre una fuente ya vertical no tiene
    ruta y el clip no produce esa pierna (auto_formato.MOTIVO_SIN_REFRAME_HORIZONTAL)."""
    import auto

    llamadas = []
    _mock_motor(monkeypatch, llamadas)
    import core

    monkeypatch.setattr(core, "get_video_info", lambda p: dict(VERTICAL))
    result = auto.ejecutar_auto(
        entorno["video"], "vid", config=AutoConfig(mode="classic", formato="16:9")
    )
    assert result["clips"] == []
