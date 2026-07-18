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
~~El caso debil (lentes oscuros) es secundario en el flujo de produccion actual.~~
**Racional actualizado s26 — producto general (MAESTRO regla #17):** ninguna fuente es
secundaria por diseño. Lentes oscuros / baja resolucion son casos que el producto debe
detectar y servir con fallback digno. El trigger operativo sigue siendo "cuando duela en
renders reales", pero la justificacion ya no es "no es el flujo de K".
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

---

### 26. F4.2-CORTES — ADELANTADA (re-priorizacion arquitecto s24)

**Razon con datos:** los 3 videos reales probados (podcast_test_60s editado 7 cortes,
prueba2personasenmedio multicam 3 cortes, pruebaparaedicion 2K 3 cortes) tienen cortes
de escena. La precondicion de toma continua no describe el material de produccion de K
(OBS/edicion). La queja de "falla el enfoque" es este mecanismo, no el detector.
**Racional actualizado s26 — producto general (MAESTRO regla #17):** la evidencia de
cortes aplica a CUALQUIER material editado, no solo al flujo de K. F4.2-CORTES no se
justifica por "las clases OBS de K" sino porque el material editado es la norma del
video real; las clases de K fueron el primer dato, no el dominio.
Nota: C1=93% de s23 queda CORREGIDO a "C1 ilegible fuera de dominio" — con cortes,
C1 cuenta frames de hold fantasma entre planos distintos (caveat D6 de DECISIONES.md).

**Orden actualizado:** A/B YuNet (s24) → F4.2-CORTES (sesion inmediata) → F5-s2.

**Diseno de referencia F4.2-CORTES** (credito: proyecto de referencia `referencia/yunet/`,
estudiado en s24 — SOLO LECTURA, reimplementacion propia):

#### 26a. Cortes-primero con frame representativo

1. Detectar cortes de escena: `ffmpeg -vf "select='gt(scene,0.4)',showinfo"` (umbral 0.4
   validado contra video de referencia: cortes reales 0.91-1.00, max no-corte 0.024, ~40x
   separacion — cualquier valor entre 0.05 y 0.85 da el mismo resultado en switching ATEM).
2. Por cada segmento `[start, end)`: extraer frame en `(start+end)/2` (frame representativo).
3. Detectar caras UNA VEZ en ese frame → clasificar segmento: `single`/`split`/`none`/`wide-fallback`.
4. Trackear DENTRO del segmento con muestreo periodico (no EMA continuo).

Fallbacks: `none` → crop centrado fijo sin tracking; `wide-fallback` (3+ caras) → igual.

#### 26b. Waypoints + paneo interpolado (reemplaza EMA adaptativo para cam fija)

Dentro de cada segmento ya clasificado:
- Muestrear posicion horizontal cada 500ms (`single`) / 200ms (`split`).
- Mantener `crop_x_actual` (inicializado en primera deteccion, no en t=0 del segmento).
- Si no se detecta cara: conservar ultimo `crop_x_actual`, no disparar nada.
- Si desplazamiento < deadzone (18% del ancho del recorte de salida): no mover nada.
- Si desplazamiento >= deadzone: crear waypoint y panes 500ms hacia la posicion nueva.
- Con la lista de waypoints, armar expresion FFmpeg de `x` dinamico para el filtro crop
  (interpolacion lineal en cada ventana de transicion, valor fijo fuera de ellas).

~~**Candidato a reemplazar EMA para clases OBS de K**~~ **Candidato a reemplazar EMA para
camara fija** (cuadro clavado en reposo, sin deriva EMA) — aplica a clases OBS y a cualquier
fuente de camara estatica (racional actualizado s26 — producto general). Requiere A/B de
render comparativo sobre clase real antes de decidir.

Constantes a parametrizar: `--deadzone-pct 18`, `--pan-duration-ms 500`,
`--sample-interval-single-ms 500`, `--sample-interval-split-ms 200`.

#### 26c. Identidad por continuidad + debounce (para split)

Mecanismo de una capa gateada por debounce (`last_cx["top"]` / `last_cx["bottom"]` ES
la identidad, no un estado derivado):
- `cost_keep` vs `cost_swap` en cada muestra.
- Si `cost_keep <= cost_swap`: confirmar inmediato, reset contador a 0.
- Si `cost_swap < cost_keep`: incrementar contador; solo al llegar a N muestras
  consecutivas (default 3) se acepta el swap y se actualiza `last_cx`.
- Con 0 caras: no actualizar nada. Con 1 cara: nearest-neighbor sin tocar el contador.
- La salida SIEMPRE es `last_cx` despues del procesamiento — ningun frame intermedio
  puede reflejar una identidad no confirmada.

**Leccion de testing para MAESTRO.md** (nota del arquitecto s24): las aserciones deben
verificar la SALIDA DE CADA MUESTRA INTERMEDIA, no solo el estado final — el bug del
proyecto de referencia (2 frames de identidad erronea que ningun test detectaba) fue
encontrado solo con aserciones frame a frame, no con aserciones de estado final.

#### 26d. Trucos con datos del proyecto de referencia

- **Umbral score 0.75**: validado contra busto y punos en prueba2personasenmedio.mov
  (nuestro video). Busto 0.65-0.69, punos 0.73 → filtrados. Caras reales 0.90-0.92.
  Adoptar como default en F4.2-CORTES.
- **Filtro de area** (`FACE_MAX_AREA_FRAC_DEFAULT = 0.02056`): derivado de 3260
  detecciones en video de referencia real; ninguna cara real (score>=0.9) supero ese
  valor. Manos compactas distintas (misma area que cara, indistinguibles — area no
  es señal unica).
- **Override manual por segmento** (JSON `{start_s, end_s, label, reason}`): version
  minima de nuestra #24b seleccion manual de caras — escape pragmatico por episodio.
  Implementar junto con #24b, no antes.
- **Score 0.75 vs busto nuestro video**: verificado en s24 con YuNet sobre
  prueba2personasenmedio.mov en el A/B (ver reporte s24).

#### 26f. Selector de tracker en Studio — deuda s25

El Studio siempre usa el default (escenas). `--tracker ema` existe solo por CLI.
Regla 15 pide "activable desde el Studio": pasar `tracker` por start_reframe →
run_reframe + selector en la UI. Diff pequeno, proxima sesion de Studio.

#### 26e. Nota de testing obligatoria — REGISTRADA como MAESTRO regla #18 (s26)

Tests de tracking deben tener aserciones en cada muestra intermedia, no solo estado final.
Referencia: el bug de SplitIdentityTracker del proyecto de referencia fue invisible a
aserciones de estado final pero detectable con aserciones frame a frame.
~~Propuesta para MAESTRO.md regla #17 (a registrar al abrir F4.2-CORTES).~~
Registrada en s26 como regla #18 (el slot #17 lo tomó el principio de producto).

---

### 27. MODO PANTALLA — grabaciones de pantalla / tutoriales (GAP #1, s26)

**Dato:** `pruebaedicionvideoyo.mov` (2560x1440, 75s, tutorial de ComfyUI grabado de
pantalla, material real de K — y uno de los tipos de video mas comunes que existen).

**Diagnostico s26 (evidencia en `revision/inventario/`):**
1. **NO hay webcam.** Las 1-3 "caras" que YuNet detecta (conf 0.89-0.94, h=0.02-0.14)
   son caras DENTRO del contenido de pantalla: previews de imagenes generadas en el
   workflow. Posiciones coinciden con los paneles de la UI, no con una burbuja estable.
2. **Reframe modo escenas hoy:** clasifica seg 0 (0-12s) como "multi 2 caras" y seg 1
   (12-75s) como "single" con C1v2=96.7% — es decir, **trackea con exito una cara que
   no es una persona**. El crop 9:16 queda centrado en los previews de imagenes; la UI
   del workflow (nodos, textos) es ILEGIBLE en el output. Frames:
   `frames/pantalla_reframe_t{5,20,40,65}.png`.
3. No cae a none/center-crop: el detector SI encuentra caras (del contenido), asi que
   la ruta single/multi se activa con confianza alta. Es el caso exacto de la regla #17:
   hoy el sistema produce basura CON metricas verdes, sin avisar.

**Opciones de diseno (decision del arquitecto DESPUES, no implementar):**

- **(a) Crop de pantalla + burbuja webcam reposicionada.** Detectar si existe webcam
  real (cara persistente en posicion fija de esquina, distinta del contenido); recortar
  la region de pantalla relevante como banda principal y recolocar la webcam como
  burbuja/banda inferior. Trade-offs: el resultado mas "producto" (equivale a lo que
  hace captions.ai con tutoriales); requiere clasificador cara-real-vs-contenido +
  deteccion de region activa; es la opcion mas cara. Sin webcam (este video) degrada
  a (b) o (c).
- **(b) Zoom a region activa de la pantalla.** Seguir la actividad (cursor, diffs de
  pixeles entre frames) y hacer crop 9:16 con paneos waypoint sobre la zona activa.
  Trade-offs: mantiene legible lo que importa; heuristica de actividad fragil (scroll
  rapido = mareo); reusa la maquinaria de waypoints de F4.2-CORTES.
- **(c) Solo captions, sin reframe.** Detectar "es grabacion de pantalla" y NO reencuadrar:
  entregar 16:9 con captions, o 9:16 pillarbox con la pantalla completa y captions en la
  banda libre. Trade-offs: cero riesgo de basura, siempre digno; no aprovecha el formato
  vertical; es el fallback minimo que la regla #17 exige mientras (a)/(b) no existan.

**Prerequisito transversal a las 3 opciones:** clasificador de fuente "pantalla vs camara"
(senales: caras chicas y ancladas a paneles de UI, bordes rectos y texto denso, cortes
casi nulos con scroll continuo). Es la primera neurona del modo AUTO.

### 28. MULTI V2 — segmentos multi rutean a stack o turnos POR SEGMENTO (s26)

**Estado v1 (D15):** en modo escenas, un segmento clasificado `multi` solo sigue la cara
principal (mayor score del frame representativo). Caras que entran a mitad de segmento no
generan track. Stack y turnos son rutas GLOBALES por video, no por segmento.

**Dato s26:** `pruebapodcast2personas.mp4` (12.6 min multicam editado, 55 cortes): los
planos alternan close-up single (mayoria) y plano abierto con 2 personas (tramo mas largo:
426-462s, 36s). No existe ruta que sirva bien TODO el video: tracking-escenas trata los
planos abiertos como "multi -> cara principal" (ignora al segundo hablante), y stack
global arruina los close-ups (precedente s18: misma persona en ambas bandas).

**Spec propuesta:** el clasificador por segmento de F4.2-CORTES ya distingue single/multi/
none; multi v2 = poder rutear cada segmento a su layout: single->tracking, multi->stack
(o turnos si hay brain/turnos), none->crop centrado. Transiciones = corte seco (precedente
D-turnos). Con la regla #17 (producto general) esto es PRIORIDAD, no detalle: el podcast
multicam es un formato de primera clase.

**Dependencias:** identidad de personas entre planos (la persona A del plano 3 es la del
plano 7) — hoy no existe; seleccion manual #24b puede aportar las anclas confirmadas.

---

### 29. MODO AUTOMATICO — roadmap de la capa (registrado s27, NO implementar aun)

Nota de numeracion: el arquitecto pidio registrar esto "a PREGUNTAS #28", pero #28 ya
esta ocupado por MULTI V2 (s26); queda como #29.

v1 (s27, implementada): objetivo unico "Clips virales" = pipeline probado en s26 RUTA A,
paquete a output/paquetes/ con REPORTE.md de calidad por tramos.

Roadmap futuro (cada item se disena/vota antes de implementarse):
1. **Recetas/presets.json por objetivo:** cada objetivo (clips virales, clase depurada,
   reel con marca...) es una receta declarativa que nombra herramientas del motor y sus
   parametros. Anadir objetivo = anadir receta, no codigo.
   *Nota s30:* los presets del CVE ya son elegibles desde el Studio (/api/presets +
   dropdown, modo Creador). El Modo Automatico CONSERVA su default (hormozi+emojis);
   "preset CVE en el autopiloto" es exactamente este item: la receta nombrara un preset
   por nombre cuando se implemente. No se cablea antes de disenar la receta.
2. **Batch:** carpeta completa por el modo automatico con un solo click/comando.
3. **Score de publicacion v2:** ponderar score IA del clipper con las metricas de calidad
   de tramos (un clip 90/100 con 40% de tramos con aviso no debe salir primero).
4. **Brand kit aplicado:** cuando exista M2/M3 de K (logo, colores, estilo de captions
   de marca) la receta lo aplica automatico.
5. **Headless:** ya existe via CLIs (caption.py/reframe.py); documentar la secuencia
   equivalente al boton como script de una linea.
6. **Agentes/MCP (fase futura):** exponer las herramientas del motor como tools para
   agentes; el modo automatico se vuelve un agente con presupuesto.

**Insight de K (s26, clips 95/100):** "cada usuario podria sugerir o revisar — expectativas
distintas". Consecuencia adoptada en MAESTRO regla #19: el paquete SIEMPRE termina en
revision humana antes de publicar; la aprobacion de F7 (Telegram) es la misma compuerta.

---

### 30. GREMLIN 0-BYTE — **RESUELTO (s30): cazado, reproducido y arreglado**

**Causa raiz (reproducida en vivo, s30):** los hooks de `.claude/settings.json` se
invocaban como `cmd /c hooks\autoformat.bat`. Cuando el harness ejecuta ese string a
traves de la capa POSIX (Git Bash/MSYS), la conversion automatica de argumentos de MSYS
transforma `/c` en `C:\` (lo interpreta como ruta Unix). Resultado: cmd arranca SIN `/c`
= MODO INTERACTIVO, y ejecuta su stdin — el JSON del hook, que lleva el CONTENIDO del
archivo recien escrito — LINEA POR LINEA como comandos. Cada linea con `-> palabra` crea
`palabra` (0 bytes) por redireccion; cmd corta el nombre en la coma (huella que descarto
bash/PowerShell: por eso `list[tuple[int` y no `list[tuple[int,`).

**Verificacion (cada gremlin mapeado a su linea fuente con `-> palabra`):**
- `bool` <- cve_keywords.py:75 `-> bool` | `la` <- cve.py:114 `-> la default del preset`
- `list[tuple[int` <- cve_keywords.py:98 `-> list[tuple[int, int, int, str]]` (corte en coma)
- `hook` <- ESTADO.md:30 `... -> hook post-Write ...` | `completado` <- ESTADO.md:62 `-> completado a 3/3`
- `paquete`/`crop`/`captions`/`el`/`cae`/`dict` <- construcciones `-> palabra` equivalentes
  en bitacoras y codigo de sus sesiones.

**Reproduccion controlada:** `printf 'algo -> tokentrampa, int, str\n' | cmd /c hooks/autoformat.bat`
desde Git Bash -> aparece el banner interactivo de cmd y nace `tokentrampa` (0 bytes).
Descartados con cebo directo (NO reproducen): autoformat.bat y gate.bat con stdin JSON
cebado via `cmd //c`, check.bat, Write en vivo con hook activo, git hooks (LFS estandar
bien citados), settings globales (~/.claude, sin hooks), commands de .claude/, y todo el
subprocess del repo (list-args, cero shell=True).

**FIX APLICADO (.claude/settings.json):** hooks invocados como `hooks/autoformat.bat` y
`hooks/gate.bat` (sin envoltura cmd, forward slashes). Verificado con cebo en los 3
spawners: Git Bash ejecuta el .bat correcto (sin conversion posible), PowerShell tambien;
un spawner cmd puro fallaria fail-open (exit 1, hook no corre) — en ningun caso queda cmd
interactivo leyendo contenido. La bomba de perdida de datos (truncar un archivo real como
`core` o `styles`) queda eliminada. El fix rige desde la PROXIMA sesion (los hooks se
capturan al inicio); en esta sesion se vigila la raiz antes de cada commit.

---

*(registro historico de la deuda:)*

### 30-historial. GREMLIN 0-BYTE — archivos vacios con nombres de palabras del dominio (deuda real, s28A)

**Sintoma:** aparecen en la raiz del repo archivos de 0 bytes cuyos nombres son palabras
sueltas del dominio: `captions`, `crop`, `paquete`, `dict`, `el`, `completado` (lista no
exhaustiva; el conjunto varia entre corridas). En el snapshot de arranque de s28A la raiz
estaba limpia de ellos, pero han reaparecido en sesiones previas.

**Hipotesis (NO investigada hoy, por decision de bloque):** redireccion o escritura con una
variable vacia o mal expandida en algun script/hook/comando. Un patron tipo `> $VAR archivo`
o `comando > palabra` donde `palabra` es un token que iba a ser argumento y termino como
destino de redireccion. Candidatos a auditar cuando se aborde: hooks en `.claude/`, `.bat`
del repo (arranque/check), y cualquier one-liner de PowerShell que use `>` con variables.

**Riesgo (por lo que es deuda REAL, no cosmetica):** si alguna vez el token mal expandido
coincide con el nombre de un archivo REAL del proyecto (p.ej. `core`, `styles`), la
redireccion lo truncaria a 0 bytes silenciosamente. Es una bomba de perdida de datos, no
suciedad de directorio.

**Decision s28A:** NO es cosmetica (no va a .gitignore), NO se investiga hoy. Queda como
deuda con hipotesis y riesgo documentados para una sesion dedicada. Cuando se aborde:
reproducir, localizar la redireccion culpable, y blindar (comillas/validacion de variable).

**REPRODUCIDO EN VIVO (s28A):** durante el BLOQUE 1 aparecio en la raiz un archivo `cae`
de 0 bytes (mtime 17:08, coincide con la extraccion de frames de referencia + escrituras de
archivos). El token `cae` es una palabra del dominio (aparece en textos que se estaban
escribiendo). Refuerza la hipotesis de redireccion/hook disparado por escritura de archivos.
Se elimino manualmente para que no contaminara el commit. Pista para la sesion dedicada:
revisar hooks en `.claude/` que corran en PostToolUse/Stop sobre Write.

**EVIDENCIA FUERTE (s29, 5 reproducciones en una sesion):** aparecieron `el` (18:21),
`desactivar` (18:29), `bool` (18:39), `la` (18:41) y `list[tuple[int` (18:45). Los tres
ultimos NO son palabras del dominio: son FRAGMENTOS DEL CODIGO PYTHON que se estaba
escribiendo con el tool Write en ese momento (`bool` y `la` de docstrings/firmas,
`list[tuple[int` es un pedazo de anotacion de tipo de cve_keywords.py). Conclusion casi
segura: un hook post-escritura procesa el CONTENIDO del archivo escrito a traves de un
shell sin comillas, y tokens con `>` o expansiones crean archivos por redireccion. El
nombre `list[tuple[int` (corchetes crudos) descarta que sea un script Python nuestro y
apunta a un one-liner de shell (PowerShell/cmd) en un hook de `.claude/`. Todos borrados
antes de sus commits. La sesion dedicada deberia empezar listando los hooks activos.

---

### 31. SESION 28B — Direccion de Producto / "dos modos" formal (PENDIENTE, NO cancelada)

La discusion de Direccion de Producto y la formalizacion del modelo "dos modos, un motor"
(hoy vive como MAESTRO regla #19 + D17) se saca de s28A y queda agendada como **SESION 28B**,
en documento aparte. NO esta cancelada: es un bloque de trabajo propio (vision de producto,
posicionamiento vs OpusClip/Captions, roadmap de recetas #29). Registrada aqui para que no
se pierda al haber priorizado s28A en cierre de cabos + F5-s2 captions cineticos.

---

### 33. F6 caption_viral_engine — SPEC DE K NO LLEGO (s29) — **RESUELTO (s30)**

**Hecho:** el prompt de la sesion 29 debia traer el documento integro de K del
caption_viral_engine ("Quiero que F6 no sea un estilo fijo..." hasta "...dopaminergico o
experimental") pero llego el PLACEHOLDER sin reemplazar, seguido del texto de la sesion
s28A antigua. El documento tampoco existe en el repo (verificado con grep).

**Decision de sesion (MAESTRO: decidir, anotar, seguir):** el diseno se construyo sobre
las DECISIONES DEL ARQUITECTO a-h del mismo prompt, que son autosuficientes para v1
(5 presets nombrados, 3 intensidades, deteccion v1, marcado v1, safe zones, config, plan
Sonnet). Los huecos que SOLO el spec de K puede llenar quedaron marcados
`[SPEC-K PENDIENTE]` en revision/fase-6/DISENO_CVE.md:
1. Presets 6-12: quedan como SLOTS con criterio de viabilidad resuelto (via ASS puro /
   via overlays / via compositing) — no se inventaron nombres para no contradecir a K.
2. Posiciones exactas del spec (se mapearan a las constantes de safe zone).
3. Sintaxis completa de marcado manual (v1 = [strong]/[big]/[center] + popups.json).

**RESUELTO (s30):** el documento integro de K llego y esta guardado tal cual en
`revision/fase-6/SPEC_K_CVE.md` (trackeado). Los huecos [SPEC-K PENDIENTE] quedaron
resueltos en DISENO_CVE.md sin reabrir la arquitectura:
1. Presets 6-12 nombrados y clasificados por via tecnica (§9.1): storytelling_cinematic
   y premium_flat y hook_takeover via ASS puro, meme_impact via ASS+video_fx,
   educational_clear y commentary_reactor via ASS+overlays, glitch_cyber via compositing.
2. Posiciones del spec (13 opciones) mapeadas a las constantes de safe zone (§5.1);
   auto_safe ya es el default del engine, behind_text va a S31, full_screen_takeover a backlog.
3. Sintaxis futura de marcado registrada: [shake]/[image:id]/[glitch] (§7 → backlog §9.2).
Refinamientos del spec integrados (refinan sin contradecir): cadena de conflicto ampliada
a 5 pasos con SIMPLIFICAR ANIMACION (§5.3), claves extra de config con destino (§6),
nota de alcance del "nunca sin captions" vs nivel 0 (§8). CERO contradicciones duras con
las decisiones a-h. Una divergencia menor para voto del arquitecto: #34.

**Registro del diseno:** revision/fase-6/DISENO_CVE.md (arquitectura de orquestacion
sobre 3 subsistemas existentes, extension aditiva default-off del motor ASS, merge
manual > brain > reglas, cadena reducir->mover->desactivar, fallback de 5 niveles,
plan de sesiones Sonnet S30-S34).

---

### 34. F6 marcado manual — ¿marcas por FRASE (spans con cierre) o por PALABRA? — **RESUELTO (voto arquitecto, s30)**

**VOTO DEL ARQUITECTO (s30): (a) HOY + (b) EN S32 con regla pre-firmada.**
- v1 sigue por-palabra HOY (no se reabre la decision e).
- En S32 entran los spans de frase con regla PRE-FIRMADA: el span aplica el efecto a
  CADA palabra del span, y las marcas MANUALES quedan EXENTAS de kw_max_por_grupo.
  Jerarquia manual > brain > reglas: lo manual gana; si el usuario marco una frase,
  saturar es su decision.
- **Implementado s30 (consecuencia del voto):** garantia de no-fuga — `[/strong]` y
  cualquier marca invalida JAMAS aparecen como texto visible en el ASS quemado. El engine
  consume las marcas (validas o invalidas) del texto Y de las words en TODOS los presets,
  incluso con keywords off (test de contrato con .ass real:
  test_marcas_invalidas_jamas_visibles_en_ass). Alcance: cubre la ruta CON preset (engine);
  la ruta clasica sin preset se cablea en S32 junto con el editor E2E.

---

*(registro original de la divergencia, s30:)*

**Hecho:** el spec de K (SPEC_K_CVE.md) ejemplifica el minimo v1 con SPANS cerrados sobre
frases: `[strong]esto cambió todo[/strong]`, `[big]10 millones[/big]`,
`[center]la frase principal[/center]`. El parser implementado en s29 (decision e,
subconjunto v1) aplica la marca a UNA palabra (la siguiente inmediata) y no reconoce tags
de cierre — un `[/strong]` se elimina como marca invalida (el texto sale plano; el
contrato "jamas rompe render" SI se cumple).

Ademas, el enfasis de frase/grupo entero fue diferido explicitamente a backlog en el
diseño ("frase destacada", DISENO_CVE §4.2/§9.2: el hook es una FRASE, no una palabra).

**Opciones:**
- (a) v1 se queda por-palabra (`[strong]palabra`); el span por frase entra junto con
  "frase destacada" (backlog) o en S32 (marcado E2E) si el arquitecto lo adelanta.
- (b) S32 implementa spans con cierre: la marca aplica a todas las palabras del span.
  Nota: multiples keywords por grupo rompe la regla kw_max_por_grupo=1 — habria que
  definir la excepcion para marcas manuales.

**Pregunta binaria:** ¿v1 por-palabra (a, propuesta — no reabre decision e) o spans en S32 (b)?

---

### 32. F7 Telegram / distribucion — DIFERIDA post-v1 (D18, s28A)

Decision de roadmap del arquitecto (DECISIONES D18): F7 se DIFIERE fuera del alcance de v1,
NO se cancela. Razon: la distribucion no es motor; en v1 el usuario revisa el paquete y
publica a mano (compuerta de revision humana, regla #19). "Terminado v1" = video entra ->
paquete de clips listos para revisar sale (loop ya funcional, Modo Automatico v1).

Spec de F7 (cuando se retome, post-v1): worker de distribucion a Telegram; la PC solo hace
requests SALIENTES (poll), cero puertos abiertos (MAESTRO F7). Bloqueada por M5 de K
(canal/grupo destino + quien aprueba). Estado: **diferida, post-v1**.

---

### 35. Caption QA (S33) — deudas y decisiones tomadas asumiendolas razonables

**Deuda: Caption QA en el Studio (pendiente, NO era barato).** El CLI ya expone
`--caption-qa/--caption-qa-mode/--guion/--glosario/--caption-qa-llm`, pero jobs.py
llama process-flow propio sin qa_opts. Exponerlo bien en el Studio implica: checkbox +
selector de modo en Render, subida/edicion del guion, y un panel para revisar las
alertas pendientes del sidecar `{stem}_caption_alerts.json` (aprobar/rechazar cada
sugerencia). Ese panel de revision CONECTA con el panel de keywords manuales de D23
(misma UX de aprobar/editar/forzar) — conviene diseniarlos JUNTOS en la sesion del
"panel de revision" para Alpha. Consistente con precedentes CLI-only: --popups (s31),
manual keywords (s32).

**Decisiones tomadas en s33 (no votadas, razonables):**
- (a) El auditor DeepSeek es un flag EXTRA opt-in (`--caption-qa-llm`) y no parte de
  `--caption-qa`: costo LLM jamas se gasta sin pedirlo explicito (regla 15 + patron #8).
- (b) `auto_seguro` corrige EN MEMORIA del render; `transcripts/{stem}_words.json` en
  disco JAMAS se toca -> la edicion manual del Editor siempre gana. Si se quisiera
  persistir la correccion, seria una accion explicita del usuario (futuro Studio).
- (c) Convencion del guion: `transcripts/{stem}_guion.txt` (sidecar junto al transcript,
  mismo patron que `{stem}_keywords.json`), o ruta libre via `--guion`.
- (d) El Modo Automatico corre el QA en modo SOLO-LECTURA (alertas al REPORTE.md, cero
  correcciones): una capa nueva no altera el output de la capa automatica sin veredicto
  de K (regla 15). Cuando K valide auto_seguro, la receta del autopiloto podra activarlo.

**Limitaciones documentadas v1 (siguiente iteracion si duelen):**
- La similitud fuzzy solo corre por token individual contra terminos >= 6 chars;
  errores multi-palabra nuevos se cubren agregando variantes al glosario (editable).
- El contexto del guion usa bigrama PRECEDENTE exacto; parafrasis fuerte del guion
  reduce el recall (el vocabulario fuzzy del guion compensa parcialmente).

**Nota s34 (fix 2 del revisor, aclara el punto (b) de arriba):** la garantia
"la edicion manual del Editor siempre gana" aplica a la CLI y al modo `alertas`.
En el STUDIO con `auto_seguro` el render REAGRUPA desde `{name}_words.json`
corregido (mismo camino que el selector "palabras por grupo") y por tanto
DESCARTA las ediciones guardadas en `{name}_groups.json` para ESE render — es
una eleccion explicita del usuario y el selector lo avisa en su etiqueta
("reagrupa: ignora ediciones del Editor"). Los archivos de disco no se tocan:
las ediciones siguen ahi para el siguiente render sin QA. Conciliar ambos
mundos (aplicar QA SOBRE los groups editados) es parte del panel de revision
de D23 (futuro).

---

### 36. Multi-clip de b-roll de video Pexels — DIFERIDO (V1: un clip por render)

El PR B (D31) integra b-roll de CLIP de video Pexels como cutaway, pero V1 admite como maximo UNA
entrada `source="pexels_video"` activa por render: si `{stem}_popups.json` trae varias, se procesa
la PRIMERA por orden del JSON y las demas se omiten con log ASCII (las entradas PNG y Pexels-imagen
se siguen procesando normal). Razon: acotar el alcance visual del primer PR, verificar bien la
regla #19 (audio) y la costura del loop con un solo clip antes de tejer varios inputs de video en el
mismo filter_complex.

**Pendiente (PR posterior):** soporte de N clips por render (varios inputs `-i` + overlays
encadenados), politica de solape entre clips y con popups de imagen, y quiza `contain` como segundo
modo de encaje (tambien diferido en D31). Nada de esto bloquea V1. Estado: **diferido, post-PR B**.

### 37. Editor de Paquete (S35) — aprobar/rechazar persistente y edicion, DIFERIDOS

El Editor de Paquete de Alpha 0.1 es SOLO-LECTURA (D32). Hoy "Marcar como revisado en esta sesion"
guarda solo en `localStorage` del navegador y no toca el paquete. Quedan diferidos, para una fase de
persistencia posterior: (a) aprobar/rechazar clips de forma persistente (server-side), (b) edicion
manual conjunta de Caption QA / keywords desde el Editor, (c) acciones de re-render desde el Editor.
Ninguno se implementa aun; requieren decidir modelo de persistencia (¿archivo por paquete? ¿estado en
`paquete.json`?) y no romper la regla #19 (revision humana antes de publicar). Estado: **diferido**.

### 38. Editor de Paquete (S35) — extraccion de `s35.css`/`s35.js`, DIFERIDA

`static/index.html` sigue siendo el monolito de la UI. El PR B (cierre visual S35) toco solo unidades
S35 sin refactor general. La extraccion de los bloques S35 a `static/s35.css` / `static/s35.js`
(sugerida en el plan) se difiere: el riesgo de romper otras pestanas (los handlers `onclick` viven en
scope global del `<script>` inline y varias funciones se comparten con Home/Creador/Automatico) supera
el beneficio inmediato, y el monolito no crecio de forma relevante con S35. Estado: **diferido**; si
`index.html` sigue creciendo, retomar extrayendo primero el CSS (menos acoplado) y luego el JS con
cuidado de conservar las funciones publicas usadas por `onclick`.

### 39. Editor de Paquete (S35) — captura pixel-perfect a 390px exacto (headless)

Edge headless en el equipo de dev (Windows a 125%) fija un viewport CSS minimo de ~492px, asi que las
capturas "moviles" se tomaron a ~492px (rango movil, reglas responsive activas) y la ausencia de scroll
horizontal se verifico por medicion (`scrollWidth == innerWidth`). El render pixel-perfect a 390px
exacto no se pudo capturar en este headless. No es un defecto del producto (se valida en vivo con
devtools); es una limitacion de la herramienta de captura. Estado: **nota, no bloqueante**.

### 40. S36 (SRT round-trip) — decisiones que S36-A dejo ABIERTAS (para S36-B/C)

S36-A (D33) entrego solo el contrato/parser/validacion/serializacion del SRT. Lo siguiente sigue sin
decidir y NO se resolvio en este PR (no preguntar lo ya cerrado por D33):

- (a) **Politica de overlaps al render:** mantener cues simultaneos, desplazarlos o rechazarlos. Hoy
  solo se **diagnostican** como warning.
- (b) **Markup del SRT en ASS:** tratar `<i>`/etiquetas como texto literal, permitir un subset, o hacer
  strip seguro. Hoy se conservan como TEXTO, sin interpretar.
- (c) **Alineacion palabra-por-palabra (S36-B):** motor (forced alignment / Whisper) y umbral de
  confianza; el SRT NO trae timing por palabra.
- (d) **Fallback de timing** cuando no hay alineacion fiable: proporcional por caracteres, por palabras
  o a nivel de frase completa.
- (e) **Bloques posteriores a la duracion del video:** hoy se marcan como warning
  (`cue_after_video`/`cue_partially_out_of_video`); falta la politica de que hacer con ellos al render.
- (f) **Rebase de cues despues de cortes** (clipper/depurador): como remapear tiempos tras editar.
- (g) **Nombre definitivo del sidecar** del contrato SRT en produccion (¿`{stem}_srt.json`?): en S36-A
  el JSON solo es contrato/evidencia local; el nombre se decide en S36-B.
- (h) **UI:** si el Studio permitira editar los saltos de linea originales del cue o solo el texto.

### 41. S37 densidad de b-roll (Automatico v2) — **RESUELTA (D34, s37)**

- target **27%**;
- maximo duro **35%** (nunca se supera);
- el target detiene el greedy; puede quedar por debajo si faltan senales validas.

### 42. S37 duracion de b-roll — **RESUELTA (D34, s37)**

- imagen **2.5-4.5s** (preferred 3.5);
- video **3-6s** (preferred 4.5);
- el planner solicita la duracion deseada; la duracion real del asset remoto es de PR B.

### 43. S37 imagen vs video — **RESUELTA (D34, s37)**

- **imagen es el default**;
- **video** solo con senal textual EXPLICITA de movimiento/accion/proceso;
- **maximo un video** por clip en V1; el resto se degrada a imagen (`video_limit_fallback_to_image`).

### 44. S37 hook — **RESUELTA (D34, s37)**

- **3.0 segundos** protegidos desde el inicio del clip ya rebasado;
- el lead-in nunca entra al hook; una senal con `kw_ts` dentro del hook se rechaza.

### 45. S37 FX default del Automatico v2 — **RESUELTA (D34, s37)**

- **express** por default;
- **pro** solo para perfil viral fuerte;
- **premium** explicito (reserva outro de 2.5s). El planner solo INFORMA el preset; el render lo aplica en PR B.

### 46. S37 b-roll default — **RESUELTA (D34, s37)**

- **ON solo en Automatico v2**;
- el toggle vive en PR C;
- el **Auto clasico permanece identico** (sin b-roll automatico, sin cambios de salida).

### 47. S37-B — deudas del resolver — **RESUELTA (D34 addendum, s37 PR B)**

Emergen del contrato del planner y se deciden cuando PR B conecte Pexels/render:

- (a) **Ningun video de Pexels cubre la duracion pedida:** loop del clip corto o fallback a imagen.
- (b) **Precedencia por ventana entre manual y automatico** al fusionar `{stem}_popups.json` (manual)
  con `{stem}_popups.auto.json` (generado).
- (c) **Formato final del merge** manual/auto y su orden de resolucion.
- (d) **Tolerancia A/V** y politica de sincronizacion al componer el b-roll.
- (e) **Politica de desplazamiento de punch-in** si un asset real difiere de la ventana planeada.
- (f) **Cache de assets automaticos** (reuso entre clips/renders).

Ninguna de estas se decidio en PR A: el planner solo produce INTENCION auditable.

**RESOLUCION (S37-B, valores exactos aplicados y testeados):**

- (a) video que no cubre la duracion: **fallback a imagen, NUNCA loop**
  (`video_no_cover_fallback_image`); fallos operativos de busqueda/descarga tambien caen a
  imagen; doble fallo -> ventana omitida con ambos pasos registrados.
- (b) precedencia por ventana: **manual gana por conflicto temporal** ([start, end), tocar
  borde no bloquea); la ventana auto bloqueada se omite ANTES de descargar; un clip manual
  ocupa el slot de video (auto video -> imagen).
- (c) formato del merge: **fuentes separadas + combinacion en memoria**; `_popups.auto.json`
  (solo lo renderizado, formato compatible) + `_broll_resolved.json` (auditoria); el manual
  jamas se toca; sin sidecar hibrido.
- (d) tolerancia A/V: **integridad = payload identico por hash de paquetes**; sync = start
  audio <=0.050s, duracion audio <=0.050s, delta inicial A/V <=0.120s, drift final <=
  max(0.120s, 2/fps_final). Excepciones tipadas, nunca fail-open.
- (e) punch-in vs cutaway: **el FX se ELIMINA, no se desplaza** (D34 addendum, #47e).
- (f) cache: **la existente de los fetchers** (`existing_fetcher_cache`), sin cache paralela.

**Deudas menores diferidas a PR C (no bloquean):** bloquear precedencia por INTENCION
manual (hoy bloquea por elemento manual RESUELTO, documentado); toggle de b-roll y preset
FX en Studio; rerender selectivo desde el Editor.
