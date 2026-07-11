"""Tests de contrato del Editor de Paquete (paquete_editor.py, S35, D26).

Verifican que la agregacion es SOLO-LECTURA y fail-open: reutiliza el estado y la
recomendacion de auto_report, resuelve las alertas de Caption QA del sidecar cuando
el paquete viejo no las trae inline, y nunca escribe ni recalcula. Sin GPU ni red.
"""

import json

import paquete_editor as pe


def _clip(**kw):
    base = {
        "archivo": "vid_clip1_corto_9x16_hormozi.mp4",
        "titulo": "Demo",
        "razon": "Hook fuerte",
        "score": 84,
        "dur_s": 30.0,
        "avisos": [],
        "qa": {"n_alertas": 0, "aplicadas": 0, "pendientes": 0},
        "emojis_msg": "sin overlays",
    }
    base.update(kw)
    return base


def test_stem_desde_alerts_file():
    c = _clip(qa={"alerts_file": "vid_clip1_corto_9x16_caption_alerts.json"})
    assert pe._stem_de_clip(c) == "vid_clip1_corto_9x16"


def test_stem_cae_al_archivo_sin_estilo():
    c = _clip(qa={})
    assert pe._stem_de_clip(c) == "vid_clip1_corto_9x16"


def test_alertas_inline_ganan(tmp_path):
    inline = [{"timestamp": 1.0, "texto_detectado": "x", "sugerencia": "y", "confianza": "alta"}]
    c = _clip(qa={"n_alertas": 1, "alertas": inline})
    assert pe.alertas_del_clip(c, tmp_path) == inline


def test_alertas_se_leen_del_sidecar_cuando_faltan(tmp_path):
    # paquete viejo: qa trae conteo + alerts_file pero NO la lista inline
    (tmp_path / "vid_clip1_corto_9x16_caption_alerts.json").write_text(
        json.dumps(
            {"alertas": [{"timestamp": 24.1, "texto_detectado": "mira", "confianza": "baja"}]}
        ),
        encoding="utf-8",
    )
    c = _clip(qa={"n_alertas": 1, "alerts_file": "vid_clip1_corto_9x16_caption_alerts.json"})
    alertas = pe.alertas_del_clip(c, tmp_path)
    assert len(alertas) == 1
    assert alertas[0]["texto_detectado"] == "mira"


def test_alertas_fail_open_si_sidecar_ausente(tmp_path):
    c = _clip(qa={"n_alertas": 2, "alerts_file": "no_existe.json"})
    assert pe.alertas_del_clip(c, tmp_path) == []


def test_enriquecer_clip_agrega_estado_y_urls(tmp_path):
    c = _clip(avisos=[{"t_ini": 1.0, "t_fin": 2.0, "texto": "revisa"}])
    out = pe.enriquecer_clip(c, "vid_20260101-0000", tmp_path)
    # estado viene del mismo semaforo del REPORTE.md (avisos -> REQUIERE REVISION)
    assert out["estado"] == "REQUIERE REVISION"
    assert out["video_url"] == "/output/paquetes/vid_20260101-0000/vid_clip1_corto_9x16_hormozi.mp4"
    assert out["ruta_fs"].startswith("output/paquetes/")
    assert out["score"] == 84


def test_enriquecer_clip_sin_metricas_es_no_publicar(tmp_path):
    c = _clip(avisos=[], tramos_disponibles=False)
    out = pe.enriquecer_clip(c, "vid_x", tmp_path)
    assert out["estado"] == "NO PUBLICAR AUN"


def test_vista_paquete_incluye_resumen_y_recomendacion(tmp_path):
    data = {"clips": [_clip()], "meta": {"fecha": "20260101-0000", "t_total_s": 90.0}}
    vista = pe.vista_paquete(data, "vid_20260101-0000", tmp_path)
    assert vista["id"] == "vid_20260101-0000"
    assert vista["reporte_url"].endswith("/REPORTE.md")
    assert isinstance(vista["recomendacion"], list) and vista["recomendacion"]
    assert len(vista["clips"]) == 1


def test_resumen_lista_paquete_parsea_nombre_y_estados():
    data = {
        "clips": [_clip(), _clip(avisos=[{"t_ini": 0.0, "t_fin": 1.0, "texto": "x"}])],
        "meta": {"fecha": "20260711-1316"},
    }
    r = pe.resumen_lista_paquete("mariosoto_20260711-1316", data)
    assert r["name"] == "mariosoto"
    assert r["fecha"] == "20260711-1316"
    assert r["n_clips"] == 2
    assert r["estados"] == ["LISTO", "REQUIERE REVISION"]
