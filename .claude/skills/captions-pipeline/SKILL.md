# Skill: Centrito Studio — Pipeline de Captions

## Cuando usar esta skill
- Agregar captions animados a un video (CLI o UI web)
- Diagnosticar errores de transcripción, ASS, o FFmpeg
- Agregar un nuevo estilo visual
- Operar o extender la UI web (FastAPI + HTML)
- Editar una transcripción antes de renderizar

## Arquitectura v2.0 (2026-07-08)

```
core.py           Funciones puras (import desde caption.py y app.py)
caption.py        CLI — importa core.py
app.py            FastAPI server puerto 8787
static/index.html UI web completa (vanilla JS, CSS inline)
arranque.bat      Doble clic → server + browser
vocabulario.txt   30+ términos técnicos como initial_prompt para Whisper
styles.py         4 estilos: hormozi, karaoke, bounce, pms
models/medium/    Whisper medium descargado localmente (sin symlinks)
```

## Arranque del Studio
```bat
arranque.bat   ← doble clic
# o manualmente:
$env:PYTHONIOENCODING="utf-8"
$env:HF_HUB_DISABLE_SYMLINKS_WARNING="1"
.\venv\Scripts\python -m uvicorn app:app --host 0.0.0.0 --port 8787
```

## API endpoints principales

```
GET  /api/videos                      → lista de videos con estado
POST /api/videos/upload               → subir .mp4
POST /api/videos/{name}/transcribe    → iniciar transcripción (background)
GET  /api/jobs/{job_id}               → polling de estado del job
GET  /api/videos/{name}/transcript    → obtener grupos editables
PUT  /api/videos/{name}/transcript    → guardar grupos editados
POST /api/videos/{name}/render        → iniciar render (background)
```

## CLI (sin UI)
```powershell
$env:PYTHONIOENCODING="utf-8"; $env:HF_HUB_DISABLE_SYMLINKS_WARNING="1"
.\venv\Scripts\python caption.py input/video.mp4 --style hormozi --lang es
.\venv\Scripts\python caption.py input/ --style karaoke --lang es   # batch
```

## Funciones clave de core.py

| Función | Descripción |
|---------|-------------|
| `detect_device()` | → (device, compute_type) |
| `resolve_model(arg)` | → (path, label). "auto" usa medium local si existe |
| `get_video_info(path)` | → dict con width, height, duration, mean_volume |
| `transcribe_video(path, lang, ...)` | → {"words": [...], "language": str} |
| `group_words(words, ...)` | → lista de Groups con timestamps |
| `rebalance_timestamps(group)` | Re-distribuye timestamps tras editar texto |
| `build_ass(groups, w, h, style, out)` | Genera .ass con animaciones word-by-word |
| `burn_video(input, ass, output)` | FFmpeg: quema .ass → .mp4 |
| `extract_thumb(video, out)` | Frame @1s, escala a 200px ancho |

## Formato de Group (JSON)
```json
{
  "id": 0,
  "start": 1.22,
  "end": 3.45,
  "text": "Fui a Tacos Juan",
  "edited": false,
  "words": [
    {"text": "Fui", "start": 1.22, "end": 1.56, "line_idx": 0},
    {"text": "a", "start": 1.56, "end": 1.72, "line_idx": 0},
    {"text": "Tacos", "start": 1.72, "end": 2.04, "line_idx": 0},
    {"text": "Juan", "start": 2.04, "end": 2.22, "line_idx": 1}
  ]
}
```

## Mejoras de transcripción activas
- `vocabulario.txt` → `initial_prompt`: "ComfyUI" en vez de "confiwai"
- `condition_on_previous_text=False`: evita alucinaciones en clips largos
- `beam_size=5`: más preciso que default (beam=1)
- `vad_filter=True` con `min_silence_duration_ms=300`: filtra silencio
- Agrupación por pausas > 0.4s y puntuación final (`.!?…`)
- Anti-huérfano: último grupo de 1 sola palabra se fusiona con el anterior

## Colores ASS (referencia rápida)
Formato `&HAABBGGRR` (alpha, blue, green, red — NO es RGB):
- Blanco: `&H00FFFFFF` | Amarillo: `&H0000FFFF` | Cian: `&H00FFFF00`
- Naranja: `&H000080FF` | Morado #7C3AED: `&H00ED3A7C`
Conversor: RGB(R,G,B) → `&H00` + hex(B) + hex(G) + hex(R)

## Escala de fuente (consistencia entre resoluciones)
```python
ref_height = 1920 if video_height >= video_width else 1080
dim_scale  = max(video_height / ref_height, 0.40)
font_size  = style.font_size * dim_scale
# → 1056x1920 y 1080x1920 dan dim_scale=1.0 → fuente idéntica
```

## Diagnostico de problemas

### UI no carga
- Verificar que arranque.bat se ejecutó
- Puerto 8787 libre: `netstat -an | findstr 8787`

### "confiwai" u otro nombre mal transcrito
- Agregar el término correcto a `vocabulario.txt`
- El initial_prompt se carga automáticamente en cada transcripción

### Texto demasiado grande / pequeño
- Ajustar `font_size` en `styles.py` para ese estilo
- `dim_scale` se aplica automáticamente a la resolución

### Video sin audio detectado (mean_volume < -40 dB)
- La UI muestra advertencia y bloquea transcripción
- En CLI: Whisper puede transcribir basura; usar `--vad-filter` (ya activo)

### FFmpeg error con rutas Windows
- `_ffmpeg_ass_path()` en core.py maneja escape del colon
- Si falla: verificar que el output/ está en el mismo disco que el proyecto
