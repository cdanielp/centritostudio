# Fase 3 — Depurador: pruebaedicionvideoyo.mov (final)

## Setup

- Archivo: `input/pruebaedicionvideoyo.mov` (H264+AAC, .mov compatible nativo con FFmpeg)
- Duración original: **75.21s**
- Resolución: 2560×1440 @ 30fps · Volumen medio: -35.4 dBFS (OBS, voz humana)
- Palabras: **142** (Whisper medium-auto, CUDA, 5.8s)
- Modos: **seguro** y **agresivo**
- Naturaleza: grabación cruda de tutorial ComfyUI en OBS, voz real

## Umbral y parámetros

| Parámetro | Valor |
|-----------|-------|
| SILENCE_GAP | **0.8s** |
| SILENCE_COMPRESS | 0.25s |
| MULETILLA_PAUSE | 0.25s |
| DELTA_CLEAN_DB | 6 |
| DELTA_NOTABLE_DB | 15 |

## Silencios detectados

7 gaps > 0.8s (incluye uno de 6.32s — pausa larga entre secciones):

| # | Desde | Hacia | Gap |
|---|-------|-------|-----|
| 1 | "videos," [33] | "ahí" [34] | 2.360s |
| 2 | "ven," [46] | "ahora" [47] | 2.790s |
| 3 | "¿sale?" [63] | "Ese" [64] | 1.190s |
| 4 | "generamos," [70] | "vamos" [71] | **6.320s** |
| 5 | "cuenta" [80] | "dice" [81] | 1.340s |
| 6 | "1280," [84] | "muy" [85] | 1.290s |
| 7 | "hizo," [95] | "este" [96] | 2.200s |

## Candidatos a muletilla evaluados

| Idx | Palabra | Pausa antes | Pausa después | Decisión |
|-----|---------|-------------|---------------|----------|
| [96] | "este" | 2.200s ✓ | 0.000s ✗ | Descartada — sin pausa posterior |
| [140] | "este" | 0.000s ✗ | 0.000s ✗ | Descartada — en flujo continuo |

## Resultados

| Métrica | Seguro | Agresivo |
|---------|--------|----------|
| Cortes | **7** | **7** (0 muletillas) |
| Ahorrado | **15.74s (20.9%)** | **15.74s (20.9%)** |
| Drift | 0.0s | 0.0s |
| Tiempo proceso | **12.4s** | **12.6s** |

EDL: `[(0.0, 15.74), (17.85, 22.10), (24.64, 33.74), (34.68, 36.59), (42.66, 47.09), (48.18, 51.69), (52.73, 55.82), (57.77, 75.21)]`

## Diagnóstico de uniones (voz-a-voz)

| Unión @output | Delta | Clasificación |
|---------------|-------|---------------|
| 15.74s | 11.0 dB | `salto_leve` |
| 19.99s | 1.3 dB | **`limpia`** |
| 29.09s | 8.2 dB | `salto_leve` |
| 31.00s | 30.2 dB | `salto_notable` |
| 35.43s | 10.8 dB | `salto_leve` |
| 38.94s | 0.1 dB | **`limpia`** |
| 42.03s | 30.7 dB | `salto_notable` |

**Interpretación:**
- Las 2 uniones `limpia` (@20s y @39s): secciones grabadas al mismo nivel — transición natural.
- Las 4 `salto_leve` (8-11dB): variación de nivel entre secciones del tutorial — audiblemente suave, crossfade de 30ms lo suaviza.
- Las 2 `salto_notable` (@31s y @42s): secciones con nivel muy diferente (habla apagada vs sección nueva). Considerar normalización de ganancia si se publican en su estado actual.

El arquitecto aprobó el audio de oído — el diagnóstico es informativo, no prescriptivo.

## Evidencia visual

Fronteras sin artefactos — ver frames `v2_pre_t*.png` y `v2_post_t*.png` en esta carpeta.
