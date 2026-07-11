# F5-s2 — comparativa de 3 versiones (s28A) · para el ojo de K

**Clip base (idéntico en las 3):** `output/clips/videolargo_clip1_largo_9x16.mp4`
(reframe crudo sin captions, 1080x1920, 67.8s). Transcript reutilizado (sin re-transcribir).
Contenido: grabación de pantalla (ComfyUI) — caso #27 MODO PANTALLA; sirve para juzgar
legibilidad de captions sobre fondo claro/UI.

## Los 3 entregables (todos en output/)

| Versión | Archivo | Qué mirar |
|---|---|---|
| Hormozi pop **suave** 1.08 | `videolargo_clip1_largo_9x16_hormozi_suave.mp4` | palabra activa crece poco (108%) |
| Hormozi pop **fuerte** 1.15 | `videolargo_clip1_largo_9x16_hormozi_fuerte.mp4` | palabra activa crece más (115%) |
| **Clean** | `videolargo_clip1_largo_9x16_clean.mp4` | sobrio: sin caja, sombra suave, sin pop |

## Frames comparativos (mismo instante, 3 estilos)

Trío en el arranque de palabra (donde el scale-pop está en su pico ~90ms):
- `A_18.76s_*` — palabra activa "CARPETA"
- `B_33.74s_*` — palabra activa "HACIENDO"
- `C_51.06s_*` — palabra activa "IMÁGENES"

## Lectura del agente (K decide)

1. **El pop se ve y la intensidad se distingue:** en el trío A, "CARPETA" es notoriamente
   más grande en *fuerte* que en *suave*. La diferencia 1.08 vs 1.15 es legible en frame fijo
   (y más aún en movimiento).
2. **Clean cumple "sobrio":** minúsculas, contorno mínimo (sin caja), sombra suave, la palabra
   activa solo cambia a dorado — sin salto de escala. Buena opción para material serio.
3. **Legibilidad sobre grabación de pantalla:** hormozi (outline grueso) se lee sobre la UI
   clara; clean (outline mínimo) depende más de la sombra — sobre fondos muy claros pierde algo
   de contraste. Dato para elegir estilo por tipo de fuente.
4. **Sin brain/keywords en esta corrida:** `caption.py` (modo creador simple) no aplica el
   cerebro editorial, así que el color de énfasis lo lleva la palabra ACTIVA, no el keyword.
   En el Modo Automático (auto.py) sí se combinan keyword_color + pop. No es regresión: es el
   camino simple del CLI. Follow-up posible: exponer `--pop` y `clean` también en el Studio web
   (hoy el pop es solo CLI; ver riesgo #1 del revisor s28A).

**El caption estático anterior sigue disponible/reproducible:** basta `--pop off` (o cualquier
estilo con pop_scale 1.0) para volver al comportamiento previo sin scale-pop.
