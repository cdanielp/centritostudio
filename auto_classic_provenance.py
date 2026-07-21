"""auto_classic_provenance.py — Procedencia explicita del Auto CLASSIC (H2, P2-CLASSIC-REUSE).

Sella QUE video EXACTO + parametros produjeron el transcript/clips reutilizables del Modo
Automatico classic. Antes se reutilizaba por `stem` + `mtime>=video`: un `.mov` y un `.mp4` con
el mismo stem, o el mismo stem con distinto tamano/mtime, podian reutilizar timings/clips ajenos.
Fail-closed: sin procedencia o incompatible -> se retranscribe / se re-ejecuta el clipper.

Provenance minima: schema_version, pipeline_mode=classic, filename normalizado, st_size,
st_mtime_ns, lang y model (afectan el resultado de la transcripcion). No calcula hash del video.

PURO: sin FFmpeg, sin red, sin Auto, sin UI. Solo lee `stat()` del video. NO se mezcla con las
rutas SRT/v2 (que ya tienen sus propios contratos de fingerprint/procedencia).
"""

from __future__ import annotations

from pathlib import Path

SCHEMA_VERSION = 1
PIPELINE_MODE = "classic"


def _strict_int(value: object) -> int | None:
    """int estricto (rechaza bool y no-int). None si no es un entero limpio."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def build_provenance(video_path: Path, *, lang: str, model: str) -> dict:
    """Bloque de procedencia classic del video EXACTO (basename + size + mtime + lang + model)."""
    video_path = Path(video_path)
    st = video_path.stat()
    return {
        "schema_version": SCHEMA_VERSION,
        "pipeline_mode": PIPELINE_MODE,
        "filename": video_path.name,
        "size_bytes": int(st.st_size),
        "mtime_ns": int(st.st_mtime_ns),
        "lang": lang,
        "model": model,
    }


def matches(stored: object, video_path: Path, *, lang: str, model: str) -> bool:
    """True SOLO si `stored` es procedencia classic v1 del video EXACTO y mismo lang/model.

    Fail-closed: estructura invalida, schema/pipeline distinto, filename ajeno, size/mtime que no
    coinciden con el `stat()` real (o video ausente/no-regular), o lang/model distintos -> False.
    Procedencia AUSENTE (dict vacio / None) tambien devuelve False -> no se reutiliza.
    """
    if not isinstance(stored, dict):
        return False
    if _strict_int(stored.get("schema_version")) != SCHEMA_VERSION:
        return False
    if stored.get("pipeline_mode") != PIPELINE_MODE:
        return False
    video_path = Path(video_path)
    filename = stored.get("filename")
    if not isinstance(filename, str) or filename != video_path.name:
        return False
    if stored.get("lang") != lang or stored.get("model") != model:
        return False
    size = _strict_int(stored.get("size_bytes"))
    mtime = _strict_int(stored.get("mtime_ns"))
    if size is None or size < 0 or mtime is None or mtime <= 0:
        return False
    try:
        st = video_path.stat()
    except OSError:
        return False
    if not video_path.is_file():
        return False
    return size == int(st.st_size) and mtime == int(st.st_mtime_ns)


__all__ = ["SCHEMA_VERSION", "PIPELINE_MODE", "build_provenance", "matches"]
