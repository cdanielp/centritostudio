# Centrito Studio

Suite local de produccion de video con IA para Prompt Models Studio.

Sin Docker. Sin suscripcion. Sin API externa (salvo DeepSeek para analisis editorial y
ComfyUI local para assets — ambos opcionales y configurables en `.env`).

## Que hace

| Herramienta | Descripcion |
|---|---|
| **Captions** | Captions animados word-by-word (Hormozi / karaoke / bounce / PMS) sobre cualquier video |
| **Depurador** | Elimina silencios y muletillas de clases grabadas |
| **Clipper** | Extrae los mejores momentos virales de un video largo (analisis con LLM) |
| **Reframe** | Convierte clips 16:9 a 9:16 con face tracking — modo escenas (cortes-primero + waypoints) y modo EMA |
| **Stack** | Layout vertical para podcast de 2-3 personas (bandas estaticas) |
| **Emojis IA** | Overlays PNG generados por ComfyUI sincronizados a keywords del brain |
| **Studio** | UI web (FastAPI + HTML vanilla) que orquesta todo en el navegador |

## Arranque rapido

```powershell
# 1. Crear entorno y dependencias
python -m venv venv
.\venv\Scripts\pip install -r requirements.txt

# 2. Copiar y llenar secretos (solo DeepSeek si quieres clips/enfasis IA)
copy .env.example .env
# editar .env: DEEPSEEK_API_KEY=sk-...

# 3. Verificar que todo esta en orden
.\check.bat

# 4. Levantar Centrito Studio
.\arranque.bat   # abre el navegador en http://localhost:8787
```

## CLI directa

```powershell
$env:PYTHONIOENCODING="utf-8"

# Captions sobre un video
.\venv\Scripts\python caption.py input/video.mp4 --style hormozi --lang es

# Captions + emojis IA (requiere ComfyUI encendido)
.\venv\Scripts\python caption.py input/video.mp4 --style hormozi --emojis

# Reframe 16:9 -> 9:16 (modo escenas por defecto)
.\venv\Scripts\python reframe.py output/clips/clip.mp4
.\venv\Scripts\python reframe.py output/clips/clip.mp4 --tracker ema  # EMA continuo (F4.1)

# Depurar silencios
.\venv\Scripts\python caption.py input/clase.mp4 --depurar seguro

# Generar clips virales
.\venv\Scripts\python caption.py input/clase_larga.mp4 --clips ambos
```

## Estilos de captions

| ID | Look | Animacion |
|---|---|---|
| `hormozi` | Blanco bold + amarillo en palabra activa | Color highlight |
| `karaoke` | Relleno progresivo cian | `\kf` fill |
| `bounce` | Naranja, escala 122% al activarse | `\t()` scale |
| `pms` | Morado #7C3AED, configurable en `styles.py` | Color highlight |

## Donde vive la verdad

| Archivo | Que contiene |
|---|---|
| `MAESTRO.md` | Spec completa de todas las fases, reglas de oro, decisiones de arquitectura |
| `ESTADO.md` | Estado actual de cada fase, bitacora de sesiones |
| `DECISIONES.md` | Registro de decisiones tecnicas con justificacion |
| `PREGUNTAS.md` | Preguntas pendientes del arquitecto + deudas tecnicas |

Lee `MAESTRO.md` antes de tocar cualquier cosa.

## Estructura del proyecto

```
caption.py          CLI principal (captions, depurar, clips)
reframe.py          CLI reframe 9:16 con face tracking
reframe_escenas.py  Modo escenas: cortes-primero + waypoints
reframe_track.py    Matematicas puras del tracker (EMA, deadzone, waypoints)
reframe_detect.py   Deteccion de caras (YuNet default, BlazeFace fallback)
core.py / core_ass.py  Pipeline de transcripcion, ASS y quemado FFmpeg
brain.py            Cerebro editorial (DeepSeek / mock)
depurador.py        Eliminacion de silencios y muletillas
clipper.py          Extraccion de clips virales
assets_comfy.py     Puente ComfyUI para assets PNG con transparencia (rembg)
app.py              API FastAPI del Studio
jobs.py             Workers de background con progreso
static/index.html   UI del Studio (HTML vanilla)
tests/              Suite de tests de contrato (157 tests, ruff limpio)
revision/           Evidencia de validacion por fase (.jpg, .csv, .md)
```

## Requisitos

- Windows 11 (PowerShell o Git Bash)
- Python 3.12
- FFmpeg en PATH (`choco install ffmpeg` o Gyan.dev)
- GPU NVIDIA + CUDA (opcional; fallback a CPU)
- ComfyUI Desktop (opcional, para emojis IA — debe estar en `http://127.0.0.1:8188`)

## Regla de colaboracion

> **Cambios por rama + pull request, nunca directo a main.**
> `check.bat` debe estar verde antes de todo PR.

### Notas para agentes y colaboradores en Windows

- **Hooks de Claude Code:** invocar los `.bat` DIRECTO (`hooks/autoformat.bat`),
  nunca via `cmd /c`. La capa POSIX (Git Bash/MSYS) convierte `/c` en `C:\` y deja
  un cmd INTERACTIVO ejecutando el stdin del hook — es la causa raiz del gremlin
  de archivos 0-byte (ver PREGUNTAS #30).
- **Smokes de UI con navegador:** cada smoke lanza su PROPIA instancia (headless,
  con `--user-data-dir` temporal propio) y al terminar mata SOLO su PID. Prohibido
  matar el navegador por nombre de proceso (`taskkill /im msedge.exe`): tumba la
  sesion real del usuario.

```powershell
git checkout -b mi-feature
# ... trabajar ...
.\check.bat           # lint + format + tests — debe terminar "===== TODO OK ====="
git push origin mi-feature
# abrir PR en GitHub
```
