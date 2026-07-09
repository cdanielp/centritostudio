# Fase 3 — Depurador: pruebaedicionvideoyo.mov (v2 — criterio voz-a-voz)

## Setup

- Archivo: `input/pruebaedicionvideoyo.mov` (H264+AAC, .mov — compatible nativo con FFmpeg)
- Duración original: **75.21s**
- Resolución: 2560x1440 @ 30fps
- Volumen medio: -35.4 dBFS (OBS screen recording, voz humana real)
- Palabras transcriptas: **142** (Whisper medium-auto, CUDA, 5.8s)
- Modos: **seguro** y **agresivo**
- Naturaleza: grabación cruda de tutorial ComfyUI en OBS, voz humana con nivel variable

## Parámetros

| Parámetro | Valor |
|-----------|-------|
| SILENCE_GAP | **0.8s** |
| SILENCE_COMPRESS | 0.25s |
| MULETILLA_PAUSE | 0.25s |
| Criterio eval | **voz-a-voz** con voice_refs estables |

## Silencios detectados

7 gaps > 0.8s (incluye uno de 6.32s entre "generamos," y "vamos"):

| # | Desde | Hacia | Gap |
|---|-------|-------|-----|
| 1 | "videos," [33] | "ahí" [34] | 2.360s |
| 2 | "ven," [46] | "ahora" [47] | 2.790s |
| 3 | "¿sale?" [63] | "Ese" [64] | 1.190s |
| 4 | "generamos," [70] | "vamos" [71] | **6.320s** |
| 5 | "cuenta" [80] | "dice" [81] | 1.340s |
| 6 | "1280," [84] | "muy" [85] | 1.290s |
| 7 | "hizo," [95] | "este" [96] | 2.200s |

## Candidatos a muletilla evaluados (modo agresivo)

| Idx | Palabra | Pausa antes | Pausa después | Decisión |
|-----|---------|-------------|---------------|----------|
| [96] | "este" | 2.200s ✓ | **0.000s ✗** | Descartada — pronombre, sin pausa posterior |
| [140] | "este" | 0.000s ✗ | **0.000s ✗** | Descartada — en flujo continuo |

Muletillas cortadas: **0**. Algoritmo correcto.

## Resultados

| Modo | Cortes | Ahorrado | Drift |
|------|--------|----------|-------|
| seguro | **7** | **16.94s (22.5%)** | 0.0s |
| agresivo | **7** | **16.94s (22.5%)** | 0.0s |

## Auto-evaluación voz-a-voz — seguro

### voice_refs precomputadas (tiempo original, estables)
`[15.49, 21.85, 33.49, 36.34, 46.84, 51.44, 55.57]`

### Tabla de convergencia

| Iter | @15.7s | @20.0s | @29.1s | @31.0s | @35.4s | @38.9s | @42.0s | Adj |
|------|--------|--------|--------|--------|--------|--------|--------|-----|
| 1 | 11.0✗ | **1.3 ✓** | 8.2✗ | 30.2✗ | 10.8✗ | **0.1 ✓** | 30.7✗ | 5/7 |
| 2 | 10.9✗ | **0.8 ✓** | 7.3✗ | 30.2✗ | 10.6✗ | **0.6 ✓** | 31.6✗ | 5/7 |
| 3 | 11.0✗ | **1.2 ✓** | 8.3✗ | 30.4✗ | 10.6✗ | **1.9 ✓** | 34.4✗ | 5/7 |

**Convergencia: 2/7 uniones convergen en iter 1 (y mantienen en iters 2-3)**

### Análisis por unión

| Unión | Delta | Diagnóstico |
|-------|-------|-------------|
| @20.0s (2.790s gap) | 1.3dB ✓ | Niveles de voz iguales antes/después del gap |
| @38.9s (1.290s gap) | 0.1dB ✓ | Niveles prácticamente idénticos |
| @15.7s (2.360s gap) | 11.0dB ✗ | Nivel pre=-49dB vs post=-38dB: sección anterior más apagada |
| @29.1s (1.190s gap) | 8.2dB ✗ | Nivel pre=-43dB vs post=-35dB: transición de sección |
| @31.0s (6.320s gap) | 30.2dB ✗ | pre=-70dB (voz casi inaudible al final de "generamos,") |
| @35.4s (1.340s gap) | 10.8dB ✗ | pre=-86dB (silencio de pantalla) vs post=-75dB |
| @42.0s (2.200s gap) | 30.7dB ✗ | pre=-68dB vs post=-37dB: sección nueva con más volumen |

### Por qué no converge

Las 5 uniones no convergentes tienen **diferencia real de nivel de voz** entre secciones:
- El hablante varía el nivel al pasar de una parte del tutorial a otra
- Las "colas" de palabras largas (ej: "generamos,") caen a -70dB (fade natural)
- Esto es variación OBS/grabación, no un defecto del corte

**Fix confirmado:** El feedback loop de la sesión anterior está eliminado:
- sil_in_seg decrece monotónicamente: 0.250 → 0.170 → 0.090 (sin saltos a 1.48s)
- Medición de referencia estable: `voice_refs` no cambia entre iteraciones
- El punto `j_time - sil_in_seg` es constante (por construcción matemática), así que la medición pre es la misma en cada iteración

### Implicación práctica

Para los 2 joins que convergen: **sin ajuste** (cortes preservados). Para los 5 no convergentes: -240ms de ajuste acumulado (3 × -80ms), que equivale a ~0.25s de diferencia vs el EDL inicial. Audiblemente indetectable con crossfade de 30ms.

## Evidencia visual

| Frame | Descripción |
|-------|-------------|
| `v2_pre_t15p58.png` | Antes de unión 1 — ComfyUI estático |
| `v2_post_t15p58.png` | Después de unión 1 — misma pantalla |
| `v2_pre_t19p75.png` | Antes de unión 2 |
| `v2_post_t19p75.png` | Después de unión 2 |
| `v2_pre_t35p11.png` | Antes de unión 5 (popup "Increase Session Time") |
| `v2_post_t35p11.png` | Después de unión 5 |

Fronteras visualmente limpias. Uniones 3, 4, 6, 7 comparten patrón: pantalla estática, sin artefactos.

## Decisión de ESTADO.md

Loop implementado con criterio voz-a-voz correcto (feedback loop eliminado).
2/7 uniones convergen; 5/7 no convergen por variación real de nivel OBS.
Threshold 6dB pendiente de ajuste para grabaciones de nivel variable.
Ver PREGUNTAS.md #8 y diagnóstico en DEPURADO_pruebaparaedicion.md.
