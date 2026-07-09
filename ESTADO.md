# ESTADO — Centrito Studio
Actualizado: 2026-07-09 · Sesión: 5

## Fases
- [x] F0 Auditoría + equipamiento — evidencia sintética en revision/fase-0/
- [x] F1 Studio core + fixes transcripción
- [x] F2 Cerebro editorial (DeepSeek) — re-cerrada con énfasis visible (keyword_color persistente)
- [x] F3 Depurador de clases — validado con 2 videos reales, drift=0, fronteras limpias. Criterio voz-a-voz implementado (feedback loop eliminado, voice_refs estables). 2/7 uniones convergen (V2); 5/7 y 4/4 (V1) no convergen por variación real de nivel entre secciones. Threshold 6dB pendiente ajuste para grabaciones de nivel variable. Ver PREGUNTAS.md #8.
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
- 2026-07-09: Sesión 5b — Depurador validado: 2 videos reales. Fix voz-a-voz con voice_refs estables (feedback loop eliminado). V1: 4 cortes, -4.8s. V2: 7 cortes, -16.94s, 22.5%. 2/7 uniones V2 convergen iter1; resto: variación real de nivel. Threshold 6dB pendiente ajuste (ver PREGUNTAS #8). 3 tests unitarios nuevos.
