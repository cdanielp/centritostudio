---
name: centrito
description: Skill principal de Centrito Studio. Qué es el proyecto, comandos frecuentes, arquitectura de dos motores, dónde vive cada cosa. Activar al iniciar cualquier sesión de trabajo en este proyecto.
---

# Centrito Studio — Skill principal

## Qué es esto

Suite local de producción de video con IA para Prompt Models Studio (PMS). Corre en Windows 11 con RTX 5070 Ti. Convierte videos de clase/reel en contenido viral con captions animados word-by-word, similar a Captions AI pero completamente local y controlable.

## Comandos frecuentes

```powershell
# Setup de sesión (siempre primero)
$env:PYTHONIOENCODING="utf-8"; $env:HF_HUB_DISABLE_SYMLINKS_WARNING="1"

# Smoke test (regla #1 de cada sesión)
.\venv\Scripts\python caption.py input\tacosjuan.mp4 --style hormozi --lang es --out-stem _smoke
del output\_smoke* 2>$null

# Un video
.\venv\Scripts\python caption.py input\video.mp4 --style hormozi --lang es

# Batch
.\venv\Scripts\python caption.py input\ --style karaoke

# Studio web (puerto 8787)
arranque.bat

# Análisis de calidad
check.bat                # ruff + tests (debe ser 100% verde)
check.bat full           # agrega smoke render con GPU

# Extraer frame para verificar
ffmpeg -y -i output\video_estilo.mp4 -ss 5 -vframes 1 revision\check.png

# Clipper viral (F4 — requiere transcript previo)
.\venv\Scripts\python caption.py input\video.mp4 --clips ambos
# Clips en output\clips\  |  Transcripts re-basados en transcripts\
# SCORE_MIN=60  MAX_CLIPS=3  tipos: corto(20-40s) largo(55-100s)
```

## Arquitectura de dos motores

```
video.mp4 → Whisper (GPU) → words.json → Motor A o Motor B → output.mp4
```

**Motor A — ASS + FFmpeg** (captions, depurador, clipper — el motor principal)
- `core.py`: todas las funciones puras del pipeline
- `caption.py`: CLI que consume core.py
- `app.py` + `static/index.html`: Studio web en FastAPI puerto 8787
- Estilos: hormozi, karaoke, bounce, pms (definidos en styles.py)

**Motor B — HyperFrames** (motion graphics premium — Fase 6)
- `motion/`: workspace HyperFrames
- Plantillas: centrito-kinetic, centrito-promo
- `motion/render.py`: inyección de props y llamada a npx hyperframes render

**Cerebro LLM** (`brain.py` — Fase 2+)
- Provider intercambiable via LLM_PROVIDER env var (deepseek, anthropic, ollama, mock)
- `analizar_grupos()` marca keywords y emojis por grupo
- Los emojis se guardan en brain.json pero se renderizan hasta Fase 5

## Dónde vive cada cosa

```
caption.py          CLI principal (--style, --clips, --depurar)
core.py             Toda la lógica del pipeline (ÚNICA fuente)
styles.py           4 estilos ASS
brain.py            Cerebro LLM (Fase 2+) — chat_json alias publico
clipper.py          Clipper viral F4: segmenta, puntua, selecciona, corta SIN captions
clipper_brain.py    Etapas LLM del clipper: segmentar_transcript + puntuar_candidatos
depurador.py        Depurador de silencios/muletillas (modos seguro/agresivo)
reframe.py          Reframe 16:9->9:16 con face tracking (F4.1) — CLI independiente
reframe_track.py    Matematicas puras del tracker (EMA adaptativo, deadzone, crops)
reframe_detect.py   Deteccion de cara con MediaPipe Tasks API (I/O video, OpenCV)
app.py              FastAPI server (puerto 8787)
static/index.html   UI del Studio (1 archivo, JS vanilla)
arranque.bat        Doble-click para iniciar el Studio
check.bat           Verificación completa del proyecto
vocabulario.txt     initial_prompt para Whisper (corrige "confiwai" etc.)
pytest.ini          testpaths=tests (excluye referencias/)
ruff.toml           Lint: complejidad ≤12, linea ≤100, bugbear

input/              Videos de entrada
output/             Videos con captions quemados + .ass
output/clips/       Clips virales MP4 cortados (F4) + {stem}_clips.json
transcripts/        {video}_words.json, {video}_groups.json, {video}.brain.json
                    {clip}_words.json y _groups.json re-basados a t=0 (F4)
                    {clip}_turnos.json — turnos multi-cara para reframe (F4.1)
thumbs/             Miniaturas para la UI + thumbnails de caras (reframe)
models/medium/      Modelo Whisper local (symlinks=False)
models/blaze_face_short_range.tflite   Detector MediaPipe activo (F4.1)
models/blaze_face_full_range.tflite    Detector alternativo (disponible, no activo)
revision/           Evidencia visual por fase
revision/fase-4.1/  CSVs de trayectoria + frames + decisiones + REFRAME_REPORT.md
references/         Repos clonados solo para estudio (NO tocar)
```

## Comandos F4.1 — Reframe vertical

```powershell
# Reframe de un clip (single-face, sin turnos)
.\venv\Scripts\python reframe.py output\clips\clip.mp4 --tray-dir revision\fase-4.1

# Con turnos multi-cara (requiere transcripts\{stem}_turnos.json)
.\venv\Scripts\python reframe.py output\clips\clip.mp4 --turnos transcripts\clip_turnos.json

# Con punch-ins en keywords (opt-in)
.\venv\Scripts\python reframe.py output\clips\clip.mp4 --punch-in
```

## Comandos F4.2-LITE — Layout stack (CERRADA)

```powershell
# Stack N=2 o N=3 personas (toma fija, sin turnos, sin EMA)
.\venv\Scripts\python reframe.py input\clip.mp4 --layout stack

# Primero verificar precondicion de cortes (fail-open, no bloquea)
# WARNING emitido si _contar_cortes_escena devuelve > N_CORTES_WARN=2
```

## Contratos F4.1/F4.2-LITE — reframe_track.py (math puro)

```python
# Alpha EMA adaptativo (D5): regimen lento/rapido segun error camara->target
ALPHA_BASE_LENTO  = 0.08   # tau ~0.41s @ 30fps
ALPHA_BASE_RAPIDO = 0.28   # tau ~0.11s @ 30fps
RAMP_LENTO_FACTOR = 1.0    # umbral_lento  = dz_half * 1.0
RAMP_RAPIDO_FACTOR = 3.0   # umbral_rapido = dz_half * 3.0
N_CORTES_WARN = 2           # en reframe.py (no en reframe_track)

calcular_alpha_adaptativo(error_px, deadzone_w, fps) -> float
ema_smooth_adaptativo(positions, fps, deadzone_w) -> list[float]
calcular_alpha_fps(alpha_base, fps, fps_ref=30.0) -> float  # ^(fps_ref/fps) CORRECTO
aplanar_conf_por_turnos(conf_multi, turnos_list, fps, total_frames) -> dict[int, float]
calcular_bandas_stack(caras, src_w, src_h, output_w=1080, output_h=1920) -> list[tuple[int,int,int,int]]  # (x,y,crop_w,src_h)

# CSV de trayectoria generado en cada render con --tray-dir:
# t, cam_center_x, face_x_asignada, distancia, conf_asignada
# (conf_asignada vacío = frame interpolado/hold; presentes = deteccion viva)

# Precondicion de dominio: fuente DEBE ser toma continua (sin cortes de escena)
# Si es editada: check emite WARNING pero NO bloquea el render
# Filtro de artefacto: _filtrar_artefactos_cortes(timestamps, min_t=1.0) -> list[float]
```

## Arquitectura core.py — funciones públicas

```python
# Formato de words (lo que transcribe_video devuelve y group_words consume)
{"words": [{"w": str, "s": float, "e": float, "prob": float}], "language": str}

# Formato de grupo (lo que group_words devuelve y build_ass consume)
{"id": int, "start": float, "end": float, "text": str,
 "words": [{"text": str, "start": float, "end": float, "line_idx": int}]}

detect_device()         -> (device, compute_type)
resolve_model(arg)      -> (model_path, label)
get_video_info(path)    -> {width, height, duration, mean_volume, has_audio}
transcribe_video(...)   -> dict  # words + language
group_words(words, ...) -> list[dict]  # grupos de subtítulo
apply_brain(groups, brain_data) -> list[dict]  # añade is_keyword
build_ass(groups, w, h, cfg, path) -> None
burn_video(in, ass, out) -> float  # segundos
extract_thumb(path, out) -> None
```

## Reglas de oro (siempre vigentes)

1. Smoke test al arranque — si falla, arreglar ANTES de tocar código
2. Consola Windows = solo ASCII en print(); UTF-8 libre en archivos
3. UTF-8 explícito en todo I/O (`encoding="utf-8"`)
4. No re-transcribir lo ya transcrito (el transcript es la fuente de verdad)
5. La función de escape de rutas ass= de FFmpeg no se cambia
6. Descargas HF: siempre `local_dir_use_symlinks=False` hacia `models/`
7. Verificación visual obligatoria antes de dar algo por bueno
8. Fail-open del cerebro: si la API LLM falla, el render sigue sin énfasis
9. Secretos en .env, jamás impresos en consola ni en reportes
10. CLI caption.py no puede romperse en ninguna fase

## Referencia MAESTRO.md
El documento de verdad para la secuencia de fases, DoD por fase y reglas globales está en `MAESTRO.md` en la raíz del proyecto.
