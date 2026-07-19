# S36-C1 — Contrato backend SRT de Studio (asociación video↔SRT)

Evidencia sintética de la sesión 39 (D37). **Solo backend/API**: sin UI, sin render, sin Auto.
PR `feat/s36-c1-studio-srt-backend` **abierto y NO mergeado**.

## Qué hace

Infraestructura para que Studio administre, de forma privada y segura, la asociación entre un
video de `input/` y **un** archivo SRT seleccionado:

1. recibe un SRT por multipart;
2. lo valida con la infraestructura de S36-A (`srt_import`) y contra la duración real del video;
3. guarda los **bytes originales** por hash en almacenamiento privado (nunca servido);
4. lo asocia **explícitamente** a un único video (sin autodiscovery);
5. permite consultar estado/diagnósticos, reemplazar e desasociar de forma idempotente.

## Módulos

- `studio_srt.py` — dominio puro (cero FastAPI): confinamiento de video, validación de nombre,
  parseo+validación, almacenamiento por hash, idempotencia/reparación/reemplazo, escritura
  atómica, delete-desasocia, capacidades. Errores tipados
  (`StudioSrtNotFound/Invalid/TooLarge/Unsupported/StorageError`).
- `studio_srt_manifest.py` — construcción y **saneamiento por whitelist** del manifiesto v1
  (helpers de basename/sha256, `build_manifest`, `sanitize_manifest`). Puro, sin FastAPI.
- `studio_srt_routes.py` — APIRouter delgado que traduce errores tipados a HTTP.
- `app.py` — solo `include_router(...)` + delegación de `_resolver_video_input` al helper puro.

## API

| Método | Ruta | Descripción | Status |
|---|---|---|---|
| GET | `/api/srt/capabilities` | Capacidades estáticas del contrato | 200 |
| GET | `/api/videos/{name}/srt` | Estado de la selección (manifest v1 o `none`) | 200 / 404 |
| POST | `/api/videos/{name}/srt` | Asocia un SRT validado | 201 nuevo / 200 idempotente / 400 / 404 / 413 / 415 |
| DELETE | `/api/videos/{name}/srt` | Desasocia (idempotente) | 200 |

## Almacenamiento privado

```
transcripts/studio_srt/{video_stem}/{sha256_completo}.srt  # bytes originales, nunca montado
transcripts/{video_stem}_srt_selection.json                # manifiesto v1 saneado
```

El basename usa el **SHA256 completo** (64 hex): `hash(archivo) == manifest.source_sha256`
siempre, sin colisiones de prefijo.

`transcripts/` ya está gitignored. Ningún mount (`/input`, `/output`, `/clips`, `/static`)
sirve estos archivos; no existe endpoint de descarga.

## Manifest v1 (saneado)

Incluye `version, video{name,filename,duration_ms}, selection{selected, source_name,
managed_file(basename), source_sha256, encoding}, summary{n_cues,start_ms,end_ms,n_errors,
n_warnings}, diagnostics[{code,severity,cue_position,cue_index}], status`. **Nunca** texto de
cues, rutas absolutas, `message`, bytes ni tracebacks.

## Reproducir la evidencia

```powershell
$env:PYTHONIOENCODING="utf-8"
.\venv\Scripts\python.exe revision\s36-c1-studio-srt-backend\gen_fixture.py --create
.\venv\Scripts\python.exe revision\s36-c1-studio-srt-backend\smoke_api.py
.\venv\Scripts\python.exe revision\s36-c1-studio-srt-backend\gen_fixture.py --clean
```

El smoke crea un MP4 sintético con FFmpeg en un tempdir efímero, recorre
capabilities → none → upload → idempotencia → reemplazo → delete, verifica que el archivo
administrado no se publica por ningún mount y que **no** se inicia ningún job/render/Auto.
No versiona MP4, manifiesto ni SRT privado; solo `fixtures/demo.srt` es sintético y versionado.

## Endurecimiento (2º commit, D37 addendum)

1. **Lectura acotada** por chunks de 64 KiB con límite duro; `file.size` solo rechazo temprano.
2. **Duración validada**: cache reutilizado solo si reciente (mtime ≥ video) y finito > 0
   (rechaza NaN/Inf/0/negativo); si no ffprobe; si no `StudioSrtStorageError` (500). Nunca `0`.
3. **Idempotencia que verifica el storage**: hash + bytes del archivo administrado; si falta o
   está corrupto, lo REPARA (200, `repaired`).
4. **SHA256 completo** como basename → sin colisiones (`hash(archivo) == manifest.source_sha256`).
5. **Temporales únicos** (`mkstemp`) + fsync + `os.replace` con reintento anti-`PermissionError`
   de Windows (last-writer-wins, nunca parcial ni `.tmp`).
6. **Manifiesto público reconstruido por whitelist** (`sanitize_manifest`); contrato violado o
   ilegible → 500 sin filtrar. Errores del router no reflejan el `name`; resolver rechaza NUL.
7. **Saneamiento de VALORES** (3º commit): basenames que rechazan caracteres de control;
   `filename` basename; `encoding` en allowlist; `code` en el conjunto de S36-A; números
   semánticos (`n_cues≥1`, `end_ms≥start_ms`, `n_errors==0`, …); `status` exactamente `ready`.
   Cualquier valor manipulado → 500 y nunca se refleja en la respuesta.

## Tests

- `tests/test_studio_srt.py` — dominio (confinamiento, validación, almacenamiento por hash
  completo, integridad/reparación, atomicidad con temporales únicos y concurrencia, idempotencia,
  reemplazo, saneamiento por whitelist + validación de VALORES, independencia entre videos).
- `tests/test_studio_srt_api.py` — API (status HTTP, lectura acotada, cache de duración, errores
  públicos sin reflejar input, reflexión de valores manipulados, privacidad, mounts, historia
  intacta, sin jobs/render/Auto/Whisper).
- Suite total: **1385 passed, 1 warning** preexistente (`StarletteDeprecationWarning`).

## Fuera de alcance (S36-C2)

UI de selección, render con SRT, Auto v2, batch, edición de SRT en UI, QA específico de SRT,
forced aligner, templates 9:16.
