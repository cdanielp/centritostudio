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

## D33 — S36-A: el SRT es un documento de CUES, no un transcript word-by-word (feat/s36-srt-import-contract)

Apertura de **S36 (SRT round-trip + composicion 9:16)**. Este primer bloque, **S36-A**, es
infraestructura pura: una capa SRT pequena, pura y reusable, **sin salida visual** y **sin tocar**
captions, render, FFmpeg ni la UI. Objetivo: base extremadamente confiable para que S36-B/C puedan
usar un `.srt` como fuente oficial de captions, conservar el texto corregido por el usuario y respetar
sus timestamps.

**Principios (vinculantes para S36-B/C):**

1. El texto y los limites de cue del SRT son **autoridad** (se conservan tal cual: acentos, ñ, emojis,
   `<i>`/`<script>` como texto literal, mayusculas, comillas, espacios internos).
2. Los tiempos canonicos se guardan en **milisegundos enteros** (nunca floats).
3. El parser **nunca inventa timing por palabra**: un SRT solo tiene timing a nivel de cue/frase.
4. El **orden fuente** se conserva; no se reordena por timestamp; `source_position` 0-based.
5. Los **overlaps se diagnostican** (warning), no se corrigen en silencio.
6. El **original nunca se sobreescribe** (normalize exige `--output` distinto; contrato no sobreescribe).
7. **Round-trip v1 es semantico, no byte-identico** (BOM/line-endings se normalizan; decimal -> coma).
8. La **alineacion palabra-por-palabra** pertenece a **S36-B**.
9. Los **templates 9:16** pertenecen a **S36-C**.
10. El SRT real del usuario es **evidencia local, nunca fixture versionada** (gitignoreado en `input/`).

**Contraste con el modelo actual (diagnostico):** hoy una palabra es
`{"w": texto, "s": segundos_float, "e": segundos_float, "prob": float}` (Whisper, `core.transcribe_video`)
y los grupos de caption se derivan de esas palabras. Un SRT **no** tiene timing ni confianza por palabra;
aporta **texto corregido + limites de frase + tiempos enteros**. Por eso repartir el tiempo del cue a
palabras exige un motor de alineacion (S36-B) y no puede hacerse en este PR sin fabricar datos.

**Arquitectura entregada:** `srt_types.py` (tipos/excepciones/limites/codigos), `srt_time.py`
(timestamps), `srt_parse.py` (decode UTF-8/BOM/cp1252 + parser de estado + `load_srt`),
`srt_validate.py` (validacion independiente), `srt_serialize.py` (serializacion + contrato JSON v1),
`srt_import.py` (**fachada publica**, unico punto de import) y `srt_tool.py` (CLI local:
validate/inspect/normalize/contract). Cero dependencias nuevas (solo stdlib). Todos los archivos de
produccion <=400 lineas; funciones <=50. Excepciones tipadas (`SrtError` base + `SrtDecodeError`/
`SrtParseError`/`SrtLimitError`); sin catch-all en la libreria.

**Evidencia:** 132 tests nuevos en `tests/test_srt_import.py` (sin red/GPU/FFmpeg). Smoke real
(`revision/s36-srt-import/smoke_srt_real.py` sobre `input/0717_corregido.srt`): `n_cues=1072`, ultimo
index `1072`, ultimo `start_ms=2473300`/`end_ms=2474600`, `0` errores, `0` warnings, round-trip
semantico PASS, original intacto (sha256 identico). README completo en `revision/s36-srt-import/`.
**S36 NO esta cerrada** (faltan integracion con captions, word alignment, upload Studio, rebase tras
cortes y templates 9:16 — ver ESTADO.md y PREGUNTAS.md).

## D34 - S37-A: brain senala, planner decide, auto orquesta (feat/s37-broll-planner)

**Contexto:** con el brain aportando senales (grupo, keyword, timestamp, emoji), el Modo
Automatico v2 necesita una capa PURA que decida ventanas de b-roll antes de conectar cualquier
resolver. S37-A entrega solo esa capa; no toca `brain.py` ni `auto.py`, no usa Pexels/FFmpeg/red,
no descarga assets y no cambia la salida visual.

**Decision:** separar responsabilidades en la cadena del Auto v2.

Principios vinculantes:

1. `brain.py` NO genera planes de b-roll: solo entrega senales editoriales.
2. El planner recibe `groups + brain + duration + config` y devuelve un `BrollPlan v1`.
3. El planner es PURO, determinista y sin red (misma entrada + config = mismo JSON semantico).
4. El planner solicita INTENCION (ventana + tipo + query + duracion deseada); NO selecciona assets reales.
5. Imagen es el default.
6. Video requiere senal textual EXPLICITA de movimiento/accion/proceso.
7. Maximo un video por clip en V1 (`max_video_windows` 0 o 1); el resto se degrada a imagen si cabe.
8. Hook protegido 3.0s desde el inicio del clip; el lead-in nunca entra al hook.
9. Densidad: target 27%, maximo duro 35% (nunca se supera).
10. Imagen 2.5-4.5s (preferred 3.5); video 3-6s (preferred 4.5).
11. `express` es el FX default del Auto v2; `pro` solo perfil viral fuerte; `premium` explicito.
12. `premium` reserva outro de 2.5s; `express`/`pro` no reservan outro.
13. El sidecar manual `{stem}_popups.json` JAMAS se sobreescribe.
14. `{stem}_broll_plan.json` es AUDITORIA, no el sidecar de render.
15. Errores por capas (D31): input superior invalido lanza; item malformado se rechaza y continua;
    bug de programacion se propaga (sin `except Exception: return empty`).
16. IDs de ventana deterministas (`broll-0001`...) tras ordenar por inicio.
17. Solo stdlib; sin dependencias nuevas. Cinco modulos <=400 lineas, funciones <=50.

**Arquitectura entregada:** `broll_plan_types.py` (tipos/errores/codigos/validacion de config),
`broll_plan_query.py` (normalizacion + query determinista + deteccion de movimiento),
`broll_plan_place.py` (colocacion temporal + greedy de cobertura), `broll_planner.py`
(orquestacion pura + `plan_broll`, fachada publica) y `broll_plan_io.py` (contrato JSON v1 +
escritura atomica del sidecar).

**Evidencia:** 161 tests nuevos en `tests/test_broll_planner.py` (sin red/GPU/FFmpeg/Pexels/keys/
archivos reales); total de la suite **915 passed, 1 skipped**. Smoke sintetico
(`revision/s37-broll-planner/smoke_broll_planner.py`): `signals=8`, `windows=2` (image 1, video 1),
`coverage=25.0%`, `overlaps=0`, determinista PASS, sidecar PASS. README completo en
`revision/s37-broll-planner/`.

**Track S37 (NO cerrada):** PR A (planner) MERGEADA (#11); **PR B** (auto-v2-render)
APROBADA tecnica y visualmente: **VEREDICTO VISUAL DE K: APROBADO**. PR #12 autorizado
para merge. **PR C** (Studio/toggle) PENDIENTE y NO iniciada. S37-A no modifico el output;
S37-B si cambia salida visual y ya completo su validacion. **S37 sigue ABIERTA** hasta
terminar S37-C (ver `revision/s37-auto-v2-render/CHECKLIST_VISUAL.md`).

### D34 — Addendum S37-B: decisiones #47 aplicadas al Auto v2 (feat/s37-auto-v2-render)

Vinculantes para el resolver/render del Modo Automatico v2:

1. **47a — video corto:** NUNCA loop automatico; si ningun candidato de Pexels cubre la
   duracion pedida -> fallback a IMAGEN (`video_no_cover_fallback_image`); fallos operativos
   de busqueda/descarga de video tambien caen a imagen con codigo propio; si la imagen de
   fallback tambien falla, la ventana se omite con ambos pasos registrados.
2. **47b — precedencia:** el sidecar manual GANA por conflicto temporal ([start, end); tocar
   borde no bloquea); la ventana auto bloqueada se omite ANTES de descargar
   (`manual_precedence`); el manual jamas se desplaza ni se modifica (hash intacto). Un clip
   manual ocupa el slot de video: la ventana auto de video se degrada a imagen.
3. **47c — merge:** fuentes SEPARADAS (`_popups.json` manual intocable, `_broll_plan.json`,
   `_popups.auto.json` solo con lo que llego al render, `_broll_resolved.json` auditoria);
   la combinacion manual+auto ocurre EN MEMORIA; no existe sidecar hibrido.
4. **47d — tolerancias A/V (compuertas DURAS, excepciones tipadas, nunca fail-open):**
   integridad = payload de audio identico por hash de paquetes (ffprobe data_hash sha256,
   fallback ADTS documentado); sync = start audio <=0.050s, duracion audio <=0.050s, delta
   inicial A/V <=0.120s, drift final <= max(0.120s, 2/fps_final).
5. **47e — FX:** un punch/flash/scanner que traslapa un cutaway se ELIMINA, no se desplaza
   (codigos `*_removed_cutaway`); el logo/outro se conserva; conflicto manual en zona de
   outro -> warning `premium_outro_manual_conflict`.
6. **47f — cache:** `cache_policy = existing_fetcher_cache` (la de broll_stock /
   broll_video_stock); sin cache paralela; sin keys/URLs firmadas en sidecars.
7. **Compatibilidad:** `ejecutar_auto` sin config = classic EXACTO (sin planner, sin Pexels,
   sin FX, sin sidecars S37); paquetes v2 con naming `{name}_v2_{fecha}` + fingerprint
   SHA256 de config; checkpoints v2 solo se reutilizan con fingerprint identico y A/V pass.

**Arquitectura entregada:** `auto_config.py`, `auto_v2.py`, `auto_broll.py`,
`auto_broll_io.py`, `auto_fx.py`, `auto_av.py` (todos <=400 lineas, cero dependencias
nuevas); `auto.py`/`auto_report.py` extendidos de forma aditiva; `broll_plan_io` con
temporal unico (unica modificacion autorizada a S37-A). **Evidencia:** 133 tests nuevos
(suite 1048 passed, 1 skipped), E2E sin red con render FFmpeg real, CFR 29.97 real, VFR
real (2 deltas de PTS distintos), demos sinteticos en output/revision-s37b/ (no
versionados). Hallazgo documentado: el punch-in (zoompan) exige input CFR; el pipeline
real lo garantiza via reframe.

**Cierre de revision visual (K, 2026-07-18):** **VEREDICTO VISUAL DE K: APROBADO.**
S37-B queda aprobada tecnica y visualmente y el PR #12 queda autorizado para merge.
Observaciones no bloqueantes: `cocina` puede detectarse falsamente como movimiento por
relacion morfologica con `cocinar`; y, a futuro, conviene limpiar queries como
`conectamos Ahora maquina tostado`. Ninguna bloquea S37-B ni inicia S37-C.

## D35 — S37-C: Studio configura, AutoConfig decide, auto orquesta y Editor lee

**Fecha:** 2026-07-18. **Rama:** `feat/s37-modo-automatico-studio`.

S37-C expone el pipeline ya aprobado sin reimplementarlo ni cambiar su resultado visual:

1. **Classic continúa como default.** La llamada histórica sin `mode` produce `config=None`; Auto v2 solo se activa explícitamente con `mode=v2`.
2. **Studio solo configura.** `studio_auto.py` valida modos/presets, construye `AutoConfig` y publica capabilities seguras. No usa red, reloj, rutas, render ni escritura.
3. **Protecciones fijas.** En v2 Studio fuerza `verify_av=True` y `manual_sidecars=True`; captions y reframe 9:16 están siempre activos. No se exponen parámetros avanzados del planner ni fingerprint.
4. **Un orquestador.** `jobs.run_auto` adapta progreso/resultado y pasa la config; `auto.ejecutar_auto` sigue siendo el único orquestador público. No se importa `auto_v2` desde jobs ni se reconstruye config allí.
5. **Preview honesto.** Antes del procesamiento solo existe un resumen de configuración. El plan temporal real se calcula por clip después del clipper y solo se muestra desde datos guardados.
6. **Editor read-only.** `paquete_editor.py` sanea resúmenes de b-roll/FX/A/V y lee el resolved confinado únicamente para crear markers de ventanas realmente renderizadas. No resuelve Pexels, no recalcula, no re-renderiza y no escribe.
7. **Sin sidecars crudos.** No hay endpoints de `broll_plan.json`, `popups.auto.json`, `broll_resolved.json`, `info.json` ni `paquete.json`; tampoco se publican hashes completos, URLs, assets, secretos o rutas absolutas.
8. **Gobernanza visual.** El PR queda abierto y NO se mergea aunque la validación técnica esté verde. S37 sigue ABIERTA hasta el veredicto visual APROBADO de K en desktop/móvil y el merge posterior.

Evidencia sintética y checklist: `revision/s37-modo-automatico-studio/`.

## D35 addendum — Veredicto visual de K: S37-C APROBADA — S37 COMPLETA

**Fecha:** 2026-07-18. **PR mergeado:** #13 (merge commit en main).

**VEREDICTO VISUAL DE K: APROBADO.** S37-C queda aprobada técnica y visualmente.

- S37-A: cerrada (PR #11 mergeado).
- S37-B: cerrada (PR #12 mergeado).
- S37-C: cerrada (PR #13 mergeado, veredicto visual de K APROBADO 2026-07-18).
- **S37 COMPLETA.**

Deudas declaradas fuera de alcance (no bloquean ninguna fase futura, no se resuelven en S37):
- falso positivo morfológico `cocina`/`cocinar` (Caption QA, deuda #48);
- limpieza futura de queries como `conectamos Ahora maquina tostado`;
- extracción del monolito `static/index.html` (deuda #38);
- aprobación/rechazo persistente en el Editor (deuda #37);
- re-render selectivo desde el Editor (deuda #37);
- SRT con captions word-by-word y soporte multi-video (S36-B/C, independiente de S37).

Auto clásico continúa como default. Auto v2 ya está disponible en Studio. El Editor muestra b-roll, FX y A/V en modo read-only.

## D36 — S36-B: Texto SRT autoritativo, timings reales, fallback por cue y round-trip

**Fecha:** 2026-07-18. **Rama:** `feat/s36-b-srt-caption-roundtrip`. **Sesión:** 38.

Conecta la capa SRT pura de S36-A con el pipeline de captions y el clipper, sin tocar los
motores aprobados de S37. Funcionalidad **opt-in**: sin `--srt` el comportamiento es
byte-idéntico al histórico.

1. **El texto del SRT es la fuente oficial (D36B-1).** Con `--srt`, el texto visible sale
   tal cual del SRT: no se sustituye por Whisper, no se corrige, no se cambian acentos ni
   puntuación, no lo toca Caption QA. Whisper (o un transcript existente) aporta ÚNICAMENTE
   timings por palabra.
2. **No se inventan timings (D36B-2).** Solo tres tipos: `exact_match`, `substitution_match`
   (1:1 entre anclas reales) y `cue_fallback`. Prohibido `duración/n_palabras`. Un token del
   SRT sin ancla real NO recibe timing fabricado.
3. **Alineación.** `srt_align.py` (puro): normaliza SOLO para comparar (NFKC + casefold +
   sin acentos + sin puntuación de borde; preserva números/emoji y SIEMPRE el token
   original). Particiona las timing words por punto medio dentro de la ventana de cada cue
   (disjunta, sin reusar una word dos veces) y alinea con edit-distance determinista
   (traceback estable). Complejidad O(n_tokens_cue · n_words_ventana), acotada; sin matriz
   global. Un cue es `word_aligned` solo si TODOS sus tokens anclan (cobertura 1.0,
   `min_coverage` por defecto 1.0); si no, `cue_fallback`.
4. **Fallback honesto (D36B-3).** El cue conserva su texto y sus start/end exactos y se
   pinta ESTÁTICO (un solo evento ASS, sin color/animación inline), nunca karaoke falso.
   Cambio mínimo y aditivo en `core_ass.build_ass`: los groups con
   `timing_mode="cue_fallback"` emiten un evento estático; los groups históricos (sin la
   clave) son byte-idénticos.
5. **Validación (D36B-4).** Errores estructurales del SRT abortan el render (no se toca el
   original); los warnings (cue fuera del video, etc.) se reportan y no abortan. Se valida
   contra la duración real del video.
6. **Caption QA (D36B-5).** Con `--srt`, Caption QA NO se aplica al texto oficial;
   `--caption-qa-mode auto_seguro` se RECHAZA con error claro (exit≠0). El modo alertas no
   modifica nada.
7. **Compatibilidad (D36B-6).** Sin `--srt`: CLI, batch, Auto clásico/v2, clipper, nombres
   de salida y sidecars idénticos. Con `--srt`: la salida lleva sufijo `_srt`
   (`{stem}_{style}_srt.mp4/.ass`) y se escribe `transcripts/{stem}_srt_alignment.json`.
8. **Batch (D36B-7).** `--srt` explícito solo con un video individual; carpeta + `--srt` se
   rechaza. El mapeo video↔SRT es S36-C.
9. **Round-trip del clipper (D36B-8/9).** Con `srt_document`, por cada clip: `slice_srt`
   recorta los cues al intervalo real `[clip.start, clip.end)` (semántica fin-exclusivo),
   los rebasa contra el `clip.start` REAL (con padding, no la primera palabra), reindexa
   desde 1, preserva líneas/texto, y guarda `transcripts/{clip_stem}.srt` +
   `_srt.json` + metadata saneada en `clips.json`. La fuente nunca se modifica; un fallo del
   SRT derivado no borra el MP4 ya cortado. Sin `srt_document`: comportamiento histórico
   exacto (no lee ni genera SRT).
10. **Auto/Studio (D36B-10).** No se conecta SRT con Auto v2 ni con Studio en esta sesión;
    `auto*.py`, `studio_*.py`, `app.py`, `jobs.py`, `static/index.html` quedan intactos.

Módulos nuevos (puros salvo el adaptador): `srt_align.py`, `srt_slice.py`, `srt_caption.py`.
Evidencia sintética y checklist visual: `revision/s36-b-srt-caption-roundtrip/`.

**Gobernanza.** PR abierto y NO mergeado: cambia el resultado visual de captions y requiere
veredicto visual de K. S36 sigue ABIERTA (S36-C pendiente).

### D36 addendum — Endurecimiento tras revisión técnica (2º commit del PR #14)

Se corrigen 5 bloqueantes técnicos detectados en la revisión, antes del veredicto visual:

1. **Flags no ignorados con `--srt`.** `_process_srt` recibe y usa `use_emojis`, `use_popups`,
   `fx_preset` y `qa_opts`. La ruta SRT reutiliza EXACTAMENTE los mismos motores downstream
   que la histórica (preset CVE, `cve_popups`/`cve_clips`, `assets_comfy`, FX,
   `burn_video`/`burn_video_with_emojis`) vía el helper único `_resolver_capas_y_quemar`.
   Ningún flag se acepta y luego se ignora sin mensaje.
2. **Preset CVE completo pero acotado.** `_aplicar_preset_srt` separa los groups por
   `timing_mode`, corre `cve.aplicar_preset` SOLO sobre los `word_aligned` y reinserta los
   `cue_fallback` intactos, preservando orden temporal e IDs deterministas. Un preset jamás
   convierte un fallback en word-by-word.
3. **`substitution_match` conservador.** Una sustitución solo ancla si (a) el cue tiene ≥1
   `exact_match` y (b) la similitud léxica (Levenshtein normalizado por longitud máxima sobre
   tokens normalizados) es ≥ `SUBSTITUTION_MIN_SIM` = **0.60**. Texto arbitrario de igual
   longitud (`gatos verdes corren` vs `lunes martes miércoles`) o un único token distinto ya
   NO alcanzan cobertura 1.0 → `cue_fallback`. El texto visible siempre es el del SRT.
4. **Timestamps reales sin modificar.** Se elimina todo desplazamiento: no hay `+1 ms`, no se
   mueve `start`, no se extiende `end`. Se preservan los ms exactos de la timing word. Se
   valida `end>start`, orden no decreciente y uso único; si el cue queda temporalmente
   inválido/no monótono → `cue_fallback` con razón `non_monotonic_timings`.
5. **Sin `sys.exit` en la API.** `_process_srt` propaga `SrtError` (error de usuario tipado);
   `main()` lo traduce a mensaje corto con basename y exit≠0. Los bugs no se tragan.

**Caption QA con `--srt`:** política cerrada — `--caption-qa` (cualquier modo) se RECHAZA con
`--srt` (Caption QA opera sobre el transcript de Whisper, no sobre el SRT autoritativo; no hay
auditor de SRT en S36-B). QA específico de SRT queda para S36-C.

**Naming:** el sufijo SRT es determinista e incluye las capas activas
(`{stem}{variante}_srt[_emojis][_popups][_fx-<preset>].mp4`), sin colisiones; los nombres sin
`--srt` no cambian.

**Sidecar:** añade `exact_matches`, `substitution_matches`, `rejected_substitutions` (agregado
y por cue) y `fallback_reason` por cue. Sin texto privado adicional en logs.

### D36 addendum — Veredicto visual de K: S36-B APROBADA — S36-B CERRADA

**Fecha:** 2026-07-18. **PR mergeado:** #14 (commits `e844ba2` + `3cf2cb8` + docs).

**VEREDICTO VISUAL DE K: APROBADO.** S36-B queda cerrada técnica y visualmente. Confirmado en
la revisión visual:

- El texto del SRT es la fuente oficial; Whisper solo aporta timings.
- `substitution_match` conservador aprobado (ancla exacta + similitud ≥0.60).
- Los timestamps reales no se modifican (sin `+1 ms`; inválido/no monótono → fallback).
- El cue fallback permanece estático (un evento, sin karaoke falso).
- Preset CVE + FX funcionan solo sobre los cues alineados; el fallback no se anima.
- Round-trip del clip aprobado (SRT rebasado contra `clip.start` real, arranca en t=0).
- Audio idéntico entre renders; SRT fuente intacto; sin datos privados.

**S36-B CERRADA. S36 sigue ABIERTA: S36-C pendiente** (upload/selección de SRT en Studio,
mapeo video↔SRT y batch, integración Auto v2, edición de SRT en UI, forced aligner si la
cobertura real no alcanza). S37 permanece COMPLETA. Avance 86/100 sin cambios.

## D37 — S36-C1: Studio administra SRT privados por asociación explícita video↔SRT

**Fecha:** 2026-07-18. **Sesión 39.** **Rama:** `feat/s36-c1-studio-srt-backend`. **PR abierto,
NO mergeado.** Solo backend/API; sin UI, sin render, sin Auto (S36-C2 conectará eso).

**Decisiones:**

1. **Un SRT seleccionado por video.** La asociación es EXPLÍCITA por el endpoint del video
   (`POST /api/videos/{name}/srt`). Sin autodiscovery, sin buscar por nombre parecido, sin
   asociar por orden de subida, sin aplicar un SRT a varios videos.
2. **Almacenamiento privado.** Los bytes originales válidos se guardan por hash en
   `transcripts/studio_srt/{video_stem}/{sha256_corto}.srt` (nunca montado, nunca servido por
   `/input`, `/output`, `/clips`, `/static` ni endpoint de descarga; `transcripts/` ya está
   gitignored). El manifiesto de asociación vive en `transcripts/{video_stem}_srt_selection.json`.
3. **Manifest v1 saneado.** `version, video{name,filename,duration_ms}, selection{selected,
   source_name, managed_file(basename), source_sha256, encoding}, summary{n_cues,start_ms,
   end_ms,n_errors,n_warnings}, diagnostics[{code,severity,cue_position,cue_index}], status`.
   NO incluye texto de cues, rutas absolutas, `message`, bytes ni tracebacks.
4. **Bytes originales preservados.** El SHA256 se calcula sobre los bytes recibidos; el archivo
   administrado son esos bytes tal cual (no se re-serializa el documento).
5. **Validación reutilizando S36-A** (`srt_import`: parseo tolerante + `validate_srt` contra la
   duración real del video). Warnings NO abortan; errors abortan; SRT sin cues utilizables aborta.
6. **Idempotencia y reemplazo.** Mismo video + mismo SHA ya seleccionado → no duplica, `ready`,
   respuesta determinista (200). SHA distinto → valida completo, escribe el nuevo archivo y solo
   entonces promueve el manifiesto (escritura atómica tmp+os.replace; el archivo administrado va
   primero, el manifiesto al final). La selección anterior no se borra.
7. **Delete solo desasocia.** Elimina el manifiesto activo (idempotente); no borra archivos
   administrados, ni el SRT original del usuario, ni captions/words/groups/clips.
8. **Errores tipados** (`StudioSrtNotFound/Invalid/TooLarge/Unsupported/StorageError`) → HTTP
   404/400/413/415/500; la extensión y el parser son la autoridad (no se confía en el MIME).
9. **Arquitectura:** `studio_srt.py` (dominio puro, cero FastAPI) + `studio_srt_routes.py`
   (APIRouter). `app.py` solo registra el router y delega su `_resolver_video_input` al helper
   puro compartido para no divergir del confinamiento.

**Auto/render/captions/UI NO se conectan aún.** S36-C2 pendiente. S36 sigue ABIERTA.

### D37 addendum — Endurecimiento del backend SRT (2º commit del PR #15, sesión 39)

Antes del merge se endureció el almacenamiento tras revisión técnica (5 bloqueantes + extras):

1. **Lectura acotada real.** El upload se lee por chunks de 64 KiB con límite DURO
   (`_read_upload_limited`); `file.size` solo sirve como rechazo temprano, nunca como única
   defensa. Acepta exactamente `MAX_SRT_BYTES`, rechaza `+1` con 413 antes de parsear/almacenar.
2. **Duración real, no cache obsoleto.** `{name}_info.json` solo se reutiliza si existe, es
   regular, su mtime ≥ mtime del video y `duration` es numérica, finita y > 0 (rechaza
   NaN/Infinity/0/negativo/bool/str). Si no, cae a `core.get_video_info`; si tampoco hay una
   duración válida → `StudioSrtStorageError` (500 genérico). Nunca se valida el SRT con `0`.
3. **Idempotencia que verifica el storage.** Mismo SHA solo es idempotente si el archivo
   administrado existe, es regular, está confinado en el dir del video y sus bytes + hash
   coinciden. Si el manifiesto coincide pero el archivo falta/está corrupto/apunta a un basename
   inseguro/hash distinto, se RECONSTRUYE atómicamente y se regenera el manifiesto (`repaired`,
   HTTP 200; el contenido seleccionado no cambió).
4. **Sin colisiones de hash.** El archivo administrado usa el **SHA256 completo** como basename
   (`{sha}.srt`): `hash(archivo) == manifest.source_sha256` SIEMPRE; se elimina la ambigüedad
   del prefijo corto. (Al mergearse el PR #15 no había históricos previos ⇒ sin migración.)
5. **Temporales únicos por operación.** `tempfile.mkstemp` en el mismo directorio (nunca
   `{pid}` compartido) + fsync + `os.replace` con reintento acotado ante `PermissionError`
   transitorio de Windows (last-writer-wins con archivos completos; nunca parciales ni `.tmp`).

Extras: el manifiesto público se **reconstruye por whitelist** (`sanitize_manifest`) y se valida
contra el contrato v1 (version, `video.name`, basenames, sha256 de 64 hex, tipos enteros,
diagnósticos de 4 claves); si viola el contrato o es ilegible → `StudioSrtStorageError` (500)
sin filtrar contenido. Los mensajes de error del router ya **no reflejan el `name`** del usuario
("Video no encontrado en input."), y el resolver rechaza NUL/control y captura `ValueError` de
`stat` (antes un NUL en `name` reventaba con 500). +49 tests nuevos (suite 1355, 1 warning).
La construcción/saneamiento del manifiesto se extrajo a `studio_srt_manifest.py` (whitelist)
para mantener cada módulo bajo el límite de 400 líneas (`studio_srt.py` 328, manifest 204).

**Cierre del saneamiento de VALORES (3º commit, `fix: cerrar saneamiento del manifiesto SRT`):**
la whitelist no solo filtra claves, ahora valida cada valor: basenames estrictos que rechazan
caracteres de control (C0/DEL) además de rutas; `video.filename` validado como basename seguro;
`encoding` restringido a la allowlist que el parser puede emitir (`utf-8`, `windows-1252`);
`diagnostics[].code` validado contra el conjunto de códigos `ERR_*/WARN_*` de S36-A (en sync por
introspección); números semánticos (`n_cues≥1`, `start_ms≥0`, `end_ms≥start_ms`, `n_errors==0`
en un manifiesto `ready`, `n_warnings≥0`, `duration_ms≥0`, `cue_position≥0`, `cue_index≥1`);
y `status` debe ser exactamente `ready`. Cualquier violación → 500 genérico sin reflejar el valor
manipulado. +30 tests (dominio + API contra reflexión de valores). Suite 1385, 1 warning.

### D37 addendum — Cierre del contrato del manifiesto SRT (S36-C1 CERRADA, sesión 40)

**El PR #15 quedó mergeado en main (`937c81e`); S36-C1 está CERRADA.** El backend (dominio +
router + endurecimiento + saneamiento de valores) dejó de ser "solo en PR". Dos hotfixes
posteriores cerraron invariantes del manifiesto **sin abrir S36-C2** ni tocar la superficie
visual/render/Auto:

- **S36-C1.1 (PR #16, mergeado `46d24ec`) — invariantes de `sanitize_manifest`.** El saneamiento
  por whitelist garantiza que cualquier manifiesto leído de disco que viole el contrato v1
  (rango degenerado, tipos, códigos, status) produce `ValueError` → 500 genérico sin filtrar el
  valor manipulado. CERRADA.

- **S36-C1.2 (esta tarea) — rango temporal REAL del summary.** `build_manifest` calculaba el
  rango con `cues[0].start_ms` / `cues[-1].end_ms` (primer y último cue en orden fuente). Con un
  SRT **válido pero no monótono** —el warning `time_not_monotonic` NO aborta la asociación— eso
  daba un rango degenerado: p.ej. cue1 1000–2000, cue2 0–1000 ⇒ `start_ms=1000, end_ms=1000`.
  El POST devolvía 201 y persistía ese manifiesto, pero el GET posterior lo saneaba con
  `_clean_summary` (que exige `end_ms > start_ms`) → `ValueError` → **500**. **Fix:** el rango
  usa `min(start)/max(end)` sobre TODOS los cues (garantiza `start ≤ end` y refleja el tramo real
  del SRT); el `else 0` para 0 cues es defensivo (el parser ya rechaza SRT sin cues, pero
  `build_manifest` es puro y `min([])` reventaría). **No se relajó `sanitize_manifest`**: sigue
  rechazando rangos degenerados; el fix corrige el productor, no el validador. +2 tests (unit de
  `build_manifest` no monótono + E2E POST→GET→re-upload con bytes/SHA idénticos). CERRADA.

## D38 — Studio renderiza una seleccion SRT explicita mediante `caption_source=srt` (S36-C2A1)

Conecta la asociacion privada video<->SRT de S36-C1 con el **render normal** de Studio, sin UI
nueva, sin Auto v2 y sin tocar el clipper. Es la primera mitad de S36-C2A (la segunda, C2A2, cubre
Auto v2 + clipper + SRT derivado por clip + checkpoints, y NO se inicia aqui).

**Contrato (opt-in explicito):** `POST /api/videos/{name}/render` gana `caption_source` con
allowlist `transcript` (default) | `srt`. La peticion historica sin el parametro sigue EXACTA la
ruta transcript (byte-identica): mismos groups.json, args, kwargs, naming, ASS/MP4, Caption QA,
agrupamiento, enfasis, emojis y presets. La ruta transcript **no lee el manifiesto SRT, no importa
el runtime y no consulta la seleccion** (fijado por import-spy).

**Ruta SRT (`caption_source=srt`):**
- El **texto del SRT es la fuente oficial** (S36-B); las words de Whisper **solo aportan timings**;
  no se inventan timings. Cues `word_aligned` se animan word-by-word; `cue_fallback` quedan
  **estaticos** (`timing_mode="cue_fallback"`, D36B-3).
- **Asociacion explicita** obligatoria (sin autodiscovery, sin buscar `.srt` en input/, sin primer
  `.srt`, sin usar el archivo privado). Sin seleccion -> 400; nunca cae al transcript en silencio.
- **Rechaza con 400** las combinaciones incompatibles: `caption_qa` (el QA no puede alterar el texto
  oficial), `words_per_group` (los cues definen el agrupamiento) y `use_emphasis` (el brain del
  transcript no se aplica por indice a cues SRT sin contrato). Permitidos: `style`, `pop`, `preset`,
  `intensidad`, `use_emojis`. El **preset CVE anima SOLO los cues alineados**.
- Output con sufijo `_srt` (no pisa historicos) + **sidecar de alineacion privado**
  (`transcripts/{name}_srt_alignment.json`). El resultado del job lleva un **resumen publico
  saneado** (source/sha/sidecar/conteos/ratios): sin cues, sin texto, sin rutas.

**Runtime privado (`studio_srt_runtime.py`, capa PURA):** `resolve_selected_srt` lee el manifiesto
saneado, exige `managed_file == {sha}.srt`, **confina** el archivo (resolve+relative_to) y verifica
su **hash real** (no confia solo en el manifiesto); no repara durante el render (la reparacion es del
contrato C1). `verify_runtime_integrity` revalida al iniciar el worker (borrado/manipulacion entre
endpoint y worker -> job en error saneado, SIN fallback). `prepare_selected_srt_groups` carga las
words (solo timings), delega en `srt_caption.preparar_desde_srt` (no duplica parser/alineador/
validador), escribe el sidecar y valida `word_aligned + cue_fallback == n_cues`. Errores tipados:
`StudioSrtRuntimeError`/`StudioSrtSelectionMissing`/`StudioSrtTimingMissing`/`StudioSrtIntegrityError`
(heredan de `StudioSrtError`/`StudioSrtStorageError`); app traduce seleccion/timings/contrato -> 400,
integridad/storage -> 500 generico.

**Helpers reutilizables (`srt_render.py`):** `apply_preset_to_srt_groups` (preset solo en alineados,
IDs deterministas, fail-open) + naming `_srt`. `caption.py` **delega** sus helpers historicos aqui
(fuente unica CLI<->Studio); la salida de la CLI `--srt` no cambia. `jobs_render.run_render` conserva
su firma publica (+ `*, srt_selection=None`) y hace split interno `_run_render_transcript` (verbatim)
/ `_run_render_srt`.

**Pendientes:** Auto v2 y clipper (C2A2), UI de seleccion (C2B), forced aligner si la cobertura real
no alcanza (no se activa automaticamente; solo se registra el numero). **El merge requiere veredicto
visual de K** (este PR modifica salida de video cuando `caption_source=srt`). Evidencia sintetica
(FFmpeg real, offline) en `revision/s36-c2a1-studio-srt-render/`; checkpoint privado real PENDIENTE
(no existe asociacion explicita del usuario).

### D38 addendum — Identidad video↔SRT: `manifest.video.filename` es autoritativo (P2, PR #18)

Corrige un P2 detectado en revisión: la ruta SRT resolvía el video con el resolver genérico
`_resolver_video_input(name)`, que busca por stem y **prioriza `.mp4`**. Una selección asociada y
validada contra `demo.mov` podía renderizarse sobre un `demo.mp4` aparecido después (mismo stem).

**Invariante:** para `caption_source=srt`, el video se identifica por el **filename EXACTO** del
manifiesto (`manifest.video.filename`), nunca por stem ni por prioridad de extensión. El stem por sí
solo NO identifica el video. No hay búsqueda por extensiones, glob, autodiscovery ni primer
coincidente; nunca se cruza `.mov`↔`.mp4`. Si el archivo exacto no está disponible, el render se
**bloquea** (no cae a otra extensión ni al transcript).

**Runtime:** `SelectedSrtRuntime` gana `video_filename` (del manifiesto saneado). `resolve_selected_video(runtime, *, input_dir)` construye sólo `input_dir/filename`, confina (resolve+relative_to) y
exige archivo regular; filename inconsistente con el manifiesto → `StudioSrtIntegrityError` (500),
archivo exacto ausente/no confinado → `StudioSrtSelectedVideoMissing` (409). El worker revalida con
`verify_selected_video_match(runtime, video_path)` (nombre+stem+extensión+regular) **antes** de leer
video info / alinear / generar ASS / escribir output; mismatch → job error saneado, sin ASS/MP4/
sidecar, sin ruta, sin fallback. **La ruta transcript histórica no cambia** (sigue usando
`_resolver_video_input` en Auto y demás endpoints, intactos).

**HTTP:** sin selección → 400; **archivo exacto ausente → 409** ("El video asociado al SRT ya no está
disponible."); manifiesto/storage corrupto → 500. Ningún mensaje refleja name/filename/extensión/ruta.
Comentario P2 de PR #18 resuelto. +20 tests (runtime/endpoint/worker) + E2E: MOV asociado (4s) +
decoy MP4 (2s) → el render usa el MOV (4s), nunca el decoy. Sigue requiriendo veredicto visual de K.

### D38 addendum — Procedencia de timings: `{stem}_words.json` ligado al video EXACTO (P2, PR #18)

Cierra un segundo P2 de identidad: el video exacto ya se resolvía por `manifest.video.filename`,
pero `{stem}_words.json` era **stem-only**. Con `demo.mov` seleccionado y un `demo.mp4` del mismo
stem transcrito, el render alineaba el texto oficial del MOV contra timings del MP4 (subtítulos
mal-timed silenciosos). El `cue_fallback` NO es garantía suficiente (mismo contenido con timings
desplazados sí alinea).

**Invariante:** el video, el SRT y las words comparten la MISMA identidad. `{stem}_words.json`
declara `source_video` = `{version:1, filename exacto, size_bytes, mtime_ns}` del video del que
salieron los timings. Módulo puro nuevo `transcript_provenance.py` (`build_video_provenance` /
`attach_video_provenance` / `validate_video_provenance`): int estricto (bool no cuenta), basename
seguro, extensión .mp4/.mov, filename == esperado, size+mtime == `stat()` real; nunca refleja
valores manipulados ni rutas.

**Producción:** `jobs.run_transcribe` adjunta `source_video` del video EXACTO recibido (sin tocar
words/language/timings/groups). `POST /transcribe?caption_source=srt` transcribe el video EXACTO
asociado (por `manifest.video.filename`); sin selección→400, video ausente→409, storage corrupto→500;
la ruta transcript histórica no cambia. El render SRT valida la procedencia en el ENDPOINT
(`verify_timing_provenance`): words legacy (sin `source_video`), de otro archivo/versión, con
size/mtime distintos o corruptas → **409** ("Los timings no corresponden al video asociado al SRT.
Transcribe nuevamente el video asociado.") sin thread/job/ASS/MP4/sidecar/fallback. El WORKER
revalida la procedencia (TOCTOU) antes de FFmpeg; mismatch → job error saneado, sin fallback.
Error tipado `StudioSrtTimingSourceMismatch` (endpoint→409, worker→job error), NO hereda de
StudioSrtStorageError (no dispara reparación ni retranscripción automática dentro del render).

**Legacy:** los `{stem}_words.json` históricos sin `source_video` los sigue aceptando la ruta
transcript, pero el render SRT los rechaza con 409 (retranscribir el video asociado). No se migran
ni se adivina la procedencia. No rompe una feature mergeada porque S36-C2A1 sigue en PR. +50 tests
(procedencia + transcribe API + run_transcribe + render endpoint + worker TOCTOU) + E2E: words de
`demo.mp4` → render rechazado; tras transcribir el MOV → render usa el MOV (4s). Comentario P2 de
Codex resuelto (la respuesta anterior de "follow-up" queda superada).

### D38 addendum — Aislamiento de artefactos SRT + reconfinamiento TOCTOU (P2-A/P2-B, PR #18)

Cierra dos P2 de Codex sobre HEAD 77a0662.

**P2-A — aislamiento de artefactos SRT.** Un `transcribe?caption_source=srt` del video seleccionado
`demo.mov` NO puede sobrescribir los artefactos historicos stem-only (`transcripts/demo_words.json`
/`demo_groups.json`), que el render transcript default del `demo.mp4` sigue consumiendo. Los timings
SRT viven ahora en un **namespace privado por filename EXACTO**:
`transcripts/studio_srt_timings/{stem}/{sha256(filename)}/words.json` (+`groups.json`). Un `.mp4` y un
`.mov` con el mismo stem dan directorios DISTINTOS. `transcript_provenance.resolve_srt_timing_artifacts`
valida stem/filename (basename seguro, ext, `stem==video_stem`) y confina el namespace. `run_transcribe`
gana `srt_artifact_key`/`selected_video_binding` keyword-only: sin key = ruta historica EXACTA; con key
= namespace privado (escritura de ambos JSON via temporal+replace, nunca uno nuevo con otro viejo). El
render SRT (endpoint + worker) usa SOLO el words/groups privado (emojis incluidos); NUNCA los stem-root
historicos. Words legacy stem-root: transcript las acepta; render SRT las ignora (falta el exacto -> 409
si hay historico, 400 si no hay ningun timing).

**P2-B — reconfinamiento del video en el worker.** El endpoint confinaba el video pero el worker solo
revalidaba nombre/stem/ext/is_file (seguia symlinks sin repetir `resolve()+relative_to`). Nuevo
`SelectedVideoBinding` (frozen, interno): captura `path`, `input_root_resolved`, `resolved_target`
(resolve strict), `size_bytes`, `mtime_ns` en el endpoint. `bind_selected_video` lo crea; el worker de
render y de transcribe revalidan con `verify_selected_video_binding` ANTES de FFmpeg/Whisper:
re-resuelve strict, exige `relative_to(input_root)`, `target==resolved_target`, size y mtime del enlace.
Bloquea retarget de symlink (dentro o fuera de input/), reemplazo del archivo, cambio de ruta/extension
y borrado -> job error saneado, sin output/sidecar/fallback. Mismo binding valida el TOCTOU de la
transcripcion SRT (Whisper no corre si el video cambio).

+~70 tests (namespace, no-envenenamiento, binding, symlink/retarget/reemplazo, TOCTOU render y transcribe).
Ruta transcript historica intacta (byte-identica). E2E: transcript MP4 historico intacto tras transcribe
SRT del MOV; render SRT del MOV usa su namespace; TOCTOU (reemplazo) aborta. Ambos comentarios P2
resueltos.


## D39 — S36-C2C: cierre E2E del flujo SRT, manifiesto final saneado y decision retry-vs-resume

Cierra S36-C2 (y con ella S36): el flujo SRT completo queda verificado end-to-end sin nuevas
superficies de motor. NO agrega features; consolida el pipeline ya construido en C2A1/C2A2/C2B con
un manifiesto publico estable, robustez de checkpoint y documentacion de cierre.

**Manifiesto FINAL saneado del run SRT.** Nuevo modulo PURO `auto_srt_manifest.py`: reconstruye por
whitelist el resumen publico de un run `caption_source=srt` a partir de la lista de clips que
devuelve `ejecutar_auto`. Forma v1:
`{version, run_id, caption_source:"srt", source:{video_filename, srt_selected}, clips:[{clip_id,
status(done|error), output, duration_ms, caption_coverage, fallback_ratio}], summary:{total, done,
error}}`. Se escribe (atomico) en `{paquete}/srt_run_manifest.json` solo para runs SRT. Invariantes:
NUNCA rutas absolutas, texto de cues ni hashes; `clip_id`/`output`/`video_filename` son basenames
seguros (rechaza dot-segments y traversal con `AutoSrtManifestError`); ratios clampados a [0,1];
un clip en `error` NUNCA expone `output` (no hay MP4 publicable). `fallback_ratio` = fraccion de cues
caidos a `cue_fallback` (sin karaoke real). 34 tests unitarios.

**Robustez de checkpoint.** El lector de checkpoint (`_cargar_checkpoint`) ahora tolera un sidecar
`{clip}.info.json` corrupto/ilegible: se trata como inexistente y se re-renderiza, en vez de reventar
el run. Un artefacto de salida faltante (MP4 borrado) tambien fuerza re-render en el resume.

**Decision retry dedicado vs resume (formal).** NO se implementa un endpoint dedicado
`POST /api/auto/{run_id}/clips/{clip_id}/retry` en v1. El resume EXISTENTE cubre el caso: un run
interrumpido (paquete sin `paquete.json`) se REANUDA en el siguiente `ejecutar_auto` con el mismo
video/config (mismo `config_fingerprint`); cada clip con checkpoint valido (sidecar + MP4 presente)
se conserva y SOLO los faltantes/fallidos se re-renderizan. Un clip fallido escribe sidecar
`status="error"` sin MP4 -> en el resume su `output` no existe -> se re-renderiza. La UI de C2B expone
"Reanudar clips fallidos" sobre este mismo mecanismo. Un endpoint dedicado exigiria un registro
persistente run->video/config (estado nuevo, superficie de API nueva) sin beneficio funcional para v1;
se DIFIERE explicitamente a post-v1 y deja de ser ambiguo.

**E2E real (FFmpeg).** `revision/s36-c2c/smoke_srt_e2e_batch.py`: batch de 3 clips reales 1080x1920
audio+video con captions oficiales del SRT; MP4 y MOV con el mismo stem NO se cruzan (el run usa el
`.mov` asociado, nunca el decoy `.mp4`); manifiesto saneado validado; fallo parcial (clip 2) ->
done=2/error=1 sin `output`; resume -> reanuda el MISMO paquete y recupera solo el fallido -> done=3.
Evidencia audiovisual en `output/revision-s36-c2c/` (gitignored). Escenarios restantes (cue sin words,
sustitucion/fallback, timings stale, video reemplazado TOCTOU, dos runs sin colision) cubiertos por
tests unitarios/integracion existentes (`test_srt_align`, `test_studio_srt_runtime`,
`test_auto_srt_artifacts`, `test_auto_srt_e2e`, `test_auto_srt_manifest`).

**S36 CERRADA:** C2A1 (PR #18), C2A2 (PR #20), C2B (PR #21) mergeadas con veredicto visual de K;
C2C consolida el cierre. Cero P1/P2 abiertos. Forced aligner sigue diferido (la cobertura real solo
se registra, no se activa automaticamente).
