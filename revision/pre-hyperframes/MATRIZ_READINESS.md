# Matriz de Readiness Pre-HyperFrames

Base actual `cdcea7a` (merge PR #28, cierre GPU/NVENC). **H1 CERRADO EN MAIN — merge `4dab852`. H2
CERRADO EN MAIN — merge `5779a77`. H3 CERRADO EN MAIN — merge `b59989f`. GPU/NVENC CERRADO EN MAIN —
merge `cdcea7a`.** **H4 (documentación) técnicamente preparado en este PR, pendiente de merge. H5
pendiente. HyperFrames no iniciada.** Baseline de suite de este commit: `2410 passed, 4 skipped`
(4 skips = los cuatro históricos de symlink). Detalle y evidencia en `AUDITORIA.md` /
`H1_EVIDENCIA.md` / `H2_EVIDENCIA.md` / `H3_EVIDENCIA.md` / `NVENC_EVIDENCIA.md`. Plan en
`PLAN_DE_PR.md`.

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
| P1-BOOT-1 | P1 | `core.py:108-122` FFmpeg faltante revienta críptico | Arranque/diagnóstico | **CERRADO EN MAIN — merge b59989f** (`system_preflight`+excepciones tipadas `media_deps`) | no | sí | H3 |
| P1-BOOT-2 | P1 | `.gitignore`+`reframe_detect.py:165` modelos sin descarga | Reframe en clone limpio | **CERRADO EN MAIN — merge b59989f** (`model_assets`+`scripts/setup_models.py` verificado por SHA256) | no | no | H3 |
| P2-DOCS-* | P2 | ESTADO/DECISIONES/PREGUNTAS/README/ALPHA | Docs/tester | **EN CURSO — H4 (este PR)** | no | no | H4 |
| P2-POLL-5/6/7 | P2 | `static/index.html` dedupe/aria/`pollJobP` | UI | **CERRADO EN MAIN — merge 5779a77** (dedupe por job ID + `role=status/alert`/`aria-live` + `pollJobP` estructurado) | UI | no | H2 |
| P2-BOOT-3..6 | P2 | `arranque.bat`/`check.bat` guards | Arranque | **CERRADO EN MAIN — merge b59989f** (`studio_launcher`+`arranque.bat` wrapper+`check.bat` preflight) | no | no | H3 |
| P2-ATOM-STATE | P2 | `auto.py:568` checkpoint + varios | Resume/estado | **CERRADO EN MAIN — merge 5779a77** (`atomic_io` en checkpoints/markers/procedencia/words/groups/REPORTE) | no | no | H2 |
| P2-CLASSIC-REUSE | P2 | `auto.py` reuso por stem+mtime | Auto classic CLI | **CERRADO EN MAIN — merge 5779a77** (`auto_classic_provenance` explícita) | no | no | H2 |
| P2-PAQUETE-DIR | P2 | `auto.py` reanuda cualquier dir sin `paquete.json` | Auto classic CLI | **CERRADO EN MAIN — merge 5779a77** (marker `auto_classic.json` + confinamiento) | no | no | H2 |
| P3-* | P3 | HyperFrames/F7/features diferidas | — | Clasificado | — | — | — |

## Criterio "LISTO ANTES DE HYPERFRAMES" — estado actual

| Criterio | Estado |
|----------|--------|
| 0 P0 abiertos | ✅ 0 (P0-1/2/3/4 cerrados en main, `4dab852`) |
| 0 P1 abiertos | ✅ 0 (POLL/OUT/BOOT cerrados en main) |
| P2/P3 documentados con trigger y fase | ✅ (este doc + PLAN_DE_PR) |
| Documentación actual sin contradicciones | ⏳ **H4 en curso (este PR)** |
| Arranque comprobado | ✅ launcher + preflight (H3, `b59989f`) |
| Errores principales accionables | ✅ PASS (FFmpeg/jobs con mensaje accionable) |
| No hay spinner infinito | ✅ cerrado (`job_polling.js`, H2) |
| Outputs parciales no se publican | ✅ cerrado (atómico + ffprobe, H1/H2) |
| Resume no reutiliza datos incorrectos | ✅ cerrado (`video_reanudable` + procedencia, H2) |
| Privacidad técnica verificada | ✅ cerrada (loopback + confinamiento + allowlist, H1) |
| Suite completa verde | ✅ 2410/4-skip |
| Quality gate local reproducible | ✅ `check.bat` |
| CI remoto verde o ausencia justificada | ⚠️ ausente (→ H5) |
| Smoke E2E sintético completo verde | ✅ harness aislado; blockers=0 tras H1/H2/H3 |
| Guía de testers actualizada | ⏳ **H4 en curso (este PR)** |
| Review fresco sin P0/P1 | ✅ (Codex por PR; 0 P0/P1) |
| PR abierto y no mergeado | ✅ (rama `docs/h4-readiness-docs`) |
| HyperFrames no iniciada | ✅ |

**Veredicto:** P0-1..4, P1-POLL-1..4, P1-OUT-1..3 **cerrados en main** (H1 `4dab852` + H2 `5779a77`).
P1-BOOT-1/2 y P2-BOOT-3..6 **cerrados en main** (H3 `b59989f`). GPU/NVENC **cerrado en main**
(`cdcea7a`). Readiness técnica alcanzada: **0 P0 / 0 P1 abiertos**. Resta: **H4** (documentación —
este PR, pendiente de merge) y **H5** (CI ligero), no bloqueantes del arranque de HyperFrames.
HyperFrames no iniciada (bloqueada hasta gate final).

## Fase GPU / NVIDIA NVENC (independiente, pre-HyperFrames)

Fase de **rendimiento**, no de readiness: mueve la codificación H.264 a NVENC con fallback CPU.
No es un blocker de la matriz anterior (la ruta CPU sigue siendo completamente válida).

| Aspecto | Estado |
|---|---|
| Módulo central `video_encoder.py` (detección real + selección + fallback) | ✅ |
| Integración depurador / captions / overlays / reframe (clipper y Auto heredan) | ✅ byte-idéntico CPU |
| Modos auto/nvenc/cpu + guard 503 pre-job + snapshot inmutable por job | ✅ |
| API `/api/system/video-encoder` (GET/PUT) + capacidad `nvenc` (no degrada) + UI Ajustes | ✅ |
| Smoke real (`smoke_nvenc.py`) | ✅ **16 checks**, blockers=0, fails=0 |
| Benchmark (`benchmark_nvenc.py`, 1080p): speedup ≥1.25x + SSIM ≥0.95 + A/V ≤50 ms | ✅ (depuración 2.52x) |
| H4 | ⏳ en curso (este PR) |
| H5 / HyperFrames | ⏸️ no iniciados |

Detalle y números: `NVENC_INVENTARIO.md`, `NVENC_EVIDENCIA.md`, `docs/GPU_NVENC.md`.
GPU/NVENC **cerrado en main** — merge `cdcea7a` (PR #28).
