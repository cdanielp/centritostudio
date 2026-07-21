# Revisión Pre-HyperFrames — Readiness + Hardening de v1

Fase formal de auditoría del producto v1 **antes** de iniciar HyperFrames. No añade features.
Base auditada: `4a378d82814b46e680cda894377b82b8eeba327d` (merge PR #23, cierre F6 esencial).

## Documentos (versionados)
- **`AUDITORIA.md`** — hallazgos completos con evidencia `archivo:línea`, P0/P1/P2/P3.
- **`MATRIZ_READINESS.md`** — tabla de hallazgos + checklist del criterio "LISTO".
- **`PLAN_DE_PR.md`** — secuencia ordenada de PRs (H1..H5) con criterio de cierre y dependencias.
- **`smoke_pre_hyperframes.py`** — arnés de readiness sintético, aislado (sandbox) y ejecutable.
- **`test_smoke_harness.py`** — tests autocontenidos del propio arnés (contrato de excepciones +
  delega la matriz al `--self-test`). Vive fuera de `testpaths`: la suite principal no lo colecta.

## Veredicto
**NO LISTO.** Alcance CASO B: **4 P0** (uno reproducido como escritura arbitraria fuera del
sandbox; el cuarto es exposición de recursos privados en LAN sin auth) + **~9 P1** dispersos
entre seguridad, jobs/UI, arranque e integridad del render.
Por regla, esta rama **solo** entrega la auditoría, el plan de PRs y el arnés; **no** implementa
fixes (irían en H1..H5). Bloqueos exactos en `MATRIZ_READINESS.md`.

## Cómo correr el arnés
```powershell
$env:PYTHONIOENCODING="utf-8"
.\venv\Scripts\python revision\pre-hyperframes\smoke_pre_hyperframes.py
.\venv\Scripts\python revision\pre-hyperframes\smoke_pre_hyperframes.py --self-test
```
- Usa `TestClient` (no abre puerto), no requiere GPU ni red.
- **Aislamiento:** monta la app sobre un **sandbox temporal completo** — redirige los globals de
  `app` **y de los routers montados** (`studio_srt_routes`, `studio_packages`, que definen sus
  propios `INPUT_DIR`/`TRANSCRIPTS`/…), reconstruye los mounts `StaticFiles` sobre un
  `TemporaryDirectory`, y añade una **defensa por snapshot** (metadata-only) que falla si el arnés
  toca cualquier archivo o directorio real fuera del sandbox.
- Prueba salud, contrato de jobs/videos (sólo fixtures sintéticos), y **probes P0** con centinelas
  **sintéticos** (creados y borrados en la misma corrida, con verificación de "sin residuos").
- **Traversal multiplataforma:** payloads Windows (backslash), POSIX (`/`), absolutos, dot-segments
  y NUL, por endpoint `{name}` y por upload multipart. Contrato: 2xx-con-escape → BLOCKER;
  4xx-sin-efecto → PASS; 5xx/excepción interna → FAIL (una excepción **nunca** es PASS).
- **Exposición cubierta:** P0-3 prueba `/output` con `.ass` **y** `.keyword_selection.json`; P0-4
  prueba los mounts `/input`, `/thumbs` **y** `/clips`.
- **Muestra representativa, NO exhaustiva:** el traversal sólo se prueba en `PUT …/transcript`; los
  demás endpoints `{name}` (brain/analyze/depurar/clips/reframe/turnos) **no** se prueban aquí
  (check `cobertura_p0_no_exhaustiva = SKIP`). Verde ≠ todos los P0 cerrados: el smoke **no** es un
  gate de cierre exhaustivo de H1; el mapa P0 completo vive en `AUDITORIA.md`/`PLAN_DE_PR.md`.
- Corrida confirmada: **4 BLOCKERs** (P0-1 traversal, P0-2 upload, P0-3 `/output` texto privado,
  P0-4 exposición de mounts en LAN) → exit code 1; `aislamiento_datos_reales = PASS`.
- `--self-test` valida las **mecánicas del arnés** (sandbox, contrato de clasificación, detección y
  limpieza de escape sobre un caso **controlado**, independiente de la app/SO) — **no** el estado
  vulnerable de hoy ni un SO concreto. Las probes contra la app viva sólo confirman que corren y
  producen una clasificación **válida** (`BLOCKER` vulnerable / `PASS` endurecido o traversal
  contenido·rechazado / `FAIL` defecto real del endpoint como crash-NUL o ruta no escapable en
  POSIX), así que **seguirá verde tras H1 y en Linux/macOS**. Sale verde aunque el smoke principal
  (que sí reporta el estado actual) declare NO LISTO.
- El E2E de render (classic/CVE/reframe/Auto/SRT/resume/editor) está **diferido** hasta cerrar
  H1-H3: con los P1-OUT abiertos, un E2E "verde" sería engañoso.

## Privacidad
- **Nota honesta (corregida en review):** el primer arnés tenía un defecto de aislamiento
  (creaba el `TestClient` con la app apuntando a las rutas reales). No se observó ni imprimió
  deliberadamente contenido privado, pero esa afirmación absoluta no era demostrable y se retiró.
  El arnés corregido (`sandboxed-v2`) usa un **sandbox completo** y la nueva corrida confirma
  **cero acceso** a directorios reales (`aislamiento_datos_reales = PASS`).
- **Nunca** se abre, imprime ni versiona `input/video.srt` ni nada bajo
  `input/`, `transcripts/`, `output/`, `studio_srt/`, `thumbs/`.
- Las probes usan datos sintéticos (`_SMOKE_PRE_HF_SENTINEL`, `texto-sintetico-de-prueba-no-privado`).
  El snapshot de defensa lee **sólo metadata** (ruta/tamaño/mtime), nunca contenido.
- La evidencia de corrida se escribe en `output/revision-pre-hyperframes/` (**NO versionada**,
  cubierta por `.gitignore: output/`).

## Qué NO entra en esta fase (clasificado, no implementado)
HyperFrames, F7, Telegram/publicación, presets 6–12, detector full-range, selección manual de
caras, Multi V2, forced aligner, editor persistente, rerender selectivo, edición de SRT en UI.
Ver P3 en `AUDITORIA.md`.
