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


def _entero_publico(valor) -> int | None:
    if isinstance(valor, bool) or valor is None:
        return None
    try:
        return max(0, int(valor))
    except (TypeError, ValueError):
        return None


def _texto_publico(valor, fallback: str = "") -> str:
    """Texto corto sin URLs ni controles para la vista publica."""
    if not isinstance(valor, str):
        return fallback
    texto = " ".join(valor.split())[:180]
    lower = texto.lower()
    ruta_windows = len(texto) > 2 and texto[1] == ":" and texto[2] in ("/", "\\")
    if (
        ruta_windows
        or texto.startswith(("/", "\\"))
        or "://" in lower
        or lower.startswith(("www.", "file:", "data:"))
    ):
        return fallback
    return texto


def resumen_broll_seguro(clip: dict, meta: dict | None = None) -> dict | None:
    """Resumen v2 sin nombres de sidecar, assets, URLs ni rutas."""
    if clip.get("pipeline_mode") != "v2" or not isinstance(clip.get("broll"), dict):
        return None
    broll = clip["broll"]
    meta = meta if isinstance(meta, dict) else {}
    config = meta.get("config") if isinstance(meta.get("config"), dict) else {}
    enabled = config.get("broll_enabled")
    return {
        "enabled": enabled if isinstance(enabled, bool) else None,
        **{
            k: _entero_publico(broll.get(k))
            for k in ("planned", "resolved", "images", "videos", "fallbacks", "blocked", "omitted")
        },
        "manual_popups": _entero_publico(broll.get("manual_popups")),
        "manual_clips": _entero_publico(broll.get("manual_clips")),
    }


def resumen_fx_seguro(clip: dict) -> dict | None:
    """Auditoria FX v2 saneada; nunca devuelve intervalos internos completos."""
    if clip.get("pipeline_mode") != "v2" or not isinstance(clip.get("fx"), dict):
        return None
    fx = clip["fx"]
    preset = fx.get("preset") if fx.get("preset") in ("express", "pro", "premium") else None
    conteos = ("punch", "flash", "scanner", "logo")
    before = fx.get("before") if isinstance(fx.get("before"), dict) else {}
    after = fx.get("after") if isinstance(fx.get("after"), dict) else {}
    warnings = fx.get("warnings") if isinstance(fx.get("warnings"), list) else []
    return {
        "enabled": fx.get("enabled") if isinstance(fx.get("enabled"), bool) else None,
        "preset": preset,
        "before": {k: _entero_publico(before.get(k)) for k in conteos},
        "after": {k: _entero_publico(after.get(k)) for k in conteos},
        "removed": len(fx["removed"]) if isinstance(fx.get("removed"), list) else None,
        "warnings": [_texto_publico(w) for w in warnings if _texto_publico(w)],
    }


def _estado_av(valor) -> str:
    return valor if valor in ("pass", "fail", "skipped", "no_audio") else "unknown"


def resumen_av_seguro(clip: dict) -> dict | None:
    """Estados A/V y drift redondeado; excluye hashes y metadata de paquetes."""
    if clip.get("pipeline_mode") != "v2" or not isinstance(clip.get("av"), dict):
        return None
    av = clip["av"]
    if av.get("skipped"):
        return {"integrity": "skipped", "sync": "skipped", "drift_s": None}
    sync = av.get("sync") if isinstance(av.get("sync"), dict) else {}
    integrity = av.get("integrity") if isinstance(av.get("integrity"), dict) else {}
    drift = _num(sync.get("av_end_drift_s"))
    allowed = _num(sync.get("allowed_end_drift_s"))
    return {
        "integrity": _estado_av(integrity.get("status")),
        "sync": _estado_av(sync.get("status")),
        "drift_s": round(drift, 3) if drift is not None else None,
        "allowed_drift_s": round(allowed, 3) if allowed is not None else None,
    }


def leer_resolved_seguro(clip: dict, transcripts_dir: Path) -> dict | None:
    """Lee el resolved v1 confinado y solo si pertenece a este clip/config."""
    broll = clip.get("broll") if isinstance(clip.get("broll"), dict) else {}
    p = resolver_sidecar_seguro(transcripts_dir, broll.get("resolved_sidecar"))
    if p is None or not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    fingerprint = clip.get("config_fingerprint")
    if not isinstance(data, dict) or data.get("version") != 1 or not fingerprint:
        return None
    return data if data.get("config_fingerprint") == fingerprint else None


def markers_broll_resueltos(clip: dict, transcripts_dir: Path) -> list[dict]:
    """Markers solo de ventanas que llegaron realmente al render."""
    if clip.get("pipeline_mode") != "v2":
        return []
    data = leer_resolved_seguro(clip, transcripts_dir)
    if data is None or not isinstance(data.get("decisions"), list):
        return []
    dur = _num(clip.get("dur_s")) or 0.0
    markers = []
    for decision in data["decisions"]:
        if not isinstance(decision, dict):
            continue
        status, media = decision.get("status"), decision.get("final_media_type")
        t, t_fin = _num(decision.get("start_s")), _num(decision.get("end_s"))
        if status not in ("resolved", "fallback") or media not in ("image", "video"):
            continue
        if t is None or t_fin is None or t < 0 or t_fin <= t or (dur > 0 and t_fin > dur):
            continue
        markers.append(
            {
                "tipo": f"broll_{media}",
                "t": t,
                "t_fin": t_fin,
                "texto": _texto_publico(decision.get("query"), f"B-roll {media}"),
                "status": status,
            }
        )
    return sorted(markers, key=lambda m: (m["t"], m["tipo"]))


def _stem_de_clip(clip: dict) -> str | None:
    """Stem para sidecars: alerts_file exacto o archivo sin sufijo de estilo."""
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
    dur_s: float,
    avisos: list[dict],
    qa_alertas: list[dict],
    brain_markers: list[tuple[str, float]],
    broll_markers: list[dict] | None = None,
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
    m.extend(broll_markers or [])
    m = [x for x in m if x["t"] is not None]
    if dur_s and dur_s > 0:
        m = [x for x in m if x["t"] <= dur_s + 0.5]
    return sorted(m, key=lambda x: x["t"])


def enriquecer_clip(
    clip: dict,
    pkg_id: str,
    pkg_dir: Path,
    transcripts_dir: Path,
    package_meta: dict | None = None,
) -> dict:
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
    markers = construir_markers(
        dur_s,
        avisos,
        alertas,
        markers_de_brain(clip, transcripts_dir),
        markers_broll_resueltos(clip, transcripts_dir),
    )
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
        "pipeline_mode": clip.get("pipeline_mode"),
        "pipeline_version": clip.get("pipeline_version"),
        "brain_ok": clip.get("brain_ok") if clip.get("pipeline_mode") == "v2" else None,
        "broll": resumen_broll_seguro(clip, package_meta),
        "fx": resumen_fx_seguro(clip),
        "av": resumen_av_seguro(clip),
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
        "clips": [
            enriquecer_clip(c, pkg_id, pkg_dir, transcripts_dir, data.get("meta") or {})
            for c in clips
        ],
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
