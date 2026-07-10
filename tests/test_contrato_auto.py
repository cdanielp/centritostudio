"""Tests de contrato del Modo Automatico v1 (auto.py, regla MAESTRO #19).

Verifican que la capa es DELGADA: orquesta funciones existentes (con mocks),
el reporte de tramos sale de las metricas que el modo escenas ya devuelve,
y el fail-open de emojis/brain no rompe el paquete. Sin GPU ni red.
"""

import json

import pytest

# ── Funciones puras: avisos de tramos ─────────────────────────────────────────


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


def test_fmt_t():
    import auto

    assert auto._fmt_t(39.7) == "0:39"
    assert auto._fmt_t(76) == "1:16"
    assert auto._fmt_t(0) == "0:00"


def test_aviso_multi_en_lenguaje_humano():
    import auto

    avisos = auto.avisos_de_segmentos([_seg(t_ini=39.0, t_fin=52.0, tipo="multi", n_caras=2)])
    assert len(avisos) == 1
    assert "0:39-0:52" in avisos[0]["texto"]
    assert "2 personas en cuadro" in avisos[0]["texto"]
    assert "solo siguio a una" in avisos[0]["texto"]


def test_aviso_none_centercrop():
    import auto

    avisos = auto.avisos_de_segmentos([_seg(tipo="none", n_caras=0, c1v2=None)])
    assert len(avisos) == 1
    assert "sin cara detectada" in avisos[0]["texto"]
    assert "centrado fijo" in avisos[0]["texto"]


def test_aviso_c1v2_bajo():
    import auto

    avisos = auto.avisos_de_segmentos([_seg(c1v2=auto.C1V2_AVISO - 5.0)])
    assert len(avisos) == 1
    assert "pudo perder a la persona" in avisos[0]["texto"]


def test_single_bueno_sin_aviso():
    import auto

    assert auto.avisos_de_segmentos([_seg(c1v2=auto.C1V2_AVISO)]) == []
    assert auto.avisos_de_segmentos([_seg(c1v2=100.0)]) == []


def test_multi_con_c1v2_bajo_un_solo_aviso():
    import auto

    avisos = auto.avisos_de_segmentos([_seg(tipo="multi", n_caras=3, c1v2=40.0)])
    assert len(avisos) == 1  # el aviso multi cubre; no se duplica por c1v2


def test_c1v2_none_en_single_no_avisa():
    import auto

    # single sin detecciones vivas reporta c1v2=None: no hay dato, no hay aviso falso
    assert auto.avisos_de_segmentos([_seg(c1v2=None)]) == []


# ── Funciones puras: resumen y reporte ────────────────────────────────────────


def test_resumen_sin_avisos():
    import auto

    info = [{"archivo": "a.mp4", "avisos": []}, {"archivo": "b.mp4", "avisos": []}]
    assert auto.resumen_paquete(info) == "2 clip(s) listos, sin avisos"


def test_resumen_con_aviso_nombra_clip_y_tiempo():
    import auto

    info = [
        {"archivo": "a.mp4", "avisos": []},
        {"archivo": "b.mp4", "avisos": [{"t_ini": 16.3, "t_fin": 30.0, "texto": "x"}]},
    ]
    assert auto.resumen_paquete(info) == "2 clip(s) listos, 1 con aviso (clip 2 en 0:16)"


def test_resumen_cero_clips():
    import auto

    assert auto.resumen_paquete([]) == "0 clips generados"


def test_reporte_md_contiene_lo_esencial():
    import auto

    info = [
        {
            "archivo": "v_clip1_corto_9x16_hormozi.mp4",
            "titulo": "Titulo X",
            "razon": "Razon Y",
            "score": 88,
            "dur_s": 30.0,
            "avisos": [{"t_ini": 16.3, "t_fin": 30.0, "texto": "revisa 0:16-0:30: prueba"}],
            "emojis_msg": "sin overlays (ComfyUI apagado o sin keywords)",
        }
    ]
    md = auto.generar_reporte_md("v", info, {"fecha": "20260710-1200", "costo_usd": 0.001})
    assert "score IA 88/100" in md
    assert "revisa 0:16-0:30" in md
    assert "REVISION HUMANA REQUERIDA" in md
    assert "ComfyUI apagado" in md
    assert "$0.0010" in md


# ── Orquestador: capa delgada con mocks ──────────────────────────────────────


@pytest.fixture
def entorno_auto(tmp_path, monkeypatch):
    """Redirige los directorios de auto.py a tmp y prepara artefactos minimos."""
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
    # words.json posterior al video -> _asegurar_transcript reutiliza (voto #10)
    (transcripts / "vid_words.json").write_text(
        json.dumps({"words": [{"w": "hola", "s": 0.0, "e": 0.5, "prob": 0.9}], "language": "es"}),
        encoding="utf-8",
    )
    # transcript re-basado del clip (lo exporta el clipper real)
    grupos = [{"id": 0, "start": 0.0, "end": 1.0, "text": "hola", "words": []}]
    (transcripts / "vid_clip1_corto_words.json").write_text(
        json.dumps({"words": [], "language": "es"}), encoding="utf-8"
    )
    (transcripts / "vid_clip1_corto_groups.json").write_text(json.dumps(grupos), encoding="utf-8")
    (clips_dir / "vid_clip1_corto.mp4").write_bytes(b"fake-clip")
    return {"video": video, "transcripts": transcripts, "clips_dir": clips_dir}


def _mock_motor(monkeypatch, llamadas, brain_falla=True):
    """Mockea las funciones del motor que auto.py debe orquestar (no reimplementar)."""
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
        llamadas.append(("reframe.reframe_clip", kw.get("tracker")))
        output_path.write_bytes(b"fake-9x16")
        return {
            "output": str(output_path),
            "n_caras": 2,
            "segmentos": [
                _seg(t_ini=0.0, t_fin=16.3, c1v2=95.0),
                _seg(seg=1, t_ini=16.3, t_fin=30.0, tipo="multi", n_caras=2, c1v2=46.5),
            ],
        }

    def fake_analizar(grupos, **kw):
        llamadas.append(("brain.analizar_grupos",))
        if brain_falla:
            raise RuntimeError("sin API key")
        return {"groups": [{"g": 0, "kw": 0, "emoji": None, "kw_ts": 0.0}]}

    def fake_overlays(groups_path, brain_path):
        llamadas.append(("assets_comfy.resolver_overlays",))
        return []  # ComfyUI apagado: fail-open

    def fake_burn(inp, ass, out, overlays, style_cfg):
        llamadas.append(("core.burn_video_with_emojis", len(overlays)))
        out.write_bytes(b"fake-final")
        return 1.0

    monkeypatch.setattr(clipper, "generar_clips", fake_generar_clips)
    monkeypatch.setattr(reframe, "reframe_clip", fake_reframe_clip)
    monkeypatch.setattr(brain, "analizar_grupos", fake_analizar)
    monkeypatch.setattr(assets_comfy, "resolver_overlays", fake_overlays)
    monkeypatch.setattr(core, "get_video_info", lambda p: {"width": 1080, "height": 1920})
    monkeypatch.setattr(core, "build_ass", lambda *a, **k: None)
    monkeypatch.setattr(core, "burn_video_with_emojis", fake_burn)


def test_ejecutar_auto_orquesta_el_motor_existente(entorno_auto, monkeypatch):
    import auto

    llamadas = []
    _mock_motor(monkeypatch, llamadas)
    result = auto.ejecutar_auto(entorno_auto["video"], "vid")

    nombres = [c[0] for c in llamadas]
    assert nombres == [
        "clipper.generar_clips",
        "reframe.reframe_clip",
        "brain.analizar_grupos",
        "assets_comfy.resolver_overlays",
        "core.burn_video_with_emojis",
    ]
    # el reframe de la capa automatica usa el tracker default validado por K (D16)
    assert ("reframe.reframe_clip", "escenas") in llamadas
    assert result["resumen"] == "1 clip(s) listos, 1 con aviso (clip 1 en 0:16)"


def test_paquete_contiene_reporte_y_clip_final(entorno_auto, monkeypatch):
    import auto

    llamadas = []
    _mock_motor(monkeypatch, llamadas)
    result = auto.ejecutar_auto(entorno_auto["video"], "vid")

    paquete = auto.PAQUETES_DIR / result["paquete"].split("/")[-1]
    assert (paquete / "REPORTE.md").exists()
    assert (paquete / "paquete.json").exists()
    assert (paquete / "vid_clip1_corto_9x16_hormozi.mp4").exists()
    md = (paquete / "REPORTE.md").read_text(encoding="utf-8")
    # el aviso viene de las metricas por segmento existentes, en lenguaje humano
    assert "revisa 0:16-0:30: 2 personas en cuadro" in md
    assert "REVISION HUMANA REQUERIDA" in md


def test_fail_open_emojis_y_brain_no_rompen_paquete(entorno_auto, monkeypatch):
    import auto

    llamadas = []
    _mock_motor(monkeypatch, llamadas, brain_falla=True)
    result = auto.ejecutar_auto(entorno_auto["video"], "vid")

    # brain fallo (sin API key) y ComfyUI apagado: el paquete sale igual
    assert ("core.burn_video_with_emojis", 0) in llamadas
    assert result["clips"][0]["emojis_msg"].startswith("sin overlays")
    assert len(result["clips"]) == 1


def test_transcript_reutilizado_no_retranscribe(entorno_auto, monkeypatch):
    import auto

    llamadas = []
    _mock_motor(monkeypatch, llamadas)
    result = auto.ejecutar_auto(entorno_auto["video"], "vid")
    # words.json era mas reciente que el video: cero llamadas a Whisper (voto #10)
    assert result["meta"]["transcript_reutilizado"] is True


def test_objetivo_invalido_rechazado():
    import auto

    with pytest.raises(ValueError, match="no soportado"):
        auto.ejecutar_auto(None, "x", objetivo="karaoke-3d")
