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

---

## PREGUNTAS F4.1 — Cierre (sesion 16)

### 20. Veredicto de densidad de punch-in — NO VOTABLE HOY (por diseño)

La feature de punch-ins (9 zooms/31s en el clip de prueba, opt-in default off) queda
congelada hasta que K valide los renders de F5 con captions+emojis activos — contexto real
de juicio. En ese momento el arquitecto decide si la densidad de punch-ins (frecuencia,
intensidad PUNCH_ZOOM=1.12) es la correcta o hay que calibrar.

**Voto del arquitecto (sesion 17):** NO VOTABLE HOY por diseño. El voto se toma con
renders de F5 completos. Sigue pendiente.

Pregunta binaria cuando llegue el momento: densidad actual OK / necesita reduccion.

### 21. Descuadre en reposo — CAUSA RAIZ CORREGIDA (sesion 18)

**Voto del arquitecto (sesion 17):** ESPERAR. Trigger: cuando moleste en renders reales.

**Causa raiz real (sesion 18, forense de planos):**
El HOLD en t=54-60s NO es principalmente por "cara debil con 34.4% deteccion".
Es por el CORTE DE ESCENA en t=51.38s que introduce un plano donde la persona
esta a cx≈870-1010, FUERA del gate de ancla_0 (ancla=1362, zone=[1074,1650]).
El gate rechaza todas las detecciones post-corte => 0 detecciones validas =>
HOLD desde t=51.38+2.62=54s. El creep hacia la cara no funciona durante un HOLD
porque no hay cara detectada en la nueva posicion.

**Detalle tecnico:** el diagnostico original atribuia el HOLD a la cara debil.
Es incorrecto. La fuente `podcast_test_60s.mp4` tiene 7 cortes de escena duros
(scores 0.877-1.000). El sistema de anclas fijas asume toma continua y no puede
adaptarse a planos donde la misma persona esta en posicion diferente.

**Orden de fix correcto (sesion 18):**
1. PRIMERO: cortes de escena → re-scan de anclas por plano (va a F4.2 completo).
   Esto es lo que realmente genera los holds largos en material editado.
2. SEGUNDO: full-range (#22) como mejora de deteccion, no como fix principal.
3. TERCERO: creep lento SOLO si el descuadre persiste CON detecciones frescas.
4. CUARTO: stack (F4.2-LITE) cubre el caso podcast estatico de raiz.

**Candidatos de fix (no implementar sin decision):**
- (a) Deteccion de cortes + re-scan de anclas por plano — FIX REAL para material editado.
  Va a F4.2 completo (junto a la linea de tiempo de layouts ya contemplada).
- (b) Creep lento HACIA LA CARA dentro de la deadzone (alpha~0.005). Solo util con
  detecciones frescas. NUNCA hacia source_center (era el bug viejo de manejar_cara_perdida).
- (c) Reducir dz_half: DEADZONE_PCT 0.25->0.18, umbral_lento ~55px. Mas temblor.
- (d) Stack (F4.2-LITE): sin tracking, faces siempre centradas. Requiere fuente estatica.

**Warning automatico implementado (sesion 18):** `reframe.py` detecta cortes y emite
WARNING si > N_CORTES_WARN=2. No bloquea, informa al usuario.

### 22. Evaluar detector full-range para cara debil — DEUDA (actualizado s21)

**Dato nuevo de K (s21):** K identifico visualmente los lentes oscuros del hablante izquierdo
como posible causa de la deteccion debil — sin conocer las confianzas del detector.
Correlacion confirmada:
- cara_1 conf=0.345 (s19) / 0.3632 (s20): DEBIL
- Causa probable: lentes oscuros + 480p + angulo — los lentes eliminan los ojos, que son
  la feature mas discriminante de MediaPipe blaze_face.

**Datos acumulados:**
- short_range en podcast 1920x1080: cara_1 conf=0.43, det=34.4%
- short_range en extracto 854x480: cara_1 conf=0.3632, det=38.6% (480p empeorar la conf)
- full_range (comparativa s14): cara_1 conf=0.73, det=41.2% (mejora significativa)

**Analisis:** full_range detecta features mas robustas a variaciones de illuminacion/
oclusiones parciales. Probablemente mas robusto a lentes oscuros. El .tflite ya esta en
`models/blaze_face_full_range.tflite`. Data en `revision/fase-4.1/model_selection.md`.

El rechazo de full_range en s14 fue correcto (no meter segunda variable durante el retune
del alpha). Ahora el alpha esta estabilizado y full_range puede evaluarse con confianza.

**Trigger:** si el ojo detecta encuadre pobre de la cara debil en renders reales. El dato
de los lentes oscuros sube la prioridad — es un caso recurrente en contenido real de K.
Conecta con la deuda de descuadre (#21).

### 23. Riesgos del revisor de s15 — triage (sesion 16)

El subagente revisor de la sesion 15 reporto 4 riesgos no bloqueantes:

1. **EMA_ALPHA como alias publico** — `EMA_ALPHA=0.08` sigue exportado en reframe_track.py
   aunque ya no lo usa el codigo de produccion. Un script externo podria usarlo como
   argumento de `ema_smooth()` y obtener el alpha base sin correccion por fps.
   **Triage:** IGNORAR (patron de uso incorrecto desde antes; la constante existe como
   alias de ALPHA_BASE_LENTO para backward-compat explicito).

2. **`import csv` dentro del cuerpo de `_exportar_trayectoria_csv`** (reframe.py:259) —
   inconsistente con imports al inicio del modulo.
   **Triage:** DEUDA BAJA — no afecta runtime ni tests. Mover al tope en F4.2 si se toca
   el archivo.

3. **`tau = (1/alpha)/fps` como aproximacion** en `test_alpha_adaptativo_tau_fps` — la
   formula exacta es `tau = -1/(fps*ln(1-alpha))`. Con la tolerancia del 10% el test pasa
   para todos los valores actuales.
   **Triage:** IGNORAR — la aproximacion es suficiente para el rango de alpha del proyecto
   (0.04-0.28). Si se sube ALPHA_BASE_RAPIDO a >0.5 en el futuro, revisar.

4. **Log `[reframe] modelo: blaze_face_short_range.tflite`** condicionado a `tray_dir != None`
   en lugar de a un flag --verbose.
   **Triage:** IGNORAR — comportamiento deseado: el log es de diagnostico y solo aparece
   cuando se pide el CSV de trayectoria.

### 24. F4.2-LITE — IMPLEMENTADO EN SESION 17, VALIDACION PENDIENTE

**Voto del arquitecto (sesion 17):** F4.2-LITE AHORA, F5 despues.
**Estado:** implementado. Pendiente validacion visual de K sobre fuente de toma fija.

**SPEC COMPLETADA:**
- calcular_bandas_stack, renderizar_stack, reframe_stack_clip, --layout stack
- Studio: selector Seguimiento|Stack en static/index.html:251-254
- Criterio de cierre original: render sobre toma fija N=2 + ffprobe + ojo K

**Aprendizaje de la fuente editada (sesion 18-19):**
- Precondicion de dominio: fuente DEBE ser toma continua (un solo plano) N hablantes
- N_CORTES_WARN=2 implementado como check automatico (fail-open)
- Fuente valida para validar: K aporta toma fija con 2 personas

### 24d. Intrusion cruzada en stack — RESERVA ACTIVA (voto arquitecto s22)

K verifico el stack sobre `stack_test_estatico.mp4` y califico 9/10. La intrusion cruzada
en bordes de banda (sep=309px < crop_w=540px) esta PRESENTE y K la acepta — "no molesta".

**Voto del arquitecto (s22): NO cerrar como permanentemente aceptada.**
La geometria cambia con N=3 o separaciones mayores. Mantener como reserva activa.

**Fix en reserva:** parametro `ALTURA_CROP_PCT` que reduce el crop_h desde src_h hasta un
porcentaje (ej. 0.90 * src_h) y centra verticalmente. Permite aumentar crop_w sin intrusion.
Alternativa: dejar el crop de ancho completo (crop_w = band_w * src_h / band_h) como ahora,
pero reducir la zona visible con un centrado vertical ajustado.

**Trigger:** si la intrusion molesta visualmente con N=3 o sujetos mas separados. No implementar aun.

---

**DEUDA F4.2 COMPLETO — Spec adicional del arquitecto (sesion 19):**

### 24a. C1v2 — metrica mejorada para F4.2 completo

**Propuesta del arquitecto:** C1v2 = C1 medido SOLO sobre frames con deteccion viva
(conf_asignada presente en el CSV, no en hold/interpolacion).

**Racional:** C1 actual incluye holds; en fuentes editadas, holds con track fantasma
aprueban como "cerca" aunque la cara real este lejos. Dentro de dominio los holds son
cortos y C1 ~= realidad; fuera de dominio C1 es optimista. C1v2 discrimina ambos casos.

**Implementacion:** la columna conf_asignada del CSV ya permite calcularla sin cambio de
codigo. C1v2 = % de filas CON conf_asignada donde distancia <= 80px. Agregar a la
funcion de analisis del CSV. No es criterio de aceptacion de F4.2-lite pero si de F4.2
completo.

### 24b. Seleccion manual de caras (pedido de K, prioridad justo despues de F5)

**Spec del arquitecto (no implementar en esta sesion):**

Antes del render, el Studio muestra los thumbnails de las caras detectadas. K puede:
- Excluir una cara (no entra al tracking ni al stack)
- Anadir una manualmente (click sobre el frame del video en el Studio)
- Arrastrar el ancla de cada cara para corregir su posicion de referencia

Tracking y stack consumen las anclas CONFIRMADAS, no las autodetectadas crudas.
El flujo automatico (anclas de detectar_caras_video sin editar) sigue siendo el default
de un click — la seleccion manual es opt-in cuando el auto falla.

**Motivacion:** el stack con fuentes de baja separacion de anclas produce intrusion cruzada
(caso prueba2personasenmedio: sep=293px < crop_w=540px). La seleccion manual permite al
usuario excluir la intrusion o ajustar las anclas antes del render.

**Bloqueos a resolver antes de implementar:**
- Define la API de seleccion (POST /api/clips/{stem}/anclas con body de anclas editadas)
- Thumbs de cara ya existen en thumbs/{stem}_cara{id}.jpg — reutilizables
- Click sobre frame necesita canvas o video+overlay en el Studio

**Prioridad:** justo despues de F5 (emojis). F4.2 completo incluye seleccion manual.

### 24c. Precondicion de fuente — check ampliado [REVOCADO PARCIALMENTE]

**REVOCADO (arquitecto s20):** la propuesta de usar threshold=0.5 para filtrar
por score queda REVOCADA. Cortes reales en mismo set puntuan 0.65 (ver fuente 2
en cortes_dataset.md); un threshold=0.5 habria filtrado cortes REALES.

**VIGENTE (implementado en s20):** filtro temporal t<1.0s — el artefacto del
primer frame de scdet siempre ocurre en t~0s con score=1.0; se filtra como
artefacto conocido. Ver `_filtrar_artefactos_cortes` en reframe.py.

Dataset de calibracion: `revision/fase-4.2-lite/cortes_dataset.md` — 3 fuentes,
9 cortes etiquetados. Cualquier nuevo umbral se valida contra este dataset.

---

### 8. Umbrales de diagnostico _eval_joins — RESUELTO
- **Decision del arquitecto:** el loop de ajuste fue eliminado. La medicion voz-a-voz queda
  como diagnostico puro: DELTA_CLEAN_DB = 6, DELTA_NOTABLE_DB = 15.
- **Estado:** implementado. "Threshold irrelevante — el ajuste se elimino; la medicion quedo
  como diagnostico con umbrales 6/15dB." Ver depurador.py.

---

### 22. Detector full-range (cara con lentes oscuros) — ESPERAR (voto arquitecto s22)

El .tflite de full-range esta descargado en `models/`. No activar aun.
**Trigger:** cuando duela en renders reales de K (contenido 1080p talking-head sin lentes).
El caso debil (lentes oscuros) es secundario en el flujo de produccion actual.
Estado: PENDIENTE — sin trigger activo.

### 24b. Seleccion manual de caras — prioridad JUSTO DESPUES DE F5 (voto arquitecto s22)

No posponer a F4.2 completo. Prioridad: terminar F5 emojis → implementar seleccion manual.
Spec en PREGUNTAS #24b (sesion 19). Ver MAESTRO F4.1 spec de seleccion manual.

### 25. Poll de job sin respuesta cuelga el spinner en silencio — deuda UX (s22)

**Síntoma:** si un job del Studio desaparece del registro (reinicio del server, crash del worker)
el `pollJob` hace fetch silencioso indefinidamente → spinner eterno sin mensaje de error.
Viola regla #16 (NINGUN ERROR SIN ACCION).

**Fix propuesto:** añadir timeout al poll (ej. 5 min) → si se supera, mostrar mensaje de error
con botón "Reintentar" o "Cancelar" y marcar el job como stale.
**Prioridad:** follow-up de s22, próxima sesión de Studio.

### Nota de higiene s20/s21
Extracto `stack_test_estatico.mp4` tiene audio 52.5s vs video 48.5s (cola por -c copy).
Benigno en test. Regla nueva de higiene para extractos de validacion:
generarlos con `-shortest` o re-encode completo para que la compuerta "AAC identico"
no pase con asteriscos silenciosos. Aplicar en proxima sesion de extractos.
