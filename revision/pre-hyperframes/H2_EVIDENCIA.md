# H2 — Evidencia de cierre (jobs y recuperación pre-HyperFrames)

**Base:** `4dab852185c8eb220c3da45e6af52cfd8610bb65` (merge PR #25, cierre H1). **Rama:** `fix/h2-jobs-resume`.
**PR abierto, NO mergeado.** **Alcance:** P1-POLL-1..4, P1-OUT-3, P2-POLL-5/6/7, P2-ATOM-STATE,
P2-CLASSIC-REUSE, P2-PAQUETE-DIR. **NO** H3/H4/H5/HyperFrames.

Todas las pruebas usan `TemporaryDirectory`/fixtures sintéticos, sin GPU ni red, y sin tocar
`input/0717_corregido.srt` (nunca se abre, imprime, hashea ni versiona). ffprobe se sustituye por
un stub en memoria (no invoca FFmpeg) en los tests de orquestación.

---

## Motor único de polling — `static/job_polling.js` (nuevo)

Reemplaza la lógica triplicada de `pollJob`/`pollJobP`/`_pollReframe`. Doble entorno
(`window.CentritoJobPolling` en navegador, `module.exports` en Node), sin bundler ni dependencias.
Una sesión por job con:
- `setTimeout` recursivo (nunca `setInterval`); a lo más **una** request activa por job;
- `AbortController`; cleanup garantizado (timer + controlador + entrada del mapa);
- **dedupe por job ID** (iniciar de nuevo cancela el seguimiento anterior);
- `deadlineMs` + `maxConsecutiveErrors` configurables; reset del contador tras éxito;
- cancelación local; reinicio explícito (`retry` re-consulta el MISMO job, sin crear otro);
- **resultado terminal estructurado** `{reason, job?, message}`.

Semántica de estados terminales (`done`, `job_error`, `lost`, `unavailable`, `timeout`,
`cancelled`, `invalid_response`):

| Respuesta | Terminal |
|-----------|----------|
| 200 + status done | `done` (limpia timer/controlador/mapa) |
| 200 + status error | `job_error` (conserva el mensaje saneado del job) |
| 404 | `lost` — "El servidor se reinició o el trabajo ya no existe." (sin reintento infinito) |
| 500/502/503/504 | reintenta hasta `maxConsecutiveErrors` → `unavailable` |
| error de red | mismo contrato de errores consecutivos → `unavailable` (no se confunde con 404) |
| JSON inválido / status desconocido | contador controlado → `invalid_response` (nunca colgado) |
| deadline excedido | `timeout` (NO declara que el worker fue cancelado) |
| cancelación | aborta fetch + limpia timer → `cancelled` (solo seguimiento LOCAL) |

**No** se creó endpoint backend para cancelar jobs (fuera de alcance).

## UI adaptada (`static/index.html`)

- `pollJob`: capa adapter sobre el motor; **fallo seguro por defecto** sin `onFailure` (entrega un
  job sintético `{status:'error'}` al callback → el control se re-habilita). Cierra P1-POLL-1 en los
  10 call sites.
- `pollJobP`: devuelve `{ok, reason, job?, message?}` (P2-POLL-7). Sus 2 consumidores
  (`transcribeFromRender`, `transcribeAndGenerateClips`) leen la causa exacta sin refetch.
- `_pollReframe`: reescrito sobre `trackJob` — **sin `setInterval`**, siempre re-habilita el botón,
  sin promesas rechazadas sin manejar (P1-POLL-2).
- `trackJob` + `renderJobFailureUI`: estado accionable compartido. Mientras corre marca el contenedor
  `role="status"`/`aria-live="polite"`; en terminal NO-job pinta `role="alert"` + botones:
  - `unavailable`/`invalid_response`: **Reintentar conexión** (mismo job) + **Cancelar seguimiento**;
  - `timeout`: **Seguir esperando** (deadline nuevo, sin crear job) + **Cancelar seguimiento**;
  - `lost`: aviso de reinicio + **Entendido** (sin reintento infinito, no relanza el job).
  Ningún botón afirma que se detuvo FFmpeg/el worker.
- Render y Auto usan el estado accionable; el resto de flujos hereda el fallo seguro por defecto.

## Resume profundo (P1-OUT-3) — `media_integrity.video_reanudable`

Wrapper fail-closed de `verificar_video` (H1): archivo regular + tamaño>0 + ffprobe + stream de
video + duración finita>0. Cableado en los 4 predicados:
`_clip_incompleto`, reutilización classic (`_renderizar_clip` + bucle de checkpoint),
checkpoint SRT y `auto_v2.checkpoint_v2_valido`. MP4 inexistente/0-byte/truncado/sin stream/
duración 0·NaN·Inf → re-render; checkpoint done + MP4 inválido → **no** se reutiliza; un clip
inválido **no** obliga a reprocesar los sanos. El archivo inválido **no** se borra automáticamente.

## Provenance classic (P2-CLASSIC-REUSE) — `auto_classic_provenance` (nuevo)

Procedencia `{schema_version, pipeline_mode=classic, filename, size_bytes, mtime_ns, lang, model}`.
`_asegurar_transcript` sella el bloque en `{name}_words.json`; `_asegurar_clips` usa un sidecar
`{name}_clips.provenance.json`. Reuso SOLO si coincide el video EXACTO + lang/model; procedencia
ausente/corrupta o video distinto (mismo stem) → retranscribe / re-ejecuta el clipper (fail-closed).
No se mezcla con SRT/v2. No calcula hash del video.

## Package marker (P2-PAQUETE-DIR) — `auto_classic.json` (nuevo)

`_paquete_dir` ya NO reanuda cualquier `{name}_*` sin `paquete.json`. Solo reanuda un dir que sea
hijo directo de `PAQUETES_DIR` (sin symlink que escapa), del video correcto, con marker
`auto_classic.json` legible (schema + `pipeline_mode=classic` + procedencia que coincide) y sin
`paquete.json` final. Dir manual sin marker / marker corrupto / de otro video / v2/SRT → paquete
nuevo (sin borrar el viejo). Nombre con precisión de **segundos** + sufijo único → dos corridas del
mismo minuto no comparten directorio.

## Atomicidad de recuperación (P2-ATOM-STATE) — `atomic_io` (nuevo)

`atomic_write_text`/`atomic_write_json`: temporal ÚNICO (mkstemp) en el mismo directorio + `flush`
+ `os.fsync` + `os.replace`; error → borra temporal y preserva el final anterior; dos writers al
mismo destino nunca colisionan. Aplicado a: `{name}_words.json`/`_groups.json` (classic),
`{name}_clips.json` (clipper), `{name}_clips.provenance.json`, checkpoint sidecar `*.info.json`,
marker `auto_v2.json`, marker `auto_classic.json`, `REPORTE.md`, `paquete.json` (unificado, ya era
atómico), transcript de clip del clipper, `{name}_limpio_words.json` (depurador), `_write_json_pair`.
**Residual P2 (documentado, NO tocado):** `.ass`, keyword sidecars y otros archivos que **no**
gobiernan resume.

## Tests

- **Motor JS real (`tests/job_polling_harness.cjs` + `test_h2_job_polling_js.py`):** 23 casos con
  fetch/timers/reloj/AbortController inyectables — done, job error, pending→running→done, 404 lost,
  500 recovery, 500→unavailable, red recovery, red→unavailable, JSON inválido (recupera y límite),
  status desconocido (recupera y límite), deadline, cancel, retry mismo job, dedupe, nueva sesión
  cancela anterior, no-overlap, timer limpio tras done/error, AbortController usado, reset tras
  éxito, job_error conserva causa.
- **Gate DOM (`test_h2_ui_polling.py`):** role=alert + botones por causa (Reintentar/Cancelar/Seguir
  esperando/Entendido), Reintentar re-consulta mismo job, lost sin reintento infinito, Cancelar no
  reintenta, `trackJob` marca `role=status/aria-live`. Aserciones estáticas: sin `setInterval`,
  motor compartido, `pollJobP` estructurado.
- **Python (`test_h2_resume_integrity.py`, `test_h2_classic_provenance.py`, `test_h2_paquete_marker.py`,
  `test_h2_atomic_io.py`):** 38 casos de resume/provenance/marker/atomicidad.
- Tests de orquestación existentes actualizados al nuevo contrato (procedencia sellada + marker +
  firma `_paquete_dir(name, video)`); ffprobe stub compartido en `conftest.py` (`ffprobe_ok`,
  `words_con_procedencia`).

## Smoke y suite

- `revision/pre-hyperframes/smoke_h2_jobs_resume.py --self-test` → **VERDE (2/2)**.
- `smoke_h2_jobs_resume.py` → `checks=12 blockers=0 fails=0 skips=0`, **exit 0** (A polling, B resume,
  C provenance, D package dir, E atomicidad).
- `smoke_pre_hyperframes.py --self-test` → **VERDE (20/20)**; `smoke_pre_hyperframes.py` →
  `checks=12 blockers=0 fails=0` (H1 intacto).
- `pytest` → **2224 passed, 4 skipped** (baseline H1: 2173/4). Los 4 skips son EXACTAMENTE los
  cuatro históricos de symlink (Windows sin privilegio); **cero skips nuevos**.
- `ruff check .` limpio · `ruff format --check .` (160 files) limpio · `git diff --check` limpio ·
  `check.bat` → `===== TODO OK =====`.

## Evidencia funcional (no versionada, bajo `output/revision-pre-hyperframes/h2/`)

- `smoke_h2_report.json` (matriz A–E).
- `ui_states_gate.txt` (role/mensaje/botones de `unavailable`/`timeout`/`lost`/`invalid_response` +
  `running`), generado ejecutando el bundle REAL de `index.html` en el sandbox `vm`. La salida
  audiovisual **no** cambia; el gate funcional/UX de los nuevos mensajes/botones **no** reclama
  aprobación visual de K.

## Fuera de alcance / residual

- Cancelación REAL del worker/FFmpeg en backend (H2 solo cancela el seguimiento local).
- Writers FFmpeg diferidos de H1 (`clipper`/`reframe`/`depurador`/`broll_*`/`submagic`/`auto_av`).
- Atomicidad de `.ass`/keyword sidecars (no gobiernan resume) → P2 residual.
- GC de temporales `.render_tmp` abandonados (documentado en H1).

## H3 / H4 / H5 / HyperFrames

**No iniciados.**
