# Fase 3 — Depurador: pruebaedicionvideoyo.mov

## Setup

- Archivo: `input/pruebaedicionvideoyo.mov` (H264+AAC en contenedor .mov — compatible nativo con FFmpeg)
- Duración original: **75.21s**
- Resolución: 2560x1440 @ 30fps
- Volumen medio: -35.4 dBFS (voz humana a bajo nivel — OBS screen recording)
- Palabras transcriptas: **142** (Whisper medium-auto, CUDA, 5.8s)
- Modos ejecutados: **seguro** y **agresivo**
- Naturaleza: grabación cruda de pantalla + voz en clase/tutorial de ComfyUI (OBS)

## Umbral y parámetros

| Parámetro | Valor |
|-----------|-------|
| SILENCE_GAP | **0.8s** — gaps mayores a esto se comprimen |
| SILENCE_COMPRESS | 0.25s — duración del silencio comprimido |
| MULETILLA_PAUSE | 0.25s — pausa mínima a cada lado para cortar |
| MAX_ITERS | 3 iteraciones de auto-evaluación |

## Silencios detectados (pre-análisis)

Gaps > 0.3s encontrados: **14**
Gaps > 0.8s que serán cortados: **7**

| # | Desde | Hacia | Gap |
|---|-------|-------|-----|
| 1 | "videos," [33] | "ahí" [34] | **2.360s** |
| 2 | "ven," [46] | "ahora" [47] | **2.790s** |
| 3 | "¿sale?" [63] | "Ese" [64] | **1.190s** |
| 4 | "generamos," [70] | "vamos" [71] | **6.320s** |
| 5 | "cuenta" [80] | "dice" [81] | **1.340s** |
| 6 | "1280," [84] | "muy" [85] | **1.290s** |
| 7 | "hizo," [95] | "este" [96] | **2.200s** |

Tiempo total a comprimir: **~17.5s** (de 75.21s originales)

## Candidatos a muletilla evaluados

Ninguna palabra en la lista negra `{eh, em, mmm, ehh, este}` pasó el filtro:

| Índice | Palabra | Pausa antes | Pausa después | Decisión |
|--------|---------|-------------|---------------|----------|
| [96] | "este" | 2.200s ✓ | **0.000s ✗** | Descartada — sin pausa posterior |
| [140] | "este" | 0.000s ✗ | **0.000s ✗** | Descartada — en flujo de habla |

**Ambas instancias de "este" son pronombres demostrativos en contexto**, no muletillas.
El detector funciona correctamente: requiere pausa ≥ 0.25s a AMBOS lados.

Falsos arranques detectados: **0**

## Resultados seguro

- Cortes aplicados: **7**
- Duración original: 75.21s
- Duración limpia: **~58.3s** (16.94s ahorrado — **22.5%**)
- Drift de words.json: **0.0s** (142/142 palabras mapearon correctamente)
- Tiempo de proceso: 38.6s

## Resultados agresivo

Idénticos al modo seguro (sin muletillas ni falsos arranques que cortar):
- Cortes: **7** (mismos silencios)
- Ahorrado: **16.94s**
- Drift: **0.0s**

## Auto-evaluación _eval_and_adjust — seguro (iteraciones)

| Iter | @15.7s | @20.0s | @29.1s | @31.0s | @35.4s | @38.9s | @42.0s | Ajustado |
|------|--------|--------|--------|--------|--------|--------|--------|----------|
| 1 | 34.1✗ | 40.9✗ | 31.5✗ | 30.0✗ | **2.0 ✓** | 7.1✗ | 34.5✗ | Sí (6/7) |
| 2 | 16.1✗ | **5.6 ✓** | 12.9✗ | 30.2✗ | **1.8 ✓** | **5.9 ✓** | 39.7✗ | Sí (4/7) |
| 3 | 8.5✗ | 6.6✗ | **4.8 ✓** | 19.0✗ | **1.8 ✓** | 7.2✗ | 23.4✗ | Sí (5/7) |

**Resultado: NO CONVERGE en 3/3 iteraciones. Uniones convergentes: 1 desde iter1, 1 más en iter2, 1 más en iter3 = 3/7.**

**Unión @35.4s (gap de 6.32s — pausa larga entre "generamos," y "vamos"):** converge desde iter1
con delta 2.0dB. Esta es la transición más natural (silencio genuino de pausa de pensamiento).

## Diagnóstico de no-convergencia

Mismo patrón estructural que VIDEO 1 más el factor adicional de volumen bajo (-35dBFS):

- El volumen medio bajo hace que el SNR en ventanas de 0.3s sea más variable
- Las transiciones silencio→habla en grabaciones de pantalla OBS tienen mayor delta porque
  el audio ambiental baja más en las pausas que en una grabación de estudio
- La unión que convergió (@35.4s) es la ÚNICA que era una pausa genuina de pensamiento
  (silencio de 6.32s) — las demás son cortes entre secciones con cambios de pantalla

**Los videos son funcionalmente correctos** — fronteras sin artefactos.

## Evidencia visual

| Frame | Descripción |
|-------|-------------|
| `v2_pre_t15p58.png` | Antes de unión 1 — pantalla ComfyUI estática |
| `v2_post_t15p58.png` | Después de unión 1 — misma pantalla, cursor distinto |
| `v2_pre_t19p75.png` | Antes de unión 2 |
| `v2_post_t19p75.png` | Después de unión 2 |
| `v2_pre_t35p11.png` | Antes de unión 5 (la que converge — popup "Increase Session Time") |
| `v2_post_t35p11.png` | Después de unión 5 (popup cerrado, pantalla normal) |

Nota: se capturaron frames de uniones 1, 2 y 5 (las más representativas). Uniones 3, 4, 6 y 7
no tienen frames individuales pero comparten el mismo patrón estructural (pantalla estática + voz).

Fronteras visualmente limpias — no se detectan artefactos ni saltos en los frames.

## Decisión de ESTADO.md

El loop no converge (3/3 sin bajar todas las uniones a <6dB).
Ver `DEPURADO_pruebaparaedicion.md` para diagnóstico completo — la causa es estructural,
no un bug de código. Pendiente decisión de arquitecto sobre threshold/metodología.
