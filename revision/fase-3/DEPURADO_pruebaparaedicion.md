# Fase 3 — Depurador: pruebaparaedicion.mov (v2 — criterio voz-a-voz)

## Setup

- Archivo: `input/pruebaparaedicion.mov` (H264+AAC, .mov — compatible nativo con FFmpeg)
- Duración original: **92.02s**
- Resolución: 2618x1440 @ 30fps
- Volumen medio: -14.2 dBFS (voz TTS clara)
- Palabras transcriptas: **242** (Whisper medium-auto, CUDA, 11.8s)
- Modo ejecutado: **seguro**
- Naturaleza: 4 clips TTS unidos con cortes duros; voz sintética, sin muletillas

## Umbral y parámetros

| Parámetro | Valor |
|-----------|-------|
| SILENCE_GAP | **0.8s** — gaps mayores se comprimen |
| SILENCE_COMPRESS | 0.25s — duración del silencio comprimido |
| XFADE_S | 0.03s (30ms crossfade audio) |
| MAX_ITERS | 3 |
| Criterio eval | **voz-a-voz** — mide última ventana de voz antes del corte vs primera voz post-corte |

## Silencios detectados (pre-análisis)

Gaps > 0.8s que se comprimen: **4**

| # | Desde | Hacia | Gap original |
|---|-------|-------|-------------|
| 1 | "hecho." [46] | "En" [47] | 1.060s |
| 2 | "cero." [94] | "En" [95] | 1.290s |
| 3 | "obra." [143] | "En" [144] | 1.200s |
| 4 | "estilo." [192] | "Piensa" [193] | 1.290s |

Nota: las duraciones en tabla son de Whisper (redondeadas). El ahorro real lo mide ffprobe post-render.
Gaps 0.3–0.8s: **18** → NO cortados. Muletillas: **0**. Falsos arranques: **0**.

## Resultados

- Cortes: **4**
- Duración limpia: **~87.2s** (~4.8s ahorrado — 5.2%)
- Drift words.json: **0.0s** (242/242 palabras mapeadas)

## Auto-evaluación _eval_and_adjust — nuevo criterio voz-a-voz

### Cómo funciona el nuevo criterio

1. `voice_refs` precomputados desde el EDL inicial (estables, no cambian con ajustes):
   `[16.5s, 36.32s, 55.55s, 71.71s]` (fin de última palabra antes de cada corte, tiempo original)
2. En cada unión: mide ventana de 150ms justo antes del silencio comprimido → volumen de la voz pre-corte
3. Compara contra voz post-corte (`j_time + 0.02s`)
4. Si delta > 6dB → ajusta corte -80ms
5. `sil_in_seg` decrece monotónicamente: 0.250 → 0.170 → 0.090 (no hay feedback loop)

### Tabla de convergencia

| Iter | @16.7s | @35.8s | @54.0s | @69.2s | Ajustado |
|------|--------|--------|--------|--------|----------|
| 1 | 10.3✗ | 18.3✗ | 10.0✗ | 6.7✗ | Sí (4/4) |
| 2 | 10.5✗ | 24.9✗ | 11.9✗ | 6.7✗ | Sí (4/4) |
| 3 | 10.4✗ | 20.2✗ | 11.1✗ | 8.6✗ | Sí (4/4) |

**Resultado: NO converge en 3/3 iteraciones.**

### Diagnóstico de no-convergencia

**Causa identificada: variación genuina de nivel entre clips TTS distintos.**

- El punto de medición `pre_start = j_time - sil_in_seg - 0.15` es **matemáticamente constante** entre iteraciones: cuando `j_time` y `edl[j][1]` decrementan en la misma cantidad (−0.08s/iter), `j_time − sil_in_seg` no cambia. La medición pre es siempre la misma.
- `pre ≈ −21dB` (cola del clip anterior) vs `post ≈ −11dB` (inicio del clip siguiente): **10dB de diferencia real de nivel TTS**. El ajuste de −80ms no puede corregir diferencias de nivel entre clips.
- El feedback loop de la versión anterior (sil_restante creciente) está **eliminado**: sil_in_seg decrece correctamente (0.250→0.170→0.090).

**Implicación**: convergencia < 6dB requiere que los clips TTS tengan niveles similares. Para grabaciones humanas de una sola sesión, el umbral de 6dB debería funcionar. Para TTS multi-clip, el umbral necesita ajuste.

**Los videos de salida son funcionalmente correctos** — fronteras visualmente limpias, audio con crossfade aplicado.

## Pendiente de decisión del arquitecto

El umbral de 6dB es demasiado estricto para variación de nivel TTS cross-clip:
- Con umbral 12dB: unión @69.2s convergería (delta=6.7dB)
- Con umbral 15dB: 3/4 uniones convergirían (solo @35.8s=18-25dB no)
- El parámetro está hardcodeado como `6` en `_eval_and_adjust`; ver PREGUNTAS.md #8 (DELTA_THRESHOLD como constante nombrada)

## Evidencia visual

| Frame | Descripción |
|-------|-------------|
| `v1_pre_t16p59.png` | Antes de unión 1 — frontera limpia |
| `v1_post_t16p59.png` | Después de unión 1 — sin artefactos |
| `v1_pre_t35p44.png` | Antes de unión 2 |
| `v1_post_t35p44.png` | Después de unión 2 |
| `v1_pre_t53p47.png` | Antes de unión 3 |
| `v1_post_t53p47.png` | Después de unión 3 |
| `v1_pre_t68p52.png` | Antes de unión 4 |
| `v1_post_t68p52.png` | Después de unión 4 |
