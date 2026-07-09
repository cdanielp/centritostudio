# CALIBRACION_CLIPPER.md — Fase 4: Validación del Clipper Viral

Fecha: 2026-07-09 | Provider: deepseek-chat | SCORE_MIN=60 | MAX_CLIPS=3

---

## 0. Bug encontrado y corregido antes de ejecutar

**Bug**: `clipper.py` verificaba `DEEPSEEK_API_KEY` via `os.getenv()` antes de que
`brain.py` (que carga dotenv al importarse) fuera importado. Resultado: el check siempre
fallaba aunque la clave estuviera en `.env`.

**Fix mínimo** (mismo patrón que `brain.py`):
```python
# Añadido al inicio de clipper.py, tras los imports stdlib
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
```

---

## 1. Smoke Test — `pruebaedicionvideoyo.mov` (1:15 min)

**Video**: 75s, 142 palabras, 10 frases, 1 chunk de segmentación

### Cadena completa verificada

| Etapa | Resultado |
|-------|-----------|
| Transcript _words.json | pre-existente (10:31, usada sin re-transcribir) |
| Frases construidas | 10 |
| Candidatos LLM | 3 |
| Tras dedup | 3 (sin duplicados) |
| Tras filtro duración | 3 |
| Scored | 3/3 |
| Elegidos (≥60) | 1 |
| Descartados score_bajo | 2 |
| Clips .mp4 generados | 1 → `output/clips/pruebaedicionvideoyo_clip1_corto.mp4` |
| Transcripts clip | `transcripts/pruebaedicionvideoyo_clip1_corto_words.json` + `_groups.json` |

### Clip generado

| Campo | Valor |
|-------|-------|
| Archivo | `pruebaedicionvideoyo_clip1_corto.mp4` |
| Tipo | corto |
| Rango | 42.51s – 73.76s |
| Duración | 31.25s |
| Score total | 63 |
| hook | 40 |
| autocontenido | 60 |
| densidad | 80 |
| cierre | 70 |
| score_duracion | 94 |
| Título | "Calidad superior al escalar" |
| Razón | Arranque directo con dato concreto; muestra resolución y compara con Seedance/BO3; cierre sólido. |

### Descartados (score_bajo)

| Score | Tipo | Duración | Razón |
|-------|------|----------|-------|
| 53 | largo | 70.76s | Hook bajo por repetición, densidad alta al mostrar resoluciones (→ "casi", 50-59) |
| 36 | corto | 30.84s | Arranque administrativo sin tensión; referencias a Playgram sin contexto; cierre débil |

### Telemetría smoke test

| Etapa | Llamadas | Tokens | Costo USD | Latencia LLM |
|-------|----------|--------|-----------|--------------|
| Segmentación | 1 | 817 | $0.00034 | 3.19s |
| Scoring | 1 | 1094 | $0.00053 | 3.75s |
| **Total** | **2** | **1911** | **$0.00087** | **6.94s** |
| Wall clock | — | — | — | 13.0s |

**Resultado esperado cumplido**: 0-1 clips para 1:15 de video. Obtenido: 1 clip.

---

## 2. Calibración — `videolargo.mov` (57.1 min)

**Video**: 3427s, 227MB | Transcripción: 7559 palabras, 227.0s, modelo `medium-auto` en CUDA

### 2.1 Etapa A — Segmentación semántica

| Chunk | Frases aprox. | Candidatos LLM | Tokens | Costo | Latencia |
|-------|--------------|----------------|--------|-------|---------|
| 0 | ~150 | 8 | 6529 | $0.00207 | 4.06s |
| 1 | ~100 | 8 | 6268 | $0.00199 | 4.80s |
| 2 | ~110 | 8 | 6464 | $0.00206 | 3.61s |
| 3 | ~112 | 7 | 2980 | $0.00108 | 3.14s |
| **Total** | **472 frases** | **31** | **22241** | **$0.00720** | **15.61s** |

Tras dedup IoU>0.6: **31 candidatos** (sin duplicados — los chunks no generaron solapes significativos).

### 2.2 Reclasificaciones de tipo

El LLM asignó tipo incorrecto para la duración real en 3 casos; el sistema los reclasificó:

| Segmento | Tipo LLM | Duración real | Tipo reclasificado | Razón |
|----------|----------|--------------|-------------------|-------|
| f10-f19 | corto | 79.9s | largo | >40s (tope corto), cabe en 55-100s |
| f167-f170 | largo | 26.9s | corto | <55s (mín largo), cabe en 20-40s |
| f450-f455 | corto | 71.9s | largo | >40s (tope corto), cabe en 55-100s |

### 2.3 Filtro de duración

18 candidatos descartados por duración (fuera de rangos corto 20-40s / largo 55-100s):

| # | Frases | Tipo asignado | Duración | Motivo exacto |
|---|--------|--------------|----------|---------------|
| 1 | f0-f8 | corto | 48.4s | Zona muerta (40-55s) |
| 2 | f34-f42 | corto | 48.6s | Zona muerta |
| 3 | f43-f53 | largo | 52.6s | Zona muerta |
| 4 | f54-f60 | corto | 47.4s | Zona muerta |
| 5 | f61-f70 | largo | 47.4s | Zona muerta |
| 6 | f71-f82 | largo | 110.8s | >100s (tope largo) |
| 7 | f151-f152 | corto | 10.4s | <20s (mín corto) |
| 8 | f153-f154 | corto | 16.5s | <20s |
| 9 | f155-f157 | corto | 17.9s | <20s |
| 10 | f158-f160 | corto | 12.3s | <20s |
| 11 | f161-f161 | corto | 9.5s | <20s |
| 12 | f162-f165 | largo | 41.5s | Zona muerta |
| 13 | f166-f166 | corto | 9.1s | <20s |
| 14 | f309-f324 | largo | 106.9s | >100s |
| 15 | f337-f345 | corto | 44.5s | Zona muerta |
| 16 | f356-f371 | largo | 143.9s | >100s |
| 17 | f438-f445 | largo | 51.6s | Zona muerta |
| 18 | f469-f471 | corto | 19.7s | <20s (20.0 mín, 19.7s fuera por 0.3s) |

**13 candidatos** pasan a scoring.

### 2.4 Etapa B — Scoring

| Batch | Candidatos | Scores válidos | Tokens | Costo | Latencia |
|-------|-----------|---------------|--------|-------|---------|
| 0 | 12 | 12 | 3775 | $0.00185 | 7.70s |
| 1 | 1 | 1 | 795 | $0.00031 | 2.13s |
| **Total** | **13** | **13/13** | **4570** | **$0.00216** | **9.83s** |

### 2.5 Todos los candidatos: subscores + total + tipo + timestamps

Ordenados por score descendente. ✓ = clip entregado | ✗ = descartado.

| # | Título | Tipo | Start | End | Dur | hook | auto | dens | cierre | dur_s | **Total** | Motivo |
|---|--------|------|-------|-----|-----|------|------|------|--------|-------|-----------|--------|
| ✓1 | Recap: archivos, learning rate y pasos | corto | 19:07 | 19:34 | 26.9s | 85 | 90 | 90 | 80 | 85 | **86** | — |
| ✓2 | Nodos rojos resueltos con Manager | corto | 54:47 | 55:17 | 30.4s | 70 | 80 | 75 | 80 | 98 | **78** | — |
| ✓3 | Arrastra imagen para recuperar workflow | largo | 37:38 | 39:08 | 89.4s | 75 | 85 | 80 | 70 | 71 | **77** | — |
| ✗4 | Resuelve nodos rojos con Manager | corto | 50:24 | 50:47 | 23.3s | 80 | 85 | 70 | 75 | 67 | **77** | max_clips |
| ✗5 | Cambia la ropa para mejor lora | largo | 32:03 | 33:07 | 63.8s | 70 | 80 | 85 | 75 | 72 | **76** | max_clips |
| ✗6 | Crea tus propios nodos en ComfyUI | largo | 55:21 | 56:45 | 84.3s | 55 | 70 | 80 | 60 | 81 | **67** | max_clips |
| ✗7 | Genera 48 imágenes con 12 prompts | largo | 03:08 | 04:17 | 68.9s | 60 | 70 | 70 | 50 | 85 | **66** | max_clips |
| ✗8 | Lee el workflow de izquierda a derecha | largo | 40:07 | 41:25 | 77.8s | 65 | 70 | 60 | 50 | 94 | **66** | max_clips |
| ✗9 | Custom Nodes: poderes extra para Confi | largo | 50:49 | 52:10 | 81.6s | 50 | 60 | 65 | 40 | 87 | **58** | max_clips* |
| ✗10 | Reinicia tras instalar custom nodes | largo | 53:32 | 54:44 | 71.9s | 45 | 50 | 55 | 30 | 92 | **51** | max_clips* |
| ✗11 | Elige 25 mejores imágenes | largo | 33:06 | 34:38 | 91.6s | 40 | 50 | 60 | 30 | 67 | **48** | max_clips |
| ✗12 | Última clase: guarda resultados | corto | 35:28 | 35:49 | 20.5s | 50 | 60 | 20 | 40 | 52 | **45** | max_clips |
| ✗13 | Workflow listo, solo pon tu lora | largo | 01:48 | 03:08 | 79.9s | 30 | 40 | 50 | 20 | 90 | **41** | max_clips |

\* Clarificacion de la etiqueta `max_clips`:
`seleccionar_clips()` aplica el check `len(elegidos) >= MAX_CLIPS` ANTES de `score < SCORE_MIN`.
Cuando el cupo ya esta lleno, todos los candidatos restantes reciben `max_clips` SIN importar su score.

Desglose real por motivo semantico:
- Items 4-8 (scores 77→66): **CUPO LLENO** — score >= 60, habrian pasado el umbral, pero MAX_CLIPS=3 ya estaba lleno.
  El 4o candidato que habria sido entregado con MAX_CLIPS=4: "Resuelve nodos rojos con Manager" (score=77, corto, 23.3s).
- Items 9-10 (scores 58, 51): **CUPO LLENO + SCORE BAJO** — score < 60 Y cupo lleno. La etiqueta `max_clips` oculta que ademas estan bajo el umbral.
- Items 11-13 (scores 48-41): **CUPO LLENO + SCORE BAJO** — mismo caso que 9-10.

Para v2: campo `razon_real` con valores `cupo_lleno`, `score_bajo`, `cupo_y_bajo`. Ver PREGUNTAS.md #13.

**Columna auto** = autocontenido. Timestamps en mm:ss desde inicio del video.

### 2.6 Cuáles pasaron SCORE_MIN=60

**8 candidatos con score ≥ 60** (de 13 scored):
- Clip 1 (86), Clip 2 (78), Clip 3 (77), #4 (77), #5 (76), #6 (67), #7 (66), #8 (66)
- Los 3 primeros se entregaron; los 5 restantes cayeron en max_clips.

**2 candidatos en zona "casi" (50-59)**:
- #9 score=58 — "Custom Nodes" — hook bajo (50) y cierre muy débil (40)
- #10 score=51 — "Reinicia tras instalar" — cierre casi nulo (30)
- Ambos recibieron `max_clips` (no `score_bajo`) porque MAX_CLIPS ya estaba lleno.

**3 candidatos bajo 50**:
- #11 (48), #12 (45), #13 (41) — arranque plano, referencias externas, sin tensión en hook.

### 2.7 Distribución de scores (histograma)

```
80-89: █ (1)  — score=86
70-79: ████ (4)  — scores=78, 77, 77, 76
60-69: ███ (3)  — scores=67, 66, 66
50-59: ██ (2)  — scores=58, 51
40-49: ███ (3)  — scores=48, 45, 41

Total: 13 candidatos scored
Media: ~65.2 | Mediana: 66 | Mín: 41 | Máx: 86
```

### 2.8 Clips entregados

| # | Archivo | Tipo | Start | End | Duración | Score | Razón (1 línea) |
|---|---------|------|-------|-----|----------|-------|-----------------|
| 1 | `videolargo_clip1_corto.mp4` | corto | 19:07 | 19:34 | 26.9s | 86 | Datos precisos y autónomos, cierre con número exacto. |
| 2 | `videolargo_clip2_corto.mp4` | corto | 54:47 | 55:17 | 30.4s | 78 | Cierre con resumen claro y método reutilizable. |
| 3 | `videolargo_clip3_largo.mp4` | largo | 37:38 | 39:08 | 89.4s | 77 | Truco útil y autónomo, cierre con recomendación. |

Tamaño de archivos en `output/clips/`:
- `videolargo_clip1_corto.mp4`: 1.2 MB (26.9s)
- `videolargo_clip2_corto.mp4`: 1.6 MB (30.4s)
- `videolargo_clip3_largo.mp4`: 4.6 MB (89.4s)

Transcripts en `transcripts/`:
- `videolargo_clip1_corto_words.json` (4.5 KB, 49 palabras) + `_groups.json` (6.8 KB, 11 grupos)
- `videolargo_clip2_corto_words.json` (6.8 KB, 74 palabras) + `_groups.json` (10.2 KB, 15 grupos)
- `videolargo_clip3_largo_words.json` (19.2 KB, 209 palabras) + `_groups.json` (28.4 KB, 38 grupos)

### 2.9 Telemetría desglosada

| Etapa | Llamadas | Tokens input | Tokens output | Tokens total | Costo USD | Latencia LLM |
|-------|----------|-------------|--------------|-------------|-----------|--------------|
| Transcripción (Whisper) | 1 | — | — | — | $0.00 (local) | 227.0s |
| Segmentación (LLM) | 4 | ~20.8k | ~1.4k | 22241 | $0.00720 | 15.61s |
| Scoring (LLM) | 2 | ~3.5k | ~1.1k | 4570 | $0.00216 | 9.83s |
| **Total LLM** | **6** | — | — | **26811** | **$0.00936** | **25.44s** |
| Wall clock total | — | — | — | — | — | **45.0s** |

Transcripción separada (corrida previa): 227s. Wall del clipper (desde transcript): 45s.

---

## 3. Observaciones para el arquitecto

1. **Zona muerta 40-55s**: 6 de los 18 descartados por duración caen aquí. El LLM tiende a
   proponer segmentos de ~47-53s que no encajan en ningún tipo. Considerar ampliar largo.min
   a 45s o crear un tipo "medio" para esta franja.

2. **Candidatos demasiado cortos**: 6 items < 20s. El LLM sobrefracciona en momentos de
   enumeración o procedimientos paso a paso. FRASE_PAUSA_S=0.7 puede estar cerrando frases
   en cada pausa procedural, generando muchas frases cortas que el LLM agrupa mal.

3. **Candidatos demasiado largos**: 3 items > 100s. El LLM agrupa bloques completos de
   explicación conceptual. CHUNK_WORDS=2500 (activo: 4 chunks) funcionó correctamente —
   no se partió ningún candidato potencial entre chunks.

4. **Score de hook bajo en la mayoría**: 9 de 13 candidatos tienen hook < 70. El contenido
   es clase magistral, no contenido nativo de redes. SCORE_MIN=60 parece calibrado
   correctamente — los 3 clips entregados son genuinamente los mejores del video.

5. **"Casi" vacío**: Los 2 candidatos en 50-59 reciben `max_clips` en lugar de `score_bajo`
   porque MAX_CLIPS=3 se llena antes. La lista `casi` solo se poblará cuando hay menos de
   3 clips válidos (≥60) y algún candidato adicional queda entre 50-59.

6. **Dedup**: 0 duplicados en 57 min de video. IoU_DUP=0.6 funciona bien; los chunks no
   generan candidatos solapados en este contenido.

7. **Costo real por video largo**: $0.0094 para 57 min / 7559 palabras. Muy por debajo
   del threshold de rentabilidad. Proyección para 60 min: ~$0.01 USD total.
