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
  Implementado en s28C BLOQUE 1.
