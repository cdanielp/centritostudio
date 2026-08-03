# Plan de PRs — Hardening Pre-HyperFrames

**Alcance CASO B (hallazgos dispersos):** 4 P0 + ~9 P1 en seguridad, jobs/UI, arranque e integridad del render. No caben en un solo PR cohesivo → secuencia H1..H5.

**Estado de la secuencia (sobre `3cbac46`):**

| PR | Fase | Estado | Merge |
|---|---|---|---|
| H1 | Seguridad e integridad | **COMPLETADO en main** | `4dab852` (PR #25) |
| H2 | Jobs y recuperación | **COMPLETADO en main** | `5779a77` (PR #26) |
| H3 | Arranque y diagnóstico | **COMPLETADO en main** | `b59989f` (PR #27) |
| — | GPU/NVENC (fase independiente de rendimiento) | **COMPLETADO en main** | `cdcea7a` (PR #28) |
| H4 | Documentación y readiness | **COMPLETADO en main** | `3cbac46` (PR #29) |
| **H5** | CI / quality gate remoto ligero | **ACTUAL — PR abierto, no mergeado** | — |

HyperFrames/F7 queda **fuera** de la secuencia H1–H5 (bloqueado hasta el gate final; no hay H6).

> Regla: una tarea coherente = una rama = un PR. Cada PR con cambio de UI genera capturas escritorio+móvil + demo de error/timeout/recuperación (sin reclamar gate de K). Ningún PR de esta serie cambia salida audiovisual, así que no requieren gate visual de K — **excepto** que P0-3 se resuelva moviendo/renombrando archivos (no cambia el render → tampoco requiere gate).

---

## PR-H1 — Seguridad e integridad de outputs `[BLOQUEANTE]` · ✅ MERGEADO `4dab852` (PR #25)
**Rama:** `fix/h1-seguridad-integridad`
**Cierra:** P0-1, P0-2, P0-3, P0-4, P1-OUT-1, P1-OUT-2.
**Cambios mínimos:**
- Guard `is_safe_basename(name)` compartido (dependency/middleware) en todos los endpoints `{name}` de `app.py`.
- `upload_video`: validar basename + extensión (`.mp4/.mov`), escritura por chunks con tope de bytes (reusar `_read_upload_limited`), `.tmp`+`os.replace`.
- Sacar `.ass`/`.keyword_selection.json` del árbol servido **o** restringir `/output` a `.mp4`.
- **P0-4 (exposición LAN):** default de host a `127.0.0.1` en `arranque.bat` y `app.py.__main__`; LAN sólo por opt-in explícito y documentado (p.ej. `CENTRITO_HOST`); con LAN activo, warning visible + token/auth; **quitar** el mount público `/input` (o endpoint validado); revisar `/thumbs` y `/clips`; `/output` sólo tipos permitidos.
- `burn_video*`: quemar a `*.mp4.part` → validar returncode+`st_size>0`+ffprobe(`duration>0`, stream de video) → `os.replace`; si falla, borrar parcial y `raise`.
**Tests:** traversal (`..\`, `../`, absoluto, NUL) → 404 en cada endpoint; upload traversal/oversize → 400/413; `GET /output/x.ass` → 404; host default = loopback y con opt-in emite warning; `GET /input/*` no accesible sin endpoint validado; `burn_video` con salida 0-byte → `raise`, job `error` no `done`.
**Criterio de cierre:** suite verde; probe de traversal (sintético) no escribe fuera del sandbox; `.ass` no accesible por HTTP; server no bindea `0.0.0.0` por default; ningún MP4 0-byte publicable.
**Dependencia:** ninguna. **Primero** (mayor riesgo).

## PR-H2 — Jobs y recuperación `[BLOQUEANTE]` · ✅ MERGEADO `5779a77` (PR #26)
**Rama:** `fix/h2-jobs-resume`
**Cierra:** P1-POLL-1..4, P1-OUT-3; P2-POLL-5/6/7, P2-ATOM-STATE, P2-CLASSIC-REUSE, P2-PAQUETE-DIR.
**Cambios mínimos:**
- `pollJob`/`pollJobP`/`_pollReframe`: fallo por defecto sin `onFailure`; try/catch + `r.ok`; `deadlineMs`+`maxFallos`; `clearInterval`/dedupe; estado "servidor reiniciado/job perdido" + Reintentar/Cancelar; `role=status`/`aria-live`.
- Resume: añadir `st_size>0` (ideal ffprobe) a los 4 predicados de validez (`auto.py:457,546,119`, `auto_v2.py:62`).
- Atomicidad de estado con `_atomic_write_text` para checkpoint sidecar (`auto.py:568`) y clips/marker/REPORTE.
- Auto classic: sellar procedencia (size+mtime) en `{name}_words.json` (portar patrón de Studio).
**Tests:** JS real (harness node) para 404/500/red/timeout → mensaje+botón, sin doble intervalo; resume con MP4 0-byte → re-render; mismo stem distinto size → no reusa.
**Criterio:** no existe spinner infinito silencioso; resume no acepta truncados; suite verde.
**Dependencia:** ideal tras H1 (comparte el tmp+rename de P1-OUT-2).

## PR-H3 — Instalación y diagnóstico `[BLOQUEANTE]` · ✅ MERGEADO `b59989f` (PR #27)
**Rama:** `fix/h3-arranque-diagnostico`
**Cierra:** P1-BOOT-1, P1-BOOT-2; P2-BOOT-3..6.
**Cambios mínimos:**
- Preflight `shutil.which("ffmpeg"/"ffprobe")` en startup de `app.py` con mensaje accionable (qué falta, cómo instalar, qué queda deshabilitado) sin tumbar la UI.
- Documentar URLs+ruta de modelos yunet/blazeface (README/ENTORNO) o autodescarga con hash; URL en el `FileNotFoundError`.
- `arranque.bat`: guard de venv (copiar de `check.bat:9-12`), abrir navegador tras health-check, capturar bind-error del puerto.
- `check.bat`: paso "entorno" (ffmpeg + modelos + versión Python).
**Tests:** unit del preflight (mock `which`); mensajes accionables. **Criterio:** arranque desde estado limpio da errores accionables, no tracebacks crípticos.
**Dependencia:** ninguna.

> **Nota:** entre H3 y H4 se ejecutó la fase independiente **GPU/NVENC** (rendimiento, no readiness):
> `video_encoder.py` con modos auto/nvenc/cpu y fallback CPU. **MERGEADO `cdcea7a` (PR #28).** No
> es parte de la secuencia bloqueante; la ruta CPU sigue siendo válida. Ver `NVENC_EVIDENCIA.md`.

## PR-H4 — Documentación y tester readiness `[NO BLOQUEANTE]` · ✅ MERGEADO `3cbac46` (PR #29)
**Rama:** `docs/h4-readiness-docs`
**Cierra:** todos los P2-DOCS + guía de testers + taxonomía de PREGUNTAS + README (conteo de tests).
**Cambios (documentación únicamente, base `cdcea7a`, suite 2410/4):**
- `README.md`: Alpha pre-HyperFrames, funciones verificadas, tabla local/remoto, baseline 2410/4 en un solo bloque, sin el conteo antiguo de tests ni conteo de líneas.
- `ESTADO.md`: encabezado con estado real (H1/H2/H3/NVENC cerrados + merges exactos), readiness verificable (0 P0/0 P1), bitácora de H1–H4; marcar 88/100 y 1894 como HISTÓRICO (no borrar).
- `DECISIONES.md`: addendum de cierre de D40 (mergeado) + D41 (hardening) + D42 (NVENC) + D43 (privacidad/servicios). **No** reescribir bloques históricos.
- `PREGUNTAS.md`: tabla de navegación por estado (ACTIVA/CERRADA/DIFERIDA-TRIGGER/HISTÓRICA); cerrar #52 y las resueltas por S36/Auto v2/F6/H1-3/NVENC.
- `docs/ALPHA_TESTERS.md`: contrastar con el producto real y añadir SRT, Auto v2, GPU/NVENC, 7 pestañas (incl. Submagic), recuperación, servicios externos, compatibilidad, formato de feedback, limpieza segura.
- `docs/ENTORNO.md`: checklist de clon limpio + matriz de compatibilidad + requisito vs opcional + enlaces.
- `MATRIZ_READINESS.md` / `PLAN_DE_PR.md`: readiness 0 P0/0 P1, H1/H2/H3/NVENC cerrados, smoke NVENC 16 checks.
- Saneamiento de referencias privadas (SRT privado del usuario → placeholder genérico).
**Criterio:** documentación actual sin contradicciones; ALPHA no promete lo inexistente; sin cambios de producción ni audiovisuales.
**Dependencia:** va **después** de H1/H2/H3 y GPU/NVENC (documenta el estado ya endurecido).

## PR-H5 — CI / quality gate remoto ligero `[NO BLOQUEANTE]` · 🔶 ACTUAL (PR abierto, no mergeado)
**Rama:** `ci/h5-quality-gate`
**Contexto:** la suite completa depende de Windows/FFmpeg/modelos/Node → se separa en dos gates:
1. **Gate remoto ligero (GitHub Actions, Ubuntu, Python 3.12):** `.github/workflows/quality.yml` con
   `ruff check` + `ruff format --check` + smoke H4 (docs) + smoke H5 (contrato del propio gate) +
   subconjunto portable de tests puros (`ci/run_pytest_light.py` sobre `ci/pytest-light.txt`), con la
   red bloqueada (`pytest-socket`). Permisos `contents: read`, sin secrets, sin cache, solo acciones
   oficiales (`checkout@v6`, `setup-python@v6`). `requirements-ci.txt` mínima (sin deps pesadas).
2. **Gate local completo autoritativo:** `check.bat` (entorno real + suite completa) y `check.bat full`
   (smoke render GPU sobre fixture sintético).
**Criterio:** workflow **verde** en el HEAD final; documentar qué valida y qué NO valida cada gate.
**Dependencia:** después de H1..H4 (para que el subconjunto remoto y las docs sean estables).

---

## Orden y dependencias
```
H1 ✅ → H2 ✅ → H3 ✅ → [GPU/NVENC ✅] → H4 ✅ → H5 🔶 → (gate final) → HyperFrames
BLOQ.   BLOQ.   BLOQ.    rendimiento      docs   CI
```
Readiness técnica **ya alcanzada** al cerrar **H1+H2+H3** (0 P0 / 0 P1). GPU/NVENC se cerró como
fase independiente de rendimiento. H4 (docs) cerrado en main. H5 (CI, este PR) eleva calidad y
confianza pero no bloquea el arranque de HyperFrames, que queda detrás del gate final. HyperFrames/F7
queda **fuera** del plan H1–H5.
