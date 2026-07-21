# H4 — Evidencia (documentación y readiness pre-HyperFrames)

**Base:** `cdcea7a9860043eb175972758e660895bf9df44c` (merge PR #28, cierre GPU/NVENC).
**Rama:** `docs/h4-readiness-docs`. **Naturaleza:** documentación únicamente.

## Base

- `main` en `cdcea7a…` (PR #28 MERGED). Árbol limpio al iniciar. Rama creada desde ese HEAD.
- Suite de la base, verificada con `pytest -q`: **2410 passed, 4 skipped** (4 skips históricos de
  symlink en Windows). Cero skips nuevos.

## Archivos revisados (Fase 1)

Contrastados contra el **producto real** (código/tests/merges), no contra otro Markdown:
`README.md`, `MAESTRO.md`, `ESTADO.md`, `DECISIONES.md`, `PREGUNTAS.md`, `.env.example`,
`docs/ENTORNO.md`, `docs/GPU_NVENC.md`, `docs/ALPHA_TESTERS.md`,
`revision/pre-hyperframes/{AUDITORIA,PLAN_DE_PR,MATRIZ_READINESS,H3_EVIDENCIA,NVENC_EVIDENCIA}.md`.
Producto: `app.py`, `jobs.py`, `jobs_render.py`, `static/index.html`,
`static/system_capabilities.js`, `static/job_polling.js`, `video_encoder.py`,
`studio_srt_routes.py`, `studio_srt_runtime.py`, `studio_auto.py`, `auto.py`, `auto_v2.py`,
`submagic.py`, `broll_stock.py`, `brain.py`, `assets_comfy.py`, `core.py`, `arranque.bat`,
`check.bat`. Detalle en `H4_INVENTARIO.md`.

## Contradicciones corregidas

Todas las mínimas exigidas quedaron detectadas y corregidas (ver `H4_INVENTARIO.md`):

- README con conteo antiguo de tests (157 → **2410/4**).
- ESTADO previo a H1/H2/H3/NVENC (88/100 + 1894 + "PR #23 autorizado para merge" → **estado
  verificable**, histórico marcado).
- H3 marcado como pendiente (MATRIZ "PENDIENTE MERGE") → **cerrado en main** `b59989f`.
- NVENC marcado como PR abierto → **cerrado en main** `cdcea7a`; smoke real **16 checks**.
- Afirmaciones absolutas "nada se sube" (README, ALPHA) → **tabla local/remoto** + frase canónica.
- Capacidades SRT/Auto v2/F6/CVE/Caption QA ausentes de la guía → añadidas.
- Límites multi-persona desactualizados → descritos con precisión.
- Rutas/archivos privados en documentos históricos → **saneados**.
- Documentos que mezclan roadmap histórico con estado actual (ESTADO, MAESTRO) → separados y
  marcados como histórico donde corresponde.

## Jerarquía documental establecida

- `README.md` — presentación pública, estado Alpha, arranque rápido, enlaces a las guías.
- `docs/ENTORNO.md` — instalación reproducible, requisitos, diagnóstico, compatibilidad.
- `docs/ALPHA_TESTERS.md` — protocolo de prueba, uso, checklist, privacidad, formato de feedback.
- `ESTADO.md` — estado vivo, merges cerrados, siguiente fase, baseline.
- `DECISIONES.md` — decisiones técnicas aprobadas (se añadieron D41/D42/D43; addendum de cierre D40).
- `PREGUNTAS.md` — tabla de navegación por estado; solo activas/diferidas con trigger; historial
  preservado.
- `MAESTRO.md` — arquitectura y roadmap histórico (addendum que aclara que NO es estado línea a
  línea).
- `MATRIZ_READINESS.md` / `PLAN_DE_PR.md` — readiness verificable y secuencia H1–H5.

## Saneamiento (Fase 10)

Escaneo final sobre **todos los archivos de texto VERSIONADOS por Git** (`git ls-files`), no solo
markdown:

- **Cero referencias protegidas en archivos de texto versionados** (`.md`, `.py`, `.bat`, `.txt`,
  etc.): el identificador del SRT del usuario ya no aparece en ningún archivo rastreado.
- Rutas absolutas del perfil de Windows: **0**.
- Rutas absolutas del proyecto en la máquina del usuario: **0** (README_KIT y MAESTRO genericizados
  a `C:\ruta\centrito`).
- Patrones de API key reales: **0** (`.env.example` usa placeholder `sk-xxx`).
- **Test histórico saneado con sentinel sintético.** El único test tocado, `tests/test_h3_check_bat.py`,
  ya no conserva el identificador protegido: su aserción de privacidad se reescribió a un guard por
  **clase** (verifica que `check.bat` no referencia ningún fixture de video real, solo su fixture
  sintético `_smoke_synth`), usando un sentinel genérico (`input/archivo_privado.srt`). El guard
  quedó **más fuerte**, no más débil, y sin cambiar el comportamiento de `check.bat`.

Total de referencias sensibles saneadas: **19** (solo se reporta la cantidad, no cuáles). Todos los
reemplazos usan placeholders genéricos (`input/video.srt`, "SRT privado del usuario",
`C:\ruta\centrito`, `input/archivo_privado.srt`).

- Los nombres de videos de prueba históricos en las bitácoras (`ESTADO.md`/`DECISIONES.md`/
  `PREGUNTAS.md` y READMEs de `revision/`) se preservan como **historia útil** vía una allowlist
  explícita de fixtures sintéticos/históricos; no son el SRT protegido.
- **Una única modificación de test, exclusivamente por privacidad**; ninguna modificación de
  producción ni de salida audiovisual.

## Smoke documental (Fase 11)

`revision/pre-hyperframes/smoke_h4_docs.py` — sin red, GPU, FFmpeg, modelos ni archivos privados.

- `--self-test`: **VERDE (23/23)**. Demuestra la detección de cifra vieja de tests, H3 pendiente,
  GPU/NVENC abierto, afirmación absoluta "nada se sube", ruta absoluta realista, input específico
  (separador POSIX **y** Windows `input\...`; referencia privada dentro de un `tests/demo.py`
  sintético detectada, placeholder genérico no), enlace relativo roto, H5/HyperFrames cerrado
  indebidamente y secreto (con contraprueba negativa de cada uno), más que el gate solo mira
  archivos versionados (no dirs locales). Ningún fixture usa un nombre o ruta privada real.
- `--real`: **blockers=0, fails=0** (`checks=1064` en este commit; el conteo es **determinista** —
  se basa en `git ls-files`, así que es idéntico en un clon limpio y **no** depende de dirs locales
  como `.claude/`). El gate escanea **todos los archivos de texto VERSIONADOS** (`.md`, `.py`,
  `.bat`, `.ps1`, `.js`, `.html`, `.css`, `.json`, `.yml/.yaml`, `.toml`, `.txt`, `.example`) —
  excluyendo el propio smoke (fixtures sintéticos) y binarios — buscando rutas personales, secretos
  reales e inputs privados fuera de la allowlist. Además verifica archivos requeridos, enlaces
  relativos, estado H1/H2/H3/NVENC, H4 pendiente de merge, H5 pendiente, HyperFrames no iniciado,
  baseline 2410/4, ausencia de cifras históricas en los encabezados actuales, privacidad
  local/externa, formato de feedback en ALPHA, enlaces del README a las guías y consistencia
  MATRIZ/PLAN.

Los errores del smoke muestran archivo + categoría, nunca el texto sensible.

## Suite

`pytest -q` → **2410 passed, 4 skipped** (los 4 skips históricos de symlink; cero skips nuevos).
`ruff check` / `ruff format --check` / `git diff --check` limpios. `check.bat` → `===== TODO OK =====`.

## Alcance excluido

- **Sin** cambios en Python de producción, JavaScript/HTML/CSS, tests, `requirements.txt`,
  `arranque.bat`/`check.bat`, workflows ni assets.
- **Sin** cambios audiovisuales (no requiere veredicto visual de K).
- **Sin** benchmark NVENC, renders reales, videos privados, smoke Submagic con red ni Pexels real.
- **Snapshots por fase.** Las evidencias `H1_EVIDENCIA.md`…`NVENC_EVIDENCIA.md` describen el estado
  **al cerrar su propia fase** (p. ej. "H4/H5 no iniciados"): son registros congelados de su
  momento, no el estado vivo. El estado actual autoritativo vive en `ESTADO.md`,
  `MATRIZ_READINESS.md` y `PLAN_DE_PR.md` (H4 en curso). Solo se tocaron esas evidencias para
  saneamiento de privacidad, sin reescribir su contenido histórico.
- **H5 y HyperFrames/F7 NO iniciados.**
