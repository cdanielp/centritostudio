# AUDITORÍA — S36-C2A2 (Auto v2 + clipper + SRT por clip)

Pipeline REAL verificado en el código (no inventado). Base para el contrato de C2A2.

## Pipeline actual (Motor A)
```
video (input/{stem}.mp4|.mov)
 → transcripción  jobs.run_transcribe → core.transcribe_video → {stem}_words.json + {stem}_groups.json
                   (S36-C2A1: caption_source=srt escribe en namespace privado por filename)
 → análisis IA    jobs.run_analyze → brain.json (keywords/énfasis, opcional)
 → Auto           auto.ejecutar_auto (config: AutoConfig) — orquesta clips end-to-end
 → selección      clipper.generar_clips(video, words, tipos, *, srt_document=None)
                   candidatos por frases → score (hook/autocontenido/densidad/cierre/duración)
                   → elegidos (SCORE_MIN, MAX_CLIPS, no solapados)
 → extracción     clipper.cortar_clip(video, start, end, out) vía depurador.run_edl (re-encode)
 → transcript/clip clipper.exportar_transcript_clip(words, wi, wf, out_name)
                   + (con srt_document) SRT rebasado por clip vía srt_slice.slice_srt
 → reframe        reframe 16:9→9:16 (face tracking) [según config]
 → captions/render caption/core_ass (Motor A) — quema ASS
 → paquete        output/paquetes/{...} (paquete.json + REPORTE.md + sidecars)
```

## Contratos/estructuras reales
- **Clip (clipper):** `{tipo, start, end (s), score, wi, wf, ...}`. `cortar_clip` re-encodea `[start,end]`.
- **words:** `[{"w","s","e","prob"}]` (segundos). `groups`: `core.group_words(words)`.
- **SRT por clip (S36-B, ya existe):** `srt_slice.slice_srt(document, start_ms, end_ms, rebase, reindex)`
  intersecta `[start,end)`, recorta bordes, rebasa a t=0, renumera. PURO, testeado (`test_srt_slice.py`).
- **SRT de Studio (S36-C2A1):** selección explícita video↔SRT (`studio_srt*`), video exacto por
  `manifest.video.filename`, timings en namespace privado `transcripts/studio_srt_timings/{stem}/{sha256(filename)}/`,
  binding TOCTOU (`SelectedVideoBinding`), procedencia `source_video`.
- **Checkpoints Auto v2 actuales:** por fingerprint de `AutoConfig`; paquete `{name}_v2_{fecha}` (S37-B).
- **Workers:** `jobs.run_auto` (Auto), `jobs_render.run_render` (render; ruta SRT en C2A1), `jobs.run_transcribe`.

## Qué YA existe (no duplicar)
- Derivación de SRT por clip: `srt_slice.slice_srt` (fórmula de intersección/rebase/reindex de 1B).
- Transcript por clip por índices: `clipper.exportar_transcript_clip`.
- Contrato SRT seguro (video/timings/procedencia/binding/namespace): S36-C2A1.
- Checkpoints/fingerprint Auto v2: S37-B.

## Trabajo NUEVO de C2A2
1. **1B (clip_srt.py):** wrapper fino sobre `srt_slice` que añade el filtro de cues degenerados < 50 ms
   (contrato 1B) y devuelve el SRT derivado del rango del clip. Reutiliza srt_slice (regla anti-duplicación).
2. **1C (clip_transcript.py):** derivar words+groups de un clip desde los timings del video padre
   (intersección temporal + recorte + desplazamiento a t=0 + `core.group_words`) con **procedencia por clip**
   (`parent_video` + `clip` + `output_clip`). PURO.
3. **1D namespace por clip:** `transcripts/studio_srt_clips/{stem}/{filename_key}/{run_id}/{clip_id}/`.
4. **1E checkpoints por run:** stages + estado por clip (resume/retry/cancel, aislamiento de fallos).
5. **1F Auto v2:** `caption_source=transcript|srt` (default transcript byte-idéntico); ruta SRT usa
   selección + video exacto + timings privados + clip_srt + clip_transcript + render por clip `caption_source=srt`.
6. **1G clipper:** integrar sin reescribir la selección; cada clip → MP4 + SRT + words + groups + manifest + alignment.
7. **1H API + 1I tests + 1J E2E + 1K gate visual de K.**

## Alcance de este PR (foundation, NO visual)
Este PR entrega **1A + 1B + 1C**: la auditoría + los dos módulos puros de derivación por clip
(`clip_srt.py`, `clip_transcript.py`) con tests exhaustivos. Sin FFmpeg, sin Auto, sin UI, sin salida
visual → mergeable con suite/ruff/check.bat verdes (no requiere gate de K). La integración Auto v2/clipper/
checkpoints (1D–1J) y el gate visual (1K) quedan como continuación de C2A2 (misma fase, PR posterior),
por su tamaño y por requerir veredicto visual de K.
