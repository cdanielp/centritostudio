# CHECKLIST VISUAL — S36-C2A2 Auto SRT (E2E FFmpeg REAL)

Generado por `smoke_auto_srt_clips.py` (offline, sin GPU/red/LLM: la selección de clips se
inyecta, pero extracción FFmpeg + reframe + derivación + ASS + burn corren de verdad).
Video padre sintético: 1080x1920, 16 s, color+tono. SRT del padre: 4 cues.
Evidencia (NO versionada) en `output/revision-s36-c2a2-integration/`.

## Clips (rango fuente → clip rebasado a t=0)
| clip | rango fuente (s) | dur | cues del padre que caen | rebase esperado | SHA256 (12) |
|------|------------------|-----|--------------------------|-----------------|-------------|
| clip_001_srt.mp4 | [0, 5) | 5 s | cue1 "Uno dentro" [0,2) | [0,2) | 5fb442a6785a |
| clip_002_srt.mp4 | [4, 8) | 4 s | cue2 "Dos cruza corte" [4,6)→recorte | [0,2) | 180e414768cd |
| clip_003_srt.mp4 | [12, 16) | 4 s | cue4 "Cuatro final" [14,16) | [2,4) | 65c0c2f684e5 |

## ffprobe (real)
- clip 1: dur 5.000000 s, streams [audio, video].
- clip 2: dur 4.000000 s, streams [audio, video].
- clip 3: dur 4.000000 s, streams [audio, video].
- Tres MP4 DISTINTOS (SHA256 distintos). 1080x1920 vertical.

## Revisión visual interna (mis propios ojos, NO veredicto de K)
- clip_002_mid.png (t=1.0 s): muestra **"DOS CRUZA CORTE"** — cue del padre [4,6)s rebasado a
  [0,2)s del clip, texto OFICIAL del SRT, tiempo relativo a 0. ✔
- captions comienzan en tiempo relativo 0 del clip. ✔
- no aparecen cues de otro rango (cada clip solo muestra los cues de SU rango). ✔
- texto correcto del SRT (no del transcript del padre). ✔
- vertical 1080x1920, sin flash negro, audio presente. ✔

## Frames entregados
`clip_001_mid.png`, `clip_002_mid.png`, `clip_003_mid.png` (extraídos a t=1.0 s de cada clip).

## Estado
Evidencia AUDIOVISUAL REAL lista para el ojo de K. No se afirma aprobación de K.
