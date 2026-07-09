# Preguntas y Decisiones Pendientes

## Para validar con el usuario

### 1. Modelo Whisper: ¿small o medium?
- **Situacion actual:** Se usa `small` en GPU (ya cacheado, 3.8s/video de 15s)
- **Medium:** Mas preciso para acentos y vocabulario tecnico, pero requiere descargar ~1.5GB y el primer arranque falla si Windows no tiene Developer Mode activado (symlink issue con HuggingFace Hub)
- **Pregunta:** ¿Prefiere activar Developer Mode en Windows para permitir symlinks y usar `medium`? O ¿`small` es suficiente para tu caso de uso?
- **Fix si quiere medium:** Activar Developer Mode en Windows Settings → Update & Security → For Developers, o correr Python como admin una sola vez para descargar el modelo

### 2. Posicion vertical del texto
- Actualmente: 10-12% desde abajo del frame (configurable por `margin_pct` en cada estilo)
- ¿Quieres captions mas centrados (50%) o mas abajo (8-10%)?

### 3. Numero de palabras por grupo
- Actualmente: max 18 caracteres/linea, 2 lineas max
- CapCut/Captions.ai tipicamente usa 1-3 palabras a la vez (no 4-6 como ahora)
- ¿Prefiere estilo "una palabra a la vez" o "grupo de palabras" (actual)?

### 4. Fuente del estilo hormozi
- Actualmente usa `Arial Black` (disponible en Windows por defecto)
- El estilo original de Hormozi usa "The Bold Font" (gratuita) o "Montserrat ExtraBold"
- ¿Quieres instalar "The Bold Font" para el look mas autentico?
  - Descarga: https://www.theboldguy.co/ (gratuita para uso personal)
  - Luego editar `styles.py`: `font_name="TheBoldFont-Regular"`

### 5. Referencia Captions AI para benchmark (Regla #13)
El archivo `revision/benchmark/referencia_captions.mp4` no existe todavía. Para activar el
benchmark permanente contra Captions AI:
1. Procesa `input/tacosjuan.mp4` con Captions AI y guarda el output como
   `revision/benchmark/referencia_captions.mp4`
2. Los benchmarks de Fase 2 son comparaciones CON vs SIN énfasis IA (no contra la referencia
   externa, que se activa en cuanto el archivo exista).

### 6. Keywords de calidad baja — ajuste del prompt
DeepSeek marcó "muy" (adverbio) y "fue" (verbo auxiliar) como keywords en tacosjuan.
Posible mejora: añadir al prompt "NUNCA adverbios de intensidad (muy, bastante, super)" y
"NUNCA verbos auxiliares (fue, era, está)". Dejar para Fase 2 v2 si el usuario quiere ajustar.

## Decisiones que tome (asumiendolas razonables)

- Primera corrida lenta (181s) fue por descarga del modelo + warmup de CUDA — las corridas subsiguientes son 4x tiempo real (~3.8s para 15s de video)
- La variable `HF_HUB_DISABLE_SYMLINKS_WARNING=1` debe setearse antes de correr (o agregar al `.env`)
- El modelo medium falla en la descarga por permisos de symlinks en Windows sin Developer Mode — se usa small como fallback estable
- Audio de test generado con `es-MX-JorgeNeural` (voz masculina, Mexico). Whisper lo detecta correctamente como `es`

### 7. app.py→jobs.py — RESUELTO
- app.py: 243 lineas (workers extraidos a jobs.py).
- jobs.py: 185 lineas (new_job, update_job, get_job + 4 workers).
- Deuda saldada antes de F4.

### 9. F4 Clipper — ¿ranking unico o cuota por tipo? (responder ANTES de implementar)
- **Diseño actual (DISENO_CLIPPER.md §5):** ranking unico puro por score — pueden salir
  3 cortos y 0 largos si el score manda. El tipo es informativo.
- **Alternativa:** garantizar al menos 1 clip de cada tipo si ambos superan el umbral 60.
- **Pregunta binaria:** ¿ranking unico puro (propuesta) SI/NO?

### 10. F4 Clipper — ¿caption.py reutiliza el transcript del clip?
- El clipper emite `transcripts/{clip}_words.json` re-basado a t=0 (regla de oro #4).
  El Studio lo aprovecha directo; la CLI `caption.py` hoy SIEMPRE re-transcribe
  (~1-2s por clip en GPU, costo bajo).
- **Propuesta:** en la sesion de implementacion, caption.py prefiere el transcript
  existente si el mtime del .json es posterior al del video. Toca la CLI (regla #10),
  cambio pequeño y con test.
- **Pregunta binaria:** ¿autorizas tocar caption.py para reutilizar transcripts? SI/NO
  (si NO: la CLI re-transcribe clips, cero cambios; el Studio ya los reutiliza igual)

### 11. F4 Clipper — ¿--vertical (center-crop 16:9 a 9:16) entra en la implementacion?
- **DECISIÓN (sesión 7):** pospuesto a F4.1.
- **Nota:** center-crop puro no sirve para clases con screen-share. F4.1 necesitará diseño propio (¿recuadro lateral? ¿zoom semántico?). Face-tracking sigue explícitamente fuera.

### 12. F4 Clipper v2 — Zona muerta de duracion 40-55s (primera mejora candidata)

18 de 31 candidatos de segmentacion fueron descartados por duracion en la calibracion.
6 de esos 18 caen en la zona 40-55s (entre el tope del tipo corto y el minimo del tipo largo).
Estos son tipicamente bloques de procedimiento completos, medianos, que no encajan en ningun tipo.

Opciones para v2 (NO decidir ahora — registrar para cuando el arquitecto quiera iterar):
- **A) Ampliar largo.min a 45s**: cobertura inmediata, invalida la calibracion actual.
- **B) Tipo "medio" (45-60s)**: mas granular, requiere prompt de segmentacion actualizado.
- **C) Dejar como esta**: los 6 candidatos son clase normal; el usuario los puede encadenar a mano.

### 13. F4 Clipper v2 — Razones de exclusion precisas (mejora UX)

`seleccionar_clips()` hoy aplica el check `len(elegidos) >= MAX_CLIPS` ANTES del check
`score < SCORE_MIN`. Resultado: items con score<60 reciben "max_clips" cuando el cupo ya
esta lleno, ocultando que tambien son "bajo el umbral". Ejemplo de la calibracion:
- Candidato score=58 ("Custom Nodes"): cupo lleno + score<60 → etiqueta "max_clips"
- Candidato score=41 ("Workflow listo"): cupo lleno + score<60 → etiqueta "max_clips"

Para v2: agregar campo `razon_real` con valores:
- `cupo_lleno`: score>=60 pero MAX_CLIPS ya estaba lleno (habria sido un clip entregado)
- `score_bajo`: score<60, cupo no lleno (genuinamente bajo el umbral)
- `cupo_y_bajo`: score<60 Y cupo lleno (ambos criterios aplican)
- `solape`: solapamiento con clip de mayor score
- `separacion`: muy cercano a otro clip entregado

### 8. Umbrales de diagnostico _eval_joins — RESUELTO
- **Decision del arquitecto:** el loop de ajuste fue eliminado. La medicion voz-a-voz queda
  como diagnostico puro: DELTA_CLEAN_DB = 6, DELTA_NOTABLE_DB = 15.
- **Estado:** implementado. "Threshold irrelevante — el ajuste se elimino; la medicion quedo
  como diagnostico con umbrales 6/15dB." Ver depurador.py.
