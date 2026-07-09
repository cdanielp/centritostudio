# Fase 3 — Depurador: pruebaparaedicion.mov (final)

## Setup

- Archivo: `input/pruebaparaedicion.mov` (H264+AAC, .mov compatible nativo con FFmpeg)
- Duración original: **92.02s**
- Resolución: 2618×1440 @ 30fps · Volumen medio: -14.2 dBFS (TTS)
- Palabras: **242** (Whisper medium-auto, CUDA, 11.8s)
- Modo: **seguro**
- Naturaleza: 4 clips TTS unidos con cortes duros; voz sintética

## Umbral y parámetros

| Parámetro | Valor |
|-----------|-------|
| SILENCE_GAP | **0.8s** — gaps mayores se comprimen |
| SILENCE_COMPRESS | 0.25s |
| XFADE_S | 0.03s (crossfade 30ms) |
| DELTA_CLEAN_DB | 6 — union limpia |
| DELTA_NOTABLE_DB | 15 — salto notable |

## Silencios detectados

Gaps > 0.8s: **4** (todos entre 1.06s y 1.29s — cortes entre clips TTS).
Gaps 0.3–0.8s: **18** → NO cortados. Muletillas: **0**. Falsos arranques: **0**.

| # | Desde | Hacia | Gap |
|---|-------|-------|-----|
| 1 | "hecho." [46] | "En" [47] | 1.060s |
| 2 | "cero." [94] | "En" [95] | 1.290s |
| 3 | "obra." [143] | "En" [144] | 1.200s |
| 4 | "estilo." [192] | "Piensa" [193] | 1.290s |

## Resultados

| Métrica | Valor |
|---------|-------|
| Cortes aplicados | **4** |
| Duración limpia | **~88.2s** (3.84s ahorrado — 4.2%) |
| Drift words.json | **0.0s** (242/242) |
| Tiempo de proceso | **44.7s** (render único, sin loop de ajuste) |

EDL exacto: `[(0.0, 16.75), (17.56, 36.57), (37.61, 55.80), (56.75, 71.96), (73.0, 92.02)]`

## Diagnóstico de uniones (voz-a-voz)

| Unión @output | Delta | Clasificación |
|---------------|-------|---------------|
| 16.75s | 10.3 dB | `salto_leve` |
| 35.76s | 18.3 dB | `salto_notable` |
| 53.95s | 10.0 dB | `salto_leve` |
| 69.16s | 6.7 dB | `salto_leve` |

**Interpretación:** las 4 uniones muestran variación de nivel entre clips TTS distintos
(nivel de entrada de cada clip difiere del nivel de salida del anterior). Esto es
característica del contenido, no un defecto de posición del corte. El arquitecto aprobó
estos videos de oído con deltas de 10-25dB presentes — el diagnóstico confirma la
observación. Considerar normalización de audio (-14 LUFS) para el clip @35.76s si
la discontinuidad de 18dB es audible en producción.

## Evidencia visual

Fronteras sin artefactos — ver frames `v1_pre_t*.png` y `v1_post_t*.png` en esta carpeta.
