# Decisiones de Arquitectura

**Fecha:** 2026-07-08

## Decisión Principal: Pipeline nativo Python (sin Docker)

### Opciones evaluadas
1. **Docker con ai-video-captions** — servidor web Flask + frontend React, pensado para SaaS, requiere Docker Desktop (no instalado)
2. **Pipeline nativo Python** (elegido) — CLI directo, sin servidor, sin overhead

### Razones para elegir CLI nativo
- FFmpeg 8.0 ya instalado y en PATH
- RTX 5070 Ti + driver 610.47: faster-whisper puede usar CUDA directamente sin contenedor
- Sin Docker Desktop: la opción 1 requeriría instalación adicional
- El repo cutcaption confirma que el enfoque CLI es viable y mantenible
- Menos superficie de fallo: un solo proceso Python, no microservicios

---

## Decisiones técnicas de implementación

### Modelo Whisper
- **GPU (RTX 5070 Ti):** `medium` con `compute_type=float16` vía CUDA  
- **CPU fallback:** `small` con `compute_type=int8`
- Justificación: medium en GPU es ~10x más rápido que small en CPU

### Formato de subtítulos
- **ASS (Advanced SubStation Alpha)** en vez de SRT porque:
  - Soporta color por palabra (`\c{color}`)
  - Soporta karaoke con relleno progresivo (`\kf{duration_cs}`)
  - Soporta animaciones de escala (`\t(t1,t2,\fscxN\fscyN)`)
  - FFmpeg lo quema nativo con filtro `ass=...`

### Técnica de highlight word-by-word
- Adaptada de `ai-video-captions/backend/subtitles.py`
- Por cada palabra activa se crea UN evento ASS que muestra todo el grupo pero con tags de color solo en la palabra activa
- El evento dura desde `word[i].start` hasta `word[i+1].start` (o fin del bloque para la última)
- Esto crea el efecto karaoke/captions animados

### Agrupación de palabras
- Máximo 2 líneas por bloque de subtítulo
- ~18-20 caracteres por línea (configurable por estilo)
- Escalado de fuente relativo a altura del video (ref: 1920px altura para 9:16)

### Quemado
- `ffmpeg -vf ass=... -c:v libx264 -crf 18 -c:a copy`
- Audio original intacto (`-c:a copy`)
- Misma resolución que el input

---

## Fase 2 — Cerebro editorial

### SDK OpenAI-compatible para DeepSeek (no httpx directo)

Opciones evaluadas:
1. **`openai` SDK con `base_url="https://api.deepseek.com"`** (elegido)
2. `httpx` directo a la API REST de DeepSeek

Razones para elegir el SDK:
- DeepSeek expone la API OpenAI-compatible exactamente para ser usada así
- El SDK maneja reintentos automáticos, timeouts y `response_format=json_object`
- Compatibilidad inmediata con otros providers (Anthropic, Ollama) si cambia `LLM_PROVIDER`
- `python-dotenv` (dependencia complementaria) carga `.env` sin código adicional

## Fase 4 — Clipper viral (sesión de diseño)

Las decisiones de diseño del clipper (frase como unidad atómica de segmentación,
chunking 2500 palabras con solape 300, scoring de duración y total ponderado
calculados en Python — nunca por el LLM, depurar ANTES del clipper, validación
estricta-en-estructural / laxa-en-cosmético) están documentadas y justificadas en
`revision/fase-4/DISENO_CLIPPER.md`. Sin dependencias nuevas: reusa el SDK openai
vía brain.py y la maquinaria EDL de depurador.py.

### Votos del arquitecto — F4 implementación (sesión 7)

- **#9 Ranking**: único puro por score, sin cuotas por tipo. 3 cortos y 0 largos es resultado válido.
- **#10 Reutilizar transcript**: SÍ. caption.py prefiere `{clip}_words.json` si su mtime >= mtime del video; loguea "reutilizando transcript existente" explícito. Fail-open mudo prohibido.
- **#11 --vertical**: pospuesto a F4.1. Center-crop puro no sirve para clases con screen-share; F4.1 necesitará diseño propio.

### python-dotenv para carga del .env

Se elige `python-dotenv` sobre manejo manual de `.env` porque:
- Es el estándar de facto, mínimo peso
- `load_dotenv()` es no-destructiva (no pisa variables ya seteadas)
- Fall-through con try/except ImportError: si no está instalado, el sistema sigue funcionando
  vía `os.environ` directa (útil en CI/CD donde las vars vienen del entorno del runner)

## Fase 4 — Calibración y cierre (sesión 8, 2026-07-09)

**Aprobacion humana del arquitecto:** clips de calibracion revisados y aprobados — coherentes y utilizables.

### SCORE_MIN y MAX_CLIPS — confirmados

- **SCORE_MIN=60 se queda.** Evidencia: entregados 86/78/77 (calibracion 57 min), 63 (smoke 1:15 min).
  El piso filtra arranques planos y referencias externas sin sacrificar buenos candidatos.
- **MAX_CLIPS=3 se queda.** El 4o candidato elegible habria sido "Resuelve nodos rojos con Manager"
  (score=77, corto 23s) — buen clip, pero 3 es el limite correcto para la experiencia del usuario.

### Zona muerta de duracion 40-55s — no se toca en v1

Cambiar rangos corto/largo invalidaria la calibracion hecha. Queda registrada como primera mejora
de v2 en PREGUNTAS.md. Los 6 candidatos descartados por zona muerta son clase normal de clases
magistrales con secuencias de pasos medianos — no indican falla del sistema.

### Clips SIN captions en F4 — diseno correcto

El clipper entrega MP4 limpio + `{clip}_words.json` re-basado a t=0. El usuario aplica
`caption.py --style X` cuando quiera el estilo. Mas flexible que quemar el estilo en el corte.
La nota del MAESTRO.md "clips con captions" se interpreta como "clips listos para recibir
captions" — el transcript re-basado a t=0 es lo que habilita esto sin re-transcribir.

### Etiqueta max_clips — aclaracion

`seleccionar_clips()` aplica max_clips ANTES del check de SCORE_MIN. Esto hace que items
con score<60 reciban "max_clips" cuando el cupo ya esta lleno. Semanticamente correcto
para el codigo, pero ambiguo para el usuario. Para v2: distinguir cupo_lleno (score>=60)
de cupo_y_bajo (score<60 Y cupo lleno). Ver PREGUNTAS.md.

---

## Fase 4.1 — Reframe Vertical (sesion 9, 2026-07-09)

### Votos del arquitecto para v2 del clipper (PREGUNTAS #12 y #13)

**#12 — Opcion A: ampliar largo.min a 45s**
Los 6 candidatos en zona 40-55s son bloques de procedimiento completos validos.
Ampliar el rango corrige el fallo de cobertura. La calibracion actual queda invalida
al implementarse — requiere re-calibracion con videolargo.mov antes del merge.
No implementar hasta que el arquitecto abra la sesion v2 del clipper.

**#13 — SI al campo razon_real**
Agregar `razon_real` a `seleccionar_clips()` con valores: `cupo_lleno`, `score_bajo`,
`cupo_y_bajo`, `solape`, `separacion`. No implementar hasta la sesion v2 del clipper.

### Decisiones de disenio de F4.1 (delegadas al disenio)

Todas las decisiones tecnicas (estrategia de render, parametros, casos borde, formato
de turnos, estructura de modulos, audio) estan justificadas en:
`revision/fase-4.1/DISENO_REFRAME.md`

Resumen ejecutivo:
- **Render**: OpenCV frame-a-frame + pipe a FFmpeg (no zoompan, no sendcmd)
- **EMA_ALPHA=0.08**, **DEADZONE_PCT=0.30**, **DETECT_EVERY_N=3**, **PUNCH_ZOOM=1.12**
- **Audio**: `-map 1:a -c:a copy` — nunca se re-encodea
- **Punch-ins**: opt-in (--punch-in flag), desactivados por default — pendiente voto #14
- **Multi-cara**: `{clip}_turnos.json` obligatorio; fallo accionable si falta con 2+ caras
- **Sin caras**: center-crop + log (no falla)
- **Nueva dependencia**: `mediapipe==0.10.35` (CPU, sin torch; ver PREGUNTAS #18)

## Fase 4.1 — Votos del arquitecto (sesion 10, 2026-07-09)

### #14 Punch-ins: OPT-IN (propuesta confirmada)
`--punch-in` flag, desactivado por default. En el Studio: checkbox "Punch-ins en keywords".
Se decidira si pasa a default tras validacion visual con material real.

### #15 Output: SIEMPRE 1080x1920
Upscale con `cv2.INTER_LANCZOS4` cuando la fuente sea 720p u otra resolucion menor.
Correccion del diseno: §2 de DISENO_REFRAME.md atribuia el upscale a FFmpeg, pero con
el pipe fijo a `1080x1920 -s` lo hace OpenCV en el resize. Alineado en el doc.

### #16 CLI: reframe.py INDEPENDIENTE
No tocar `caption.py` (regla #10). El encadenado clipper→reframe→captions lo hace el
Studio via jobs.py. `caption.py` no se modifica en ninguna fase de reframe.

### #17 Render DIRECTO sin preview
Sin preview de frames previo al render completo. Anotar en PREGUNTAS como mejora futura
si los renders empiezan a doler (ver PREGUNTAS #19).

## Fase 4.1 — Fix y conmutacion multi-cara (sesion 11, 2026-07-09)

### Bug pix_fmt yuv444p → yuv420p

Los outputs 9:16 de sesion 10 tenian `pix_fmt=yuv444p / profile High 4:4:4 Predictive`
porque el raw BGr24 del pipe se interpreta como 4:4:4 sin que se fije el formato de salida.
Fix: agregar `-pix_fmt yuv420p` a los argumentos de SALIDA en `_cmd_ffmpeg_pipe()`.
Todos los clips 9:16 re-renderizados con el fix. Verificado con ffprobe.

### Conmutacion real multi-cara

Decision del arquitecto: se implementa ya en sesion 11 porque hay material de validacion.
- 2+ caras SIN turnos: WARNING + render con cara principal (ya no es ValueError)
- 2+ caras CON turnos: conmutacion real con CORTE SECO en el frame exacto de t_ini
- El tracking (EMA + deadzone) se aplica INDEPENDIENTEMENTE por segmento; al conmutar,
  la camara arranca centrada en la cara nueva sin paneo desde la posicion anterior.
- `detectar_todas_caras_frame()` agregado a reframe_track.py (devuelve todas las caras).
- `calcular_crops_por_turnos()` agregado a reframe_track.py (puro math, testeable).
- `_detectar_trayectorias_multi()` en reframe.py (con cv2, por cara activa del turno).
- `cargar_o_crear_turnos()` eliminada (codigo muerto detectado por el revisor).
- Validado con input/pruebapodcast2personas.mp4 (60s test clip).

---

## Fase 5 — Assets ComfyUI + Emojis PNG (sesion 23, pre-firmadas)

### D9: Generacion de assets via workflows/asset_base.json

Se usa el workflow existente TAL CUAL (Z-Image Turbo, Lumina2, nodo PROMPT_CENTRITO id="67").
Solo se sustituye el campo `text` del nodo "67" con el prompt del asset.
Justificacion: el workflow ya funciona localmente con los modelos de K; no reinventar.

### D10: Modulo assets_comfy.py — puente ComfyUI con cache por hash

Archivo: `assets_comfy.py`. Cache local en `assets/generados/{sha256[:16]}.png`.
Mismo prompt = mismo hash = cero regeneracion.
Fallback fail-open: si ComfyUI no esta corriendo, se omite la capa y el render sale limpio.
URL configurable via env var `COMFY_URL` (default `http://127.0.0.1:8188`).

### D11: Mapa keyword→prompt en assets/keywords.json

10 entradas de dominio de K. Prompts EN INGLES, texto dentro de imagen EN ESPANOL.
La palabra clave (lowercase) es la clave; el valor es el prompt de generacion.
Editable a mano por K sin tocar codigo.

### D12: Overlay como filtro FFmpeg — constantes nombradas

- Posicion: esquina superior derecha (W - w - MARGIN, MARGIN)
- Tamano: 18% del ancho del video (EMOJI_SIZE_PCT = 0.18)
- Duracion: 1.2s (EMOJI_DURATION_S = 1.2)
- Margen: 2% del ancho (EMOJI_MARGIN_PCT = 0.02)
- Disparo: kw_ts del brain.json (timestamp de la palabra clave)
- Capa: opt-in, default OFF. Checkbox "Emojis IA" en Studio > Render.

### D13: Arquitectura de capas — emojis no bloquean el pipeline

Si ComfyUI no corre o el keyword no tiene prompt: la capa se salta silenciosamente.
El video limpio y el video con solo captions siguen disponibles siempre (regla #15).

### D15: F4.2-CORTES — modo escenas (sesion 25, pre-firmadas)

Pipeline nuevo "modo escenas", DEFAULT del reframe tracking (--tracker escenas):
1. Detectar cortes con el detector existente (threshold 0.3 + filtro artefacto t<1s;
   NUESTRO dataset probo cortes reales a 0.65 — el threshold NO se sube).
2. Por segmento: frame representativo en el punto medio -> YuNet -> clasificar
   single / multi / none.
3. single -> tracking por WAYPOINTS dentro del segmento; multi -> sistema de anclas
   existente RE-ESCANEADO por segmento (EMA scoped); none -> crop estatico centrado.
4. Los tracks se REINICIAN en cada corte — cero estado cruzando fronteras (cada
   segmento es una llamada independiente a funciones puras sin estado de modulo).

WAYPOINTS (reemplaza al EMA dentro de segmentos single del modo escenas):
- Muestreo de cara cada 500ms (MUESTREO_ESCENAS_S).
- Deadzone 18% del ancho del crop (DEADZONE_PCT_ESCENAS) como DISPARADOR.
- Al excederse: UN paneo lineal de 500ms (PAN_DURACION_S). Cuadro CLAVADO el resto.
- x piecewise-linear calculado en Python (nuestro renderer ya recibe crops por frame;
  cero expresiones ffmpeg).

El EMA adaptativo F4.1 queda INTACTO como --tracker ema (fallback y comparacion, regla 15).
Turnos fuerzan la ruta EMA (tiempo global, incompatible con re-escaneo por segmento v1).
Limitacion v1: en segmentos multi solo se sigue la cara principal (mayor score) del frame
representativo; caras que entran a mitad del segmento no generan track propio.
Metrica: C1v2 por segmento (solo detecciones vivas, spec #24a) + n_paneos por segmento;
0 paneos esperados en tramos estaticos.

### D14: rembg para transparencia real (sesion 25)

Veredicto de K sobre v1 (PNG cuadrado en esquina): "no me sirve". Fixes pre-firmados:
- **rembg** (u2net via onnxruntime ya presente) quita el fondo tras generar; el cache
  guarda la version RGBA. Alternativa descartada: chroma key por color (fragil con
  sombras y bordes del sticker). Fail-open: sin rembg el PNG sale sin transparencia
  pero el render no se cae. `U2NET_HOME=models/u2net` (Regla #6).
- **PROMPT_TEMPLATE fijo** estilo sticker 3D con fondo blanco liso (ayuda a rembg).
  keywords.json ahora mapea keyword→concepto; el hash se calcula sobre el prompt
  templado → cambiar template o concepto invalida el cache automaticamente.
- **Posicion**: centrado horizontal, arriba del bloque de captions (y derivada de
  margin_pct + fontsize escalado del ASS via _scaled_fontsize, fuente unica de la
  formula). Tamano 20% del ancho. Fade in/out 120ms via -loop 1 + fade alpha + setpts.

---

## D16: Veredictos de K sobre la sesion 26 (sesion 27)

Sobre los 4 entregables de `revision/para-K/README.md`:

1. **A/B reframe — ESCENAS gana.** K: "ya no pierde a la persona tras los cortes".
   DECISION: modo escenas = DEFAULT de la ruta tracking (ya lo era en CLI desde s25;
   ahora tambien es el default explicito del Studio). EMA queda disponible como
   `--tracker ema` y como opcion del selector (regla 15: nada se elimina).
   Cierre formal de F4.2-CORTES.
2. **Emojis v2 — APROBADOS.** K: "ya parece emoji de app, posicion perfecta".
   F5-s1 VALIDADA y cerrada.
3. **Clips E2E — 95/100.** Los momentos elegidos por la IA son correctos.
   Insight de K registrado en PREGUNTAS #29: cada usuario podria sugerir o revisar
   (expectativas distintas) -> el paquete final SIEMPRE incluye paso de revision
   humana antes de publicar. Conecta con la aprobacion de F7.
4. **Stack — 0:00-0:36 publicable 100%.** El tramo duplicado es la limitacion
   conocida multi v2 (#28). PEDIDO DE K ADOPTADO COMO FEATURE en s27: el paquete
   avisa que tramos salieron bien y cuales revisar (reporte de calidad por tramos
   del Modo Automatico).
5. **Punch-in:** no aparecio en los renders (default off). Deuda #20 sigue esperando
   F5-s2. **Materiales M1-M5:** pendientes de K; NO bloquean — el estilo de marca
   usara placeholder hasta recibir M2/M3.

## D17: DOS MODOS, UN MOTOR (arquitectura de producto, sesion 27)

Registrada como MAESTRO regla #19 (vinculante). Resumen: Modo Automatico = capa
delgada que orquesta las herramientas existentes; Modo Creador = las herramientas
del Studio con control granular; toda funcion nueva nace como herramienta del motor
usable desde ambos modos; prohibido duplicar logica en la capa automatica y prohibido
convertir Centrito en editor generico de timeline. Roadmap de la capa en PREGUNTAS #29.

### Implementacion v1 (s27): modulo auto.py + worker run_auto

- `auto.py`: orquestador del objetivo "Clips virales" — llama core.transcribe_video
  (solo si falta words.json, voto #10), clipper.generar_clips, reframe.reframe_clip
  (tracker escenas), brain.analizar_grupos, assets_comfy.resolver_overlays y
  core.burn_video_with_emojis. CERO logica de pipeline propia.
- Reporte de calidad por tramos: traduccion 1:1 del seg_reporte que el modo escenas
  YA devuelve (tipo/c1v2/n_caras por segmento) a avisos en lenguaje humano.
  Umbral de aviso C1V2_AVISO=80.0 (heuristica inicial, ajustable con feedback de K).
- Paquete: `output/paquetes/{video}_{fecha}/` con clips finales + REPORTE.md.

## D18: F7 (Telegram / distribucion) DIFERIDA fuera de v1 (roadmap, arquitecto, s28A)

**Decision:** F7 (Telegram + distribucion automatica) se DIFIERE fuera del alcance de la v1.
NO se cancela: queda como fase futura post-v1. Su spec se conserva en PREGUNTAS marcada
"diferida, post-v1".

**Razon:** la distribucion NO es motor. En v1 el usuario revisa el paquete y publica a mano
(compuerta de revision humana, regla #19). Meter distribucion automatica en v1 mezcla una
preocupacion externa (canales, credenciales, aprobacion) con el nucleo del producto.

**Definicion de "terminado v1" (vinculante):** video entra -> paquete de clips listos para
revisar sale. Ese loop ya funciona (Modo Automatico v1, validado s27). Lo que resta para
pulir v1 no incluye distribucion.

**Mapa de fases restantes hasta v1 (actualizado):**
F5-s2 captions cineticos -> F6 HyperFrames (Motor B) -> reframe general v2 (modo pantalla #27
/ multi v2 #28 / seleccion manual de caras #24b, en el orden que dicte el uso real) -> v1.
F7 queda despues de v1.

**Recalculo de avance:** el denominador /100 ya trataba F7 como "suma aparte" (nota s26), asi
que formalizarlo no infla el numero; lo que cambia es que el alcance de v1 queda cerrado y
claro. Con el loop nucleo ya funcional y F5-s2 (motor) entregado, el avance pasa a 82/100
(F5-s2 pulido + F6 + reframe v2 son lo que resta para v1).

## D19: Veredicto de K sobre captions cineticos s28A (sesion 28C)

- **pop 1.08 (suave) y 1.15 (fuerte de s28A): DESCARTADOS.** Demasiado sutiles: "saltan las
  letras pero nada se ve mas grande que lo demas". Causa raiz: en s28A la palabra activa
  volvia a 100% (tamano de los vecinos) tras el salto; solo popeaba 180ms y el pico era bajo.
- **Estilo clean: APROBADO tal cual.**
- **Decision:** subir intensidad (medio 1.30, fuerte 1.45) y agregar REBOTE/OVERSHOOT — la
  palabra hace overshoot al pico (~pop*1.12) y baja al TAMANO DE REPOSO DEL ENFASIS (pop, no
  100), de modo que queda mas grande que los vecinos mientras esta activa. Default hormozi del
  autopiloto: medio 1.30 con rebote ON (K juzgara si sube a 1.45 con los renders de s28C).
  Implementado en s28C BLOQUE 1. **(SUPERADO por D20: K juzgo 1.30/1.45 demasiado fuertes; el
  default volvio a suave 1.08. Los niveles medio/fuerte siguen disponibles como opcion.)**

## D20: Default de captions vuelve a SUAVE 1.08 (veredicto de K sobre s28C)

- **1.30 (medio) y 1.45 (fuerte): DEMASIADO FUERTES** para K. Prefiere las intensidades
  suaves. Los 4 niveles se CONSERVAN todos (regla #15): off/suave/medio/fuerte siguen
  disponibles en CLI y Studio; SOLO cambia el default.
- **Default provisional del estilo hormozi (y del autopiloto): pop SUAVE 1.08.**
- ~~**PENDIENTE DE K — el sabor exacto del suave** (con o sin rebote)~~ **CERRADA (s29):
  veredicto final de K sobre el A/B s28D = opcion (b), suave 1.08 CON rebote.**
  **DEFAULT FINAL de captions: suave 1.08 + overshoot ON** (hormozi y pms; pms sigue
  alineado a hormozi hasta que llegue la marca real M2/M3). Los 4 niveles off/suave/medio/
  fuerte y el flag --rebote se conservan como opciones (regla #15). Motor (core_ass) NO
  tocado: el cierre es solo config de estilos (overshoot=True) + 2 tests actualizados.
  D20 queda cerrada; F5-s2 sin pendientes de sabor (solo M2/M3 para la marca real).

## D21: Veredictos de K sobre los 4 presets del CVE + calibracion keyword_punch (s31)

Sobre los demos de s29/s30 (`output/videolargo_clip1_largo_9x16_{clean_podcast,viral_bounce,keyword_punch,karaoke_highlight}.mp4`):

1. **clean_podcast — APROBADO** como estilo serio.
2. **viral_bounce — APROBADO como base/default DEL MOTOR CVE para short-form.**
   Alcance exacto: es el punto de partida cuando se usa el CVE. **NO es el default
   universal de Centrito** — el default universal de captions sigue siendo D20
   (hormozi suave 1.08 + rebote). No se toca codigo por este veredicto: el CLI y el
   Studio siguen sin preseleccionar preset; cuando la receta del Modo Automatico
   nombre presets (PREGUNTAS #29.1), viral_bounce sera el candidato para short-form.
3. **karaoke_highlight — APROBADO tal cual.**
4. **keyword_punch — OPT-IN de nicho, NUNCA default.** Diagnostico de K: repetido !=
   importante; el problema es SELECCION + AMPLIFICACION, no solo intensidad.

### Calibracion de keyword_punch (firmada, implementada s31)

- **Densidades con DOBLE FRENO (tope absoluto Y porcentaje):**
  `baja = min(5, 15%)` · `media = min(10, 20%)` · `alta = min(15, 30%)`.
  En clips cortos manda el %, en largos el tope absoluto — el doble freno es
  INTENCIONAL: no simplificarlo a solo porcentaje. (baja usa el techo del rango
  10-15% votado; el tope absoluto ya frena los clips largos.)
- **Default = densidad baja.** Las marcas MANUALES estan exentas del freno
  (consistente con voto #34: saturar es decision del usuario). La exencion aplica
  a TODAS las rutas, incluida la historica densidad=None (40%): antes el cap
  contaba manuales+autos juntas; desde s31 las manuales jamas caen por densidad
  (cambio intencional, fijado por test). El freno recorta las automaticas de
  peor score primero — con ello R7 (repetidas, score 60) es lo primero que cae,
  atacando el "repetido != importante".
- **Intensidad default = 130** (intensidad `clean`; sin glow, matriz §6.1);
  **145 + glow queda como opcion fuerte** via `--intensidad viral` (regla #15:
  nada se elimina). CLI gana `--densidad baja|media|alta`.

### Transparencia OBLIGATORIA: sidecar keyword_selection.json (s31)

Todo render con seleccion automatica de keywords (modos `brain` / `auto+brain`)
escribe `{render}.keyword_selection.json` junto al MP4 con: palabra, timestamp,
grupo y frase, regla que la eligio (R1-R7 | brain | manual), fuente
(regla | brain | manual), preset y densidad usados. Aplica a CLI y Studio
(fuente unica `cve.escribir_sidecar_seleccion`, fail-open: su fallo jamas tumba
el render). Mostrarlo en el Studio es opcional/no bloqueante; el sidecar SI es
obligatorio.

---

## D22: Veredicto K sobre s31-bis + perfil visual keyword_punch + filtro debil + manual v1 (s32)

### Veredicto K (revisado sobre los renders de s31-bis)

1. **image_popups — APROBADO.** Video revisado:
   `output/videolargo_clip1_largo_9x16_hormozi_popups.mp4`. Los popups estan bien,
   no requieren ajuste urgente. Cierra la validacion de la rebanada image_popups v1.
2. **keyword_punch: K prefiere el VIEJO (`_keyword_punch.mp4`), NO el clean
   (`_keyword_punch_clean.mp4`).** El clean NO reemplaza al viejo. El render viejo
   se mantiene como referencia visual preferida — **no borrar ni sobrescribir**.

   **Interpretacion:** el problema de keyword_punch NO es solo visual — la ENERGIA
   del viejo gusta mas. El problema real sigue siendo la SELECCION automatica de
   palabras debiles/arbitrarias (consistente con D21: "seleccion + amplificacion,
   no solo intensidad"). Objetivo S32: conservar la energia visual del viejo como
   opcion, pero mejorar CONTROL (marcado manual) y SELECCION (filtro anti-stopword).

### Perfil visual keyword_punch (ajuste a D21, sin romper lo hecho)

- keyword_punch sigue **opt-in, nunca default universal** (D21 intacto).
- **`keyword_punch` (clasico/viejo) = perfil visual PRINCIPAL** para quien elige ese
  preset: energia clasica preferida por K. El default calibrado del preset (130,
  densidad baja, sin glow) sigue vigente como punto de entrada sobrio; **145+glow**
  (`--intensidad viral`) recupera la energia fuerte del viejo (regla #15: nada se
  elimina). El render viejo `_keyword_punch.mp4` NO se sobrescribe.
- **`keyword_punch_clean` = variante SOBRIA, no reemplazo.** Es un render de
  comparacion producido con `--intensidad clean` explicito; se conserva pero NO se
  impone como default sobre el gusto de K por el viejo.
- **`viral_bounce` sigue como default short-form/CVE** cuando no se elige punch (D21).

### Filtro de keywords debiles (BLOQUE 2, s32)

El sidecar de s31 mostro que el brain elegia palabras debiles ("en", "un") con
score 100. Causa: `candidatos_brain` reancla por `kw_ts` sin filtrar stopwords
(a diferencia de las reglas R1-R7, que ya las saltan). Fix:

- **`es_keyword_debil(palabra)`**: True si la palabra normalizada es stopword o
  demasiado corta (< `LARGO_MIN_CONTENIDO`), EXCEPTO si dispara una senal fuerte
  (dinero/numeros/negaciones/fechas via `_regla_por_palabra`). Reusa STOPWORDS.
- El filtro se aplica **solo a las AUTOMATICAS del brain** (`candidatos_brain`).
  Las reglas ya filtran. **Manual SIEMPRE gana y jamas se filtra** (voto #34).
- Las descartadas se registran en `keyword_selection.json` (campo `descartadas`
  con palabra, timestamp, grupo, razon, fuente) — transparencia barata (D21).

### Marcado manual v1 (BLOQUE 3, s32)

Sidecar `{stem}_keywords.json` junto al transcript (ademas del marcado inline
`[strong]`/`[big]`/`[center]` ya existente). Permite destacar palabra exacta o
frase corta, opcional grupo/timestamp/intensidad, con **prioridad sobre reglas y
brain** (SCORE_MANUAL). En el sidecar aparece `fuente="manual"`, `regla="manual"`
(o `manual_big`) y **no se filtra por stopwords**. Fail-open: manual invalido
(JSON roto, palabra inexistente) jamas rompe el render. NO se crea editor visual
ni timeline (fuera de alcance v1).

---

## D23: Veredicto K sobre los renders s32 — el marcado MANUAL es la ruta premium

Sobre los 3 renders de s32 (`output/*_keyword_punch_{clean,classic_s32,manual_s32}.mp4`):

**K prefiere `_keyword_punch_manual_s32.mp4`** (marcado manual) sobre la version
automatica clasica (`_classic_s32`) y sobre la clean.

**Interpretacion:** el efecto visual de keyword_punch funciona MEJOR cuando las
palabras destacadas son elegidas manualmente o guiadas por intencion humana. La
seleccion automatica (brain + reglas + filtro anti-stopword de B2) AYUDA, pero no
debe ser la fuente principal cuando se busca maxima calidad. Confirma la tesis de
D21/D22: el problema es SELECCION; el humano selecciona mejor que el brain.

### Decision de producto

- **`keyword_punch` con marcado manual = la mejor ruta para resultados premium.**
- **`keyword_punch` automatico = asistencia util, NO la referencia final de calidad.**
  El brain/reglas sugieren; el filtro anti-stopword (B2) limpia; pero la aprobacion
  humana manda.
- **El sistema debe permitir sugerencias automaticas + que el usuario apruebe, edite
  o fuerce palabras.** El marcado manual v1 (B3, `{stem}_keywords.json`, SCORE_MANUAL,
  exento del filtro) ya es la base tecnica de "forzar"; falta el ciclo de aprobar/editar.
- **Para Alpha, el marcado manual es parte importante del flujo de REVISION.**

### Consecuencia para el roadmap (deudas s32 re-priorizadas)

- La deuda "manual sidecar es CLI-only, falta en el Studio" (revisor s32, riesgo #1)
  pasa de *nice-to-have* a **prioritaria para Alpha**: el flujo de revision del Studio
  debe leer/escribir `{stem}_keywords.json` (o equivalente) y dejar al usuario
  aprobar/editar/forzar las keywords que el brain sugirio. El sidecar
  `keyword_selection.json` (keywords + descartadas) ya es la fuente de datos para
  poblar esa UI de revision.
- No convierte esto en editor visual/timeline: es un panel de revision de keywords
  (aprobar/editar/forzar palabras sobre los grupos existentes), no edicion libre.

---

## D24: Caption QA — corrector de transcripcion con glosario + guion opcional (s33)

**Que es:** capa opcional (`--caption-qa`) previa al burn que detecta palabras mal
transcritas ("confeti UI" -> ComfyUI, "aflicjo" -> archivo, "Kansas" -> canvas) y
genera `transcripts/{stem}_caption_alerts.json`. Dos modos: `alertas` (solo reporta)
y `auto_seguro` (aplica SOLO confianza alta, en memoria).

### Decisiones de diseno

1. **Variantes curadas > fuzzy.** Calibracion s33 con pares reales: los errores
   FONETICOS no se cazan por similitud (confeti ui/comfyui 0.588, aflicjo/archivo
   0.429, kansas/canvas 0.667 — todos bajo el umbral util) mientras los falsos
   positivos aparecen desde 0.667 (flujo/flux) y 0.769 (archivo/activo). Por eso:
   - `assets/glosario.json` con **variantes conocidas** (confianza alta, editable
     por K sin tocar codigo) = la ruta premium — consistente con D23: la curaduria
     humana gana a la heuristica.
   - Similitud difflib SOLO para errores ortograficos contra terminos >= 6 chars
     (checpoint/checkpoint 0.947): alta >= 0.87, media >= 0.78.
2. **Guion opcional** (`{stem}_guion.txt` o `--guion`): vocabulario esperado +
   contexto de bigrama precedente ("abrir el ___" -> archivo). Sugerencias del guion
   = confianza MEDIA (el guion puede ser resumen/parafrasis): alertan, no auto-aplican.
3. **Heuristica prob Whisper < 0.40**: alerta BAJA sin sugerencia (senala donde mirar).
4. **DeepSeek = AUDITOR, no reescritor** (`--caption-qa-llm`, opt-in): recibe solo las
   alertas no-altas con contexto de +-4 palabras; puede confirmar (sube a alta),
   proponer o descartar. Fail-open: si la API cae, las alertas deterministas quedan.
5. **Nada persiste al transcript**: `auto_seguro` corrige en memoria del render; el
   words.json de disco conserva su hash (verificado en la validacion). Manual gana.
6. **Timestamps intactos**: una correccion multi-palabra fusiona el span en un word
   [s del primero, e del ultimo]; ningun otro timestamp cambia. Fijado por test.
7. **Stopwords y tokens < 4 chars jamas se corrigen** (reusa STOPWORDS de cve_keywords).
8. **Fail-open total** (regla #8 extendida): QA roto -> aviso + render con la
   transcripcion original. Fijado por test sobre el wrapper de caption.py.

**Validacion:** revision/s33-caption-qa/ (frames COMFYUI/CHECKPOINT quemados, AFLICJO
pendiente como media, baseline intacto). 316 tests. Sin dependencias nuevas (difflib
es stdlib).

---

## D25: Veredicto K sobre S33 — Caption QA APROBADO para Alpha

**K reviso los frames de `revision/s33-caption-qa/` y aprueba S33 visualmente:**

1. Sin QA: `CONFETI UI` y `CHECPOINT` visibles como errores reales (baseline honesto).
2. Modo `alertas`: conserva el caption original, no modifica a ciegas. CORRECTO.
3. Modo `auto_seguro`: corrige `CONFETI UI` -> `COMFYUI` y `CHECPOINT` -> `CHECKPOINT`.
4. `AFLICJO` queda pendiente y NO se autocorrige — correcto por ser confianza media.

### Decision de producto (vinculante)

- **Caption QA queda APROBADO como capa util y segura para Alpha.**
- **Estrategia confirmada** (es exactamente el contrato implementado en s33/D24):
  - confianza ALTA: puede autoaplicarse en `auto_seguro`;
  - confianza MEDIA/BAJA: queda como alerta para revision humana;
  - modo `alertas`: no debe modificar captions.
- **No reabrir S33 salvo bugs.**

### Siguiente paso recomendado por K

**S34 — Alpha 0.1**: estabilizacion, splits por limite de lineas (caption.py 398/400 y
auto.py 400/400, riesgo (a) del revisor s33), UI minima y guia para testers.

### Criterio Alpha 0.1 (registrado s34 B0, vinculante para el roadmap inmediato)

- **Caption QA queda aprobado TECNICAMENTE** (frames s33 + contrato de confianzas).
- **La app ya tiene suficientes funciones para preparar Alpha 0.1** (loop nucleo D18
  funcional + estaciones + CVE + Caption QA).
- **Antes de nuevas features grandes toca: estabilizacion, UI minima y flujo de
  prueba para testers cercanos.** Ninguna feature visual nueva en s34.
- **Riesgo tecnico registrado:** caption.py 398/400 y auto.py 400/400 lineas — el
  proximo cambio EXIGE split (revisor s33, riesgo (a)). El split es el BLOQUE 1 de s34.

### D26 — Editor de Paquete + 3 modos (registrado s35 B0, vinculante)

Decision de producto para dejar el Studio listo para testers cercanos (Alpha 0.1):

- **Centrito NO sera un CapCut completo.** No timeline profesional multipista, no
  cortes manuales, no drag&drop, no editor de video real. La app sigue siendo una
  fabrica de clips con IA + revision, no una suite de edicion.
- **Se agrega el concepto de "Editor de Paquete".** Es una vista de REVISION, no de
  edicion: NO reimplementa motores; solo VISUALIZA outputs, reportes y sidecars que
  ya existen en `output/paquetes/` (paquete.json, REPORTE.md, `*_caption_alerts.json`,
  `*.brain.json`). Cero recalculo, cero re-render.
- **Tres modos, un motor** (extiende regla MAESTRO #19):
  1. **Modo Automatico** — genera paquetes (pipeline intacto).
  2. **Modo Editor / Revision** — revisa clips generados: estados, alertas, timeline
     simple de markers, recomendacion del reporte.
  3. **Modo Creador / Herramientas** — herramientas existentes con control granular
     (captions, clipper, reframe, stack, caption QA, popups, keyword punch, depurador).
- **Objetivo Alpha 0.1:** que un tester entienda QUE paso y QUE revisar sin leer el
  JSON ni la CLI. La UI premium es medio, no fin.
- **Prohibido en s35:** tocar reframe/clipper/depurador/brain/core/motores de render,
  migrar framework, meter React/Vue, cambiar arquitectura, o tocar
  `.env`/`input`/`output`/`transcripts`/`models` (salvo LEER sidecars para mostrarlos).

---

## D27 — B-roll cutaway de imagen: extension de la capa de overlays (feat/broll-cutaway-image)

**Que es:** soporte de b-roll de IMAGEN en modo cutaway grande, reutilizando `core_overlays.Popup`
en vez de crear un subsistema nuevo. El popup pequeno historico (esquina, dentro de la zona util
de TikTok/Reels) y el cutaway grande (centrado, ocupa gran parte o todo el cuadro) son el MISMO
dataclass con dos ramas de geometria. Extension ADITIVA, default-off (regla #15): sin `cutaway`
el comportamiento es byte-identico.

**Decisiones tomadas (aprobadas por K antes de implementar):**

1. **Dos ejes explicitos, no un modo magico.** `size_pct` = fraccion del cuadro (1.0 = pantalla
   completa) y `fit` = estrategia de encaje. Nada se infiere del aspecto de la imagen.
2. **`fit` default = `contain`** (imagen entera visible, sin recorte, sin deformacion): es la
   opcion segura. `cover` (llena el cuadro recortando el excedente, aspecto preservado) es opt-in
   explicito. Ambos via `force_original_aspect_ratio` de FFmpeg (jamas deforman).
3. **Tamano default del cutaway = 0.85** del cuadro (grande pero deja margen). El default de
   `Popup.size_pct` es `None` (sentinel) y `Popup.__post_init__` lo resuelve: None + cutaway ->
   0.85, None + normal -> 0.20 (POPUP_SIZE_PCT); cualquier valor explicito, INCLUIDO 0.20, se
   conserva. Asi `Popup(cutaway=True)` construido directo tambien da 0.85 (no solo via cve_popups),
   sin la heuristica fragil de comparar `size_pct == 0.20` (que confundiria omitido con 0.20
   explicito). El campo NO cambia de posicion en el dataclass -> llamadas posicionales intactas.
   *(Correccion de un bloqueo detectado en revision pre-commit: el default vivia solo en
   cve_popups, dejando la construccion directa en 0.20.)*
4. **El cutaway NO se confina a `zona_util`.** El confinamiento a safe zones es correcto para el
   popup pequeno (adorno junto a la UI); un cutaway grande, por definicion, la excede. Se centra
   con expresiones `(W-w)/2 / (H-h)/2` (FFmpeg resuelve en runtime -> exacto para cualquier aspecto).
5. **`fit` invalido -> fail-open a `contain`** con aviso ASCII (mismo patron que `pos` invalido ->
   `auto_safe`). `size_pct>1.0 -> 1.0`; `<=0 -> desactivado`. Un popup nunca tumba el render.
6. **Declaracion manual: cutaway sin `behind_text` -> `behind_text=True`** (captions ENCIMA del
   b-roll, que es lo deseado para b-roll narrado). `behind_text` explicito (True o False) se
   respeta. El popup historico sin `cutaway` conserva su default `False` intacto.

**Alcance cerrado (NO implementado, por diseno):** busquedas en APIs de stock/Pexels, overlays de
video, Ken Burns, persona recortada sobre fondo (matting), cambios a brain/DeepSeek, UI/Studio,
seleccion automatica de b-roll, NVENC, audio, SRT, refactors generales, dependencias nuevas.

**Deuda anotada:** el cutaway es CLI-only via `{stem}_popups.json` (consistente con `--popups` s31,
CLI-only). Exponerlo en el Studio conecta con el panel de revision futuro (D23/D26).

---

## D28 — Fetcher de b-roll de imagenes (Pexels): modulo aislado, opt-in (feat/broll-pexels-images)

**Que es:** `broll_stock.py`, capa que busca/selecciona/descarga/cachea imagenes de stock de
Pexels para b-roll cutaway. Es una isla: NO conecta con brain, render, `core_overlays`/`Popup`,
UI ni `auto.py`. Solo produce assets tipados (`StockAsset`) y archivos en cache que una
integracion futura (el consumidor de D27) leera. Extension aditiva default-off (regla #15):
sin `PEXELS_API_KEY` la capa queda deshabilitada y el pipeline sigue (fail-open, regla #8).

**Decisiones tomadas (aprobadas por K antes de implementar):**

0. **Split en dos archivos por la regla anti-spaghetti (archivo <= 400 lineas, skill
   centrito-dev).** `broll_stock.py` (API publica: config, HTTP, seleccion, descarga,
   orquestacion) + `broll_stock_base.py` (tipos, errores, cache de busqueda + IO atomica +
   sidecar). Capas sin ciclo: base no depende de red ni de la key; `broll_stock` la consume y
   re-exporta el contrato publico (`from broll_stock import StockAsset, buscar_broll_seguro, ...`).
1. **Cliente HTTP = `requests`**, ya presente en `requirements.txt` (mismo patron que
   `submagic.py`). CERO dependencias nuevas.
2. **429 sin reintento en V1.** No hay sleep ni repeticion automatica: se lanza
   `PexelsRateLimit` conservando `Retry-After` como dato opcional; `buscar_broll_seguro` lo
   traduce a `BrollError(code="rate_limit", retry_after=...)` para que el pipeline omita el
   b-roll y continue. Los headers `X-Ratelimit-*` solo se leen en respuestas 2xx (no se depende
   de ellos al manejar el 429).
3. **Seleccion de variante determinista, prioriza RESOLUCION.** La orientacion ya se resuelve en
   la busqueda (`orientation` a la API), asi que los candidatos ya tienen composicion compatible
   con el destino; por eso NO se priorizan las variantes recortadas de Pexels. Ordenes:
   - `contain`: `large2x -> original -> large`
   - `cover` + vertical: `large2x -> original -> portrait`
   - `cover` + horizontal: `large2x -> original -> landscape`
   `large2x` (~1880px) conserva mejor detalle en salida Full HD (1080x1920 / 1920x1080); las
   variantes `portrait` (~800x1200) y `landscape` (~1200x627) estan recortadas y se ven suaves al
   llenar, por lo que quedan como ultimo fallback orientado. `original` es el fallback de maxima
   calidad. `seleccionar_variante` devuelve `SeleccionVariante(nombre, url, motivo)`; sin ninguna
   variante admitida -> `PexelsSinVariante`. Cada orden esta cubierto por un test explicito.
4. **Doble cache.** (a) Archivo descargado con identidad `provider+asset_id+variante`
   (`pexels_{id}_{variante}.{ext}`): la VARIANTE se resuelve ANTES de la ruta, asi dos variantes
   del mismo `asset_id` (p.ej. `large2x` para un destino y `portrait` como fallback de otro) NUNCA
   colisionan; la extension viene de la FIRMA de bytes (JPEG/PNG/WebP), no de la URL. (b) Respuesta
   de busqueda JSON con TTL 24h y clave determinista (query normalizada -strip + colapso de
   espacios + lowercase- + orientation + per_page + page). Ambas se escriben atomicamente
   (temporal + `os.replace`), se deshabilitan con `usar_cache=False`, y se ignoran/renuevan si
   vencen o se corrompen (jamas fingen exito). Cache en `assets/broll/cache/pexels/` (gitignored;
   las imagenes reales nunca entran al repo).
   *(Correccion post-revision: la identidad por solo `asset_id` reutilizaba la variante
   equivocada cuando cambiaba destino/fit; ahora incluye la variante.)*
5. **Estado antes/despues de descargar sin strings vacios.** `StockAsset` es frozen con
   `local_path`/`metadata_path = None` como candidato; al descargar tambien gana
   `selected_variant` y `selection_reason`, y `descargar_asset` devuelve una NUEVA instancia con
   la `download_url` realmente usada + rutas reales. **Cache hit valido SOLO si**: la imagen existe
   y su contenido sigue siendo imagen valida (firma de bytes) Y el sidecar existe y coincide en
   `provider`, `asset_id`, `selected_variant` y `download_url` con la seleccion actual. Cualquier
   desajuste (variante o URL distinta, sidecar faltante/corrupto) -> se re-descarga (nunca se
   reutiliza el archivo de otra variante).
6. **Sidecar de atribucion/licencia** por imagen (utf-8, sin la API key): `provider_url`,
   `attribution_text` ("Photo by {author} on Pexels"), `source_url`, `author_url`, dimensiones,
   `selected_variant`, `selection_reason`, `download_url`, `downloaded_utc`, `last_used_utc`,
   `sidecar_version` y bloque de licencia (uso comercial si; redistribuir como biblioteca de stock
   no; datasets/entrenamiento IA no; Centrito lo usa como material integrado). **Refresh en cache
   hit:** un hit valido reescribe el sidecar (atomico) actualizando SOLO `query` (la mas reciente),
   `selection_reason` (el actual) y `last_used_utc`; `downloaded_utc` se PRESERVA (nunca se
   reinicia). Un solo campo `query` (sin lista `queries[]` ni migracion). La identidad de archivo
   no cambia.
7. **Contrato de error seguro y tipado + fail-open acotado.** `BrollResult(assets, error,
   rate_limit)` con `BrollError(code, message, retry_after)` y `RateLimitInfo`. Mensajes saneados:
   `_sanitizar` garantiza que ni la key ni `Authorization` se filtren. La capa
   `buscar_imagenes_pexels` es HONESTA (lanza excepciones tipadas). `buscar_broll_seguro` es
   **fail-open SOLO para errores operativos conocidos**: atrapa unicamente la familia `PexelsError`
   (deshabilitado/429/auth/http/timeout/respuesta_invalida/sin_variante/descarga). Los errores de
   PROGRAMACION (RuntimeError/TypeError/ValueError/AssertionError) se PROPAGAN, no se ocultan.

**Alcance cerrado (NO implementado, por diseno):** busqueda de videos, Pixabay/Storyblocks,
overlay de clips, conexion con brain/DeepSeek, traduccion de keywords, ranking con LLM,
integracion con `core_overlays`/creacion de `Popup`, UI, aprobacion/rechazo, Ken Burns, matting,
cambios en `auto.py`, llamadas reales durante pytest.

**Requiere prueba manual con API key real:** el smoke test (`revision/broll-pexels-images/
smoke_pexels.py`) hace una busqueda + descarga real contra Pexels; no forma parte de pytest.

## D29 — Pexels como b-roll cutaway: puente aislado, entrada explicita (feat/broll-pexels-cutaway-integration)

Cierra el circuito abierto por D27 (cutaway) y D28 (fetcher): un modulo PUENTE convierte una
entrada EXPLICITA de b-roll Pexels en un `Popup(cutaway=True)` renderizable, sin acoplar el
fetcher a la capa de overlays ni al reves.

1. **Un modulo puente nuevo, no un metodo en el fetcher.** `broll_cutaway.py` importa el fetcher
   (`buscar_broll_seguro`, `descargar_asset`) y `core_overlays.Popup`; el fetcher NO conoce a
   `Popup` (sigue puro respecto al pipeline, D28) y `core_overlays` NO conoce a Pexels. Motivo
   extra: `broll_stock.py` ya estaba a 396/400 lineas; meterle la integracion habria forzado otro
   split. El puente es la costura natural y mantiene ambas capas <=400L.
2. **Contrato publico:** `resolver_cutaway_pexels(query, t0, t1, *, orientation, fit="cover",
   size_pct=1.0, behind_text=True, cache_dir=None) -> ResultadoCutawayPexels(popup, codigo,
   mensaje, asset)` + `orientacion_para_video(w, h) -> (orientation_pexels, destino)`.
   **Los timestamps vienen de la ENTRADA, no de Pexels.** Seleccion **determinista**: el PRIMER
   candidato que devuelve el fetcher (V1, sin ranking). Reutiliza el fetcher COMPLETO: cero HTTP,
   cero caché/sidecar duplicados; la geometria del cutaway es la de `_preparar_cutaway` (D27), no
   se duplica.
3. **Fail-open acotado, igual criterio que el fetcher (D28-7).** Los errores OPERATIVOS conocidos
   (familia `PexelsError`: `deshabilitado`/`rate_limit`/`auth`/`timeout`/`http`/`respuesta_invalida`/
   `sin_variante`/`descarga`) -> `ResultadoCutawayPexels` SIN popup y con `codigo` visible; el
   render omite ese b-roll y sigue. **Cero resultados NO es excepcion:** codigo `sin_resultados`.
   Los errores de PROGRAMACION (RuntimeError/TypeError/AssertionError) y los de CONTRATO (ValueError
   por query vacia, `t1<=t0`, `fit`/`size_pct`/`orientation` invalidos) se **PROPAGAN**: un contrato
   roto no se disfraza de fallo de red.
4. **Orientacion derivada del video, sin hardcodear vertical.** 9:16 (h>w) -> `portrait`/`vertical`;
   16:9 y cuadrado (w>=h) -> `landscape`/`horizontal`. `destino` es lo que consume `descargar_asset`
   para ordenar variantes de cover (D28-3). `cve_popups`/`caption.py` propagan `video_w/video_h`.
5. **Entrada por el sidecar manual ya existente** (`{stem}_popups.json`, el que consume
   `cve_popups`), extendido con `source="pexels"` + `query`. `_entrada_manual` enruta por `source`;
   ausente/`biblioteca`/`local` conserva el flujo PNG historico (compatibilidad total, incluido
   cutaway PNG de D27). `_entrada_pexels` es fail-open TOTAL (jamas lanza; log ASCII accionable) e
   importa `broll_cutaway` de forma **lazy**: sin una entrada pexels no se toca el fetcher ni la red
   (renders sin Pexels no requieren API key). `behind_text` default True para el cutaway Pexels
   (captions encima); explicito se respeta.

**Alcance cerrado (NO en este PR, por diseno):** eleccion automatica de cuantos/cuando poner
b-roll (vive en el brain), clips de VIDEO de Pexels, ranking con LLM, traduccion de la query,
seleccion de multiples b-rolls, UI de aprobacion/rechazo, Ken Burns, matting, cambios en `auto.py`
o `brain.py`, llamadas reales durante pytest.

**Requiere ojo de K (salida visual):** que el `cover` full-frame (size_pct=1.0 default) no tape
demasiado a la persona/microfono, legibilidad de captions sobre foto real, pertinencia semantica de
la imagen. Evidencia: `revision/broll-pexels-cutaway/` (README + `gen_evidencia.py` que se niega sin
key + `ejemplo_popups.json`); 3 frames antes/durante/despues sobre `input/reel01.mp4` (persona real).

## D30 - Fetcher de b-roll de VIDEOS (Pexels): modulo aislado, opt-in (feat/broll-pexels-video-fetcher)

**Contexto:** el fetcher de IMAGENES (D28) y el puente de cutaway de imagen (D29) ya estan
mergeados. El siguiente paso hacia clips de video Pexels es la PLOMERIA: buscar, seleccionar,
descargar y cachear un `video_file` MP4. Este PR es SOLO eso; la integracion con FFmpeg/render/
overlays/UI es el PR B (D31, siguiente).

**Decision:** modulo(s) nuevo(s), aislado(s), sin tocar el fetcher de imagenes ni el pipeline.

1. **Split en tres unidades** (regla anti-spaghetti, cada archivo <=400L, funciones <=50L):
   `broll_video_stock_base.py` (tipos/errores/cache/IO/sidecar/`verificar_mp4_ffprobe`),
   `broll_video_select.py` (seleccion determinista PURA, sin red) y `broll_video_stock.py`
   (config + busqueda HTTP + descarga por streaming + orquestador seguro). Se **reutilizan** de
   `broll_stock_base` la escritura atomica, el reloj UTC, la normalizacion de query y el tipo
   `RateLimitInfo` (sin ciclo: la base de imagenes no importa la de video). CERO deps nuevas.

2. **Endpoint** `GET https://api.pexels.com/v1/videos/search` (verificado contra la doc oficial).
   Un `Video` trae id/width/height/url/image/duration/user{id,name,url}/video_files[]; cada
   `video_file` trae id/quality/file_type/width/height/fps/link. No se inventan campos.

3. **size=None por defecto (decision explicita).** `size` (large|medium|small) es un FILTRO de
   busqueda opcional; por defecto NO se envia a la API. La resolucion final la decide
   `seleccionar_variante_video` sobre los `video_files`, no el filtro: asi no se descartan videos
   utiles por un filtro de resolucion grueso, y la seleccion queda en un unico lugar determinista.

4. **Seleccion determinista por VARIANTE** (`seleccionar_variante_video(video_files, *, destino,
   target_width, target_height)`): (a) filtra MP4 directos validos -> descarta HLS, `.m3u8`,
   `file_type != video/mp4`, dimensiones <=0, links vacios; (b) prioriza candidatos cuya
   orientacion coincide con el destino (`vertical`->portrait, `horizontal`->landscape); (c) entre
   los que ALCANZAN target_width y target_height, el de MENOR area suficiente (evita 4K si una
   Full HD cubre el destino); (d) si ninguno alcanza, el de MAYOR area disponible; (e) desempate
   determinista: menor diferencia de aspect ratio, luego file_id. Nunca aleatorio. Sin candidato
   valido -> `PexelsVideoSinVariante`. Ejemplos: 1080x1920 gana a 2160x3840; 1920x1080 gana a
   4096x2160; con solo 720x1280 se usa como fallback vertical.

5. **Cache por `video_id + file_id`** (NO solo video_id): la identidad de archivo es
   `pexels_{video_id}_{video_file_id}.mp4` + sidecar `.json`. Un mismo video tiene varias variantes
   (portrait/landscape, distintas resoluciones); incluir el file_id evita que una variante pise a
   otra. Cache hit SOLO si el MP4 conserva firma ISO/MP4 (ftyp) valida Y el sidecar coincide en
   provider/asset_id/video_file_id/download_url. Cache de busqueda JSON aparte, TTL 24h, identidad
   con media_type=video+query+orientation+size+locale+per_page+page. Todo en
   `assets/broll/cache/pexels_video/` (gitignored: ni MP4 ni sidecar entran al repo).

6. **Descarga honesta + segura.** Streaming por chunks con tope de 100MB, timeout explicito de 60s,
   temporal + `os.replace` (atomico). Se valida Content-Type (video/ u octet-stream) cuando viene
   y SIEMPRE la firma ftyp (HTML renombrado se rechaza). `ffprobe` es validacion REAL opcional
   (`verificar_mp4_ffprobe`, usada por el smoke/evidencia; los unit tests trabajan con MP4
   sinteticos de solo-ftyp y no dependen de ffprobe). Sidecar sin API key, con
   attribution_text="Video by {author} on Pexels" + licencia; en cache hit preserva downloaded_utc.

7. **Fail-open acotado (mismo criterio que D28).** Capa baja lanza `PexelsVideoError` tipado;
   `buscar_video_broll_seguro` atrapa SOLO esa familia -> `BrollVideoError` saneado (sin secretos)
   para que el pipeline omita el b-roll y siga. Errores de programacion (RuntimeError/TypeError/
   ValueError/AssertionError) se PROPAGAN. Seguridad #9: la key nunca se imprime/serializa/loguea.

**Alcance cerrado (NO en este PR, por diseno):** integracion con FFmpeg/render/overlays/`Popup`/
`caption`/`cve_popups`/UI, seleccion automatica de cuando/cuantos clips (brain), ranking LLM,
traduccion de la query, multiples clips, Ken Burns, matting, audio, NVENC, SRT, cambios en
`auto.py`/`brain.py`, llamadas de red durante pytest. Todo eso queda para el PR B (D31).

**Sin salida visual:** es plomeria. Verificacion: 52 tests offline (538 totales) + smoke real con
key (video_id=35568501, file_id=15070864, 1080x1920, 11s, h264 por ffprobe; MP4 no commiteado).
Evidencia: `revision/broll-pexels-video-fetcher/` (README + `smoke_video_pexels.py`).

## D31 - Clip de video Pexels como b-roll cutaway: capa aditiva, un clip, cover-only (feat/broll-pexels-video-cutaway)

**Contexto:** con el fetcher de VIDEOS mergeado (D30), el paso visible es usar un clip local
descargado como cutaway temporal dentro del MISMO render FFmpeg, con captions encima, audio original
conservado y clip silenciado. Es la contraparte de video del cutaway de imagen (D27/D29).

**Decision:** capa ADITIVA, sin romper compatibilidad ni el audio original.

1. **Tipo explicito `ClipOverlay`, NO se fuerza el video dentro de `Popup`.** `Popup` es de imagen
   (PNG/WebP) y queda intacto. `clip_overlay.py` define `ClipOverlay(clip, t0, t1, source_start,
   loop, cutaway, fit, size_pct, behind_text, fade, mute)` + los constructores PUROS del filtro
   FFmpeg. `core_overlays.construir_comando` gana `clips=None, fps=30.0` y los teje; SIN clips el
   comando es BYTE-IDENTICO (el golden de emojis/popups lo fija). `core_ass`/`caption` propagan.

2. **Solo `fit="cover"` en V1 (contain DIFERIDO, no es una omision accidental).** cover escala
   conservando aspecto (`scale ...:force_original_aspect_ratio=increase`) y recorta (`crop`) al
   area objetivo, sin deformar. `contain` (letterbox) se difiere a un PR posterior: el caso de uso
   V1 es b-roll a pantalla completa. fit distinto de cover -> ValueError de contrato.

3. **Audio: regla #19 es inviolable.** El clip se agrega como input `-i` propio (con `-stream_loop
   -1` si loop); su AUDIO nunca se mapea ni se mezcla. La salida mapea SOLO `[video_final]` + `0:a`
   (el audio original), sin `amix`/`amerge`/referencias a `N:a`. `mute=True` es obligatorio en V1.
   La evidencia lo verifica DURO: original vs salida identicos en codec/duracion/numero de paquetes.

4. **FFmpeg en un solo pase, sin congelar.** trim desde `source_start` por la ventana `t1-t0` ->
   normaliza (rebase de timestamps, `fps` de la base, `setsar=1`, `format=yuva420p`) -> cover ->
   fade alpha -> desplaza a `t0`. Overlay centrado con `eof_action=pass:repeatlast=0:enable=
   'between(t,t0,t1)'`: fuera de la ventana y cuando un clip `loop=false` corto termina, vuelve al
   VIDEO ORIGINAL (no congela el ultimo frame). `loop=true` usa `-stream_loop -1` (repite el clip
   corto hasta cubrir la ventana; la costura del loop la revisa K en el mp4 completo).

5. **Maximo UN clip pexels_video por render en V1.** Si `{stem}_popups.json` trae varias entradas
   source='pexels_video', se procesa deterministicamente la PRIMERA por orden del JSON; las demas
   se omiten con log ASCII. Las entradas PNG y Pexels-imagen se siguen procesando normal (capas
   aparte: `cve_popups` para imagen, `cve_clips` para video). Multi-clip DIFERIDO (PREGUNTAS #36).

6. **Contrato de errores POR CAPAS (corrige 'todo ValueError se propaga', que tumbaria el render
   por un typo del usuario).** El fetcher y el puente `resolver_cutaway_video_pexels` son HONESTOS:
   el ValueError de contrato (query vacia, t1<=t0, source_start<0, fit!=cover, size_pct/loop/mute
   invalidos) se PROPAGA. El adaptador de JSON manual `cve_clips` CAPTURA ese ValueError, imprime
   un mensaje accionable y OMITE solo esa entrada (no derriba el render). Los errores OPERATIVOS de
   Pexels (cero resultados, timeout, rate limit) omiten solo ese b-roll (fail-open). Los bugs
   (RuntimeError/TypeError/AssertionError) se PROPAGAN hasta arriba y nunca se convierten en [].

7. **Compatibilidad total.** source='pexels' sigue siendo imagen; source ausente/'local'/
   'biblioteca' sigue siendo PNG; renders sin Pexels no requieren API key ni tocan la red (import
   lazy del puente). El cutaway de imagen (D29) y los popups historicos quedan intactos.

**Requiere ojo de K (salida visual):** ver el MP4 de 6s COMPLETO (no solo los frames) y validar que
el clip se mueve/no se congela/no deforma, que los captions quedan legibles encima, que el audio
sigue siendo el de la persona, que empieza/termina en los tiempos correctos y que el clip
corresponde a la query. La costura del loop solo se juzga en el video completo. Evidencia:
`revision/broll-pexels-video-cutaway/` (README + gen_evidencia.py que se niega sin key +
ejemplo_popups.json); MP4/clip/frames NO commiteados.

## D32 - Editor de Paquete Alpha: backend solo-lectura, rutas confinadas, servido de binario confinado (refactor/studio-package-review-contract)

**Contexto:** el Editor de Paquete (S35) ya leia paquete.json + sidecars via `paquete_editor.py`,
pero (a) la logica HTTP vivia inline en `app.py` (ya un monolito de 569 lineas), (b) `video_url` se
construia a ciegas desde `clip["archivo"]` (nombre de fichero venido de JSON, sin validar) y (c) el
binario se servia por el mount estatico abierto `/output`, que expone TODO el arbol (paquete.json,
REPORTE.md, sidecars). Antes del cierre visual (PR B), el contrato debia quedar pequeno, seguro,
determinista y cubierto por tests.

**Decision:** endurecer el backend SIN cambio visual y SIN tocar motores.

1. **Extraccion de dominio, no migracion general.** Router propio `studio_packages.py` (APIRouter con
   `list_paquetes`, `get_paquete`, `get_paquete_video`, `get_paquete_reporte`); `paquete_editor.py`
   guarda la logica PURA (agregacion + validacion de rutas); `app.py` solo hace `include_router`. Sin
   ciclos (studio_packages -> paquete_editor -> auto_report). El resto de rutas FastAPI queda intacto.

2. **Path-safety como funciones puras.** `es_nombre_seguro` (rechaza vacio, '.', '..', separadores /
   o \\, unidad de Windows) + `resolver_hijo_seguro` (combina el basename con resolve() y rechaza el
   symlink que escapa del root) + `resolver_archivo_paquete`/`resolver_sidecar_seguro`. Los nombres de
   paquete.json y de sidecars NUNCA se confian: se validan antes de tocar disco.

3. **Servido de binario CONFINADO por DOS lados (seguridad, no cosmetico).** (a) El .mp4 de un clip
   ya no se referencia por `/output/paquetes/...` sino por el endpoint validado
   `/api/paquetes/{pkg}/video/{archivo}`, que solo entrega un basename seguro, existente y con sufijo
   `.mp4`; el REPORTE.md por `/api/paquetes/{pkg}/reporte`. (b) Ademas el mount estatico `/output` se
   subclasea (`_OutputSinPaquetes`): cualquier peticion a `/output/paquetes/**` devuelve 404, asi que
   ni siquiera por la ruta abierta se exponen `paquete.json`, `REPORTE.md` ni sidecars. El resto de
   `output/` (renders de Creador/Automatico/Submagic) se sigue sirviendo igual; la tarjeta de
   resultado del Modo Automatico se repunto a los endpoints validados para no romperse.

4. **Contrato fail-open controlado.** `video_url`/`video_disponible` reflejan si el MP4 existe (clip
   sin binario -> null/false, el resto del detalle sigue); `reporte_url` es null si falta REPORTE.md;
   sidecar QA/brain ausente o corrupto -> `[]`. Los errores de PROGRAMACION (RuntimeError/TypeError)
   se PROPAGAN: nada de `except Exception` que trague un bug. Campo `salud` aditivo en la lista.

5. **Solo-lectura, cero recalculo.** Estado y recomendacion salen de `auto_report` (fuente unica);
   markers traducen lo ya medido (tramos/QA/brain), descartando tiempos invalidos y fuera de rango.
   La entrada no se muta (el `qa` original no gana `alertas`). No se escribe, no se lanzan motores.

**Alcance cerrado, sin ojo de K:** PR A es plomeria/seguridad sin salida visual. 40 tests nuevos
(path-safety, endpoints via TestClient, confinamiento del video + del mount, fail-open, no-mutacion).
La salida visual y el veredicto de K son del PR B. Evidencia:
`revision/s35-editor-paquete-contract/README.md`.

**Contrato visual final (PR B, feat/studio-package-review-alpha):** cierre visual Alpha 0.1,
solo-lectura, sobre el contrato del PR A. Decisiones tomadas tras el checkpoint B4.5 (aprobado por K
con correcciones obligatorias, todas incorporadas):

1. **Preview vertical como elemento principal.** El clip 9:16 se muestra en una caja de
   `aspect-ratio:9/16` determinista (no depende de que el `<video>` cargue metadata), `object-fit:
   contain`, centrada, sticky en desktop, ~62-70vh de alto; un solo video cargado a la vez. El empty
   state (clip sin MP4) comparte esa huella y dice "Video no disponible", sin `<video src=null>`.
2. **Jerarquia fija:** video -> estado/score/duracion/razon -> alertas Caption QA -> calidad por
   tramos -> lista de marcadores -> timeline compacto -> recomendacion -> acciones. El timeline es
   una barra compacta de apoyo (mouse); el camino accesible es la LISTA de marcadores.
3. **Marcadores como lista clicable (nucleo), no editor pro.** `<button>` por marcador (tipo + tiempo
   + texto, rango en tramos), seek por click y por teclado (Enter/Espacio), simultaneos no se pisan,
   leyenda, fallback como lista sin video/duracion, sin division por cero. Sin drag/trim/zoom/multipista.
4. **Solo-lectura visible.** "Marcar como revisado en esta sesion" (localStorage, `aria-pressed`) con
   aviso "no se guarda — no modifica el paquete"; aprobar/rechazar persistente se difiere.
5. **Orden de paquetes por `meta.fecha` descendente** (fallback determinista por id) — el mas reciente
   primero. Tarjeta-boton accesible con CTA "Revisar paquete"; badges agrupados con conteo si hay muchos.
6. **Copy para testers y a11y minima.** "Sin elementos visuales adicionales"/"N elemento(s) visual(es)",
   "Copiar ubicacion", tooltip en Score IA, titulos a 2 lineas con `title`; `<button>` reales,
   `:focus-visible`, `aria-label`/`aria-current`, estados con texto (no solo color), sin quitar outline.
7. **Sin refactor general de `static/index.html`.** Solo se tocaron unidades S35; la extraccion a
   `s35.css`/`s35.js` se DIFIERE como deuda documentada (riesgo de romper otras pestanas > beneficio;
   el monolito no crecio de forma relevante). Sin escritura, sin motores, sin red.

Evidencia y como levantarlo: `revision/s35-editor-paquete/` (README + CHECKLIST_VISUAL + gen_fixture.py).
Pendiente: ojo visual final de K antes del merge (el agente NO mergea el PR B).
