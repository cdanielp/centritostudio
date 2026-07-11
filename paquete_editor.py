"""paquete_editor.py - Agregacion SOLO-LECTURA para el Editor de Paquete (S35, D26).

El Editor de Paquete NO reimplementa motores: lee lo que el Modo Automatico ya
escribio en output/paquetes/ (paquete.json) y en transcripts/ (sidecars de Caption
QA y brain), y lo traduce a una vista de revision para testers no tecnicos.

Reutiliza el semaforo/estado y la recomendacion de auto_report (fuente unica). Todo
lo que toca disco es lectura fail-open: un sidecar ausente o ilegible degrada a
vacio, jamas rompe la vista. Cero recalculo, cero re-render (regla MAESTRO #19).
"""

from __future__ import annotations

import json
from pathlib import Path

import auto_report


def _stem_de_clip(clip: dict) -> str | None:
    """Stem base del clip (sin estilo ni .mp4) para localizar sus sidecars. Puro.

    Preferimos el alerts_file del QA (nombre exacto del sidecar) y caemos al
    nombre del archivo quitando el sufijo de estilo. Ej.:
    'mariosoto_clip1_corto_9x16_hormozi.mp4' -> 'mariosoto_clip1_corto_9x16'.
    """
    qa = clip.get("qa") or {}
    fname = qa.get("alerts_file")
    if fname:
        return fname.replace("_caption_alerts.json", "")
    archivo = clip.get("archivo")
    if not archivo:
        return None
    return archivo.replace(".mp4", "").rsplit("_", 1)[0]


def alertas_del_clip(clip: dict, transcripts_dir: Path) -> list[dict]:
    """Alertas de Caption QA del clip. Fail-open -> []. Lectura, nunca escribe.

    Los paquetes nuevos (S34+) ya traen las alertas inline en qa['alertas']; los
    viejos solo el conteo, asi que las leemos del sidecar {stem}_caption_alerts.json.
    """
    qa = clip.get("qa") or {}
    if qa.get("alertas"):
        return qa["alertas"]
    fname = qa.get("alerts_file")
    if not fname:
        return []
    p = Path(transcripts_dir) / fname
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("alertas", [])
    except (OSError, ValueError):
        return []


def enriquecer_clip(clip: dict, pkg_id: str, transcripts_dir: Path) -> dict:
    """clip de paquete.json -> dict para el Editor. Estado y URL de preview incluidos.

    El estado sale de auto_report.estado_clip (mismo semaforo del REPORTE.md). La
    URL de video apunta al montaje estatico /output ya existente (no se copia nada).
    """
    qa = dict(clip.get("qa") or {})
    if qa:
        qa["alertas"] = alertas_del_clip(clip, transcripts_dir)
    return {
        "archivo": clip.get("archivo"),
        "titulo": clip.get("titulo", ""),
        "razon": clip.get("razon", ""),
        "score": clip.get("score"),
        "dur_s": clip.get("dur_s", 0),
        "emojis_msg": clip.get("emojis_msg", ""),
        "estado": auto_report.estado_clip(clip),
        "video_url": f"/output/paquetes/{pkg_id}/{clip.get('archivo')}",
        "ruta_fs": f"output/paquetes/{pkg_id}/{clip.get('archivo')}",
        "avisos": clip.get("avisos", []),
        "tramos_disponibles": clip.get("tramos_disponibles", True),
        "qa": qa or None,
    }


def vista_paquete(data: dict, pkg_id: str, transcripts_dir: Path) -> dict:
    """paquete.json cargado -> respuesta del detalle para el Editor de Paquete."""
    clips = data.get("clips", [])
    return {
        "id": pkg_id,
        "meta": data.get("meta", {}),
        "resumen": auto_report.resumen_paquete(clips),
        "recomendacion": auto_report.recomendacion_final(clips),
        "reporte_url": f"/output/paquetes/{pkg_id}/REPORTE.md",
        "clips": [enriquecer_clip(c, pkg_id, transcripts_dir) for c in clips],
    }


def resumen_lista_paquete(pkg_id: str, data: dict) -> dict:
    """paquete.json cargado -> tarjeta resumida para la lista /api/paquetes. Puro."""
    clips = data.get("clips", [])
    meta = data.get("meta", {})
    fecha = meta.get("fecha") or (pkg_id.rsplit("_", 1)[-1] if "_" in pkg_id else "")
    return {
        "id": pkg_id,
        "name": pkg_id.rsplit("_", 1)[0] if "_" in pkg_id else pkg_id,
        "fecha": fecha,
        "n_clips": len(clips),
        "resumen": auto_report.resumen_paquete(clips),
        "estados": [auto_report.estado_clip(c) for c in clips],
    }
