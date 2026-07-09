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
