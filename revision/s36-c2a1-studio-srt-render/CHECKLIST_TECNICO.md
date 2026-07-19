# CHECKLIST TÉCNICO — S36-C2A1

## Contrato API
- [x] `caption_source: str = "transcript"` en `POST /api/videos/{name}/render`.
- [x] allowlist `transcript|srt`; inválido → 400 "caption_source debe ser 'transcript' o 'srt'.".
- [x] Sin endpoint de render nuevo.
- [x] Respuestas sin ruta administrada/manifiesto/storage_root/texto/bytes/traceback.

## Ruta transcript (histórica, byte-idéntica)
- [x] Mismo `grp_path`, args posicionales, kwargs (`preset/intensidad/qa_mode/qa_guion`).
- [x] No lee manifiesto SRT, no importa el runtime, no valida selección, no crea sidecar SRT.
- [x] Test import-spy: `resolve_selected_srt`/`prepare_selected_srt_groups` NO se llaman.

## Ruta SRT (opt-in)
- [x] Exige video confinado + asociación explícita activa + `{stem}_words.json`.
- [x] Sin autodiscovery, sin buscar `.srt` en input/, sin primer `.srt`, sin archivo privado.
- [x] Combinaciones incompatibles → 400: `caption_qa`, `words_per_group`, `use_emphasis`.
- [x] Permitidos: `style`, `pop`, `preset`, `intensidad`, `use_emojis`.
- [x] Nunca cae al transcript en silencio (selección/timings/integridad → error explícito).

## Runtime privado (`studio_srt_runtime.py`)
- [x] `resolve_selected_srt` → `SelectedSrtRuntime | None` (None si no hay selección).
- [x] managed_file == `{sha}.srt`, confinado (resolve+relative_to), hash real == source_sha256.
- [x] No confía solo en el manifiesto; no repara durante el render.
- [x] `verify_runtime_integrity` revalida en el worker (detecta borrado/manipulación).
- [x] `prepare_selected_srt_groups`: carga words (solo timings), delega en `srt_caption`
      (no duplica parser/alineador/validador), escribe sidecar, valida `wa+fb==n_cues`.
- [x] Errores tipados: `StudioSrtRuntimeError`/`SelectionMissing`/`TimingMissing`/`IntegrityError`.
- [x] Tipos frozen; Paths internos; nunca se serializan a HTTP.

## Render (`srt_render.py` + worker)
- [x] Preset CVE **solo** en `timing_mode != cue_fallback`; fallback estático conservado.
- [x] IDs deterministas reasignados; fail-open si el preset altera el conteo.
- [x] Naming `_srt` reutilizado (fuente única con `caption.py`); no pisa históricos.
- [x] ASS `{name}{variante}_srt.ass`, MP4 `{name}{variante}_srt[_emojis].mp4`.
- [x] `jobs_render.run_render` conserva firma pública (+ `*, srt_selection=None`).
- [x] Split `_run_render_transcript` (verbatim) / `_run_render_srt`.

## Identidad video↔SRT (P2)
- [x] `SelectedSrtRuntime.video_filename` desde `manifest.video.filename` (autoritativo).
- [x] `resolve_selected_video`: sólo `input_dir/filename`, confina (resolve+relative_to), archivo
      regular; NUNCA por stem, extensión, glob, autodiscovery ni primer coincidente.
- [x] `.mov` asociado + `.mp4` decoy (mismo stem) → usa `.mov`; inverso → usa `.mp4`.
- [x] Archivo exacto ausente → 409 `StudioSrtSelectedVideoMissing`; filename corrupto → 500
      `StudioSrtIntegrityError` (no dispara reparación del SRT).
- [x] Worker: `verify_selected_video_match` antes de video info/alineación/ASS/output; mismatch →
      job error sin ASS/MP4/sidecar/ruta/fallback.
- [x] Ruta transcript intacta (sigue usando `_resolver_video_input`); SRT confina el stem sin él.
- [x] E2E: MOV(4s) + decoy MP4(2s) → output ≈ 4s (del MOV).

## Procedencia de timings (P2)
- [x] `transcript_provenance.py` (puro): `build`/`attach`/`validate` con `source_video`
      (version=1 int estricto, basename seguro, ext .mp4/.mov, filename+size+mtime exactos).
- [x] `jobs.run_transcribe` graba `source_video` del video EXACTO; no toca words/language/timings.
- [x] `POST /transcribe?caption_source=srt` transcribe el video exacto asociado (400/409/500).
- [x] Render SRT valida procedencia en endpoint: legacy/otro archivo/size/mtime/corrupta → 409.
- [x] Worker revalida procedencia (TOCTOU) antes de FFmpeg; mismatch → job error, sin fallback.
- [x] `StudioSrtTimingSourceMismatch` (endpoint→409, worker→job error); no dispara reparación.
- [x] Words legacy: transcript las acepta; render SRT las rechaza (retranscribir). No se migran.
- [x] E2E: words de demo.mp4 → render rechazado; tras transcribir el MOV → render usa el MOV.

## Privacidad y seguridad
- [x] SRT original nunca modificado; bytes/SHA administrados intactos.
- [x] Sidecar sin rutas absolutas; resumen público sin cues/texto/rutas.
- [x] Mensajes de error saneados (sin ruta/traceback/contenido).
- [x] Archivo privado `input/0717_corregido.srt` no tocado, no asociado, no impreso.

## Verificación
- [x] `git diff --check`, `ruff check .`, `ruff format --check .` verdes.
- [x] Suite: 1454 passed, 3 skipped (preexistentes), 1 warning (Starlette). check.bat verde.
- [x] E2E FFmpeg real: 2 renders (limpio + preset/emojis), frames, sidecar, SHA intacto.
- [x] Checkpoint real: PENDIENTE (no hay asociación explícita).

## Fuera de alcance (intacto)
- [x] `static/index.html`, `auto*.py`, `studio_auto.py`, `clipper.py`, `reframe.py`,
      `brain.py`, `core_ass.py`, `requirements.txt` no modificados.
