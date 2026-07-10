# Inventario canónico de fuentes — input/ (s26)

**Propósito:** tabla semilla del modo AUTO (MAESTRO regla #17: producto general).
Cada fila responde: ¿qué es este video, qué ruta le da el sistema HOY, y qué le falta
al sistema para servirlo bien?

**Método:** ffprobe + detector de cortes propio (threshold 0.3, filtro de artefacto t<1s,
`_detectar_cortes_ts`) + scan YuNet en 7 frames repartidos por la duración
(`YuNetDetector.detect_all`, filtro de área dos niveles activo).
Datos crudos: `scan_raw.json`. Frames de verificación: `frames/`.
Excluidos: sintéticos `test_*` y `audio_test.mp3`.

## Tabla canónica

| Video | Res | fps | Dur | Orient. | Cortes | Caras (scan) | RUTA HOY | GAP |
|---|---|---|---|---|---|---|---|---|
| `tacosjuan.mp4` | 1056x1920 | 25 | 12s | vertical | 0 | 1 estable, h=0.09, conf 0.90 | **ya es 9:16 — no requiere reframe** → captions/emojis directo | ninguno |
| `reel01.mp4` | 672x1248 | 25 | 10s | vertical | 0 | **0 detectadas** (hay cara enorme con VFX) | referencia de estilo (insumo F5-s2), no se procesa | dato: filtro de área 2 niveles descarta cara grande+score bajo por VFX; irrelevante aquí, relevante para selfies verticales |
| `reel02.mp4` | 672x1248 | 25 | 10s | vertical | 0 | 2 (1 real + 1 cuadro en pared = FP) | referencia de estilo (insumo F5-s2) | — |
| `reel03.mp4` | 672x1248 | 25 | 10s | vertical | 0 | 1 estable | referencia de estilo (insumo F5-s2) | — |
| `pruebaedicionvideoyo.mov` | 2560x1440 | 30 | 75s | horizontal | 1 | 1-3 por frame, **todas son caras DENTRO de la pantalla** (previews de imágenes generadas, h=0.02-0.14, sin webcam) | **SIN RUTA digna** — tracking-escenas sigue caras del contenido; center-crop deja pantalla ilegible en 9:16 | **#27 MODO PANTALLA** + distinguir caras de contenido vs personas reales |
| `pruebaparaedicion.mov` | 2618x1440 | 30 | 92s | horizontal | 3 | 1 grande y estable (h=0.38-0.50, conf 0.87-0.93) | **tracking-escenas** (F4.2-CORTES, default) | veredicto K pendiente (EMA vs ESCENAS); punch-in sin veredicto (#20) |
| `2c1b8978-…_0.mov` | 854x480 | 30 | 28.6min | horizontal | 44 | erráticas 0-7 (caras en slides/galerías del contenido) | depurador + clipper OK; **reframe SIN RUTA digna** (caras de contenido + 480p) | modo pantalla/clase (#27) + política de baja resolución (upscale 2.25x desde 480p) |
| `videolargo.mov` | 854x480 | 30 | 57min | horizontal | 105 | erráticas 0-13 (caras en slides) | clipper validado (s8, calibración); **reframe SIN RUTA digna** | ídem fila anterior — la clase OBS con slides es el caso #27 por excelencia |
| `pruebapodcast2personas.mp4` | 1920x1080 | 60 | 12.6min | horizontal | 55 | 1 por frame muestreado (multicám editado en close-ups) | **tracking-escenas** por segmento (cada plano es single); stack solo si hay plano abierto 2-caras | **multi v2 (#28):** rutear stack/turnos POR SEGMENTO; identidad de persona entre planos |
| `prueba2personasenmedio.mov` | 854x480 | 30 | 96s | horizontal | 2 | 2-3 por frame (2 reales + FP ocasional) | **stack** (validado s20-21 sobre extracto) | intrusión cruzada (#24d), selección manual de caras (#24b), 480p |
| `podcast_test_60s.mp4` | 1920x1080 | 60 | 60s | horizontal | 7 | 1 por frame (close-ups) | extracto de validación (derivado de pruebapodcast2personas) | — |
| `stack_test_estatico.mp4` | 854x480 | 30 | 52.5s | horizontal | 0 | 2-3 por frame | extracto de validación (plano 1 de prueba2personasenmedio) | audio 52.5s vs video 48.5s (higiene s21, benigno) |

## Confirmación reel01-03 (insumo F5-s2)

Frames en `frames/reel01_check.png`, `reel02_check.png`, `reel03_check.png`:
los tres son reels verticales talking-head de referencia de estilo —
reel01 mujer con VFX naranjas tipo IA, reel02 hombre a cámara en interior,
reel03 mujer en cocina con laptop. **Confirmado: son referencias de estilo, no material
a procesar.** Falta que K confirme si son SUS referencias (ver revision/para-K/).

## Lecturas transversales (semilla del modo AUTO)

1. **El material real es editado por norma:** 6 de 8 fuentes reales tienen >2 cortes.
   La precondición "toma continua" ya no existe como supuesto (F4.2-CORTES la absorbió).
2. **Caras ≠ personas.** En 4 fuentes (pantalla, 2 clases 480p, reel02) YuNet detecta
   caras que NO son el sujeto: imágenes generadas en pantalla, slides, cuadros.
   El modo AUTO necesita una señal de "cara de contenido" (posición estable no-natural,
   tamaño chico, aparición ligada a cambios de pantalla) antes de rutear a tracking.
3. **Tres clases de fuente emergen:**
   - a cámara (tacosjuan, pruebaparaedicion, podcast) → reframe actual sirve;
   - pantalla/clase (pruebaedicionvideoyo, videolargo, 2c1b8978) → #27 MODO PANTALLA;
   - multi-persona (podcast 2p, 2personasenmedio) → stack hoy, multi v2 (#28) para
     rutear por segmento.
4. **Baja resolución (854x480)** en 3 fuentes: el upscale a 1080x1920 es 2.25x —
   técnicamente funciona (lanczos) pero el modo AUTO debería reportar la pérdida
   esperada de nitidez en vez de callar.

*Generado en s26 con `inventario_scan.py` (reproducible).*
