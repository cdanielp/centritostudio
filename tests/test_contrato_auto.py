"""Tests de contrato del Modo Automatico v1 (auto.py, regla MAESTRO #19).

Verifican que la capa es DELGADA: orquesta funciones existentes (con mocks),
el reporte de tramos sale de las metricas que el modo escenas ya devuelve,
y el fail-open de emojis/brain no rompe el paquete. Sin GPU ni red.
"""

import json

import pytest
from conftest import words_con_procedencia

import auto_classic_provenance as acp


def _marcar_paquete_classic(prev, video):
    """Escribe el marker `auto_classic.json` (H2) para que _paquete_dir reanude este dir."""
    (prev / "auto_classic.json").write_text(
        json.dumps(
            {
                "schema_version": acp.SCHEMA_VERSION,
                "pipeline_mode": "classic",
                "video": acp.build_provenance(video, lang="es", model="auto"),
                "created_at": "20260101-000000",
                "run_id": "test-run",
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def _mp4_sintetico_valido(ffprobe_ok):
    """H2: los MP4 sinteticos no-vacios de estos tests de orquestacion cuentan como publicables
    (ffprobe stub de conftest). La validacion real de 0-byte/truncado vive en
    test_h2_resume_integrity.py; aqui el foco es la orquestacion/reanudacion."""


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
    # ningun clip usa emojis -> linea global, ya no la nota por clip (Alpha 0.1)
    assert "Overlays/Emojis: no usados en este paquete" in md
    assert "ComfyUI apagado" not in md
    assert "$0.0010" in md


# ── Alpha 0.1: estado por clip, QA inline, emojis global, recomendacion, telemetria ──


def test_estado_clip_listo():
    import auto

    assert auto.estado_clip({"avisos": [], "tramos_disponibles": True}) == "LISTO"


def test_estado_clip_listo_con_aviso_por_qa_pendiente():
    import auto

    c = {"avisos": [], "qa": {"n_alertas": 2, "aplicadas": 0, "pendientes": 2}}
    assert auto.estado_clip(c) == "LISTO CON AVISO"


def test_estado_clip_requiere_revision_por_tramos():
    import auto

    c = {"avisos": [{"t_ini": 1.0, "t_fin": 2.0, "texto": "x"}]}
    assert auto.estado_clip(c) == "REQUIERE REVISION"


def test_estado_clip_no_publicar_sin_metricas():
    import auto

    # clip reutilizado sin re-render: sin metricas de tramos -> no avalar a ciegas
    assert auto.estado_clip({"avisos": [], "tramos_disponibles": False}) == "NO PUBLICAR AUN"


def test_estado_clip_error_nunca_se_presenta_como_listo():
    import auto

    # un clip con status=error (fallo aislado del render) es la maxima severidad:
    # aunque tuviera tramos "OK", jamas debe salir como LISTO/publicable.
    c = {"status": "error", "avisos": [], "tramos_disponibles": True}
    assert auto.estado_clip(c) == "FALLO EL RENDER"


def test_resumen_no_cuenta_clips_fallidos_como_listos():
    import auto

    # 2 OK + 1 fallido: el resumen no puede decir "3 clip(s) listos".
    info = [
        {"titulo": "a", "avisos": []},
        {"titulo": "b", "avisos": []},
        {"titulo": "c", "status": "error"},
    ]
    resumen = auto.resumen_paquete(info)
    assert resumen.startswith("2 clip(s) listos")
    assert "1 fallaron" in resumen and "clip 3" in resumen


def test_avisos_llevan_tipo_para_la_recomendacion():
    import auto

    multi = auto.avisos_de_segmentos([_seg(tipo="multi", n_caras=2)])
    none = auto.avisos_de_segmentos([_seg(tipo="none", n_caras=0, c1v2=None)])
    segui = auto.avisos_de_segmentos([_seg(c1v2=40.0)])
    assert multi[0]["tipo"] == "multi"
    assert none[0]["tipo"] == "none"
    assert segui[0]["tipo"] == "seguimiento"


def test_reporte_estado_en_header_y_overview():
    import auto

    info = [
        {
            "archivo": "a.mp4",
            "titulo": "Clip A",
            "score": 90,
            "dur_s": 20.0,
            "avisos": [],
            "emojis_msg": "sin overlays",
        }
    ]
    md = auto.generar_reporte_md("v", info, {"fecha": "f", "costo_usd": 0.0})
    assert "[LISTO]" in md
    assert "## Estado de los clips" in md
    assert "Clip 1: LISTO — Clip A" in md


def test_reporte_qa_detalle_inline_sin_abrir_json():
    import auto

    info = [
        {
            "archivo": "a.mp4",
            "titulo": "T",
            "score": 80,
            "dur_s": 20.0,
            "avisos": [],
            "emojis_msg": "sin overlays",
            "qa": {
                "n_alertas": 1,
                "aplicadas": 0,
                "pendientes": 1,
                "alerts_file": "a_caption_alerts.json",
                "alertas": [
                    {
                        "timestamp": 12.4,
                        "texto_detectado": "confiwai",
                        "sugerencia": "ComfyUI",
                        "confianza": "alta",
                        "aplicada": False,
                    }
                ],
            },
        }
    ]
    md = auto.generar_reporte_md("v", info, {"fecha": "f", "costo_usd": 0.0})
    assert "0:12" in md
    assert '"confiwai" -> "ComfyUI"' in md
    assert "confianza alta" in md
    assert "pendiente" in md


def test_reporte_emojis_por_clip_cuando_alguno_usa():
    import auto

    info = [
        {
            "archivo": "a.mp4",
            "score": 90,
            "dur_s": 20.0,
            "avisos": [],
            "emojis_msg": "2 overlay(s)",
        },
        {
            "archivo": "b.mp4",
            "score": 80,
            "dur_s": 20.0,
            "avisos": [],
            "emojis_msg": "sin overlays",
        },
    ]
    md = auto.generar_reporte_md("v", info, {"fecha": "f", "costo_usd": 0.0})
    assert "Overlays/Emojis: no usados" not in md
    assert "2 overlay(s)" in md


def test_recomendacion_final_nombra_tramos_y_mas_publicable():
    import auto

    info = [
        {
            "archivo": "a.mp4",
            "titulo": "Bueno",
            "score": 95,
            "dur_s": 20.0,
            "avisos": [],
            "emojis_msg": "sin overlays",
        },
        {
            "archivo": "b.mp4",
            "titulo": "Multi",
            "score": 70,
            "dur_s": 20.0,
            "avisos": [{"t_ini": 16.0, "t_fin": 30.0, "tipo": "multi", "texto": "x"}],
            "emojis_msg": "sin overlays",
        },
    ]
    md = auto.generar_reporte_md("v", info, {"fecha": "f", "costo_usd": 0.0})
    assert "## Recomendacion final" in md
    assert "Clips a revisar: clip 2 (REQUIERE REVISION)" in md
    assert "Tramos a mirar: clip 2 0:16-0:30" in md
    assert "Stack o Reframe Multi v2" in md
    assert 'Mas publicable: clip 1 "Bueno"' in md


def test_telemetria_tiempo_total_en_minutos_y_segundos():
    import auto

    md = auto.generar_reporte_md(
        "v", [], {"fecha": "f", "costo_usd": 0.002, "t_total_s": 135.0, "t_clipper_s": 8.1}
    )
    assert "Tiempo total: 2m 15s" in md
    assert "Costo LLM: $0.0020" in md
    assert "Tiempos tecnicos:" in md
    assert "Clipper: 8.1s" in md


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
    # words.json con procedencia classic del video EXACTO -> _asegurar_transcript reutiliza (H2)
    (transcripts / "vid_words.json").write_text(
        json.dumps(
            words_con_procedencia(
                video, {"words": [{"w": "hola", "s": 0.0, "e": 0.5, "prob": 0.9}], "language": "es"}
            )
        ),
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


# ── Reanudacion: paquete a medias + re-corrida (regla MAESTRO #20) ────────────


def test_reanuda_sin_regenerar_clip_con_checkpoint(entorno_auto, monkeypatch):
    import auto

    llamadas = []
    _mock_motor(monkeypatch, llamadas)
    # Corrida previa interrumpida: clip1 final + su sidecar de checkpoint ya existen
    prev = auto.PAQUETES_DIR / "vid_20260101-0000"
    prev.mkdir()
    _marcar_paquete_classic(prev, entorno_auto["video"])  # H2: marker classic para reanudar
    final = prev / "vid_clip1_corto_9x16_hormozi.mp4"
    final.write_bytes(b"ya-renderizado")
    sidecar = final.with_name(final.stem + ".info.json")
    sidecar.write_text(
        json.dumps(
            {
                "archivo": final.name,
                "titulo": "T",
                "razon": "R",
                "score": 88,
                "dur_s": 30.0,
                "avisos": [],
                "emojis_msg": "3 overlay(s)",
            }
        ),
        encoding="utf-8",
    )

    result = auto.ejecutar_auto(entorno_auto["video"], "vid")

    # el clip con checkpoint NO se re-renderiza: cero reframe/burn
    nombres = [c[0] for c in llamadas]
    assert "reframe.reframe_clip" not in nombres
    assert "core.burn_video_with_emojis" not in nombres
    # el paquete se completa EN EL MISMO dir de la corrida previa
    assert result["paquete"].endswith("vid_20260101-0000")
    assert result["meta"]["reanudado"] is True
    assert (prev / "paquete.json").exists()
    assert (prev / "REPORTE.md").exists()
    # el info del clip proviene del checkpoint intacto
    assert result["clips"][0]["score"] == 88


def test_reanuda_orfano_reutiliza_render_sin_avisos(entorno_auto, monkeypatch):
    import auto

    llamadas = []
    _mock_motor(monkeypatch, llamadas)
    # Clip final de una corrida previa SIN sidecar de checkpoint (paquete pre-reanudacion), pero
    # CON marker classic (H2) para que el dir sea reanudable.
    prev = auto.PAQUETES_DIR / "vid_20260101-0000"
    prev.mkdir()
    _marcar_paquete_classic(prev, entorno_auto["video"])
    final = prev / "vid_clip1_corto_9x16_hormozi.mp4"
    final.write_bytes(b"ya-renderizado")

    result = auto.ejecutar_auto(entorno_auto["video"], "vid")

    # se reutiliza el render existente: no se vuelve a quemar
    assert "core.burn_video_with_emojis" not in [c[0] for c in llamadas]
    # se crea el sidecar faltante como checkpoint para futuras reanudaciones
    assert final.with_name(final.stem + ".info.json").exists()
    assert result["clips"][0]["tramos_disponibles"] is False
    md = (prev / "REPORTE.md").read_text(encoding="utf-8")
    assert "no disponible" in md
    assert result["meta"]["reanudado"] is True


def test_analisis_reutilizado_no_regasta_llm(entorno_auto, monkeypatch):
    import auto

    llamadas = []
    _mock_motor(monkeypatch, llamadas)
    # clips.json fresco + sidecar de procedencia classic del video EXACTO -> el clipper (LLM) no
    # se vuelve a llamar (H2, P2-CLASSIC-REUSE).
    (auto.CLIPS_DIR / "vid_clips.json").write_text(
        json.dumps(
            {
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
        ),
        encoding="utf-8",
    )
    (auto.CLIPS_DIR / "vid_clips.provenance.json").write_text(
        json.dumps(acp.build_provenance(entorno_auto["video"], lang="es", model="auto")),
        encoding="utf-8",
    )

    result = auto.ejecutar_auto(entorno_auto["video"], "vid")

    assert "clipper.generar_clips" not in [c[0] for c in llamadas]
    assert result["meta"]["analisis_reutilizado"] is True
