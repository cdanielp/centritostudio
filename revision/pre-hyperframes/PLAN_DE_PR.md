# Plan de PRs — Hardening Pre-HyperFrames

**Alcance CASO B (hallazgos dispersos):** 4 P0 + ~9 P1 en seguridad, jobs/UI, arranque e integridad del render. No caben en un solo PR cohesivo → se propone la secuencia H1..H5. **Ninguno se abre en esta fase**; se abrirán uno por uno tras aprobación.

> Regla: una tarea coherente = una rama = un PR. Cada PR con cambio de UI genera capturas escritorio+móvil + demo de error/timeout/recuperación (sin reclamar gate de K). Ningún PR de esta serie cambia salida audiovisual, así que no requieren gate visual de K — **excepto** que P0-3 se resuelva moviendo/renombrando archivos (no cambia el render → tampoco requiere gate).

---

## PR-H1 — Seguridad e integridad de outputs `[BLOQUEANTE]`
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

## PR-H2 — Jobs y recuperación `[BLOQUEANTE]`
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

## PR-H3 — Instalación y diagnóstico `[BLOQUEANTE]`
**Rama:** `fix/h3-arranque-diagnostico`
**Cierra:** P1-BOOT-1, P1-BOOT-2; P2-BOOT-3..6.
**Cambios mínimos:**
- Preflight `shutil.which("ffmpeg"/"ffprobe")` en startup de `app.py` con mensaje accionable (qué falta, cómo instalar, qué queda deshabilitado) sin tumbar la UI.
- Documentar URLs+ruta de modelos yunet/blazeface (README/ENTORNO) o autodescarga con hash; URL en el `FileNotFoundError`.
- `arranque.bat`: guard de venv (copiar de `check.bat:9-12`), abrir navegador tras health-check, capturar bind-error del puerto.
- `check.bat`: paso "entorno" (ffmpeg + modelos + versión Python).
**Tests:** unit del preflight (mock `which`); mensajes accionables. **Criterio:** arranque desde estado limpio da errores accionables, no tracebacks crípticos.
**Dependencia:** ninguna.

## PR-H4 — Documentación y tester readiness `[NO BLOQUEANTE]`
**Rama:** `docs/h4-readiness-docs`
**Cierra:** todos los P2-DOCS + ALPHA-01..07 + PREGUNTAS-TAXONOMIA + README-157.
**Cambios mínimos:**
- `ESTADO.md`: corregir estado actual (F6 esencial MERGEADA `4a378d8`, S36 COMPLETA, suite 1894); addendum de bitácora que registre el merge de #23; marcar listas viejas como HISTÓRICO (no borrar).
- `DECISIONES.md`: addendum a D40 (mergeado + suite real). **No** reescribir el bloque histórico.
- `PREGUNTAS.md`: marca de estado por ítem (ACTIVA/CERRADA/TRIGGER); cerrar #52 stale (C2C/C2A1).
- `docs/ALPHA_TESTERS.md`: contrastar con el producto real y añadir SRT, Auto v2, F6/CVE, avoid_faces, Reanudar clips fallidos, límites multi-persona reales, qué requiere ComfyUI, diagnóstico sin compartir archivos privados, cómo limpiar outputs, versión/commit probado (`4a378d8`).
- Verificar `D40-MULTITURNOS-FACEY` contra `reframe.py` antes de tocar esa línea.
**Criterio:** documentación actual sin contradicciones; ALPHA no promete lo inexistente.
**Dependencia:** debería ir **después** de H1/H2/H3 (para documentar el estado ya endurecido).

## PR-H5 — CI / quality gate remoto ligero `[NO BLOQUEANTE]`
**Rama:** `ci/h5-quality-gate`
**Contexto:** no existe `.github/`. La suite depende de Windows/FFmpeg/modelos → separar:
1. **Gate remoto ligero (GitHub Actions):** `ruff check` + `ruff format --check` + subconjunto de tests puros/contrato que no requieran FFmpeg/GPU/node/modelos/red. Determinista, sin claves, sin archivos privados.
2. **Gate local completo documentado:** `check.bat full` (suite + smoke render GPU).
**Criterio:** el workflow queda **verde** (no rojo permanente); documentar qué valida cada gate.
**Dependencia:** después de H1..H3 (para que el subconjunto remoto sea estable).

---

## Orden y dependencias
```
H1 (seguridad+integridad)  → H2 (jobs+resume)  → H3 (arranque)  → H4 (docs)  → H5 (CI)
   BLOQUEANTE                 BLOQUEANTE           BLOQUEANTE        no-bloq.     no-bloq.
```
Readiness técnica se alcanza al cerrar **H1+H2+H3** (los P0/P1). H4/H5 elevan calidad y confianza pero no bloquean el arranque de HyperFrames una vez cerrados los bloqueantes.
