# ESTADO — Centrito Studio
Actualizado: 2026-07-09 · Sesión: 5

## Fases
- [x] F0 Auditoría + equipamiento — evidencia sintética en revision/fase-0/
- [x] F1 Studio core + fixes transcripción
- [x] F2 Cerebro editorial (DeepSeek) — re-cerrada con énfasis visible (keyword_color persistente)
- [x] F3 Depurador de clases — CERRADA. Validada con TTS (4 cortes, -3.84s) y voz humana OBS (7 cortes, -15.74s, 20.9%). Aprobación auditiva del arquitecto. _eval_joins diagnóstico operativo (6/15dB, sin loop de ajuste). Render único: 44s V1, 12s V2.
- [x] Refactor app.py→jobs.py — CERRADO. app.py 243L, jobs.py 185L (deuda PREGUNTAS #7 saldada). E2E smoke OK (render+enfasis en 2.9s).
- [ ] F4 Clipper viral
- [ ] F5 Assets: emojis PNG + ComfyUI
- [ ] F6 Motor B: HyperFrames
- [ ] F7 Distribución Telegram (diseñada: [ ] · desplegada: [ ])

## Herramientas del agente
- [x] Plugin /watch operativo (frame extraction + análisis visual multimodal — tacosjuan@5s verificado)
- [x] Skills HyperFrames instaladas (Node 22.17.1 >= 22, 20 skills, 72 agentes)
- [x] Skill centrito-motion (10 reglas)
- [x] Skill centrito (principal) al día

## Bitácora

- 2026-07-07: Sesión 1 — pipeline CLI + 4 estilos ASS + renders de 4 videos reales validados
- 2026-07-08: Sesión 2 — baseline kit guardrails: ruff limpio, tests reconciliados con API real de core.py, anti-huérfano respeta max_words, pytest.ini, /revisar aplicado
- 2026-07-09: Sesión 3 — Fase 0 cerrada (node OK, HyperFrames, /watch, skills), Fase 2: brain.py + DeepSeek + keywords en Motor A + UI Énfasis IA
- 2026-07-09: Sesión 4 — TAREA B: brain.json re-ancla por kw_ts (regroup-safe), 2 tests contrato nuevos. core_ass.py split (core.py 288 lineas). TAREA C: depurador.py completo (modos seguro/agresivo, EDL, FFmpeg crossfade, auto-eval, CLI --depurar, Studio botón, recalcular_words). Fase 3 cerrada con evidencia real (reel02 demo, 2 cortes, -2.7s).
- 2026-07-09: Sesión 5 — keyword_color persistente (visible en frames), fix _eval_and_adjust (todas las uniones por iteración), fix usage tracking en brain.py, énfasis IA siempre reportado en UI (ámbar). F0/F2/F3 re-auditadas y cerradas. Bug 17vs14 en DEPURADO_reel02.md documentado y corregido.
- 2026-07-09: Sesión 5c — _eval_joins: diagnóstico voz-a-voz puro. F3 cerrada sin pendientes. 28 tests.
- 2026-07-09: Sesión 5d — Refactor app.py→jobs.py: deuda saldada (243+185L). E2E smoke: render+enfasis 2.9s. F4 lista.
