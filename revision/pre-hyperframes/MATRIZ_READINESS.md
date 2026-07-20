# Matriz de Readiness Pre-HyperFrames

Base `4a378d8` · Rama `chore/pre-hyperframes-readiness` · Suite `1894 passed, 3 skipped`.
Detalle y evidencia `archivo:línea` en `AUDITORIA.md`. Plan de corrección en `PLAN_DE_PR.md`.

## Tabla de hallazgos

| ID | Sev | Archivo/símbolo | Flujo | Estado | UI/AV | Bloquea HF | PR |
|----|-----|-----------------|-------|--------|-------|-----------|----|
| P0-1 | **P0** | `app.py` endpoints `{name}` sin `is_safe_basename` | Studio web (transcript/brain/upload/render) | **DEMOSTRADO** (write fuera del repo, un nivel arriba de la raíz) | no | sí | H1 |
| P0-2 | **P0** | `app.py:151` `upload_video` filename crudo + sin límite | Upload | DEMOSTRADO (código) + DoS | no | sí | H1 |
| P0-3 | **P0** | `/output` mount + `.ass`/`.keyword_selection.json` | Descarga | **DEMOSTRADO** | no | sí | H1 |
| P1-POLL-1 | P1 | `static/index.html:1268` `onFailure` nunca pasado | 8 flujos (render/auto/transcribe/clips…) | DEMOSTRADO | UI | sí | H2 |
| P1-POLL-2 | P1 | `static/index.html:1885` `_pollReframe` sin try/catch | Reframe | DEMOSTRADO | UI | sí | H2 |
| P1-POLL-3 | P1 | `pollJob`/`pollJobP` sin timeout/límite errores | Todos los jobs | DEMOSTRADO | UI | sí | H2 |
| P1-POLL-4 | P1 | jobs en memoria; sin estado "server reiniciado"/Reintentar | Todos los jobs | DEMOSTRADO | UI | sí | H2 |
| P1-OUT-1 | P1 | `core_ass.py:333,420` sin validar size/ffprobe | Render/paquete | DEMOSTRADO | no | sí | H1 |
| P1-OUT-2 | P1 | `core_ass.py:328` FFmpeg escribe al nombre final | Render/resume | DEMOSTRADO | no | sí | H1 |
| P1-OUT-3 | P1 | `auto.py:457,546,119`/`auto_v2.py:62` resume acepta 0-byte | Resume | DEMOSTRADO | no | sí | H2 |
| P1-BOOT-1 | P1 | `core.py:108-122` FFmpeg faltante revienta críptico | Arranque/diagnóstico | DEMOSTRADO | no | sí | H3 |
| P1-BOOT-2 | P1 | `.gitignore`+`reframe_detect.py:165` modelos sin descarga | Reframe en clone limpio | DEMOSTRADO (clone) | no | no | H3 |
| P2-DOCS-* | P2 | ESTADO/DECISIONES/PREGUNTAS/README/ALPHA | Docs/tester | Confirmado | no | no | H4 |
| P2-POLL-5/6/7 | P2 | `static/index.html` dedupe/aria/`pollJobP` | UI | Confirmado | UI | no | H2 |
| P2-BOOT-3..6 | P2 | `arranque.bat`/`check.bat` guards | Arranque | Confirmado | no | no | H3 |
| P2-ATOM-STATE | P2 | `auto.py:568` checkpoint + varios | Resume/estado | Confirmado | no | no | H2 |
| P2-CLASSIC-REUSE | P2 | `auto.py:53-54,76-77` stem+mtime | Auto classic CLI | Teórico | no | no | H2 |
| P3-* | P3 | HyperFrames/F7/features diferidas | — | Clasificado | — | — | — |

## Criterio "LISTO ANTES DE HYPERFRAMES" — estado actual

| Criterio | Estado |
|----------|--------|
| 0 P0 abiertos | ❌ 3 abiertos (P0-1/2/3) |
| 0 P1 abiertos | ❌ ~9 abiertos |
| P2/P3 documentados con trigger y fase | ✅ (este doc + PLAN_DE_PR) |
| Documentación actual sin contradicciones | ❌ (P2-DOCS, → H4) |
| Arranque comprobado | ⚠️ frágil (P1-BOOT) |
| Errores principales accionables | ❌ (FFmpeg/jobs) |
| No hay spinner infinito | ❌ (P1-POLL-1..4) |
| Outputs parciales no se publican | ❌ (P1-OUT-1..3) |
| Resume no reutiliza datos incorrectos | ⚠️ SRT/v2 OK; classic P2; 0-byte ❌ |
| Privacidad verificada | ❌ (P0-1/2/3) |
| Suite completa verde | ✅ 1894/3-skip |
| Quality gate local reproducible | ✅ `check.bat` |
| CI remoto verde o ausencia justificada | ⚠️ ausente (→ H5) |
| Smoke E2E sintético completo verde | ⚠️ harness entregado; reporta blockers |
| Guía de testers actualizada | ❌ (ALPHA-*, → H4) |
| Review fresco sin P0/P1 | ❌ |
| PR abierto y no mergeado | ✅ (esta rama) |
| HyperFrames no iniciada | ✅ |

**Veredicto:** NO LISTO. Bloqueos exactos: **P0-1, P0-2, P0-3, P1-POLL-1..4, P1-OUT-1..3, P1-BOOT-1..2.**
