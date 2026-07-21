# Centrito Studio — Alpha pre-HyperFrames

> Etiqueta de documentación: **v0.1.1-alpha candidate** (candidato de documentación; **no** existe
> aún un tag ni un release publicado).

Suite **local** de producción y revisión de video con herramientas independientes y un **Modo
Automático**. Le das un video con voz en español y obtienes clips verticales con captions
animados, listos para que **tú** revises y publiques.

No es un editor multipista ni un competidor terminado de Premiere/CapCut: es una fábrica con
opinión + una mesa de revisión. Todo corre en esta PC; las integraciones externas son **explícitas
y opcionales**.

> **Local por defecto, con integraciones externas explícitas y opcionales.** Ver
> [Privacidad y servicios](#privacidad-y-servicios).

## Qué hace (funciones verificadas)

| Herramienta | Descripción |
|---|---|
| **Transcripción local** | Whisper (faster-whisper / CUDA si hay GPU, si no CPU) |
| **Captions clásicos** | Word-by-word (Hormozi / karaoke / bounce / PMS) sobre cualquier video |
| **Captions CVE** | Motor viral: presets, spans de frase, `[center]`, avoid_faces |
| **Caption QA** | Detecta palabras mal transcritas ("confeti UI" → "ComfyUI") |
| **Depurador** | Elimina silencios y muletillas de clases grabadas |
| **Clipper** | Extrae los mejores momentos de un video largo (análisis con LLM) |
| **Reframe** | 16:9 → 9:16 con face tracking (modo escenas y modo EMA) |
| **Stack** | Layout vertical para podcast de 2-3 personas |
| **SRT seleccionado** | Asocias un `.srt` al video; su texto es la fuente oficial de captions |
| **Auto classic / Auto v2** | Modo Automático; v2 añade b-roll, FX y verificación A/V |
| **Editor de Paquete** | Vista de revisión (solo lectura) sobre los paquetes generados |
| **B-roll** | Cutaways de stock (Pexels, opt-in) sincronizados al guion |
| **Submagic** | Estación en la nube opt-in (edita/sube el video a Submagic) |
| **GPU NVENC** | Codificación H.264 acelerada con fallback CPU (libx264) |
| **Recuperación de jobs** | Detecta "servidor reiniciado / job perdido" y ofrece reintentar |
| **Studio** | UI web (FastAPI + HTML vanilla) que orquesta todo en el navegador |

## Estado y calidad

- Fase: **Alpha pre-HyperFrames**. Endurecimiento H1/H2/H3 y GPU/NVENC cerrados en `main`.
- Baseline de suite de este commit: **2410 passed, 4 skipped** (4 skips históricos de symlink en
  Windows). `ruff`/formato/`check.bat` verdes.
- Readiness: **0 P0 abiertos · 0 P1 abiertos**. Detalle en
  [`revision/pre-hyperframes/MATRIZ_READINESS.md`](revision/pre-hyperframes/MATRIZ_READINESS.md).

## Arranque rápido

Requisitos: **Python 3.12.x**, **FFmpeg + ffprobe** en el PATH, GPU NVIDIA opcional.

```powershell
# 1. Entorno y dependencias
py -3.12 -m venv venv
.\venv\Scripts\pip install -r requirements.txt

# 2. Secretos opcionales (solo si quieres LLM / b-roll / Submagic)
copy .env.example .env   # editar .env

# 3. Modelos de detección facial (verificados por SHA256)
.\venv\Scripts\python scripts\setup_models.py

# 4. Verificar entorno
.\check.bat

# 5. Levantar Centrito Studio
.\arranque.bat   # abre el navegador en http://127.0.0.1:8787
```

Guía reproducible completa (clon limpio, diagnóstico, modo degradado): [`docs/ENTORNO.md`](docs/ENTORNO.md).

## CLI directa

```powershell
$env:PYTHONIOENCODING="utf-8"

# Captions sobre un video
.\venv\Scripts\python caption.py input/video.mp4 --style hormozi --lang es

# Reframe 16:9 -> 9:16 (modo escenas por defecto)
.\venv\Scripts\python reframe.py output/clips/clip.mp4
.\venv\Scripts\python reframe.py output/clips/clip.mp4 --tracker ema  # EMA continuo

# Depurar silencios
.\venv\Scripts\python caption.py input/clase.mp4 --depurar seguro

# Generar clips virales
.\venv\Scripts\python caption.py input/clase_larga.mp4 --clips ambos
```

## Privacidad y servicios

**Local por defecto, con integraciones externas explícitas y opcionales.** No afirmamos "nada se
sube": si activas Submagic, el video puede subirse a su nube.

| Componente | Local/remoto | Qué se procesa |
|---|---|---|
| Whisper (transcripción) | **Local** | El audio del video, en esta PC |
| FFmpeg / reframe / captions / overlays | **Local** | Video y frames, en esta PC |
| Codificación (NVENC / libx264) | **Local** | Encode H.264 en GPU o CPU |
| ComfyUI (emojis/popups IA) | **Local** (loopback `127.0.0.1:8188`) | Assets PNG; no sale de la PC |
| DeepSeek / proveedor LLM | **Remoto, opcional** | Envía **texto/contexto** para análisis editorial |
| Pexels (b-roll) | **Remoto, opcional** | Envía **búsquedas** y descarga assets de stock |
| Submagic | **Remoto, opcional** | Puede **subir el video** cuando eliges esa estación |

Las integraciones remotas son **opt-in** (requieren su API key en `.env` o elegir la estación).
Sin claves, esas capas quedan deshabilitadas y el pipeline local sigue.

## Estilos de captions

| ID | Look | Animación |
|---|---|---|
| `hormozi` | Blanco bold + amarillo en palabra activa | Color highlight |
| `karaoke` | Relleno progresivo cian | `\kf` fill |
| `bounce` | Naranja, escala 122% al activarse | `\t()` scale |
| `pms` | Morado #7C3AED, configurable en `styles.py` | Color highlight |

## Dónde vive la verdad

| Archivo | Qué contiene |
|---|---|
| [`ESTADO.md`](ESTADO.md) | Estado vivo, merges cerrados y siguiente fase |
| [`MAESTRO.md`](MAESTRO.md) | Arquitectura, reglas y roadmap **histórico** |
| [`DECISIONES.md`](DECISIONES.md) | Registro de decisiones técnicas con justificación |
| [`PREGUNTAS.md`](PREGUNTAS.md) | Preguntas activas o diferidas con trigger |
| [`docs/ENTORNO.md`](docs/ENTORNO.md) | Instalación reproducible y diagnóstico |
| [`docs/ALPHA_TESTERS.md`](docs/ALPHA_TESTERS.md) | Protocolo de prueba para testers |
| [`docs/GPU_NVENC.md`](docs/GPU_NVENC.md) | Codificación NVENC / CPU, requisitos y benchmarks |
| [`revision/pre-hyperframes/MATRIZ_READINESS.md`](revision/pre-hyperframes/MATRIZ_READINESS.md) | Readiness verificable pre-HyperFrames |

## Estructura del proyecto

```
caption.py             CLI principal (captions, depurar, clips)
reframe.py             CLI reframe 9:16 con face tracking
core.py / core_ass.py  Pipeline de transcripción, ASS y quemado FFmpeg
video_encoder.py       Detección y selección NVENC/CPU con fallback
brain.py               Cerebro editorial (DeepSeek / mock)
depurador.py           Eliminación de silencios y muletillas
clipper.py             Extracción de clips virales
auto.py / auto_v2.py   Modo Automático (classic y v2)
studio_srt_*.py        Asociación y render de SRT seleccionado
paquete_editor.py      Editor de Paquete (revisión solo-lectura)
submagic.py            Estación Submagic (nube, opt-in)
assets_comfy.py        Puente ComfyUI para assets PNG
app.py                 API FastAPI del Studio
jobs.py                Orquestador de jobs + worker de transcripción
jobs_render.py         Worker de render
static/index.html      UI del Studio (HTML vanilla)
static/job_polling.js  Motor de polling + recuperación de jobs
tests/                 Suite de tests de contrato
revision/              Evidencia de validación por fase
```

## Requisitos

- Windows 11 (PowerShell o Git Bash) — validado.
- Python 3.12.x.
- FFmpeg + ffprobe en el PATH (`choco install ffmpeg` o gyan.dev / BtbN).
- GPU NVIDIA (opcional). **CUDA** (Whisper) y **NVENC** (codificación) son usos distintos de la
  GPU; ambos tienen fallback a CPU. Ver [`docs/GPU_NVENC.md`](docs/GPU_NVENC.md).
- ComfyUI Desktop (opcional, para emojis IA — en `http://127.0.0.1:8188`).

## Regla de colaboración

> **Cambios por rama + pull request, nunca directo a main.**
> `check.bat` debe terminar en `===== TODO OK =====` antes de todo PR.

```powershell
git checkout -b mi-feature
# ... trabajar ...
.\check.bat
git push origin mi-feature
# abrir PR en GitHub
```

### Notas para agentes y colaboradores en Windows

- **Hooks de Claude Code:** invocar los `.bat` DIRECTO (`hooks/autoformat.bat`), nunca vía
  `cmd /c` (la capa POSIX convierte `/c` en `C:\` y deja un cmd interactivo — causa raíz del
  gremlin de archivos 0-byte; ver PREGUNTAS #30).
- **Smokes de UI con navegador:** cada smoke lanza su propia instancia headless con
  `--user-data-dir` temporal y mata solo su PID. Prohibido `taskkill /im msedge.exe` (tumba la
  sesión real del usuario).
