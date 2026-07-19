# CHECKLIST TÉCNICO — S36-C1

Rama: `feat/s36-c1-studio-srt-backend` · D37 · PR abierto, NO mergeado.

## Seguridad / confinamiento
- [x] Traversal POSIX rechazado (`a/b`, `/etc/passwd`, `..`)
- [x] Traversal Windows rechazado (`a\b`, `C:video`, `C:\video`, UNC `\\srv\share`)
- [x] Nombre vacío rechazado
- [x] Solo basename (`Path(name).name == name` y `PureWindowsPath(name).name == name`)
- [x] `resolve()` + `relative_to(root)` confina dentro de `input/`
- [x] Symlink que escapa de `input/` no resuelve dentro (test tolerante a entorno sin symlinks)
- [x] Extensión `.srt` case-insensitive; MIME NO es autoridad

## Validación del SRT (reutiliza S36-A)
- [x] Fachada `srt_import` (no se importan submódulos)
- [x] Límite de bytes → `StudioSrtTooLarge` (413)
- [x] Decodificación UTF-8 / BOM / cp1252
- [x] Validación estructural + contra duración real del video
- [x] Warnings NO abortan; errors abortan; sin cues utilizables aborta
- [x] Cue después del video → warning (no aborta)
- [x] Bytes originales preservados; SHA256 sobre bytes originales
- [x] Entrada no mutada

## Almacenamiento / asociación
- [x] Almacenamiento por hash COMPLETO `transcripts/studio_srt/{stem}/{sha256}.srt`
- [x] `hash(archivo) == manifest.source_sha256` siempre (sin colisiones de prefijo)
- [x] `managed_file` es basename (sin `/` ni `\`)
- [x] Manifiesto v1 `transcripts/{stem}_srt_selection.json`
- [x] Un SRT seleccionado por video; asociación explícita; sin autodiscovery
- [x] Idempotencia: mismo SHA → no duplica, 200
- [x] Reemplazo: SHA distinto → 201, selección anterior no se borra
- [x] Escritura atómica (tmp + fsync + `os.replace`); no quedan `.tmp`
- [x] Fallo antes del manifiesto conserva la selección previa
- [x] Delete solo desasocia; idempotente; no borra archivos administrados
- [x] Dos videos → asociaciones independientes

## Privacidad
- [x] Manifiesto sin texto de cues
- [x] Manifiesto sin rutas absolutas ni `managed_path`
- [x] Diagnósticos solo `{code, severity, cue_position, cue_index}` (sin `message`)
- [x] `transcripts/` no montado; `/input|/output|/clips|/static` no sirven el SRT administrado
- [x] No existe endpoint de descarga del SRT

## HTTP
- [x] 200 GET capabilities / GET selección / idempotente / delete
- [x] 201 nueva selección / reemplazo
- [x] 400 SRT inválido · 404 video inexistente · 413 límite · 415 extensión
- [x] 500 solo para fallo de almacenamiento, sin filtrar detalles

## Compatibilidad
- [x] `/api/videos`, `/api/auto/capabilities`, `/api/styles` intactos
- [x] Ninguna operación inicia job/render/Whisper/Auto (sentinela sobre `jobs.new_job`)
- [x] `static/index.html` intacto; motores protegidos intactos

## Arquitectura / límites
- [x] `studio_srt.py` (328 L) + `studio_srt_manifest.py` (204 L) puros, sin FastAPI (<=400 líneas)
- [x] `studio_srt_routes.py` APIRouter separado
- [x] Sin dependencias nuevas
- [x] Errores tipados (no strings para decidir status)
- [x] `app.py`: solo import + `include_router` + delegación del resolver al helper puro

## Endurecimiento (2º commit, D37 addendum)
- [x] Lectura acotada por chunks (64 KiB), límite duro aun sin `file.size`
- [x] Acepta exactamente `MAX_SRT_BYTES`; rechaza `+1` con 413 antes de parse/store
- [x] `file.size` mentiroso menor no evade el límite real
- [x] Cache de duración solo si reciente (mtime ≥ video) y finito > 0
- [x] Rechaza NaN/Infinity/0/negativo/bool/str; fallback a ffprobe; si no, 500 genérico
- [x] Nunca valida el SRT con `duration=0`
- [x] Idempotencia verifica archivo administrado (existe, regular, confinado, hash+bytes)
- [x] Reparación atómica si el archivo falta/está corrupto/basename inseguro (200, `repaired`)
- [x] Basename por SHA256 completo; colisión de contenido ajeno rechazada por `_managed_file_ok`
- [x] Temporales únicos por operación (`mkstemp`); no compartidos entre threads
- [x] `os.replace` con reintento anti-`PermissionError` (Windows); last-writer-wins completo
- [x] Concurrencia: dos escrituras al mismo target → payload completo, nunca parcial, sin `.tmp`
- [x] Manifiesto público reconstruido por whitelist; contrato violado/ilegible → 500 sin filtrar
- [x] Errores del router no reflejan el `name`; resolver rechaza NUL/control (antes 500)

## Verificación
- [x] `ruff check .` verde · `ruff format --check .` verde
- [x] 1355 passed, 1 warning preexistente · `check.bat` verde
- [x] 7 tests de bloqueantes verificados ROJOS contra HEAD d63d69f, verdes con el nuevo código
- [x] Fixture + smoke API sintético PASS (incl. reparación, hash match, whitelist, lectura acotada)
- [x] Working tree sin binarios ni datos privados
