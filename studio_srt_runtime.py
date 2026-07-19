"""studio_srt_runtime.py — Runtime privado de la seleccion SRT para el render (S36-C2A1, D38).

Capa PURA entre el contrato de asociacion (S36-C1) y el worker de render. Resuelve la
seleccion SRT activa de un video, verifica su integridad EN TIEMPO DE USO (no confia solo
en el manifiesto) y prepara los groups reutilizando S36-B (`srt_caption`). El TEXTO del SRT
es la fuente oficial; las words de Whisper solo aportan timings.

Sin FastAPI, sin HTML, sin threading, sin jobs, sin FFmpeg, sin Auto, sin UI, sin red.
Nunca serializa Paths ni texto de cues a HTTP: `SelectedSrtRuntime` es interno; el resumen
publico (`PreparedSrtRender.summary`) solo lleva basenames, conteos y ratios.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import srt_caption
import studio_srt
import studio_srt_manifest as manifest_mod
from srt_import import SrtError
from studio_srt import StudioSrtError, StudioSrtStorageError


# ─── Errores tipados (contrato de uso / integridad, no bugs) ───────────────────
class StudioSrtRuntimeError(StudioSrtError):
    """Base de errores del runtime de render SRT."""


class StudioSrtSelectionMissing(StudioSrtRuntimeError):
    """Se pidio render SRT pero el video no tiene una seleccion activa."""


class StudioSrtTimingMissing(StudioSrtRuntimeError):
    """Falta `{stem}_words.json` o es ilegible/vacio: no hay timings para alinear."""


class StudioSrtIntegrityError(StudioSrtStorageError):
    """El archivo administrado no existe, escapa del root o su hash no coincide."""


class StudioSrtSelectedVideoMissing(StudioSrtRuntimeError):
    """La selección existe pero el archivo de video EXACTO (manifest.video.filename) no está
    disponible en input/. NO hereda de StudioSrtStorageError: no dispara reparación del SRT."""


# ─── Tipos frozen (internos: nunca se serializan a HTTP) ───────────────────────
@dataclass(frozen=True)
class SelectedSrtRuntime:
    """Seleccion SRT resuelta y verificada. INTERNO: contiene Paths, no sale por API."""

    video_stem: str
    video_filename: str
    source_name: str | None
    source_sha256: str
    managed_file: str
    managed_path: Path
    storage_root: Path
    manifest: dict


@dataclass(frozen=True)
class PreparedSrtRender:
    """Groups listos + AlignmentResult + resumen publico saneado (sin cues/texto/rutas)."""

    groups: list
    result: object
    summary: dict


# ─── Integridad del archivo administrado ───────────────────────────────────────
def _managed_path_confinada(storage_root: Path, video_stem: str, managed_file: str) -> Path:
    """Path del archivo administrado, confinado en storage_root/video_stem. Lanza si escapa."""
    video_dir = Path(storage_root) / video_stem
    managed_path = video_dir / managed_file
    try:
        managed_path.resolve().relative_to(video_dir.resolve())
    except ValueError:
        raise StudioSrtIntegrityError("archivo administrado fuera del almacenamiento") from None
    return managed_path


def _verificar_hash(managed_path: Path, expected_sha: str) -> None:
    """Exige archivo regular cuyo sha256 real coincida con lo asociado. Nunca revela contenido."""
    if not managed_path.is_file():
        raise StudioSrtIntegrityError("el archivo administrado no existe")
    try:
        actual = managed_path.read_bytes()
    except OSError:
        raise StudioSrtIntegrityError("no se pudo leer el archivo administrado") from None
    if not actual or hashlib.sha256(actual).hexdigest() != expected_sha:
        raise StudioSrtIntegrityError("el archivo administrado no coincide con el hash")


# ─── Resolucion de la seleccion activa ─────────────────────────────────────────
def resolve_selected_srt(
    video_stem: str, *, storage_root: Path, manifest_dir: Path
) -> SelectedSrtRuntime | None:
    """Seleccion SRT activa y verificada, o None si el video no tiene seleccion.

    Lee el manifiesto saneado (S36-C1), exige `managed_file == {sha}.srt`, confina el
    archivo en el storage y verifica su hash real (no confia solo en el manifiesto). No
    repara (la reparacion es del contrato C1 vía re-upload). Lanza StudioSrtIntegrityError
    /StorageError si el manifiesto o el storage estan rotos; nunca revela rutas ni contenido.
    """
    manifest = studio_srt.read_selection(video_stem, Path(manifest_dir))
    selection = manifest.get("selection", {}) if isinstance(manifest, dict) else {}
    if selection.get("selected") is not True:
        return None
    source_sha256 = selection.get("source_sha256")
    managed_file = selection.get("managed_file")
    if not manifest_mod.is_sha256(source_sha256):
        raise StudioSrtIntegrityError("sha256 de la seleccion invalido")
    if not manifest_mod.is_safe_basename(managed_file) or managed_file != f"{source_sha256}.srt":
        raise StudioSrtIntegrityError("managed_file no coincide con el sha")
    # El filename del video es AUTORITATIVO (video↔SRT): identifica el archivo exacto contra el
    # que se validó la selección. El manifiesto saneado (C1) lo garantiza; se relee defensivo.
    video_meta = manifest.get("video", {}) if isinstance(manifest, dict) else {}
    video_filename = video_meta.get("filename")
    if not isinstance(video_filename, str) or not video_filename:
        raise StudioSrtIntegrityError("filename de video invalido en el manifiesto")
    storage_root = Path(storage_root)
    managed_path = _managed_path_confinada(storage_root, video_stem, managed_file)
    _verificar_hash(managed_path, source_sha256)
    return SelectedSrtRuntime(
        video_stem=video_stem,
        video_filename=video_filename,
        source_name=selection.get("source_name"),
        source_sha256=source_sha256,
        managed_file=managed_file,
        managed_path=managed_path,
        storage_root=storage_root,
        manifest=manifest,
    )


def verify_runtime_integrity(runtime: SelectedSrtRuntime) -> None:
    """Revalida en el worker que el archivo administrado sigue existiendo y su hash coincide.

    Captura manipulacion/borrado entre el endpoint y el worker. Nunca cae al transcript.
    """
    managed_path = _managed_path_confinada(
        runtime.storage_root, runtime.video_stem, runtime.managed_file
    )
    _verificar_hash(managed_path, runtime.source_sha256)


# ─── Identidad del video (video↔SRT): filename EXACTO del manifiesto ───────────
_ALLOWED_VIDEO_EXT = frozenset({".mp4", ".mov"})


def _validar_filename_video(runtime: SelectedSrtRuntime) -> str:
    """Valida el filename autoritativo de la selección. Un filename inconsistente con el
    manifiesto (vacío/inseguro/extensión/stem) es corrupción del manifiesto -> Integrity."""
    fn = runtime.video_filename
    if not isinstance(fn, str) or not fn:
        raise StudioSrtIntegrityError("filename de video vacio")
    if not manifest_mod.is_safe_basename(fn):
        raise StudioSrtIntegrityError("filename de video inseguro")
    name_path = Path(fn)
    if name_path.suffix.lower() not in _ALLOWED_VIDEO_EXT:
        raise StudioSrtIntegrityError("extension de video no permitida")
    if name_path.stem != runtime.video_stem:
        raise StudioSrtIntegrityError("el filename no corresponde al video de la seleccion")
    return fn


def resolve_selected_video(runtime: SelectedSrtRuntime, *, input_dir: Path) -> Path:
    """Ruta EXACTA del video asociado, según `manifest.video.filename`. NUNCA por stem ni por
    prioridad de extensión: un `.mp4` y un `.mov` con el mismo stem no pueden cruzarse.

    Construye sólo `input_dir / filename`, confina (resolve+relative_to) y exige archivo regular.
    Filename inconsistente con el manifiesto -> StudioSrtIntegrityError (500). Archivo exacto
    ausente o no confinado -> StudioSrtSelectedVideoMissing (409). No expone rutas en el error.
    """
    fn = _validar_filename_video(runtime)
    input_dir = Path(input_dir)
    candidate = input_dir / fn
    try:
        candidate.resolve().relative_to(input_dir.resolve())
    except ValueError:
        raise StudioSrtSelectedVideoMissing("el video asociado no esta disponible") from None
    if not candidate.is_file():
        raise StudioSrtSelectedVideoMissing("el video asociado ya no esta disponible")
    return candidate


def verify_selected_video_match(runtime: SelectedSrtRuntime, video_path: Path) -> None:
    """Exige que `video_path` sea EXACTAMENTE el video de la selección (nombre+stem+extensión+
    regular). Protege contra que el worker reciba otro archivo o un cambio de extensión entre
    endpoint y worker. No vuelve a resolver por stem. Mismatch -> SelectedVideoMissing (sin ruta).
    """
    video_path = Path(video_path)
    if (
        video_path.name != runtime.video_filename
        or video_path.stem != runtime.video_stem
        or video_path.suffix.lower() not in _ALLOWED_VIDEO_EXT
    ):
        raise StudioSrtSelectedVideoMissing("el video no coincide con la seleccion")
    if not video_path.is_file():
        raise StudioSrtSelectedVideoMissing("el video asociado ya no esta disponible")


# ─── Preparacion de groups (delega en S36-B; no duplica parser/alineador) ──────
def _cargar_words(words_path: Path) -> list:
    """Lista `words` de `{stem}_words.json`. Solo timings. Lanza StudioSrtTimingMissing si falta."""
    words_path = Path(words_path)
    if not words_path.is_file():
        raise StudioSrtTimingMissing("no hay transcript de palabras para este video")
    try:
        raw = json.loads(words_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise StudioSrtTimingMissing("el transcript de palabras es ilegible") from None
    if not isinstance(raw, dict) or not isinstance(raw.get("words"), list):
        raise StudioSrtTimingMissing("el transcript de palabras tiene un formato invalido")
    words = raw["words"]
    if not words:
        raise StudioSrtTimingMissing("el transcript de palabras esta vacio")
    return words


def _public_summary(
    runtime: SelectedSrtRuntime, result, n_warnings: int, sidecar_name: str
) -> dict:
    """Resumen publico: solo basenames, conteos y ratios. Sin cues, texto ni rutas."""
    return {
        "source": "srt",
        "source_sha256": runtime.source_sha256,
        "alignment_sidecar": sidecar_name,
        "n_cues": result.n_cues,
        "word_aligned": result.word_aligned,
        "cue_fallback": result.cue_fallback,
        "coverage": result.coverage,
        "min_coverage": result.min_coverage,
        "exact_matches": result.n_exact,
        "substitution_matches": result.n_substitution,
        "rejected_substitutions": result.n_rejected_sub,
        "n_warnings": n_warnings,
    }


def prepare_selected_srt_groups(
    runtime: SelectedSrtRuntime,
    *,
    words_path: Path,
    video_duration_ms: int | None,
    alignment_sidecar_path: Path,
) -> PreparedSrtRender:
    """Groups del SRT seleccionado (S36-B) + sidecar + resumen publico saneado.

    Carga `{stem}_words.json` (solo timings), delega en `srt_caption.preparar_desde_srt`
    (no duplica parser/alineador/validador), escribe el sidecar y arma el resumen publico.
    Un SRT estructuralmente invalido (no deberia pasar C1) se traduce a StudioSrtRuntimeError.
    """
    words = _cargar_words(words_path)
    try:
        groups, result, payload = srt_caption.preparar_desde_srt(
            runtime.managed_path,
            words,
            video_duration_ms=video_duration_ms,
            words_file=Path(words_path).name,
        )
    except SrtError:
        raise StudioSrtRuntimeError("el SRT seleccionado no se pudo alinear") from None
    srt_caption.escribir_sidecar(payload, Path(alignment_sidecar_path))
    n_warnings = payload["summary"]["n_warnings"]
    summary = _public_summary(runtime, result, n_warnings, Path(alignment_sidecar_path).name)
    if summary["word_aligned"] + summary["cue_fallback"] != summary["n_cues"]:
        raise StudioSrtRuntimeError("resumen de alineacion inconsistente")
    return PreparedSrtRender(groups=groups, result=result, summary=summary)


__all__ = [
    "SelectedSrtRuntime",
    "PreparedSrtRender",
    "StudioSrtRuntimeError",
    "StudioSrtSelectionMissing",
    "StudioSrtTimingMissing",
    "StudioSrtIntegrityError",
    "StudioSrtSelectedVideoMissing",
    "resolve_selected_srt",
    "resolve_selected_video",
    "verify_selected_video_match",
    "verify_runtime_integrity",
    "prepare_selected_srt_groups",
]
