# F5-s2 parte 2 — pop fuerte con rebote (s28C) · para el ojo de K

**Contexto (D19):** en s28A K descartó pop 1.08/1.15 ("saltan las letras pero nada se ve más
grande que lo demás"). Causa: la palabra volvía a 100% (tamaño de los vecinos) tras el salto.
Fix s28C: la palabra activa REPOSA a `pop_scale` (más grande que los vecinos mientras está
activa) y con REBOTE hace overshoot al pico (~pop×1.12) antes de asentar.

## Los 2 entregables (en output/, con nombres claros)

| Versión | Archivo | Reposo del énfasis |
|---|---|---|
| Hormozi **medio 1.30** + rebote | `output/videolargo_clip1_largo_9x16_hormozi_medio.mp4` | palabra activa a 130% |
| Hormozi **fuerte 1.45** + rebote | `output/videolargo_clip1_largo_9x16_hormozi_fuerte.mp4` | palabra activa a 145% |

Mismo clip base que s28A (`output/clips/videolargo_clip1_largo_9x16.mp4`, grabación de
pantalla ComfyUI, 67.8s). Transcript reutilizado, ~7.6s cada render. Default del autopiloto
= **medio 1.30 con rebote** (D19); K juzga si subir a fuerte.

## IMPORTANTE — esto se juzga EN MOVIMIENTO

El **rebote/overshoot** (la palabra se pasa de tamaño y regresa, sensación premium) SOLO se ve
reproduciendo el video, no en frame fijo. Abre los 2 MP4 y mira cómo entra cada palabra activa.

## Frames (solo confirman el reposo agrandado, NO el rebote)

`{A,B,C}_*_hormozi_{medio,fuerte}.png` — extraídos ~0.30s tras el arranque de palabra (ya
asentado al reposo). Palabras activas: A="CARPETA", B="HACIENDO", C="IMÁGENES".

**Lectura del agente:** en el trío A, "CARPETA" (amarilla) reposa **claramente más grande** que
las blancas vecinas ("RECUERDAS NUESTRA … DE OUTPUT") — el defecto que K señaló está corregido.
En *fuerte* 1.45 la palabra es notablemente más dominante que en *medio* 1.30.

## Riesgo anotado (revisor s28C) a vigilar

Con *fuerte* sobre un **keyword** (que ya parte de 122%), el reposo llega a ~177% y el pico a
~198%: un keyword largo podría rozar el borde en 9:16. En este clip no hubo keyword largo activo
en esos frames (el CLI simple no aplica brain). Si K adopta *fuerte* como default de una marca,
conviene revisar un frame con keyword largo antes.

**Estático reproducible:** `--pop off` vuelve al caption sin animación (byte-idéntico).
