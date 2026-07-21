# Auditoría Pre-HyperFrames — Readiness + Hardening de v1

**Base:** `4a378d82814b46e680cda894377b82b8eeba327d` (merge PR #23, cierre F6 esencial).
**Rama:** `chore/pre-hyperframes-readiness`.
**Suite baseline:** `1894 passed, 3 skipped` (1897 colectados). ruff / format / check.bat verdes.
**Alcance:** revisión de todo el producto v1 para detectar bloqueos reales antes de HyperFrames. **No** se implementan features nuevas ni HyperFrames/F7.

> Nota de privacidad (corregida en review): el **primer** arnés de smoke tenía un defecto de
> aislamiento detectado en la revisión del PR (creaba el `TestClient` con la app apuntando a los
> directorios **reales** del repo, de modo que `GET /api/videos` podía leer metadata local). No se
> observó ni imprimió deliberadamente contenido privado, pero la afirmación absoluta original —"la
> auditoría nunca tocó rutas reales"— **no** era demostrable y se retira. El arnés corregido
> (`smoke_pre_hyperframes.py`, `harness: sandboxed-v2`) monta la app sobre un **sandbox temporal
> completo** (globals + mounts redirigidos a un `TemporaryDirectory`), usa centinelas **sintéticos**
> (`_SMOKE_PRE_HF_SENTINEL`, `texto-sintetico-de-prueba-no-privado`) y añade una **defensa por
> snapshot** (metadata-only, sin leer contenido) que **falla** si el arnés crea/borra/modifica algún
> archivo fuera del sandbox salvo el reporte de evidencia. La corrida confirmada reporta
> `aislamiento_datos_reales = PASS` (cero cambios en `input/`, `transcripts/`, `output/`, `thumbs/`,
> `static/`). En ningún momento se abre, imprime ni versiona `input/0717_corregido.srt`.

---

## Método

Cinco auditorías de dominio en paralelo (docs, jobs/polling, arranque/deps, privacidad/seguridad, integridad de outputs/resume), cada una con evidencia `archivo:línea`. Los hallazgos P0 se **reprodujeron** manualmente antes de clasificarlos.

---

## Veredicto de alcance: **CASO B (hallazgos dispersos)**

Se encontraron **4 P0** (uno reproducido como escritura arbitraria fuera del sandbox; el cuarto es exposición de recursos privados en LAN sin autenticación, elevado a P0 en review) y **~9 P1** repartidos entre seguridad, jobs/UI, arranque e integridad del render. No es un bloque cohesivo → **no** se implementan fixes en esta rama; se entrega el plan ordenado `PLAN_DE_PR.md` (PR-H1..H5). Verdict de readiness: **NO LISTO**.

---

## P0 — Bloqueos (pérdida de datos / exposición privada / ejecución insegura)

### P0-1 · Path traversal (lectura Y escritura) en endpoints `{name}` sin `is_safe_basename` — **DEMOSTRADO**
- **Archivos/símbolos:** `app.py` — `upload_video` (:151), `get_transcript` (:226), `save_transcript` (:234), `get_brain` (:256), `save_brain` (:264), `start_transcribe` (:165), `start_analyze` (:245), `start_depurar` (~:309), `start_clips` (~:327), `detectar_caras_clip`/`start_reframe` (~:364/:393), `save_turnos_clip` (~:379). El guard `studio_srt_manifest.is_safe_basename` sólo se aplica en 5 sitios (`app.py:197,288,299,572,724`); el resto interpola `{name}` crudo en la ruta.
- **Flujo afectado:** Studio web (transcript/brain/upload/render). El server escucha en `0.0.0.0:8787` (`app.py:841`) **sin auth/CORS/Depends** → alcanzable desde toda la LAN.
- **Reproducción (verificada con TestClient):**
  ```
  PUT /api/videos/..%5C..%5C_TRAVERSAL_SENTINEL/transcript   (body JSON)
  → 200 OK
  → escribió <REPO_PARENT>/_TRAVERSAL_SENTINEL_groups.json   (FUERA del repo, un nivel arriba de la raíz)
  ```
  En Windows `%5C` (backslash) atraviesa el routing de FastAPI; `Path('transcripts') / '..\\..\\x'` escapa el sandbox. NUL byte (`%00`) también pasa el routing.
- **Riesgo:** escritura arbitraria de `*_groups.json` / `*.brain.json` fuera de `transcripts/` (sobrescritura de archivos existentes) + lectura reflejada de cualquier `*_groups.json`/`*.brain.json` del disco vía la respuesta JSON. Sin auth, en red local.
- **Fix mínimo:** guard `is_safe_basename(name)` (o un `Depends` compartido / middleware) al inicio de **cada** endpoint `{name}`. El validador ya existe (`studio_srt_manifest.py:51`) y rechaza separadores POSIX/Windows y caracteres de control.
- **Tests requeridos:** por cada endpoint, `..\`, `../`, ruta absoluta y NUL → 404; nombre válido → 200. Test de que ningún archivo se escribe fuera de `TRANSCRIPTS`.
- **UI/AV:** no. **Bloquea HyperFrames:** sí (exposición en alpha con red). **PR:** H1.

### P0-2 · `upload_video` usa `file.filename` crudo + sin límite de tamaño/extensión — **DEMOSTRADO (código) / P1 DoS**
- **Archivo/símbolo:** `app.py:151-161` (`upload_video`). `dest = INPUT_DIR / file.filename` (:153) con `file.filename` del header multipart (Starlette **no** lo sanitiza); `shutil.copyfileobj` (:155) copia sin tope de bytes; sin validación de extensión.
- **Reproducción:** `filename="..\\..\\x.mp4"` → escribe fuera de `input/` (mismo mecanismo que P0-1). Body enorme → llena disco.
- **Riesgo:** escritura fuera del sandbox; DoS por disco.
- **Fix mínimo:** validar basename (`is_safe_basename(file.filename)`), forzar `.mp4/.mov`, escribir por chunks con tope de bytes (patrón ya presente en `studio_srt_routes.py:57-75`, `_read_upload_limited`), idealmente `.tmp` + `os.replace`.
- **Tests:** filename con traversal → 400; upload > límite → 413/400.
- **UI/AV:** no. **PR:** H1.

### P0-3 · Texto privado de captions/SRT servido por el mount público `/output` — **DEMOSTRADO**
- **Archivos/símbolos:** mount `/output` = `_OutputSinPaquetes` (`app.py:71`), que **sólo** bloquea el subárbol `paquetes/` (`app.py:59-67`). Se sirven sin auth:
  - `.ass` con todos los cues como `Dialogue` (`core_ass.py:281-289`), escrito a `OUTPUT_DIR/{name}...ass` (`jobs_render.py:72,369`; `caption.py:268,361`). En render `caption_source=srt` ese texto proviene del **SRT privado**.
  - `.keyword_selection.json` con `"palabra"`/`"frase"` completas (`cve_sidecar.py:22-55`), escrito a `OUTPUT_DIR/{stem}...keyword_selection.json` (`cve_sidecar.py:68`).
- **Reproducción:** tras un render, `GET http://<host-lan>:8787/output/<stem>_<preset>.ass` (o `..._keyword_selection.json`) devuelve el texto a cualquiera en la LAN.
- **Riesgo:** exposición de contenido privado derivado del SRT/transcripción; contradice el `.gitignore` que marca `output/` como privado local.
- **Fix mínimo (una opción):** (a) escribir `.ass`/`.keyword_selection.json` fuera del árbol servido (a `transcripts/` como ya se hace con `_srt_alignment.json`, o a `output/_internal/`), **o** (b) restringir `/output` a servir sólo `.mp4` (404 en `.ass`/`.json`/no-video sobre la ruta completa).
- **Tests:** `GET /output/x.ass` → 404; el binario `.mp4` sigue accesible.
- **UI/AV:** no (mueve/oculta archivos, no cambia el render). **PR:** H1.
- **OK relacionado (no hallazgo):** el sidecar `_srt_alignment.json` (incluye texto de cues) se escribe en `TRANSCRIPTS` (`jobs_render.py:344`), que **no** está montado. Correcto.

### P0-4 · Exposición de recursos privados y derivados en LAN sin autenticación — **DEMOSTRADO (código + probe)**
- **Clasificación:** hallazgo **independiente** (no es sólo el texto de captions de P0-3: cubre el binario **fuente**, miniaturas y clips además de los derivados). Elevado a **P0** por afectar privacidad real. P0-3 sigue acotado al texto de captions/SRT servido por `/output`; P0-4 es el vector de red que lo hace alcanzable + los otros mounts.
- **Archivos/símbolos:**
  - Mounts públicos **sin auth**: `/input` (`app.py:70`, binario fuente crudo), `/output` (`app.py:71`, renders + `.ass`/`.json` de P0-3), `/clips` (`app.py:72`), `/thumbs` (`app.py:73`).
  - Bind a **todas** las interfaces: `arranque.bat:9` (`uvicorn app:app --host 0.0.0.0 --port 8787 --reload`) y `app.py:841` (`uvicorn.run(..., host="0.0.0.0", ...)`).
  - **Sin** `CORSMiddleware`, `Depends`, token ni `Authorization` en toda `app.py` (grep = 0 coincidencias).
- **Reproducción (probe sintético, sandboxed):** `GET /input/<src>.mp4` → 200 sirviendo el binario fuente byte-a-byte (`input_no_expuesto_lan = BLOCKER`). El mismo mecanismo aplica a `/thumbs`, `/clips` y `/output`.
- **Riesgo:** cualquier dispositivo en la red local (Wi-Fi compartida, coworking, café) puede enumerar y descargar **videos fuente, miniaturas, clips, renders y el texto/JSON derivado** apuntando al `:8787` del equipo. No hay barrera de aplicación.
- **Fix mínimo (H1, NO implementado aquí):**
  1. **Default obligatorio a `127.0.0.1`** en `arranque.bat` y `app.py.__main__`.
  2. Acceso LAN sólo por **opt-in explícito** (variable/flag documentada, p.ej. `CENTRITO_HOST=0.0.0.0`).
  3. Si en el futuro se permite LAN: **warning visible** + autenticación/token + **no** montar rutas privadas + endpoints de binarios con **allowlist**.
  4. **Quitar** el mount público `/input` (o reemplazarlo por un endpoint validado si la UI necesita reproducir la fuente).
  5. Revisar `/thumbs` y `/clips` con el mismo criterio.
  6. `/output` debe servir **únicamente** tipos explícitamente permitidos (cierra P0-3 de raíz).
- **Tests requeridos:** default de host = loopback; con opt-in, warning emitido; `GET /input/*` no accesible sin el endpoint validado; `/output` sólo `.mp4`.
- **UI/AV:** no. **Bloquea HyperFrames:** sí (alpha con red = fuga de material privado). **PR:** H1.

---

## P1 — Rompe un flujo principal / deja jobs colgados / outputs falsamente publicables / impide diagnosticar

### Jobs / Polling (spinner infinito silencioso) — **DEMOSTRADO**

**P1-POLL-1 · `onFailure` nunca se pasa → 8 flujos quedan colgados en silencio**
- `static/index.html:1268` (`pollJob`) maneja fallo **sólo** si recibe `onFailure` (:1272 `if(!r.ok){if(onFailure)onFailure(...);return;}`, :1276 catch). Ninguno de los 8 call sites (1017,1248,1446,1502,1635,1678,1797,1973) lo pasa → `onFailure` siempre `null`.
- **Repro:** lanzar render → reiniciar server / caer red mientras `running` → `fetch` da 404 → entra por :1272 → `return` sin re-agendar → polling muere; barra congelada, botón `disabled` para siempre.
- **Fix:** comportamiento de fallo por defecto en `pollJob` (invocar `cb({status:'error',message:'Se perdió la conexión…'})`) sin depender de `onFailure`. **PR:** H2.

**P1-POLL-2 · `_pollReframe` hace `.json()` sin `try/catch` ni `r.ok` → `setInterval` fugado infinito**
- `static/index.html:1885-1886`. 404 → `.json()` lanza → promesa rechazada sin manejar; `clearInterval` sólo en done/error → el intervalo dispara cada 2 s para siempre. **Fix:** try/catch + `r.ok` + `clearInterval` + error accionable. **PR:** H2.

**P1-POLL-3 · Sin timeout ni límite de errores consecutivos → worker colgado = spinner eterno**
- `pollJob` (1268-1279) y `pollJobP` (2118-2133) sólo salen con `done`/`error` del server. Un worker colgado (p.ej. `run_submagic_render` esperando URL, `jobs.py:361`) mantiene `running` sin fin. **Fix:** `deadlineMs` + contador `maxFallos`. **PR:** H2.

**P1-POLL-4 · Sin estado "servidor reiniciado/job perdido" ni Reintentar/Cancelar**
- Jobs viven en memoria (`jobs_registry.py:12`, threads `daemon=True`); al reiniciar el server, un job `running` se vuelve 404 permanente. El frontend no distingue "perdido por reinicio" (recuperable) de error, ni ofrece Reintentar/Cerrar. **Fix:** estado dedicado ante 404 + botones. **PR:** H2.

### Integridad de outputs / resume — **DEMOSTRADO**

**P1-OUT-1 · Ningún output se valida por `size>0` / ffprobe / duración**
- `burn_video`/`burn_video_with_emojis` (`core_ass.py:333,420`) retornan tras returncode 0 sin verificar el archivo; el job pasa a `done` con sólo eso (`jobs_render.py:261,389`); `paquete_editor.py:335` marca disponible con `is_file()`; `studio_packages.py:106` sirve con `is_file()`+`.mp4`. Un MP4 de 0 bytes/parcial (returncode 0 con disco lleno, o proceso muerto) se marca **publicable**.
- **Fix:** tras quemar, exigir `is_file() and st_size>0` + ffprobe (`duration>0` y stream de video); si falla, borrar parcial y `raise`. **PR:** H1 (integridad).

**P1-OUT-2 · FFmpeg escribe DIRECTO al nombre final (no tmp+rename)**
- `core_ass.py:328,400-414`. Interrupción durante el quemado (cierre de ventana/corte de luz, escenario explícito del proyecto) deja un MP4 truncado **con el nombre final** (`auto.py:200-204`). El resume lo da por bueno (ver P1-OUT-3).
- **Fix:** quemar a `*.mp4.part` y `os.replace` al nombre final **sólo** tras validar returncode+size+ffprobe. Cierra P1-OUT-1/2/3 de raíz. **PR:** H1.

**P1-OUT-3 · Resume acepta output 0-byte/truncado (sólo `exists()`)**
- Gates de reanudación: classic `auto.py:457`, SRT `auto.py:546`, v2 `auto_v2.py:62`, selección `_clip_incompleto` `auto.py:119`. Ninguno chequea `st_size>0`. Un truncado se conserva "ya listo". **Fix:** añadir `st_size>0` (idealmente ffprobe) a los 4 predicados; se resuelve con el tmp+rename de P1-OUT-2. **PR:** H2 (recuperación).

### Arranque / diagnóstico

**P1-BOOT-1 · FFmpeg/ffprobe faltante revienta con traceback críptico; sin preflight**
- No hay `shutil.which("ffmpeg")` en el arranque. `core.py:108-122` (`get_video_info`) hace `json.loads(probe.stdout)` sobre stdout vacío → `JSONDecodeError` que no menciona FFmpeg; `_probe_volume` (`core.py:70-86`) sin try/except → `FileNotFoundError [WinError 2]` crudo. Es el fallo más común de un entorno nuevo y hoy es indiagnosticable.
- **Fix:** preflight `shutil.which` en el startup de `app.py` con mensaje accionable ("FFmpeg no está en PATH — `choco install ffmpeg`; captions/reframe quedan deshabilitados") sin tumbar la UI. **PR:** H3.

**P1-BOOT-2 · Modelos yunet/blazeface gitignoreados sin descarga real (clone limpio falla críptico)**
- `.gitignore` excluye `models/` y `referencia/yunet/` con el comentario "se descargan en primer uso", pero **no existe** código de descarga (grep `download|hf_hub_download|snapshot_download` sin resultados en `reframe_detect.py`). En clone limpio: `reframe_detect.py:190-192` cae a BlazeFace; si tampoco está, `FileNotFoundError` (:165-166) **sin URL**. En la máquina actual los archivos existen (P3 aquí; P1 en clone).
- **Fix:** documentar URLs+ruta en README/ENTORNO, o autodescarga con verificación de hash; como mínimo incluir la URL en el `FileNotFoundError`. **PR:** H3.

---

## P2 — UX / documentación / compatibilidad / deuda que no rompe el flujo principal

### Documentación desactualizada (núcleo del desfase)
- **D40-01** `ESTADO.md:2` — "PR #23 **autorizado para merge**" (está MERGEADO en `4a378d8`).
- **D40-02** `ESTADO.md:2` — "Suite **1894 passed**" es válido como cierre pero el doc convive con "1838" en D40. Real actual: 1894/3-skip (1897 colectados).
- **D40-03/04** `ESTADO.md:41,42` (bitácora) — "PR #23 sigue ABIERTO, NO mergeado / PENDIENTE veredicto de K". No hay entrada que registre el merge.
- **D40-05** `DECISIONES.md:1608,1611` (bloque D40) — "suite 1838" + "PR abierto, NO mergeado: pendiente veredicto visual de K". El addendum (1613-1621) no actualiza estado ni número.
- **S36-01** `PREGUNTAS.md:1053-1055` (#52) — "S36-C2C PR #22 ABIERTO… gate final PENDIENTE" (está MERGEADO `aa1790a`, S36 COMPLETA).
- **S36-02** `PREGUNTAS.md:1070-1073` — "PR queda abierto y no cierra S36-C2A1" (cerrada, PR #18 `d6db673`).
- **FALT-01** `ESTADO.md:17` — lista "Falta: spans #34 + avoid_faces/[center] + cve_presets.json…" (todo mergeado en F6).
- **FALT-02** `ESTADO.md:29` — "F5-s2, F6, reframe v2 y S36-B/C siguen pendientes" (S36-B/C y F6 esencial completas; sólo F6-Motor B y reframe v2 siguen).
- **PREGUNTAS-TAXONOMIA** — `PREGUNTAS.md` mezcla decisiones cerradas / triggers futuros / deudas activas sin marca de estado por ítem.
- **README-157** `README.md:96` — "157 tests" (real ~1897).
- **ALPHA-01..07** `docs/ALPHA_TESTERS.md` — describe una foto anterior a S36/S37/F6: no menciona SRT (01), Auto v2/b-roll/A-V (02), F6/CVE presets/avoid_faces (03), "Reanudar clips fallidos" (04); límites multi-persona más pesimistas que el producto (05); ComfyUI **sí** está bien cubierto (06, OK); falta versión/commit probado (07). No promete funciones inexistentes ni expone nada privado.

### Otros P2 (endurecimiento, no bloqueantes)
- **POLL-5** polling duplicado posible (sin dedupe de timers/AbortController), `static/index.html` `pollJob`/`_pollReframe`.
- **POLL-6** estados de job sin `aria-live`/`role=alert` (accesibilidad).
- **POLL-7** `pollJobP` colapsa 404/500/red en `false` sin causa (`static/index.html:2123,2129`).
- **BOOT-3** `arranque.bat:3` sin guard de venv (arranca con Python equivocado). `check.bat:9-12` sí lo tiene.
- **BOOT-4** puerto 8787 ocupado → traceback crudo; navegador abre antes del server (`arranque.bat:8-9`).
- **BOOT-5** sin validación de versión de Python (mediapipe pineado a 3.12).
- **BOOT-6** `check.bat` verde no cubre FFmpeg/modelos/Python.
- **ATOM-STATE** escrituras de estado no atómicas: checkpoint sidecar (`auto.py:568`), REPORTE.md (`auto.py:588`), marker `auto_v2.json` (`auto.py:193`), transcript classic (`auto.py:62-65`), clips (`clipper.py:257,592`), `{name}_limpio_words.json` (`jobs.py:144`), `.keyword_selection.json` (`cve_sidecar.py:69`), `.ass` (`core_ass.py:289`). El repo ya tiene `_atomic_write_text`/mkstemp+replace para reusar. Prioridad: checkpoint sidecar (insumo del resume).
- **CLASSIC-REUSE** Auto classic reusa transcript/clips por `stem`+`mtime` sin fingerprint de contenido (`auto.py:53-54,76-77`). Teórico (requiere manipular mtime); no contamina SRT/v2/Studio (que sí validan procedencia).
- **PAQUETE-DIR** `_paquete_dir` classic considera "interrumpido" cualquier dir sin `paquete.json` (`auto.py:91-97`).
- **SYMLINK-MOUNT** los mounts `/input` `/output` siguen symlinks (Starlette); teórico, no hay creación de symlinks en el pipeline.

---

## P3 — Mejora futura / feature nueva (clasificar, NO implementar)
HyperFrames, F7, Telegram/publicación, presets 6–12, marca M2/M3, detector full-range, selección manual de caras, Multi V2 por segmento, preview de 3 frames, aprobación/rechazo persistente, rerender selectivo desde Editor, edición de SRT en UI, forced aligner, batch genérico, extracción completa de `static/index.html`, recetas múltiples del Modo Automático. Ninguno bloquea la v1.
- **F6-NOMBRE** ambigüedad: "F6 esencial/CVE" (cerrada) vs "F6-Motor B/HyperFrames" (`MAESTRO.md`, pendiente). Ambos estados correctos; conviene anotar la colisión de nombres.
- **D40-MULTITURNOS-FACEY** `DECISIONES.md:1586` dice "ruta multi-cara por turnos v1 aún emite la columna vacía (fail-open)". **No verificado** contra `reframe.py`; no clasificar como cerrado sin confirmar en código.

---

## Fortalezas confirmadas (no re-arreglar)
- Fail-open uniforme y probado en DeepSeek, ComfyUI, Pexels, CVE: su ausencia nunca rompe flujos que no los requieren.
- Contrato SRT (S36) sólido: whitelist de manifiestos (`sanitize_manifest`), `managed_file` = `{sha256}.srt`, integridad por hash, procedencia video↔timings por filename+size+mtime, binding TOCTOU (`studio_srt_runtime.py:209-258`), namespace de artefactos por `sha256(filename)`.
- FFmpeg returncode **sí** se chequea (`core_ass.py:331,418`); clip en error nunca es publicable (`auto_srt_manifest.py:64-67`).
- Escrituras atómicas correctas en `paquete.json`, manifiestos SRT, artefactos por clip (`auto.py:593`, `auto_srt_manifest.py:114`, `auto_srt_artifacts.py:101`).
- Resume no reutiliza otro video/config en SRT/v2 (fingerprint + procedencia + TOCTOU); checkpoint corrupto manejado (no revienta) en las 3 rutas; no reprocesa clips sanos; no pierde el paquete anterior.
- Node correctamente opcional (sólo tests, con skip). CUDA→CPU fallback silencioso.
- Secretos: `.env` gitignoreado, keys nunca serializadas ni logueadas.
