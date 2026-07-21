# Matriz de Readiness Pre-HyperFrames

Base auditoría `4a378d8`. **H1 CERRADO EN MAIN — merge `4dab852`. H2 CERRADO EN MAIN — merge
`5779a77`. H3 (arranque/diagnóstico) cerrado en rama `fix/h3-arranque-diagnostico`, PENDIENTE
MERGE.** Suite tras H3: `2314 passed, 4 skipped` (4 skips = los cuatro históricos de symlink).
Detalle y evidencia en `AUDITORIA.md` / `H3_EVIDENCIA.md`. Plan en `PLAN_DE_PR.md`.

## Tabla de hallazgos

| ID | Sev | Archivo/símbolo | Flujo | Estado | UI/AV | Bloquea HF | PR |
|----|-----|-----------------|-------|--------|-------|-----------|----|
| P0-1 | **P0** | `app.py` endpoints `{name}` sin `is_safe_basename` | Studio web (transcript/brain/upload/render) | **CERRADO EN MAIN — merge 4dab852** (guard `_validar_name` en cada endpoint) | no | sí | H1 |
| P0-2 | **P0** | `app.py:151` `upload_video` filename crudo + sin límite | Upload | **CERRADO EN MAIN — merge 4dab852** (basename+**stem**+ext+tope+tmp+ffprobe) | no | sí | H1 |
| P0-3 | **P0** | `/output` mount + `.ass`/`.keyword_selection.json` | Descarga | **CERRADO EN MAIN — merge 4dab852** (`_OutputMedia` allowlist `.mp4`) | no | sí | H1 |
| P0-4 | **P0** | mounts `/input`,`/output`,`/clips`,`/thumbs` + `host 0.0.0.0` sin auth | Red local (fuente/thumbs/clips/render) | **CERRADO EN MAIN — merge 4dab852** (bind 127.0.0.1; `/input` eliminado; mounts allowlist) | no | sí | H1 |
| P1-POLL-1 | P1 | `static/index.html` `onFailure` nunca pasado | 10 flujos (render/auto/transcribe/clips…) | **CERRADO EN MAIN — merge 5779a77** (motor `job_polling.js` + adapter con fallo seguro por defecto) | UI | sí | H2 |
| P1-POLL-2 | P1 | `_pollReframe` sin try/catch, `setInterval` fugado | Reframe | **CERRADO EN MAIN — merge 5779a77** (reescrito sobre el motor compartido, sin `setInterval`) | UI | sí | H2 |
| P1-POLL-3 | P1 | `pollJob`/`pollJobP` sin timeout/límite errores | Todos los jobs | **CERRADO EN MAIN — merge 5779a77** (`deadlineMs` + `maxConsecutiveErrors`) | UI | sí | H2 |
| P1-POLL-4 | P1 | jobs en memoria; sin estado "server reiniciado"/Reintentar | Todos los jobs | **CERRADO EN MAIN — merge 5779a77** (terminal `lost` + Reintentar/Cancelar/Seguir esperando) | UI | sí | H2 |
| P1-OUT-1 | P1 | `core_ass.py` sin validar size/ffprobe | Render/paquete | **CERRADO EN MAIN — merge 4dab852** (`media_integrity.verificar_video`) | no | sí | H1 |
| P1-OUT-2 | P1 | `core_ass.py` FFmpeg escribe al nombre final | Render/resume | **CERRADO EN MAIN — merge 4dab852** (tmp privado + `os.replace`) | no | sí | H1 |
| P1-OUT-3 | P1 | `auto.py`/`auto_v2.py` resume acepta 0-byte | Resume | **CERRADO EN MAIN — merge 5779a77** (`media_integrity.video_reanudable` en los 4 predicados) | no | sí | H2 |
| P1-BOOT-1 | P1 | `core.py:108-122` FFmpeg faltante revienta críptico | Arranque/diagnóstico | **CERRADO EN H3, PENDIENTE MERGE** (`system_preflight`+excepciones tipadas `media_deps`) | no | sí | H3 |
| P1-BOOT-2 | P1 | `.gitignore`+`reframe_detect.py:165` modelos sin descarga | Reframe en clone limpio | **CERRADO EN H3, PENDIENTE MERGE** (`model_assets`+`scripts/setup_models.py` verificado por SHA256) | no | no | H3 |
| P2-DOCS-* | P2 | ESTADO/DECISIONES/PREGUNTAS/README/ALPHA | Docs/tester | Confirmado | no | no | H4 |
| P2-POLL-5/6/7 | P2 | `static/index.html` dedupe/aria/`pollJobP` | UI | **CERRADO EN MAIN — merge 5779a77** (dedupe por job ID + `role=status/alert`/`aria-live` + `pollJobP` estructurado) | UI | no | H2 |
| P2-BOOT-3..6 | P2 | `arranque.bat`/`check.bat` guards | Arranque | **CERRADO EN H3, PENDIENTE MERGE** (`studio_launcher`+`arranque.bat` wrapper+`check.bat` preflight) | no | no | H3 |
| P2-ATOM-STATE | P2 | `auto.py:568` checkpoint + varios | Resume/estado | **CERRADO EN MAIN — merge 5779a77** (`atomic_io` en checkpoints/markers/procedencia/words/groups/REPORTE) | no | no | H2 |
| P2-CLASSIC-REUSE | P2 | `auto.py` reuso por stem+mtime | Auto classic CLI | **CERRADO EN MAIN — merge 5779a77** (`auto_classic_provenance` explícita) | no | no | H2 |
| P2-PAQUETE-DIR | P2 | `auto.py` reanuda cualquier dir sin `paquete.json` | Auto classic CLI | **CERRADO EN MAIN — merge 5779a77** (marker `auto_classic.json` + confinamiento) | no | no | H2 |
| P3-* | P3 | HyperFrames/F7/features diferidas | — | Clasificado | — | — | — |

## Criterio "LISTO ANTES DE HYPERFRAMES" — estado actual

| Criterio | Estado |
|----------|--------|
| 0 P0 abiertos | ❌ 4 abiertos (P0-1/2/3/4) |
| 0 P1 abiertos | ❌ ~9 abiertos |
| P2/P3 documentados con trigger y fase | ✅ (este doc + PLAN_DE_PR) |
| Documentación actual sin contradicciones | ❌ (P2-DOCS, → H4) |
| Arranque comprobado | ✅ launcher testeable + preflight (H3, pendiente merge) |
| Errores principales accionables | ❌ (FFmpeg/jobs) |
| No hay spinner infinito | ❌ (P1-POLL-1..4) |
| Outputs parciales no se publican | ❌ (P1-OUT-1..3) |
| Resume no reutiliza datos incorrectos | ⚠️ SRT/v2 OK; classic P2; 0-byte ❌ |
| Privacidad verificada | ❌ (P0-1/2/3/4 — incl. exposición LAN) |
| Suite completa verde | ✅ 1894/3-skip |
| Quality gate local reproducible | ✅ `check.bat` |
| CI remoto verde o ausencia justificada | ⚠️ ausente (→ H5) |
| Smoke E2E sintético completo verde | ⚠️ harness `sandboxed-v2` entregado (aislado + self-test verde); reporta 4 blockers P0 |
| Guía de testers actualizada | ❌ (ALPHA-*, → H4) |
| Review fresco sin P0/P1 | ❌ |
| PR abierto y no mergeado | ✅ (esta rama) |
| HyperFrames no iniciada | ✅ |

**Veredicto:** P0-1..4, P1-POLL-1..4, P1-OUT-1..3 **cerrados EN MAIN** (H1 `4dab852` + H2 `5779a77`).
P1-BOOT-1/2 y P2-BOOT-3..6 **cerrados en H3** (rama `fix/h3-arranque-diagnostico`, PENDIENTE MERGE).
Restan para readiness plena: **H4** (documentación ESTADO/DECISIONES/PREGUNTAS/ALPHA) y **H5** (CI),
no iniciados. HyperFrames no iniciada.
