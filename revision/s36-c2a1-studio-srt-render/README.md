# S36-C2A1 — Render del SRT seleccionado desde Studio

Conecta la asociación privada video↔SRT de **S36-C1** con el **render normal** de Studio.
Al pedir `caption_source=srt`, el endpoint usa el SRT seleccionado como **texto oficial** y las
words de Whisper **solo como timings** (S36-B). Sin UI nueva, sin Auto v2, sin clipper.

## Alcance de este PR (S36-C2A1)
- Runtime privado de la selección (`studio_srt_runtime.py`): resuelve la selección activa,
  verifica integridad en tiempo de uso (no confía solo en el manifiesto) y prepara los groups
  reutilizando S36-B.
- Helpers de render reutilizables (`srt_render.py`): preset CVE **solo** en cues alineados +
  naming determinista `_srt` (fuente única con la CLI `caption.py --srt`).
- Endpoint `POST /api/videos/{name}/render?caption_source=transcript|srt` (default `transcript`).
- Worker `jobs_render._run_render_srt` (split; `run_render` sigue siendo el contrato público).
- Sidecar de alineación privado + resumen público saneado en el resultado del job.

Fuera de alcance (S36-C2A2 y posteriores): Auto v2, clipper con SRT, SRT derivado por clip,
batch, edición en UI, templates 9:16, forced aligner, F6, HyperFrames.

## Política
- **transcript** es el default histórico EXACTO: no consulta la selección SRT, no importa el
  runtime, byte-idéntico.
- **srt** es opt-in explícito: exige una asociación activa (sin autodiscovery), un
  `{stem}_words.json`, y rechaza con 400 las combinaciones incompatibles
  (`caption_qa`, `words_per_group`, `use_emphasis`). Nunca cae al transcript en silencio.
- Los cues `word_aligned` se animan word-by-word; los `cue_fallback` quedan **estáticos**.
- El SRT original nunca se modifica; el output usa sufijo `_srt` (no pisa históricos).
- El resultado del job y las respuestas HTTP nunca exponen rutas, bytes ni texto de cues.

## E2E sintético (FFmpeg real, sin red, sin GPU, sin Auto)
```
venv\Scripts\python revision\s36-c2a1-studio-srt-render\smoke_studio_srt_render.py
```
Fixture (`fixtures/`, sintético y versionado): `demo.srt` (4 cues) + `demo_words.json`.
El video sintético (1080x1920, 4s, con audio) y los renders/frames van a
`output/revision-s36-c2a1/` (**gitignored**, no se sube al PR).

Alineación del fixture: **word_aligned=3** (incl. **1 sustitución**: SRT dice `final`, Whisper
`finall` → se muestra `final`), **cue_fallback=1**, `exact=5`, `substitution=1`, `coverage≈0.67`,
`n_warnings=0`. SHA de la fuente intacto antes/después.

### Evidencia visual (para el ojo de K, no versionada)
`output/revision-s36-c2a1/frame_*.png`:
- `frame_A_word_aligned.png` — "HOLA MUNDO", palabra activa resaltada (word-by-word).
- `frame_A_substitution.png` — "PRUEBA **FINAL**" (texto del SRT, no `finall`).
- `frame_A_fallback.png` — "SIN TIMING AQUI" estático (sin resaltado por palabra).
- `frame_B_preset.png` — preset `viral_bounce` + emojis (offline, 0 overlays).

Renders A (`demo_hormozi_srt.mp4`) y B (`demo_viral_bounce_srt_emojis.mp4`): 1080x1920, 4s,
con audio, sin flash negro.

## Corrección P2 — identidad video↔SRT
La ruta SRT usa el **filename exacto** registrado en el manifiesto (`manifest.video.filename`); no
resuelve por stem ni cambia de extensión. Un `.mov` asociado y un `.mp4` decoy con el mismo stem no
pueden cruzarse. `resolve_selected_video` confina + exige archivo regular (ausente → 409, filename
corrupto → 500); el worker revalida con `verify_selected_video_match` antes de FFmpeg (mismatch → job
error sin ASS/MP4/sidecar/ruta/fallback). El smoke incluye el escenario: MOV asociado (4s) + decoy MP4
(2s) → el render usa el MOV (dur ≈ 4s, nunca los 2s del decoy).

## Checkpoint privado real
**PENDIENTE: no existe una asociación explícita** (`transcripts/*_srt_selection.json`) creada por
el usuario. Por gobernanza NO se asocia el archivo privado ni se adivina a qué video pertenece;
la cobertura real se registrará cuando exista una asociación explícita. El PR queda abierto y
**no cierra visualmente** S36-C2A1 hasta el veredicto visual de K.

## Estado
PR ABIERTO Y NO MERGEADO. Pendiente **VEREDICTO VISUAL DE K**.

## Corrección P2 — procedencia de timings
El video exacto ya se resolvía por `manifest.video.filename`, pero `{stem}_words.json` era
stem-only. Ahora los timings declaran `source_video` (filename+size+mtime del video EXACTO):
`run_transcribe` la graba; `POST /transcribe?caption_source=srt` transcribe el video exacto
asociado; el render SRT rechaza con **409** words legacy o de otro archivo/versión (endpoint +
worker TOCTOU), sin fallback. El smoke lo cubre: words de `demo.mp4` → render rechazado; tras
transcribir el MOV → render usa el MOV (4s).

## Corrección P2 — aislamiento de artefactos + reconfinamiento TOCTOU
- **Aislamiento (P2-A):** los timings SRT viven en `transcripts/studio_srt_timings/{stem}/{sha256(filename)}/words+groups.json`. `transcribe?caption_source=srt` NO sobrescribe los `{stem}_words/groups` históricos (que usa el render transcript del MP4). El render SRT usa solo el namespace privado (emojis incluidos).
- **Reconfinamiento (P2-B):** `SelectedVideoBinding` captura root/target(resolve strict)/size/mtime en el endpoint; los workers de render y transcribe revalidan antes de FFmpeg/Whisper → bloquean retarget de symlink, reemplazo o borrado del video, sin fallback.
- El smoke cubre: transcript MP4 histórico intacto tras transcribe SRT del MOV; render SRT del MOV usa su namespace; timings ajenos → rechazo; reemplazo del video (TOCTOU) → aborta.
