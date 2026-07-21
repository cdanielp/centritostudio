# H4 — Inventario documental (contradicciones verificadas)

**Base:** `cdcea7a9860043eb175972758e660895bf9df44c` (merge PR #28, cierre GPU/NVENC).
**Rama:** `docs/h4-readiness-docs`. **Naturaleza:** documentación únicamente.

Cada fila se verificó contra el **producto real** (código / tests / merges), no contra otro
Markdown. La columna "Fuente verificada" cita el archivo:símbolo consultado. Ninguna corrección
toca código de producción, tests ni salida audiovisual.

Baseline de suite de este commit: **2410 passed, 4 skipped** (los 4 skips históricos de symlink en
Windows). El smoke real de NVENC tiene **16 checks** (`revision/pre-hyperframes/smoke_nvenc.py`,
etiquetas `_check("1_..")`…`_check("16_..")`).

## Tabla de contradicciones

| Archivo | Afirmación actual | Estado real | Fuente verificada | Corrección |
|---|---|---|---|---|
| README.md:96 | "tests/ … (157 tests, ruff limpio)" | Baseline 2410 passed / 4 skipped; ~81 archivos de test | `pytest -q`; `tests/` | **cifra de tests** → un solo bloque de estado 2410/4; sin conteo de líneas |
| README.md:5 | "Sin API externa (salvo DeepSeek … y ComfyUI local)" | También hay Pexels (remoto) y Submagic (remoto, sube el video) | `broll_stock.py:53` `api.pexels.com`; `submagic.py:28` `api.submagic.co` | **servicio externo / privacidad** → tabla local/remoto; "local por defecto, integraciones externas explícitas y opcionales" |
| README.md (tabla "Qué hace") | Faltan Caption QA, SRT, Auto v2, Editor de Paquete, Submagic, NVENC, recuperación de jobs | Todas existen y están mergeadas | `studio_srt_*`, `auto_v2.py`, `paquete_editor.py`, `submagic.py`, `video_encoder.py`, `static/job_polling.js` | **función disponible** → añadir funciones verificadas |
| README.md:94-95 | Estructura lista solo `jobs.py` como workers | También `jobs_render.py` es worker real (render) | `jobs.py:14` importa `run_render` de `jobs_render.py` | **ruta/archivo** → listar `jobs_render.py` |
| README.md:100-106 | "GPU NVIDIA + CUDA (opcional)" sin distinguir NVENC | CUDA (Whisper) ≠ NVENC (codificación); son usos distintos de la GPU | `core.py:34` CUDA; `video_encoder.py` NVENC | **compatibilidad** → distinguir CUDA vs NVENC; ambos con fallback CPU |
| ESTADO.md:2 | "Avance real: 88/100" como estado actual | Cálculo histórico previo a hardening/NVENC | `git log` (H1..NVENC mergeados) | **estado** → readiness verificable (P0/P1=0); 88/100 marcado HISTÓRICO |
| ESTADO.md:2 | "Suite 1894 passed, 3 skipped" | 2410 passed, 4 skipped | `pytest -q` | **cifra de tests** → 2410/4 baseline |
| ESTADO.md:2 | "PR #23 autorizado para merge" como estado actual | F6 esencial mergeada en main (`4a378d8`) | memoria de proyecto; `git log` | **merge** → registrar merge; no dejar "autorizado" como estado vivo |
| ESTADO.md:2 | "HyperFrames/hardening/F7 NO iniciados" | Hardening H1/H2/H3 y GPU/NVENC CERRADOS en main | merges `4dab852`/`5779a77`/`b59989f`/`cdcea7a` | **estado** → encabezado con H1/H2/H3/NVENC cerrados; H4 en curso |
| ESTADO.md (encabezado) | No menciona H1/H2/H3/NVENC | Cuatro fases cerradas después de F6 | `git log --oneline` | **estado** → nuevo encabezado con merges exactos |
| DECISIONES.md:1611 | D40: "PR abierto, NO mergeado: pendiente veredicto visual de K" | F6/D40 mergeada (`4a378d8`, K APROBADO) | memoria de proyecto; `git log` | **merge** → addendum de cierre D40 (no reescribir el bloque) |
| DECISIONES.md | Sin decisiones para H1/H2/H3 ni NVENC | Fases ejecutadas y mergeadas | `git log`; `video_encoder.py` | **función disponible** → añadir D41 (hardening), D42 (NVENC), D43 (privacidad/servicios) |
| PREGUNTAS.md (inicio) | Sin tabla de navegación por estado | 52 preguntas; muchas ya resueltas | lectura del archivo | **terminología** → tabla ID/Estado/Tema/Trigger |
| PREGUNTAS.md #52 | S36-C2A1 "EN PR (NO mergeado)" | PR #18 MERGEADO (`d6db673`) | ESTADO.md:24; `git log` | **estado** → marcar CERRADA |
| PREGUNTAS.md #40/#50/#51 | SRT "abiertas/en PR" | S36 COMPLETA (`aa1790a`) | ESTADO.md:22-27 | **estado** → CERRADAS por S36 |
| PREGUNTAS.md #29/#41-48 | Auto/roadmap "registrado/pendiente" | Auto v2 + b-roll entregados | `auto_v2.py`; `studio_auto.py:16` | **estado** → CERRADAS por Auto v2/S37 |
| MATRIZ_READINESS.md:37-46 | "4 P0 abiertos / ~9 P1 abiertos" | 0 P0 / 0 P1 (cerrados en H1/H2) | merges `4dab852`/`5779a77`; MATRIZ filas | **readiness** → 0 P0 / 0 P1 |
| MATRIZ_READINESS.md:5,47 | "Suite tras H3: 2314 / 1894/3-skip" | 2410 passed / 4 skipped | `pytest -q` | **cifra de tests** → 2410/4 |
| MATRIZ_READINESS.md:23-27 | H3 "CERRADO … PENDIENTE MERGE" | H3 mergeado (`b59989f`) | `git log` PR #27 | **merge** → H3 cerrado en main |
| MATRIZ_READINESS.md:72,77 | NVENC "14 checks" y "PR abierto y no mergeado" | Smoke real = 16 checks; NVENC mergeado (`cdcea7a`) | `smoke_nvenc.py` `_check("16_..")`; `git log` PR #28 | **cifra / merge** → 16 checks; NVENC cerrado |
| PLAN_DE_PR.md:3 | "Ninguno se abre en esta fase" (H1..H5) | H1/H2/H3 mergeados; NVENC mergeado | `git log` PRs #25/#26/#27/#28 | **estado** → H1/H2/H3 completados; NVENC fase independiente completada; H4 actual |
| docs/ALPHA_TESTERS.md:11 | "nada se sube a la nube; el único servicio externo opcional es la IA de análisis" | Pexels y Submagic son remotos; Submagic puede subir el video | `submagic.py:28`; `broll_stock.py:53` | **privacidad** → "local por defecto, integraciones externas explícitas y opcionales" |
| docs/ALPHA_TESTERS.md:42 | Barra: "Inicio · Automático · Editor · Creador · Paquetes · Ajustes" | La UI real tiene 7 pestañas incl. **Submagic** | `static/index.html:170-176` | **función/UI** → añadir Submagic |
| docs/ALPHA_TESTERS.md (título) | "Alpha 0.1" | Etiqueta de doc: v0.1.1-alpha candidate | acuerdo H4 | **terminología** → v0.1.1-alpha candidate (candidato de doc, no tag/release) |
| docs/ALPHA_TESTERS.md §11 | Multi-persona "sigue a una sola" (sin matiz) | Reframe escenas/EMA con avoid_faces; sin selección manual multi-persona | `reframe.py`; `reframe_escenas.py`; PREGUNTAS #24b | **limitación** → describir límite multi-persona real |
| docs/ALPHA_TESTERS.md | Faltan SRT, Auto v2, GPU/NVENC, recuperación, formato de feedback, limpieza segura | Todo existe | módulos citados arriba | **función** → añadir secciones |
| ESTADO/DECISIONES + evidencia | Nombre del SRT privado del usuario en texto | Debe tratarse el repo como público | política de privacidad H4 | **archivo privado** → sustituir por `input/video.srt` / "SRT privado del usuario" |
| README_KIT.md | Ruta absoluta del proyecto en la máquina del usuario | Repo público | política de privacidad H4 | **ruta o archivo privado** → placeholder genérico `C:\ruta\centrito` |
| MAESTRO.md | Roadmap histórico presentado línea a línea | Es arquitectura/roadmap histórico, no estado vivo | lectura | **terminología** → addendum que lo marca como histórico (sin reescritura) |

## Clasificación de contradicciones detectadas (mínimos exigidos)

- **README con conteo antiguo de tests:** ✅ (157 → 2410/4).
- **ESTADO previo a H1/H2/H3/NVENC:** ✅ (encabezado 88/100 + 1894 + PR #23).
- **H3 marcado como pendiente:** ✅ (MATRIZ "PENDIENTE MERGE").
- **NVENC marcado como PR abierto:** ✅ (MATRIZ:77).
- **Afirmaciones absolutas "nada se sube":** ✅ (README:5, ALPHA:11).
- **Capacidades SRT/Auto v2/F6 ausentes de la guía:** ✅ (ALPHA, README).
- **Limitaciones multi-persona desactualizadas:** ✅ (ALPHA §11).
- **Rutas/archivos privados en documentos históricos:** ✅ (SRT privado saneado; **0** rutas absolutas del perfil de Windows; ruta de proyecto en README_KIT genericizada; **0** secretos reales — `.env.example` usa el placeholder `sk-xxx`).
- **Documentos que mezclan roadmap histórico con estado actual:** ✅ (ESTADO, MAESTRO).

## Verificado contra el producto (evidencia)

- **Navegación (7 pestañas):** `static/index.html:170-176` → Inicio, Automático, Editor, Creador,
  **Submagic**, Paquetes, Ajustes.
- **Selector de encoder:** `static/index.html:2633-2635` → Automático / GPU NVIDIA — NVENC / CPU.
- **NVENC:** `video_encoder.py` (modos auto/nvenc/cpu, env `CENTRITO_VIDEO_ENCODER`, guard 503 en
  `nvenc` explícito, fallback CPU en `auto`).
- **SRT:** asociación explícita video↔SRT sin autodiscovery (`studio_srt_runtime.py`); texto SRT
  oficial (`static/index.html`); incompatibles con SRT: Palabras por grupo / Énfasis IA / Caption QA
  (`static/index.html`).
- **Auto:** classic y v2 (`static/index.html:522-527`); `caption_source=srt` cableado
  (`studio_auto.py:16`).
- **Servicios:** DeepSeek `brain.py` (`DEEPSEEK_API_KEY`), Pexels `broll_stock.py`
  (`PEXELS_API_KEY`), Submagic `submagic.py` (`SUBMAGIC_API_KEY`, sube el video, opt-in por pestaña),
  ComfyUI `assets_comfy.py` (loopback `127.0.0.1:8188`).
- **Whisper local:** `core.py:34` (CUDA si hay GPU, si no CPU).
- **Recuperación:** `static/job_polling.js` (estado terminal `lost` "El servidor se reinició o el
  trabajo ya no existe", timeout, cancelación) + resume de paquetes en `auto.py`.

## Fuera de alcance de H4 (registrado, NO implementado)

- `revision/pre-hyperframes/NVENC_EVIDENCIA.md` y `NVENC_INVENTARIO.md` citan "14 checks" (histórico
  de esa fase). No están en la lista de archivos editables de H4; se corrige la cifra donde H4 sí
  edita (MATRIZ). Registrado como nota, sin tocar producción.
- Cualquier corrección que exija cambiar código/tests/JS/HTML queda registrada como pendiente y **no**
  se implementa en H4.
