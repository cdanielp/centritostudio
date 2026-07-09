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

### 12. F4 Clipper v2 — Zona muerta de duracion 40-55s — **RESUELTO (sesion 9)**

~~18 de 31 candidatos de segmentacion fueron descartados por duracion en la calibracion.~~
~~6 de esos 18 caen en la zona 40-55s...~~

**Voto del arquitecto: opcion A — ampliar largo.min a 45s.**
Registrado en DECISIONES.md §F4.1. No implementar hasta sesion v2 del clipper.

### 13. F4 Clipper v2 — Razones de exclusion precisas (mejora UX) — **RESUELTO (sesion 9)**

~~`seleccionar_clips()` hoy aplica el check `len(elegidos) >= MAX_CLIPS` ANTES del check...~~

**Voto del arquitecto: SI al campo razon_real** con valores: `cupo_lleno`, `score_bajo`,
`cupo_y_bajo`, `solape`, `separacion`.
Registrado en DECISIONES.md §F4.1. No implementar hasta sesion v2 del clipper.

---

## PREGUNTAS F4.1 — Reframe Vertical (para votar ANTES de implementar)

### 14. Punch-ins: ¿opt-in (--punch-in flag) o activados por default?

El diseño actual los pone como **opt-in** (desactivados por default).

**Razón para opt-in:** un punch-in mal calibrado (keywords muy juntas, zoom brusco) arruina el
reencuadre. El usuario puede probar el reframe limpio primero y activar punch-ins cuando quiera.
El flag `--punch-in` es visible y controlable.

**Alternativa:** activarlos siempre (simplifica la CLI).

- **Pregunta binaria:** ¿opt-in con `--punch-in` (propuesta) o siempre activos?

### 15. Resolución de salida: ¿siempre 1080×1920 o respetar la resolución del clip fuente?

Los clips de F4 pueden venir de fuentes 1280×720 (si la grabación de clase era 720p) o
1920×1080 (full HD). El diseño actual **siempre produce 1080×1920** (upscale si la fuente
es 720p; FFmpeg lanczos, calidad aceptable).

**Alternativa:** preservar resolución fuente → output 720×1280 para fuentes 720p.

- **Pregunta binaria:** ¿siempre 1080×1920 (propuesta) o respetar resolución fuente?

### 16. CLI del reframe: ¿módulo independiente o subcomando de caption.py?

El diseño actual expone el reframe como **módulo independiente**:
`python reframe.py output/clips/clip.mp4 [--punch-in]`

Esto respeta la regla #10 (caption.py no puede romperse) y mantiene caption.py < 400 líneas.
El Studio llama a reframe.py internamente vía subprocess.

**Alternativa:** añadir `--reframe` a caption.py (un solo punto de entrada para todo).

- **Pregunta binaria:** ¿módulo independiente `reframe.py` (propuesta) o `--reframe` en `caption.py`?

### 17. ¿El Studio muestra preview de frames ANTES del render completo?

**Propuesta:** sí — botón "Preview (3 frames)" que extrae 3 frames representativos del clip
ya reencuadrado (~1-2s) para que el usuario vea la posición del encuadre antes de esperar
el render completo (20-40s). Si el preview se ve mal, puede ajustar los turnos y re-probar.

**Alternativa:** render directo sin preview (más simple, menos iteración visual).

- **Pregunta binaria:** ¿preview de frames antes del render (propuesta) o render directo?

### 14-17: RESUELTOS — ver DECISIONES.md §F4.1 Votos del arquitecto (sesion 10)

### 18. mediapipe 0.10.14 no disponible en pip — version real 0.10.35

La version 0.10.35 elimino `mp.solutions.face_detection` (API Solutions legacy).
Se usa la nueva Tasks API con modelo TFLite descargado a `models/blaze_face_short_range.tflite`.
La API Tasks es la recomendada por Google para todas las versiones 0.10.x+.
**Accion:** requirements.txt y DISENO_REFRAME.md actualizados con la version real.
Estado: resuelto en sesion 10.

### 19. Preview de frames para reframe — mejora futura

Voto #17 fue render directo. Si los renders de 20-40s empiezan a ser un friccion frecuente
(usuario descubre encuadre incorrecto DESPUES de esperar), considerar en v2:
- Boton "Preview 3 frames" que extrae frames 10%/50%/90% del clip con el crop aplicado (~2s)
- Solo activar si el feedback real del uso indica que 20-40s es doloroso

---

### 8. Umbrales de diagnostico _eval_joins — RESUELTO
- **Decision del arquitecto:** el loop de ajuste fue eliminado. La medicion voz-a-voz queda
  como diagnostico puro: DELTA_CLEAN_DB = 6, DELTA_NOTABLE_DB = 15.
- **Estado:** implementado. "Threshold irrelevante — el ajuste se elimino; la medicion quedo
  como diagnostico con umbrales 6/15dB." Ver depurador.py.
