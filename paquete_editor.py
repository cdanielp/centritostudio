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
import os
from pathlib import Path

import auto_report


def es_nombre_seguro(nombre: str | None) -> bool:
    """True si `nombre` es un basename simple usable dentro de un root. Puro.

    Rechaza vacio, '.', '..', separadores (/ o \\) y rutas con unidad de Windows
    (C:...). Primera linea de defensa antes de tocar disco: los nombres vienen de
    paquete.json y de sidecars, nunca son de fiar (regla anti path traversal).
    """
    if not nombre or nombre in (".", ".."):
        return False
    if "/" in nombre or "\\" in nombre:
        return False
    if os.path.splitdrive(nombre)[0]:  # 'C:' u otra unidad
        return False
    return nombre == os.path.basename(nombre)


def resolver_hijo_seguro(root: Path, nombre: str | None) -> Path | None:
    """Path a un hijo DIRECTO de `root`, o None si el nombre es inseguro o escapa.

    Combina la validacion de nombre con resolve(): aunque el basename pase, si un
    symlink apunta fuera de `root` se rechaza. No crea nada; solo resuelve rutas.
    """
    if not es_nombre_seguro(nombre):
        return None
    root_r = Path(root).resolve()
    try:
        hijo = (root_r / nombre).resolve()
    except OSError:
        return None
    if hijo != root_r and root_r not in hijo.parents:
        return None
    return hijo


def resolver_archivo_paquete(pkg_dir: Path, archivo: str | None) -> Path | None:
    """Ruta segura a un archivo del paquete (basename validado). None si inseguro."""
    return resolver_hijo_seguro(pkg_dir, archivo)


def resolver_sidecar_seguro(transcripts_dir: Path, nombre: str | None) -> Path | None:
    """Ruta segura a un sidecar en transcripts/ (basename validado). None si inseguro."""
    return resolver_hijo_seguro(transcripts_dir, nombre)


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
    p = resolver_sidecar_seguro(transcripts_dir, fname)
    if p is None or not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("alertas", [])
    except (OSError, ValueError):
        return []


def _num(v) -> float | None:
    """float() defensivo: None/'' -> None (para descartar markers sin tiempo). Puro."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def markers_de_brain(clip: dict, transcripts_dir: Path) -> list[tuple[str, float]]:
    """[(tipo, t)] de keywords y popups leidos del {stem}.brain.json. Fail-open -> [].

    Un grupo con emoji marcado -> popup; con keyword (kw != None) -> keyword. Ambos
    usan kw_ts como tiempo. Solo lectura: no dispara el cerebro ni recalcula nada.
    """
    stem = _stem_de_clip(clip)
    if not stem:
        return []
    p = resolver_sidecar_seguro(transcripts_dir, f"{stem}.brain.json")
    if p is None or not p.exists():
        return []
    try:
        groups = json.loads(p.read_text(encoding="utf-8")).get("groups", [])
    except (OSError, ValueError):
        return []
    out: list[tuple[str, float]] = []
    for g in groups:
        t = _num(g.get("kw_ts"))
        if t is None:
            continue
        if g.get("emoji"):
            out.append(("popup", t))
        elif g.get("kw") is not None:
            out.append(("keyword", t))
    return out


def _texto_alerta_qa(a: dict) -> str:
    sug = a.get("sugerencia") or "sin sugerencia"
    return f"{a.get('texto_detectado', '?')} -> {sug} ({a.get('confianza', '?')})"


def construir_markers(
    dur_s: float, avisos: list[dict], qa_alertas: list[dict], brain_markers: list[tuple[str, float]]
) -> list[dict]:
    """Markers del timeline de revision (puro). No recalcula: traduce lo ya medido.

    Cada marker: {tipo, t, texto} (+ t_fin en los tramos). Se descartan los sin
    tiempo y los que caen fuera del clip; el resultado va ordenado por t.
    """
    m: list[dict] = []
    for a in avisos:
        m.append(
            {
                "tipo": "tramo",
                "t": _num(a.get("t_ini")),
                "t_fin": _num(a.get("t_fin")),
                "texto": a.get("texto", ""),
            }
        )
    for a in qa_alertas:
        m.append({"tipo": "qa", "t": _num(a.get("timestamp")), "texto": _texto_alerta_qa(a)})
    for tipo, t in brain_markers:
        m.append({"tipo": tipo, "t": _num(t), "texto": tipo})
    m = [x for x in m if x["t"] is not None]
    if dur_s and dur_s > 0:
        m = [x for x in m if x["t"] <= dur_s + 0.5]
    return sorted(m, key=lambda x: x["t"])


def enriquecer_clip(clip: dict, pkg_id: str, pkg_dir: Path, transcripts_dir: Path) -> dict:
    """clip de paquete.json -> dict para el Editor. Estado y URL de preview incluidos.

    El estado sale de auto_report.estado_clip (mismo semaforo del REPORTE.md). La
    URL de video apunta al endpoint validado /api/paquetes/{pkg}/video/{archivo} y
    SOLO se construye si el archivo es un basename seguro y existe en el paquete;
    un clip inseguro o sin MP4 sale con video_url=None y video_disponible=False.
    """
    qa = dict(clip.get("qa") or {})
    alertas = alertas_del_clip(clip, transcripts_dir)
    if qa:
        qa["alertas"] = alertas
    avisos = clip.get("avisos", [])
    dur_s = clip.get("dur_s", 0)
    markers = construir_markers(dur_s, avisos, alertas, markers_de_brain(clip, transcripts_dir))
    archivo = clip.get("archivo")
    ruta = resolver_archivo_paquete(pkg_dir, archivo)
    disponible = ruta is not None and ruta.is_file()
    return {
        "archivo": archivo,
        "titulo": clip.get("titulo", ""),
        "razon": clip.get("razon", ""),
        "score": clip.get("score"),
        "dur_s": dur_s,
        "emojis_msg": clip.get("emojis_msg", ""),
        "estado": auto_report.estado_clip(clip),
        "video_url": f"/api/paquetes/{pkg_id}/video/{archivo}" if disponible else None,
        "video_disponible": disponible,
        "ruta_fs": f"output/paquetes/{pkg_id}/{archivo}" if es_nombre_seguro(archivo) else None,
        "avisos": avisos,
        "tramos_disponibles": clip.get("tramos_disponibles", True),
        "qa": qa or None,
        "markers": markers,
    }


def vista_paquete(data: dict, pkg_id: str, pkg_dir: Path, transcripts_dir: Path) -> dict:
    """paquete.json cargado -> respuesta del detalle para el Editor de Paquete.

    reporte_url apunta al endpoint validado /api/paquetes/{pkg}/reporte y solo se
    construye si el REPORTE.md existe; si falta, queda None (la recomendacion sigue
    saliendo de auto_report, no depende del archivo).
    """
    clips = data.get("clips", [])
    reporte = Path(pkg_dir) / "REPORTE.md"
    return {
        "id": pkg_id,
        "meta": data.get("meta", {}),
        "resumen": auto_report.resumen_paquete(clips),
        "recomendacion": auto_report.recomendacion_final(clips),
        "reporte_url": f"/api/paquetes/{pkg_id}/reporte" if reporte.is_file() else None,
        "clips": [enriquecer_clip(c, pkg_id, pkg_dir, transcripts_dir) for c in clips],
    }


def resumen_lista_paquete(pkg_id: str, data: dict) -> dict:
    """paquete.json cargado -> tarjeta resumida para la lista /api/paquetes. Puro."""
    clips = data.get("clips", [])
    meta = data.get("meta", {})
    fecha = meta.get("fecha") or (pkg_id.rsplit("_", 1)[-1] if "_" in pkg_id else "")
    completo = bool(clips) and all(c.get("tramos_disponibles", True) for c in clips)
    return {
        "id": pkg_id,
        "name": pkg_id.rsplit("_", 1)[0] if "_" in pkg_id else pkg_id,
        "fecha": fecha,
        "n_clips": len(clips),
        "resumen": auto_report.resumen_paquete(clips),
        "estados": [auto_report.estado_clip(c) for c in clips],
        "salud": "completo" if completo else "incompleto",
    }
