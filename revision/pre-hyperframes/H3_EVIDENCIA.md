# H3 — Evidencia de cierre (arranque y diagnóstico pre-HyperFrames)

**Base:** `5779a77f0f46c861806a9d02c21b8e3b4d358a81` (merge PR #26, cierre H2).
**Rama:** `fix/h3-arranque-diagnostico`. **PR abierto, NO mergeado.**
**Alcance:** P1-BOOT-1, P1-BOOT-2, P2-BOOT-3, P2-BOOT-4, P2-BOOT-5, P2-BOOT-6. **NO** H4/H5/HyperFrames.

Todas las pruebas usan `TemporaryDirectory`, fixtures sintéticos y dependencias inyectadas
(versión, ejecutable, `which`, rutas de modelos, puerto, `fetch`): sin red real, sin GPU, sin abrir
puertos ni el navegador, sin matar procesos. En ningún momento se abre, imprime, hashea ni versiona
`input/video.srt`.

---

## Preflight central — `system_preflight.py` (nuevo)

Fuente única, pura e inyectable. `check_environment(...) -> {status, checks, capabilities}`:

- Checks individuales `{id, status, required_for, message, action}` para: `python`, `venv`,
  `imports`, `ffmpeg`, `ffprobe`, `model_yunet`, `model_blazeface`, `dirs` y (opcional) `port`.
- `status` global: **`ready`** (todo instalado) · **`degraded`** (UI operativa, falta una capacidad
  concreta: ffmpeg/ffprobe/modelos/puerto) · **`blocked`** (Python no soportado, venv inválido o
  import crítico ausente). **FFmpeg o modelos ausentes NUNCA son `blocked`.**
- `capabilities`: booleano + mensaje por `ffmpeg`, `ffprobe`, `video_metadata`, `upload_validation`,
  `render`, `auto`, `clips`, `reframe`, `detector_yunet`, `detector_blazeface`.
- **Privacidad:** mensajes con rutas RELATIVAS; nunca `.env`, variables completas ni rutas absolutas.
- CLI: `python -m system_preflight [--json] [--strict-local]`. `--strict-local` (para check.bat)
  exige el entorno LOCAL completo del producto (Python soportado, venv, ffmpeg, ffprobe, ≥1 detector,
  imports) y devuelve exit 1 si falta algo.

## Versión de Python y venv (FASE 3, P2-BOOT-5)

Soportada: **Python 3.12.x** (misma major.minor; patch libre), validada contra `mediapipe==0.10.35`
y el resto de deps (venv actual: 3.12.10; fastapi 0.139.0; uvicorn 0.51.0). El check distingue
exacto/mismo-minor (OK) de otra minor (error accionable: `py -3.12 -m venv venv`). El check `venv`
exige que `sys.executable` esté DENTRO de `venv/` (no basta con "activar").

## FFmpeg / ffprobe y excepciones tipadas — `media_deps.py` (nuevo) + `core.py`

`media_deps`: `shutil.which` como fuente de verdad + jerarquía `MediaDependencyUnavailable →
{FFmpegUnavailable, FFprobeUnavailable}` y `MediaProbeError` (herramienta presente, archivo inválido).
No se lanza subprocess si `which` ya dice que falta.

- `core.get_video_info`: ffprobe ausente → `FFprobeUnavailable` (mensaje accionable, **sin
  JSONDecodeError**); ffprobe presente pero returncode≠0 / stdout vacío / JSON inválido →
  `MediaProbeError` (**no** sugiere instalar FFmpeg).
- `core._probe_volume`: ffmpeg ausente / `OSError` → `FFmpegUnavailable` (no `WinError 2` crudo).
- `media_integrity._ffprobe`: guard por `which` que lanza `MediaIntegrityError` (NO
  `FFprobeUnavailable`) para preservar el contrato fail-closed de `video_reanudable` (H2).
- `app.upload_video`: ffprobe ausente → 503 accionable ("FFprobe no está disponible…") en vez del
  engañoso 422 "no es un video válido".
- `jobs._error_publico_auto`: traduce las excepciones tipadas al mensaje accionable (sin rutas), así
  un job que requiere render termina en `error` saneado.

## Capacidades y health — `app.py`

`GET /api/system/health` → 200 sirviendo; `{status: ready|degraded, service}` (sin rutas/secretos):
el launcher lo usa para saber cuándo abrir el navegador.
`GET /api/system/capabilities` → `{status, capabilities}` (booleano + mensaje): fuente del modo
degradado de la UI. El informe se computa al importar (sin red) y se **refresca en el `lifespan`**
del arranque (FastAPI lifespan, no eventos deprecated). Sin comprobaciones de red en startup.

## Modelos — `model_assets.py` + `model_setup.py` + `scripts/setup_models.py` (nuevos)

- `model_assets`: spec única (id, ruta relativa, detector, obligatorio, **URL oficial verificada**,
  **SHA256**, tamaño, instrucción de instalación).
- **URLs + hashes verificados en H3** descargando cada modelo desde su origen oficial y comprobando
  que el SHA256 coincide EXACTO con el modelo que ya funciona (no se inventaron):
  - YuNet `referencia/yunet/face_detection_yunet_2023mar.onnx` ← `media.githubusercontent.com/media/
    opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx`,
    sha256 `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` (232589 B).
  - BlazeFace `models/blaze_face_short_range.tflite` ← `storage.googleapis.com/mediapipe-models/
    face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite`,
    sha256 `b4578f35940bf5a1a655214a1cce5cab13eba73c1297cd78e1a04c2380b0152f` (229746 B).
- `model_setup.install_model`: descarga a temporal (solo http/https, redirects a esquemas no-web
  rechazados, timeout, tope DURO de bytes), valida SHA256 (**hash distinto NO se escribe**),
  publica con `os.replace` (atómico) y **preserva el modelo anterior** ante fallo. No ejecuta red
  al importar ni al arrancar; `install_all` no baja lo ya presente ni modelos no usados.
- `reframe_detect`: `DetectorUnavailable` tipado (rutas RELATIVAS + comando de setup) cuando faltan
  ambos; fallback YuNet→BlazeFace sin ruta absoluta ni traceback; un detector pedido explícito que
  falta NO cae a otro silenciosamente. El chequeo de existencia va ANTES de importar mediapipe.

## Launcher — `studio_launcher.py` (nuevo) + `arranque.bat` (wrapper)

`arranque.bat` = wrapper mínimo: valida `venv\Scripts\python.exe` (P2-BOOT-3) y delega. Sin
`activate.bat`, sin `--reload`, sin `start ""` previo, sin `0.0.0.0`.
`studio_launcher.run(...)` (inyectable):

- Preflight bloqueante: `blocked` → mensaje + exit ≠ 0; `degraded` → warning y continúa.
- Puerto libre → Uvicorn en `127.0.0.1` (loopback, sin reload). Ocupado por **otro Centrito** (vía
  `/api/system/health`) → abre esa instancia, no inicia un segundo server, exit 0. Ocupado por
  **otra app** → mensaje accionable (sin traceback) + exit ≠ 0 (P2-BOOT-4).
- Navegador: hilo que sondea `/api/system/health` y abre **solo tras el primer 200**, con timeout;
  si no queda listo, no abre e informa. Bind error → mensaje accionable; Ctrl+C limpio.

## check.bat (P2-BOOT-6)

Nuevo paso `[1/5] entorno` = `system_preflight --strict-local` (Python/venv/ffmpeg/ffprobe/≥1
detector/imports). Conserva ruff/format/imports/pytest. `check.bat full` usa un **fixture sintético**
generado con FFmpeg (`lavfi`), sin datos privados; **nunca** usa `input/video.srt`.

## UI en modo degradado — `static/system_capabilities.js` (nuevo) + `index.html`

Módulo aislado (patrón de `job_polling.js`). Consulta `/api/system/capabilities` y:
deshabilita SOLO los controles con `data-cap` cuya capacidad falta (render/auto/upload/reframe),
con `title` + `aria-disabled`; muestra un aviso discreto `#system-banner` con `role="status"` y
mensaje saneado (sin rutas). Un fallo al consultar no rompe la UI (controles quedan por defecto).
No cambia layout, colores, navegación ni resultado audiovisual.

---

## Tests (nuevos)

- `test_h3_preflight.py` (23): Python OK/mismo-minor/no-soportado, venv dentro/fuera, ffmpeg/ffprobe
  presentes/ausentes, YuNet/BlazeFace/ambos, imports, puerto, ready/degraded/blocked, salida sin
  paths absolutos ni secretos, strict-local.
- `test_h3_media_deps.py` (11): ffprobe ausente sin JSONDecodeError, returncode≠0 = MediaProbeError,
  JSON válido, ffmpeg ausente = FFmpegUnavailable, `video_reanudable` fail-closed, sin subprocess si
  falta, mensaje de job saneado, UI carga sin binarios.
- `test_h3_models.py` (15): fallback, ambos ausentes, detector explícito ausente, mensaje con setup,
  hash correcto/incorrecto/parcial/timeout, preserva anterior, cleanup, esquema no-http, oversize,
  redirect no-web, no descarga lo presente, URLs https + hash 64.
- `test_h3_launcher.py` (14): clasificación de puerto (libre/Centrito/otra), health tarda/nunca,
  navegador solo tras 200 / una vez, run() blocked/centrito/otra/bind-error/Ctrl+C, host loopback.
- `test_h3_check_bat.py` (9) + `test_h3_ui_capabilities.py` (9, harness Node
  `ui_capabilities_harness.cjs`): contrato de .bat + gate DOM ready/degraded/aria/null.
- `test_h1_bind_localhost.py`: adaptado (el bind loopback migró al launcher).

## Smoke y suite

- `smoke_h3_environment.py --self-test` → **VERDE (3/3)**; `smoke_h3_environment.py` →
  `checks=12 blockers=0 fails=0 skips=0`, **exit 0**.
- `smoke_pre_hyperframes.py --self-test` **VERDE (20/20)** + `smoke_pre_hyperframes.py`
  `checks=12 blockers=0 fails=0` (H1 intacto).
- `smoke_h2_jobs_resume.py --self-test` **VERDE (2/2)** + `smoke_h2_jobs_resume.py`
  `checks=12 blockers=0 fails=0` (H2 intacto).
- `pytest` → **2314 passed, 4 skipped**. Los 4 skips son EXACTAMENTE los cuatro históricos de
  symlink (Windows sin privilegio); **cero skips nuevos**.
- `ruff check .` limpio · `ruff format --check .` (173 files) limpio · `git diff --check` limpio.

## Evidencia funcional (no versionada, bajo `output/revision-pre-hyperframes/h3/`)

- `smoke_h3_report.json` (matriz de 12 checks). La salida audiovisual **no** cambia; el gate es
  funcional/UX (no reclama aprobación visual de K).

## Fuera de alcance / residual

- H4 (docs históricas ESTADO/DECISIONES/PREGUNTAS/ALPHA) y H5 (CI/GitHub Actions): **no iniciados**.
- Cancelación real del worker/FFmpeg (H2 solo cancela seguimiento local).
- BlazeFace full-range (no lo usa `ACTIVE_MODEL_PATH`): no se instala por defecto.
- Writers FFmpeg diferidos de H1/H2 (clipper/reframe/depurador/broll/submagic): heredan el contrato
  vía job en `error` saneado, sin reescritura masiva.

## H4 / H5 / HyperFrames

**No iniciados.**
