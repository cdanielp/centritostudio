"""auto_srt_manifest.py — Manifiesto FINAL saneado de un run de Auto `caption_source=srt` (S36-C2C).

Capa PURA que reconstruye por WHITELIST el resumen público de un run SRT a partir de la lista de
clips que produce `ejecutar_auto`. Es el cierre del flujo S36: un solo objeto estable que un
cliente (o un tester) puede leer sin tocar el estado privado del run.

NUNCA incluye rutas absolutas, texto de cues, hashes ni tracebacks: solo `run_id`/basenames
seguros, `status` normalizado (`done|error`), enteros y ratios en [0,1]. Un clip en error nunca
expone `output` (no hay MP4 publicable). Tiempos en ms enteros.

Sin FFmpeg, sin Auto, sin FastAPI, sin red, sin UI.
"""

from __future__ import annotations

from pathlib import Path

from studio_srt_manifest import is_safe_basename

MANIFEST_VERSION = 1


class AutoSrtManifestError(Exception):
    """Un clip viola el contrato del manifiesto (clip_id/output inseguro). Sin rutas ni texto."""


def _safe_basename(value: object, etiqueta: str) -> str:
    if not is_safe_basename(value) or value in (".", ".."):
        raise AutoSrtManifestError(f"{etiqueta} inseguro")
    return value  # type: ignore[return-value]


def _safe_ms(value: object) -> int:
    """Entero de ms >= 0. Acepta int; rechaza bool; None/no-int -> 0."""
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value if value >= 0 else 0


def _safe_ratio(value: object) -> float:
    """Float clampeado a [0,1]. Rechaza bool/no-numérico -> 0.0."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    if f != f:  # NaN
        return 0.0
    return 0.0 if f < 0.0 else 1.0 if f > 1.0 else round(f, 4)


def _clean_clip(clip: object) -> dict:
    """Reconstruye la entrada pública de UN clip con solo las claves aprobadas.

    `clip_id` es obligatorio y debe ser un basename seguro. `status` se normaliza a `done|error`.
    Un clip en error NUNCA expone `output` (no hay MP4 publicable). `output` (si done) es el
    basename del MP4. Coberturas/ratios se clampan a [0,1]; duración a ms>=0.
    """
    if not isinstance(clip, dict):
        raise AutoSrtManifestError("clip no es objeto")
    clip_id = _safe_basename(clip.get("clip_id"), "clip_id")
    status = "error" if clip.get("status") == "error" else "done"
    output = None
    if status == "done":
        archivo = clip.get("archivo")
        output = _safe_basename(archivo, "output") if archivo is not None else None
    dur_ms = clip.get("duration_ms")
    if (
        dur_ms is None
        and isinstance(clip.get("dur_s"), (int, float))
        and not isinstance(clip.get("dur_s"), bool)
    ):
        dur_ms = int(round(float(clip["dur_s"]) * 1000))
    return {
        "clip_id": clip_id,
        "status": status,
        "output": output,
        "duration_ms": _safe_ms(dur_ms),
        "caption_coverage": _safe_ratio(clip.get("caption_coverage")),
        "fallback_ratio": _safe_ratio(clip.get("fallback_ratio")),
    }


def build_run_manifest(
    *, run_id: str, source_filename: str, srt_selected: bool, clips: list
) -> dict:
    """Manifiesto v1 saneado del run SRT: version, run_id, source, clips[], summary.

    `run_id` y `source_filename` deben ser basenames seguros. `clips` es la lista de dicts que
    devuelve `ejecutar_auto`. Nunca incluye rutas, texto ni hashes. Lanza AutoSrtManifestError si
    un clip_id/output/filename viola el contrato (indicio de bug o manipulación, no dato del run).
    """
    _safe_basename(run_id, "run_id")
    _safe_basename(source_filename, "source_filename")
    clean = [_clean_clip(c) for c in clips]
    done = sum(1 for c in clean if c["status"] == "done")
    error = sum(1 for c in clean if c["status"] == "error")
    return {
        "version": MANIFEST_VERSION,
        "run_id": run_id,
        "caption_source": "srt",
        "source": {"video_filename": source_filename, "srt_selected": bool(srt_selected)},
        "clips": clean,
        "summary": {"total": len(clean), "done": done, "error": error},
    }


def manifest_filename() -> str:
    """Nombre del archivo del manifiesto dentro del paquete del run."""
    return "srt_run_manifest.json"


def write_run_manifest(paquete_dir: Path, manifest: dict) -> Path:
    """Escribe el manifiesto saneado en `{paquete_dir}/srt_run_manifest.json` (atómico)."""
    import json  # noqa: PLC0415

    path = Path(paquete_dir) / manifest_filename()
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    import os  # noqa: PLC0415

    os.replace(tmp, path)
    return path


__all__ = [
    "MANIFEST_VERSION",
    "AutoSrtManifestError",
    "build_run_manifest",
    "manifest_filename",
    "write_run_manifest",
]
