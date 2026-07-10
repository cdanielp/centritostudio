# ESTADO — Centrito Studio
Actualizado: 2026-07-09 · Sesión: 17

## Fases
- [x] F0 Auditoría + equipamiento — evidencia sintética en revision/fase-0/
- [x] F1 Studio core + fixes transcripción
- [x] F2 Cerebro editorial (DeepSeek) — re-cerrada con énfasis visible (keyword_color persistente)
- [x] F3 Depurador de clases — CERRADA. Validada con TTS (4 cortes, -3.84s) y voz humana OBS (7 cortes, -15.74s, 20.9%). Aprobación auditiva del arquitecto. _eval_joins diagnóstico operativo (6/15dB, sin loop de ajuste). Render único: 44s V1, 12s V2.
- [x] Refactor app.py→jobs.py — CERRADO. app.py 243L, jobs.py 185L (deuda PREGUNTAS #7 saldada). E2E smoke OK (render+enfasis en 2.9s).
- [x] F4 Clipper viral — CERRADA. Smoke test pruebaedicionvideoyo.mov: 1 clip score=63 OK. Calibración videolargo.mov (57 min): 3 clips (86/78/77), $0.0094, 45s wall. SCORE_MIN=60 y MAX_CLIPS=3 confirmados por arquitecto. Bug dotenv fix incluido. Evidencia: revision/fase-4/DISENO_CLIPPER.md + CALIBRACION_CLIPPER.md + frames clip1-3.
- [x] F4.1 Reframe Vertical (16:9 → 9:16 con face tracking) — CERRADA s16. C1 PASS ×3 (96.2/97.5/100%), C2v2 PASS (0.19/0.53%), 98 tests, D1-D5+D6 firmes. Aprobado K 90/100. Deudas: descuadre reposo (#21), full_range cara débil (#22), F4.2-LITE (#24). Avance 65/100.
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
- 2026-07-09: Sesión 6 — F4 SESIÓN DE DISEÑO (sin implementar): DISENO_CLIPPER.md completo (frase como unidad atómica, chunking 2500/300, LLM nunca calcula totales, depurar antes del clipper), esqueleto clipper.py/clipper_brain.py con validadores reales + stubs, 14 tests de contrato verdes, ruff format aplicado a todo el repo (paso nuevo de check.bat). Próximo paso: arquitecto vota PREGUNTAS #9-11 → sesión de implementación F4.
- 2026-07-09: Sesión 7 — F4 IMPLEMENTACIÓN COMPLETA: clipper_brain.py (segmentar_transcript+puntuar_candidatos con retry técnico+semántico, telemetría, chunking via chunk_frases), clipper.py (build_frases, chunk_frases, dedup_segmentos, seleccionar_clips, cortar_clip, exportar_transcript_clip, generar_clips), caption.py (--clips + reutilización words.json), jobs.py (run_clips), app.py (POST/GET /api/clips), index.html (pestaña Clips), brain.py (chat_json alias + mock mejorado), depurador.py (run_edl alias). 49 tests verdes. Smoke test mock OK. Pendiente: smoke con API real + calibración videolargo.mov.
- 2026-07-09: Sesión 8 — F4 CERRADA. Bug fix: dotenv en clipper.py (API key no cargaba antes del check). Smoke test OK (1 clip score=63). Calibración videolargo.mov (57 min, 7559 palabras): 3 clips 86/78/77, $0.0094, 45s wall. Arquitecto aprueba. SCORE_MIN=60/MAX_CLIPS=3 confirmados. CALIBRACION_CLIPPER.md aclarado (max_clips vs score_bajo, candidato #4). PREGUNTAS #12-13 para v2. Próximo paso: F5 Assets o F6 Motor B (pendiente decisión arquitecto).
- 2026-07-09: Sesión 9 — F4.1 SESIÓN DE DISEÑO COMPLETA. Votos #12/#13 registrados. DISENO_REFRAME.md completo. Esqueleto reframe.py + reframe_track.py. 27 tests de contrato. mediapipe en requirements. Pendiente: votos #14-17 → sesión de implementación.
- 2026-07-09: Sesión 10 — F4.1 IMPLEMENTACIÓN. Votos #14-17. FACE_MIN_CONFIDENCE=0.20. 4 clips validados, punch-ins x9, run_reframe/API/UI. 79 tests. Multi-cara pendiente.
- 2026-07-09: Sesión 11 — F4.1 FIX + CONMUTACION. Fix critico pix_fmt yuv420p (todos los outputs eran yuv444p). Conmutacion multi-cara real: calcular_crops_por_turnos (puro math), detectar_trayectorias_multi, detectar_todas_caras_frame. 2+ caras sin turnos: WARNING (no error). Validacion podcast 2 personas: 2 caras detectadas (cx=1362/719, score=0.40/0.24), 6 turnos test, renders OK, frames pre/post corte extraidos. 82 tests verdes.
- 2026-07-09: Sesión 12 — F4.1 FIX TRACKING. 7 correcciones: DEADZONE_PCT=0.25 sobre crop_w (era 0.30 source_w), HOLD indefinido (elimina RECENTER_ALPHA), FACE_LOST_PATIENCE_S=1.0s, gate asignacion 20% source_w, alpha normalizado fps (0.154@60fps), model_selection=short_range unico disponible en Tasks API. CSV trayectoria exportado por render. 85 tests. C1 PASS 99.1-99.3%. C2 FAIL noturnos: cam 67% en zona vacia (drift via gate 384px). Detenido per protocolo.
- 2026-07-09: Sesión 13 — F4.1 ANCLA ESTATICA. GATE_ANCLA_PCT=0.15 (era FACE_GATE_PCT=0.20). Asignacion exclusiva por frame (greedy bipartita). C1 PASS 99.2-99.8%. C2 FAIL residual 42% (cam_min 942->1082, +140px mejora). Causa: solapamiento 26px entre zona ancla [1074,1650] y zona C2 [900-1100]. Cara derecha orbita en [1082-1122] = dentro del ancla pero en C2. Opciones: gate 0.12 o C2 relativo. Model_selection: short_range unico disponible en Tasks API 0.10.x. No parchar; paquete de cierre preparado.
- 2026-07-09: Sesión 14 — F4.1 RE-VALIDACION. C2v2 criterio oficial (D1). full_range descargado y comparado: RECHAZADO (fuera_gate +62, D4). EMA fix ^30/fps aplicado (alpha 0.041@60fps). Re-renders noturnos+turnos s14: C2v2=0.2%/0.5% PASS; C1 noturnos 94.9% FAIL marginal (retune pendiente D5). CSV con confianza. DECISIONES.md creado. 88 tests.
- 2026-07-09: Sesión 15 — F4.1 RETUNE D5. Alpha adaptativo 2 regimenes: ALPHA_BASE_LENTO=0.08, ALPHA_BASE_RAPIDO=0.28, rampa lineal dz_half a 3xdz_half. C1 PASS: noturnos 96.2%, turnos 97.5%, videolargo 100% (tracking-only). C2v2 PASS: 0.19/0.53%. 10 tests nuevos (98 total). Correcciones model_selection.md (4a/4b/4c). DECISIONES.md D5 cerrado.
- 2026-07-09: Sesión 16 — F4.1 CIERRE FORMAL. DoD completo verificado. DECISIONES.md D6 (cierre K 90/100). Diagnostico descuadre t=57s (cam=1182 face=1134 dist=48px HOLD). PREGUNTAS.md: puntos 20-24 (punch-in veredicto, deuda descuadre, full-range, riesgos revisor, F4.2-LITE spec). ESTADO.md: F4.1 cerrada, avance 65/100. Siguiente: F4.2-LITE.
- 2026-07-09: Sesión 17 — F4.2-LITE. calcular_bandas_stack (math puro, 9 tests), renderizar_stack, reframe_stack_clip, --layout stack CLI. Studio: selector Seguimiento|Stack. Render podcast_test_60s stack OK (39.1s, 1080x1920 yuv420p AAC). C-STACK cara_0 100% cara_1 100%. 107 tests. Votos #20/21/24. Paquete en revision/fase-4.2-lite/. Pendiente: ojo de K y /cerrar-fase.
