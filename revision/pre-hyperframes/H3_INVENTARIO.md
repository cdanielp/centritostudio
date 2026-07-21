# H3 — Inventario de arranque, dependencias y diagnóstico (antes de modificar)

**Base:** `5779a77f0f46c861806a9d02c21b8e3b4d358a81` (merge PR #26, cierre H2). **Rama:** `fix/h3-arranque-diagnostico`.
**Alcance:** P1-BOOT-1, P1-BOOT-2, P2-BOOT-3..6. **NO** H4/H5/HyperFrames.

Este documento es el inventario previo exigido por la FASE 1 del plan. Clasifica cada dependencia
en cuatro categorías: **fatal para iniciar la UI**, **capacidad opcional degradable**, **requerida
para una acción concreta** y **fuera de alcance**.

---

## 1. Usos directos de FFmpeg / ffprobe / subprocess multimedia

| Archivo:símbolo | Binario | Rol en el producto | Categoría |
|-----------------|---------|--------------------|-----------|
| `core.py:_probe_volume` (:70) | ffmpeg | volumedetect al transcribir (info de audio) | requerida para transcripción/render |
| `core.py:get_video_info` (:106) | ffprobe | ancho/alto/duración/fps del fuente | requerida para render/reframe/clips |
| `media_integrity.py:_ffprobe` (:48) | ffprobe | validación de integridad del MP4 publicado | requerida para render/resume |
| `core_ass.py:burn_video` (:322) / `burn_video_with_emojis` (:442) | ffmpeg | quemado de captions | requerida para render |
| `core_overlays.py` (:289) | ffmpeg | overlays | requerida para render con overlays |
| `depurador.py` (:159,:195,:281) | ffmpeg/ffprobe | corte de silencios | requerida para "Depurar" |
| `reframe.py` (:67,:247) | ffmpeg | pipe de frames reframe 9:16 | requerida para reframe |
| `auto_av.py` (:47,:97) | ffprobe/ffmpeg | verificación A/V del Auto v2 | requerida para Auto v2 |
| `broll_video_stock_base.py` (:298) | ffprobe | metadata de b-roll de stock | requerida para b-roll de video |
| `test_e2e.py` (:93) | ffmpeg | extracción de frame (test manual) | fuera de alcance (test) |

**Punto único de entrada multimedia que endurece H3:** `core._probe_volume`, `core.get_video_info`
y `media_integrity._ffprobe`. Un guard central (`shutil.which`) + excepciones tipadas cubren el
contrato sin reescribir cada comando (los demás heredan el returncode ya chequeado o fallan dentro
de un job que termina en `error` saneado).

## 2. Capacidades del producto vs. dependencia real

| Capacidad | ffprobe | ffmpeg | YuNet | BlazeFace | Notas |
|-----------|:------:|:------:|:-----:|:---------:|-------|
| Cargar la UI / biblioteca | no | no | no | no | Solo FastAPI + estáticos |
| `video_metadata` (get_video_info) | **sí** | — | no | no | ffprobe |
| `upload_validation` | **sí** | — | no | no | `media_integrity.verificar_video` (ffprobe) |
| `render` (captions) | sí | **sí** | no | no | quemar + validar |
| `auto` (Modo Automático) | sí | **sí** | no | no | orquesta render |
| `clips` | sí | **sí** | no | no | corta + render |
| `reframe` 9:16 | sí | **sí** | **sí** (default) | fallback | necesita ≥1 detector |
| `detector_yunet` | — | — | **sí** | — | default |
| `detector_blazeface` | — | — | — | **sí** | fallback |

## 3. Puntos donde una dependencia ausente rompe hoy

- **ffprobe ausente:** `core.get_video_info` hace `json.loads(probe.stdout)` sobre stdout vacío →
  `JSONDecodeError` **que no menciona FFmpeg** (P1-BOOT-1). `core._probe_volume` corre ffmpeg sin
  try/except → `FileNotFoundError [WinError 2]` crudo. `media_integrity._ffprobe` **ya** captura
  `OSError` → `MediaIntegrityError("no se pudo ejecutar ffprobe")` (H1, correcto).
- **ffmpeg ausente:** `core_ass.burn_video` lanzaría `FileNotFoundError` dentro del worker; el job
  queda en `error` pero con traza cruda, no un mensaje accionable.
- **Modelos ausentes (clone limpio):** `reframe_detect._crear_detector` cae a BlazeFace si falta
  YuNet; si **ambos** faltan, `_crear_detector_blazeface` lanza `FileNotFoundError(f"...{path}")`
  con **ruta absoluta local** y **sin URL de instalación** (P1-BOOT-2).
- **Listar biblioteca / abrir UI:** NO depende de FFmpeg ni modelos (solo lee `input/` + sidecars).
  Debe seguir cargando aunque falten binarios/modelos.

## 4. Arranque actual (`arranque.bat`)

```
cd /d "%~dp0"
call venv\Scripts\activate.bat          <- BOOT-3: no valida que el venv exista
set PYTHONIOENCODING / HF_HUB...
start "" http://127.0.0.1:8787          <- BOOT-4: abre el navegador ANTES del server
uvicorn app:app --host 127.0.0.1 --port 8787 --reload   <- --reload en arranque normal
```

- **Host/puerto:** loopback `127.0.0.1:8787` (bien, H1). `app.py.__main__` usa `LISTEN_HOST/PORT`.
- **Puerto ocupado:** uvicorn revienta con traceback de bind crudo (BOOT-4).
- **Servidor lento / muere:** el navegador ya se abrió a una página que no responde.
- **Sin validación de Python** (BOOT-5): `activate.bat` puede activar cualquier intérprete.

## 5. Modelos

| Modelo | Ruta relativa esperada | Detector | Default | gitignored | Presente local | URL oficial verificada (H3) | SHA256 (H3) |
|--------|------------------------|----------|:-------:|:----------:|:--------------:|-----------------------------|-------------|
| YuNet | `referencia/yunet/face_detection_yunet_2023mar.onnx` | yunet | **sí** | sí (`referencia/yunet/`) | sí | `media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx` | `8f2383e4…2552fa4` (232589 B) |
| BlazeFace short | `models/blaze_face_short_range.tflite` | blazeface | fallback | sí (`models/`) | sí | `storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite` | `b4578f35…b0152f` (229746 B) |
| BlazeFace full | `models/blaze_face_full_range.tflite` | (no usado por defecto) | no | sí | sí | — | fuera de alcance (no lo usa `ACTIVE_MODEL_PATH`) |

- **Fallback real:** `_crear_detector("yunet")` → si falta el ONNX imprime aviso y usa BlazeFace.
- **Operaciones sin modelos:** todo excepto reframe (captions, clips sin reframe, upload, biblioteca).
- **Verificación H3 (durante implementación, no en runtime):** ambos hashes locales coinciden EXACTO
  con la descarga desde su URL oficial → se puede pinnear URL+SHA256 de forma confiable (opción A).

## 6. Versión de Python

- **venv actual:** Python **3.12.10** (`sys.version_info(3,12,10)`).
- **Compatibilidad real:** `mediapipe==0.10.35` está pineado y solo publica wheels para 3.12 en este
  entorno; `fastapi 0.139.0` / `uvicorn 0.51.0` instalados y funcionando.
- **Versión soportada oficial del proyecto:** **Python 3.12.x** (misma major/minor; patch libre).
  Otra minor → error accionable (`py -3.12 -m venv venv`).

---

## Clasificación final

| Tipo | Elementos |
|------|-----------|
| **Fatal para iniciar la UI** | Python soportado, ejecución desde el venv correcto, imports críticos (`app`, `core`, `fastapi`) |
| **Capacidad opcional degradable** | ffmpeg, ffprobe (analizar/validar), YuNet, BlazeFace (reframe) — su ausencia degrada, **no** tumba la UI |
| **Requerida para una acción concreta** | ffprobe → `video_metadata`/`upload_validation`; ffmpeg → render/auto/clips/reframe/depurar; ≥1 detector → reframe |
| **Fuera de alcance** | H4 (ESTADO/DECISIONES/PREGUNTAS/ALPHA), H5 (CI/GitHub Actions), HyperFrames/F7, cancelación real del worker, BlazeFace full-range, writers FFmpeg diferidos de H1/H2 |
