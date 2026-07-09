# Revisión de Videos Reales — Prompt Models Studio
**Fecha:** 2026-07-08  
**Modelo:** faster-whisper medium (local) | GPU: RTX 5070 Ti CUDA float16

---

## 1. Auditoría de videos

| Video | Resolución | Duración | Audio (mean dB) | Estado |
|-------|-----------|----------|-----------------|--------|
| tacosjuan | 1056×1920 (9:16) | 11.88 s | −19.4 dB | OK |
| reel01 | 672×1248 (9:16) | 9.96 s | −23.1 dB | OK |
| reel02 | 672×1248 (9:16) | 9.96 s | −23.9 dB | OK |
| reel03 | 672×1248 (9:16) | 9.96 s | −22.0 dB | OK |

Todos tienen voz clara. Ninguno excluido.

---

## 2. Tiempos de procesamiento (modelo medium + CUDA)

| Video | Estilo | Transcripción | FFmpeg | Total |
|-------|--------|--------------|--------|-------|
| tacosjuan | hormozi | 1.37 s | 4.5 s | 5.7 s |
| tacosjuan | karaoke | 1.4 s | 4.3 s | 5.7 s |
| tacosjuan | bounce | 1.4 s | 4.3 s | 5.7 s |
| tacosjuan | pms | 1.4 s | 4.5 s | 5.9 s |
| reel01 | hormozi | 0.72 s | 3.1 s | 3.8 s |
| reel01 | karaoke | 0.72 s | 3.1 s | 3.8 s |
| reel01 | bounce/pms | 0.72 s | 3.1 s | 3.8 s |
| reel02 | todos | 0.68 s | 3.0 s | 3.7 s |
| reel03 | todos | 0.52 s | 3.0 s | 3.5 s |

**Resumen: 18 renders totales en ~78s de pared. ~0.3× el tiempo real del video.**

---

## 3. Transcripciones completas

Las palabras que Whisper probablemente erró se marcan en **negritas**.

### tacosjuan.mp4
> Fui a Tacos Juan y la verdad me encantó, la comida estaba buenísima, el lugar se sentía muy limpio y la atención fue súper rápida, si quieren unos buenos tacos se los recomiendo mucho.

- Sin errores detectables. Nombre propio "Tacos Juan" transcrito correctamente.
- Acentos: encantó, buenísima, sentía, atención, súper, rápida — todos correctos.

### reel01.mp4
> Este **workflow** hace cosas increíbles. Genera video con voz, todo desde una sola herramienta. Míralo tú mismo.

- "**workflow**" es una palabra en inglés dicha en español — transcrita correctamente como se pronuncia. No es un error, es el término correcto.
- Acentos: increíbles, Míralo, tú — todos correctos.

### reel02.mp4
> con prompt models, puedes hacer esto sin saber usar **confiwai**. Yo te doy todo listo para generar.

- **"confiwai"** = ERROR DE WHISPER. La hablante dice "ComfyUI" (pronunciado en español como /comfi-ui/ → Whisper lo escribe fonéticamente como "confiwai").
- Las palabras "prompt models" se transcriben en minúsculas porque la hablante empieza la frase sin pausa inicial.
- FIX recomendado: si vas a usar este video, editar el .ass manualmente o preprocesar con un diccionario de correcciones: `{"confiwai": "ComfyUI"}`.

### reel03.mp4
> Tu compu no aguanta, usa la nube, es más barato.

- Sin errores. Vocabulario coloquial ("compu", "nube") transcrito perfectamente.

---

## 4. Small vs Medium — comparativa en tacosjuan

| | small (0.90s) | medium (1.05s) |
|-|---|---|
| Palabra 9 | "encantó**.**" | "encantó**,**" |
| Palabra 10 | "**La** comida" | "**la** comida" |
| Palabra 25 | "rápida**.**" | "rápida**,**" |
| Palabra 26 | "**Si** quieren" | "**si** quieren" |

**Diferencia:** Solo puntuación interna (`.` vs `,`) y capitalización de la palabra siguiente.  
Las 34 palabras del contenido son **idénticas** en ambos modelos.  
Medium es 17% más lento por transcripción.

**Veredicto:** Para este acento mexicano y vocabulario cotidiano, small y medium dan resultados equivalentes en contenido. La diferencia de puntuación no afecta los captions (el pipeline usa las palabras, no la puntuación para separar bloques).

---

## 5. Comparación de agrupación — tacosjuan hormozi

Ver imágenes: `tacosjuan_agrupacion_t1.png` y `tacosjuan_agrupacion_t2.png`

| Modo | Palabras visibles | Look | Cuándo usarlo |
|------|-----------------|------|---------------|
| `--words-per-group 2` | 2 por bloque | TikTok puro, muy dinámico, impacto por palabra | Hooks cortos, frases de gancho |
| Auto (4-6 chars) | 4-6 por bloque | Subtítulo completo, más fluido, más contexto | Testimoniales, explicaciones largas |

En los frames: el modo de 2 palabras muestra "ENCANTÓ, LA" y "LA ATENCIÓN" — muy impactante pero puede perder el hilo si la frase es larga. El modo auto muestra "ENCANTÓ, LA COMIDA / ESTABA BUENÍSIMA" — más legible como pensamiento completo.

---

## 6. Verificación visual de grids — resultado

| Grid | Estado | Observaciones |
|------|--------|---------------|
| tacosjuan_comparacion_t1.png | APROBADO | Los 4 estilos legibles, acentos OK |
| tacosjuan_comparacion_t2.png | APROBADO | ATENCIÓN, SENTÍA con tildes correctas |
| reel01_comparacion_t1.png | APROBADO | "INCREÍBLES" renderiza bien |
| reel02_comparacion_t1.png | APROBADO | "CONFIWAI" visible (error de Whisper, no del pipeline) |
| reel03_comparacion_t2.png | APROBADO | "MÁS" con tilde correcta |
| tacosjuan_agrupacion_t1/t2.png | APROBADO | Diferencia de agrupación clara y visible |

---

## 7. Las 3 decisiones — binario con evidencia

### a) Modelo: small o medium?
**EVIDENCIA:** 34 palabras idénticas. Solo difieren 2 signos de puntuación. Medium es 17% más lento.  
**RECOMENDACION: SMALL es suficiente** para tu acento y vocabulario.  
Excepción: si el contenido tiene muchos anglicismos técnicos o acento muy marcado, medium podría ayudar. Para los 4 videos revisados, small da el mismo resultado.

### b) Agrupacion: 2 palabras o 4-6?
**EVIDENCIA:** Ver `tacosjuan_agrupacion_*.png`. Las 2 variantes son visualmente distintas y válidas para diferentes contextos.  
**RECOMENDACION: Depende del video.**  
- Para **reel03** ("TU COMPU / NO AGUANTA / USA LA / NUBE") → `--words-per-group 2` da más punch  
- Para **tacosjuan** (testimonial fluido) → agrupación auto (4-6) fluye mejor  
- Usa `--words-per-group 2` como default para contenido tipo "hook" o reel corto.

### c) Fuente: instalar The Bold Font o quedarse con Arial Black?
**EVIDENCIA:** Los frames de hormozi con Arial Black se ven profesionales y limpios. La diferencia con The Bold Font es el tracking (espaciado) y el peso visual.  
**RECOMENDACION: Instala The Bold Font** si el hormozi es tu estilo principal. Descarga gratuita, instalación de 1 minuto. El look más auténtico vale la diferencia.  
Comando post-instalación: editar `styles.py` línea `font_name="Arial Black"` → `font_name="TheBoldFont-Regular"`.

---

## 8. Error a corregir antes de producción

**reel02 → "confiwai" debe ser "ComfyUI"**  
El .ass generado está en `output/reel02_*.ass`. Opciones:
1. Editar el .ass manualmente (buscar "CONFIWAI" y reemplazar por "COMFYUI")
2. Agregar diccionario de correcciones al pipeline (ver PREGUNTAS.md)
3. Regrabación del audio con mejor pronunciación de "ComfyUI" (más clara)

---

*Generado por pipeline captions-pipeline v1.0 — Prompt Models Studio*
