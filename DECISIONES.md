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

### python-dotenv para carga del .env

Se elige `python-dotenv` sobre manejo manual de `.env` porque:
- Es el estándar de facto, mínimo peso
- `load_dotenv()` es no-destructiva (no pisa variables ya seteadas)
- Fall-through con try/except ImportError: si no está instalado, el sistema sigue funcionando
  vía `os.environ` directa (útil en CI/CD donde las vars vienen del entorno del runner)
