# H2 — Inventario obligatorio (jobs y recuperación pre-HyperFrames)

**Base:** `4dab852185c8eb220c3da45e6af52cfd8610bb65` (merge PR #25, cierre H1). **Rama:** `fix/h2-jobs-resume`.
**Alcance H2:** P1-POLL-1..4, P1-OUT-3, P2-POLL-5/6/7, P2-ATOM-STATE, P2-CLASSIC-REUSE, P2-PAQUETE-DIR.
Inventario tomado ANTES de modificar. Evidencia `archivo:línea` sobre el árbol base.

---

## 1. Funciones de polling (todas viven en `static/index.html`)

| Símbolo | Línea | Timer | Maneja `!r.ok` | Maneja excepción | Deadline | Límite errores |
|---------|-------|-------|----------------|------------------|----------|----------------|
| `pollJob(jid, cb, interval=900, onFailure=null)` | 1268 | `setTimeout` recursivo | sólo si `onFailure` (:1272) | sólo si `onFailure` (:1276) | ❌ | ❌ |
| `pollJobP(jid, onTick, interval=900)` | 2118 | `setTimeout` recursivo | `resolve(false)` sin causa (:2123) | `resolve(false)` (:2129) | ❌ | ❌ |
| `_pollReframe(jobId, stem, btn, statusDiv, outFile)` | 1883 | **`setInterval` fugado** | ❌ (`.json()` directo :1886) | ❌ (promesa rechazada) | ❌ | ❌ |

Backend del job: `/api/jobs/{job_id}` (`app.py:997`) → 404 si no existe; job = `{status,progress,message,result,error}` (`jobs_registry.py:20`). Jobs sólo en memoria, threads `daemon` → un reinicio del server vuelve 404 permanente cualquier job `running`.

## 2. Call sites de polling

### `pollJob` (10 call sites; sólo **1** pasa `onFailure`)
| # | Línea | Flujo | Control original | Estado done | Estado error | Queda disabled tras fallo silencioso |
|---|-------|-------|------------------|-------------|--------------|--------------------------------------|
| 1 | 1017 | `srtPanel.transcribe` | `_msg` (sin botón) | msg ok | msg err | n/a |
| 2 | 1248 | `startTranscribe` | `btn` (transcribe) | msg + loadVideos | re-habilita btn | **sí** (spinner infinito) |
| 3 | 1446 | `analyzeIA` (editor) | `analyze-btn` | re-habilita | re-habilita | **sí** |
| 4 | 1502 | `runDepurar` | `box` (sin btn) | msg ok | msg err | n/a |
| 5 | 1635 | `startRender` | `render-btn` | re-habilita + preview | re-habilita | **sí** |
| 6 | 1678 | `analyzeFromRender` | statusDiv | encadena render | msg err | n/a |
| 7 | 1797 | `startClips` | `clips-btn` | re-habilita | re-habilita | **sí** |
| 8 | 1973 | `startAuto` | controles Auto | desbloquea | desbloquea + Reintentar | **NO** (único con `onFailure`, :1988) |
| 9 | 2240 | `transcribeAndGenerateClips` fase 2 | `clips-btn` | re-habilita | re-habilita | **sí** |
| 10 | 2457 | `startSubmagic` | `submagic-btn` | re-habilita | re-habilita | **sí** |

### `pollJobP` (2 call sites; colapsa 404/500/red en `false` sin causa → POLL-7)
| # | Línea | Flujo | Consumidor del `false` |
|---|-------|-------|------------------------|
| 1 | 2164 | `transcribeFromRender` | msg genérico "Error en transcripcion" |
| 2 | 2206 | `transcribeAndGenerateClips` fase 1 | intenta refetch del job (:2216) para el mensaje |

### `_pollReframe` (2 call sites)
| # | Línea | Flujo |
|---|-------|-------|
| 1 | 1915 | `startReframe` layout=stack |
| 2 | 1938 | `startReframe` tracking/ema |

Doble polling posible (POLL-5): ningún call site cancela un seguimiento previo del mismo control; re-lanzar una acción (o cambiar de pestaña y volver) puede crear timers concurrentes. Sin dedupe por job ID ni `AbortController`.

## 3. Predicados de resume

| Predicado | Archivo:línea | Valida output | Contrato |
|-----------|---------------|---------------|----------|
| `_clip_incompleto(info, paquete_dir)` | `auto.py:104` | sólo `final_path.exists()` (:120) | selecciona paquete v2/parcial a reanudar |
| Reutilización classic (`final_path.exists()`) | `auto.py:457` | sólo `exists()` | rama classic en `_renderizar_clip` |
| Reutilización SRT (checkpoint) | `auto.py:546` | `final_path.exists()` + status≠error | bucle resume `es_srt` |
| `checkpoint_v2_valido(...)` | `auto_v2.py:62` | sólo `final_path.exists()` | reuso v2 |
| `_asegurar_transcript` | `auto.py:53-54` | `exists()` + `mtime>=video` | reuso words |
| `_asegurar_clips` | `auto.py:76-77` | `exists()` + `mtime>=video` | reuso clips.json |
| `_paquete_dir` classic | `auto.py:90-97` | dir sin `paquete.json` = interrumpido | selección de paquete classic |
| `_cargar_checkpoint` | `auto.py:212` | JSON legible o None | robustez checkpoint |

**Ninguno** exige `st_size>0` ni ffprobe → P1-OUT-3 (un MP4 0-byte/truncado con nombre final se conserva "ya listo"). H1 cerró la PUBLICACIÓN atómica (`media_integrity.publicar_mp4_atomico`) pero el RESUME sigue confiando en `exists()`.

## 4. Escrituras que afectan recuperación

| Escritura | Archivo:línea | Atómica hoy |
|-----------|---------------|-------------|
| `{name}_words.json` + `_groups.json` (classic) | `auto.py:62-65` | ❌ write directo |
| `{name}_clips.json` (clipper) | `clipper.py:592` | ❌ write directo |
| checkpoint sidecar `*.info.json` | `auto.py:568` | ❌ write directo |
| marker `auto_v2.json` | `auto.py:193` | ❌ write directo |
| `REPORTE.md` | `auto.py:588` | ❌ write directo |
| `paquete.json` | `auto.py:593-598` | ✅ tmp + `os.replace` (conservar) |
| transcript clip (`{stem}_words/groups`) | `clipper.py:257,261` | ❌ write directo |
| `{name}_limpio_words.json` (depurador) | `jobs.py:144` | ❌ write directo |
| transcript worker (`_write_json_pair`) | `jobs.py:23-34` | ✅ tmp + replace (pareja) |
| artefactos SRT | `auto_srt_artifacts.py:101` | ✅ `_atomic_write_text` |
| manifiesto SRT | `auto_srt_manifest.py:119` | ✅ tmp + replace |

Helpers atómicos ya existentes (fragmentados, sin fuente única): `clipper._atomic_write_text`, `auto_srt_artifacts._atomic_write_text`, `srt_serialize._atomic_write_text`, `srt_tool._atomic_write`, `auto_broll_io`/`broll_plan_io` (mkstemp único), `studio_keywords` (mkstemp), `jobs._write_json_pair`. **La mayoría usa sufijo `.tmp` fijo (no único) → dos writers concurrentes al mismo destino colisionan.**

## 5. Reutilización de información por stem/exists/mtime/fingerprint

| Punto | Archivo:línea | Base de decisión | Riesgo |
|-------|---------------|------------------|--------|
| transcript classic | `auto.py:53-54` | `stem`+`mtime>=video` | mismo stem, video distinto de igual/menor mtime → reusa transcript ajeno (P2-CLASSIC-REUSE) |
| clips classic | `auto.py:76-77` | `stem`+`mtime>=video` | idem para el análisis del clipper |
| `_paquete_dir` classic | `auto.py:91-97` | glob `{name}_*` sin `paquete.json` | reanuda **cualquier** dir manual sin marker (P2-PAQUETE-DIR) |
| SRT/v2 | provenance + fingerprint + TOCTOU | **OK** (no tocar, ya validado en H1/S36) | — |

---

## Clasificación

### DENTRO de H2 (se implementa aquí)
- **P1-POLL-1** fallo silencioso sin `onFailure` → motor con fallo por defecto seguro (Fase 2-3).
- **P1-POLL-2** `_pollReframe` sin try/catch/`r.ok`, intervalo fugado → motor compartido (Fase 3).
- **P1-POLL-3** sin deadline ni límite de errores → `deadlineMs` + `maxConsecutiveErrors` (Fase 2).
- **P1-POLL-4** jobs perdidos tras reinicio → estado `lost` + Reintentar/Cancelar (Fase 4).
- **P1-OUT-3** resume acepta MP4 0-byte/truncado → `video_reanudable` fail-closed en los 4 predicados (Fase 6).
- **P2-POLL-5** polling duplicado/timers concurrentes → dedupe por job ID + cleanup (Fase 2).
- **P2-POLL-6** estados sin accesibilidad → `role=status`/`aria-live`/`role=alert` (Fase 4).
- **P2-POLL-7** `pollJobP` pierde la causa → resultado estructurado `{ok,reason,job,message}` (Fase 3).
- **P2-ATOM-STATE** escrituras no atómicas de recuperación → `atomic_io` (Fase 9).
- **P2-CLASSIC-REUSE** reuso classic por stem/mtime → procedencia explícita (Fase 7).
- **P2-PAQUETE-DIR** classic reanuda cualquier dir sin marker → `auto_classic.json` (Fase 8).

### YA CERRADO por H1 (se reutiliza, no se reabre)
- `media_integrity.verificar_video` / `publicar_mp4_atomico` / `ruta_temporal` (publicación atómica del MP4 final; P1-OUT-1/2).
- `paquete.json` atómico (`auto.py:593-598`) — se conserva y se añade regresión.
- `path_safety.is_safe_basename` — guard de nombres.
- Contratos SRT/v2 (fingerprint + provenance + TOCTOU) — intactos.

### DIFERIDO a H3/H4/H5 (no se toca en H2)
- Preflight FFmpeg/ffprobe, descarga de modelos, guards de `arranque.bat`, puerto → **H3**.
- Docs (ESTADO/DECISIONES/PREGUNTAS/ALPHA/README) → **H4**.
- CI remoto → **H5**.

### FUERA DE ALCANCE (documentado, no se implementa)
- Cancelación REAL del worker/FFmpeg en backend (H2 sólo cancela el seguimiento local).
- Endurecer todos los writers FFmpeg diferidos de H1 (`clipper`, `reframe*`, `depurador`, `broll_*`, `submagic`, `auto_av`).
- Atomicidad de `.ass`, keyword sidecars y otros archivos que NO controlan resume → P2 residual documentado.
- GC de temporales `.render_tmp` abandonados (documentado en H1).
