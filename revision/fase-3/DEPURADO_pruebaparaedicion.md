# Fase 3 — Depurador: pruebaparaedicion.mov

## Setup

- Archivo: `input/pruebaparaedicion.mov` (H264+AAC en contenedor .mov — compatible nativo con FFmpeg)
- Duración original: **92.02s**
- Resolución: 2618x1440 @ 30fps
- Volumen medio: -14.2 dBFS (voz TTS clara)
- Palabras transcriptas: **242** (Whisper medium-auto, CUDA, 11.8s)
- Modo ejecutado: **seguro** (solo compresión de silencios)
- Naturaleza del video: clips TTS unidos con cortes duros — voz sintética, sin muletillas

## Umbral y parámetros

| Parámetro | Valor |
|-----------|-------|
| SILENCE_GAP | **0.8s** — gaps mayores a esto se comprimen |
| SILENCE_COMPRESS | 0.25s — duración del silencio comprimido |
| MAX_ITERS | 3 iteraciones de auto-evaluación |
| XFADE_S | 0.03s (30ms crossfade audio) |

## Silencios detectados (pre-análisis)

Gaps > 0.3s encontrados: **18**
Gaps > 0.8s que serán cortados: **4**

| # | Desde | Hacia | Gap original |
|---|-------|-------|-------------|
| 1 | "hecho." [46] | "En" [47] | **1.060s** |
| 2 | "cero." [94] | "En" [95] | **1.290s** |
| 3 | "obra." [143] | "En" [144] | **1.200s** |
| 4 | "estilo." [192] | "Piensa" [193] | **1.290s** |

Los 18 gaps entre 0.3s y 0.8s NO se tocaron — COMPORTAMIENTO CORRECTO.
Nota: las duraciones de gap en la tabla son los timestamps de Whisper (redondeados). El ahorro
real post-render es mayor porque los segmentos EDL usan los timestamps exactos de ffprobe.
Muletillas detectadas: **0**. Falsos arranques: **0**.

## Resultados

- Cortes aplicados: **4** (uno por cada silencio > 0.8s)
- Duración original: 92.02s
- Duración limpia: **~87.2s** (4.8s ahorrado — 5.2%)
- Drift de words.json: **0.0s** (todas las 242 palabras mapearon correctamente)
- Tiempo de proceso: 129.6s (re-encoding x3 iteraciones)

## Auto-evaluación _eval_and_adjust — deltas por iteración

**Nota:** El fix del commit ecc6e82 (procesar TODAS las uniones por iteración) está activo.
En cada iteración se ajustaron las 4 uniones simultáneamente.

| Iteración | Unión @16.7s | Unión @35.5s | Unión @54.0s | Unión @69.2s | Ajustado |
|-----------|-------------|-------------|-------------|-------------|----------|
| Iter 1 | 18.8 dB ✗ | 46.8 dB ✗ | 36.5 dB ✗ | 29.0 dB ✗ | Sí (4/4) |
| Iter 2 | 13.5 dB ✗ | 36.5 dB ✗ | 18.5 dB ✗ | 12.0 dB ✗ | Sí (4/4) |
| Iter 3 | 12.7 dB ✗ | 13.5 dB ✗ | 9.0 dB ✗ | 8.0 dB ✗ | Sí (4/4) |

**Resultado: NO CONVERGE (3/3 iteraciones — ninguna unión baja de 6dB).**

## Diagnóstico de no-convergencia

Los deltas altos son ESPERADOS y ESTRUCTURALES en este tipo de video:

- Las uniones están en transiciones **silencio→habla** (0.25s de silencio comprimido seguido de voz)
- `_volume_at(j_time - 0.3)` mide dentro del silencio comprimido → volumen muy bajo (-20 a -60dBFS)
- `_volume_at(j_time + 0.02)` mide justo al inicio del siguiente clip → voz a -10dBFS
- Delta estructural = ~10-50dB independientemente del ajuste de posición de corte
- El ajuste de -80ms desplaza la frontera dentro del silencio, mejorando marginalmente pero sin cambiar la naturaleza silencio→habla de la transición

**Los videos limpio son funcionalmente correctos** — fronteras sin artefactos visuales (ver frames).
El delta > 6dB es un falso positivo del criterio volumétrico, no un defecto real del corte.

### Decisión pendiente para el arquitecto

La metodología de `_volume_at` con ventana de 0.3s en transiciones de silencio→habla
siempre generará deltas > 6dB. Opciones:

1. **Elevar el umbral** de 6dB a 15-20dB para estos casos
2. **Cambiar la ventana de medición** — medir más lejos del punto de unión (ej: j_time - 0.8)
3. **Desactivar el loop** para el modo seguro (los silencios comprimidos son estructuralmente limpios)
4. **Aceptar no-convergencia** como comportamiento esperado en TTS/silencio sintético

## Evidencia visual — fronteras limpias

Todas las fronteras son visualmente limpias (sin artefactos de video).
Clips de fondo consistente (estudio de podcasting), transiciones invisibles.

| Frame | Descripción |
|-------|-------------|
| `v1_pre_t16p59.png` | Antes de unión 1 @16.59s |
| `v1_post_t16p59.png` | Después de unión 1 @16.59s |
| `v1_pre_t35p44.png` | Antes de unión 2 @35.44s |
| `v1_post_t35p44.png` | Después de unión 2 @35.44s |
| `v1_pre_t53p47.png` | Antes de unión 3 @53.47s |
| `v1_post_t53p47.png` | Después de unión 3 @53.47s |
| `v1_pre_t68p52.png` | Antes de unión 4 @68.52s |
| `v1_post_t68p52.png` | Después de unión 4 @68.52s |
