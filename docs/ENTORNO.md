# Entorno de Centrito Studio (instalación, arranque y diagnóstico)

Guía reproducible para dejar el Studio funcionando en una máquina limpia y para diagnosticar
fallos de arranque. Cierra los hallazgos de arranque de la auditoría pre-HyperFrames
(P1-BOOT-1/2, P2-BOOT-3..6).

> Privacidad: **no** subas al repo `input/`, `output/`, `transcripts/`, `thumbs/`, `.env` ni los
> modelos (`models/`, `referencia/yunet/`). Ya están en `.gitignore`.

---

## 1. Versión de Python soportada

**Python 3.12.x** (misma major.minor; el patch es libre). Es la versión validada para
`mediapipe==0.10.35` y el resto de dependencias. Otra minor (3.11, 3.13…) **no** está soportada y
el arranque la rechaza con un mensaje accionable.

```powershell
py -3.12 -m venv venv
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install -r requirements.txt
```

El producto se ejecuta SIEMPRE con `venv\Scripts\python.exe` (no basta con "activar" el venv).

## 2. FFmpeg y ffprobe

Se necesitan **ambos** binarios en el `PATH` para analizar, validar y renderizar video.

```powershell
choco install ffmpeg      # Windows (Chocolatey)
ffmpeg -version
ffprobe -version
```

Sin FFmpeg la UI **sigue abriendo** en modo degradado: se deshabilitan render, Automático, clips,
reframe y la validación de subidas, con un aviso que explica qué instalar.

## 3. Modelos de detección facial (reframe 9:16)

Los modelos están gitignored y se instalan de forma reproducible y **verificada por SHA256**:

```powershell
venv\Scripts\python.exe scripts\setup_models.py          # instala los que falten
venv\Scripts\python.exe scripts\setup_models.py --list   # muestra estado y URLs
venv\Scripts\python.exe scripts\setup_models.py --model yunet
venv\Scripts\python.exe scripts\setup_models.py --force  # reinstala aunque existan
```

| Modelo | Ruta relativa | Detector | Origen oficial |
|--------|---------------|----------|----------------|
| YuNet | `referencia/yunet/face_detection_yunet_2023mar.onnx` | default | OpenCV Zoo (`opencv/opencv_zoo`) |
| BlazeFace | `models/blaze_face_short_range.tflite` | fallback | MediaPipe (`storage.googleapis.com/mediapipe-models`) |

El instalador descarga a un temporal, valida el SHA256 esperado, publica con `os.replace`
(atómico) y **preserva** el modelo anterior si algo falla. Nunca descarga nada al arrancar el
Studio y nunca instala modelos que no se usan.

Con **cualquiera** de los dos detectores el reframe funciona; si YuNet falta, se usa BlazeFace.
Si faltan ambos, solo el reframe con seguimiento facial queda deshabilitado (el resto sigue).

### Instalación manual (si `setup_models.py` no puede descargar)

Descarga desde la URL oficial (ver `--list`) y colócalo en la ruta relativa exacta de la tabla.
Comprueba el hash:

```powershell
venv\Scripts\python.exe -c "import hashlib,pathlib; p='referencia/yunet/face_detection_yunet_2023mar.onnx'; print(hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest())"
```

Debe coincidir con el `sha256` de `model_assets.py`.

## 4. Arranque

```powershell
arranque.bat
```

`arranque.bat` es un wrapper mínimo: valida que exista `venv\Scripts\python.exe` y delega en
`studio_launcher.py`, que:

- corre el **preflight** (Python, venv, ffmpeg, ffprobe, modelos, imports críticos);
- si el entorno es fatal (Python no soportado, venv inválido, import crítico ausente) **no**
  arranca y explica cómo arreglarlo;
- inicia Uvicorn en `127.0.0.1:8787` (**solo loopback**, sin `--reload`, sin LAN);
- abre el navegador **solo después** de que `/api/system/health` responde 200 (con timeout).

### Puerto 8787 ocupado

- Si ya hay **otra instancia de Centrito Studio**, el launcher lo detecta (vía health), abre esa
  instancia y **no** inicia un segundo servidor.
- Si lo ocupa **otra aplicación**, muestra un mensaje accionable (sin traceback). Puedes cerrar esa
  app o usar otro puerto en modo diagnóstico:

```powershell
venv\Scripts\python.exe studio_launcher.py --port 8790
```

## 5. Modo degradado

Si falta una capacidad opcional (FFmpeg o modelos), la UI abre igual y muestra un aviso discreto y
accesible (`role="status"`). Solo se deshabilitan los controles afectados (por ejemplo, "Renderizar"
sin FFmpeg, "Reencuadrar 9:16" sin modelos); lo demás sigue disponible. La ausencia de una
dependencia **no** genera un job que fallará: se rechaza antes con una explicación.

## 6. Diagnóstico y reparación

| Check | Significado | Reparación |
|-------|-------------|------------|
| `python` | Versión soportada (3.12.x) | `py -3.12 -m venv venv` |
| `venv` | Se ejecuta desde `venv\Scripts\python.exe` | recrea el venv e instala requirements |
| `imports` | `fastapi`/`uvicorn` importables | `pip install -r requirements.txt` |
| `ffmpeg` / `ffprobe` | binarios en el PATH | `choco install ffmpeg` |
| `model_yunet` / `model_blazeface` | modelo presente | `scripts\setup_models.py` |

Diagnóstico en un comando (también dentro de `check.bat`):

```powershell
venv\Scripts\python.exe -m system_preflight                 # informe legible
venv\Scripts\python.exe -m system_preflight --json          # informe JSON
venv\Scripts\python.exe -m system_preflight --strict-local  # exit 1 si falta algo del producto
```

`check.bat` corre el preflight estricto + ruff + formato + imports + pytest. `check.bat full`
agrega un smoke de render sobre un **fixture sintético** generado con FFmpeg (sin datos privados).

## 7. Endpoints de diagnóstico

- `GET /api/system/health` — 200 cuando el server sirve; `{status, service}` (sin rutas ni secretos).
- `GET /api/system/capabilities` — disponibilidad booleana + mensaje por capacidad; fuente del
  modo degradado de la UI. Incluye la capacidad `nvenc`; **su ausencia NO degrada la app** (CPU
  sigue siendo ruta válida).
- `GET /api/system/video-encoder` — modo solicitado + encoder efectivo + estado NVENC
  (`{requested, selected, encoder, nvenc:{available,message}}`), saneado.
- `PUT /api/system/video-encoder` `{mode: auto|nvenc|cpu}` — fija el modo de codificación (enum
  cerrado). Afecta solo jobs nuevos; los activos conservan su instantánea.

## 8. Codificación de video (NVIDIA NVENC / CPU)

La codificación H.264 usa **NVIDIA NVENC** cuando está disponible, con **fallback a CPU
(libx264)**. Ver `docs/GPU_NVENC.md` para detalle, requisitos y benchmarks.

- Default por entorno: `CENTRITO_VIDEO_ENCODER=auto|nvenc|cpu` (inválido → `auto`).
- Preferencia de UI en **Ajustes → Codificación de video** (persistida en `localStorage`).
- Comprobar NVENC: `ffmpeg -hide_banner -encoders | Select-String h264_nvenc`.
- CUDA de Whisper (transcripción) es **independiente** de NVENC (codificación). Reframe,
  detección facial, libass y audio siguen en CPU.
