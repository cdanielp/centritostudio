# Revisión Pre-HyperFrames — Readiness + Hardening de v1

Fase formal de auditoría del producto v1 **antes** de iniciar HyperFrames. No añade features.
Base auditada: `4a378d82814b46e680cda894377b82b8eeba327d` (merge PR #23, cierre F6 esencial).

## Documentos (versionados)
- **`AUDITORIA.md`** — hallazgos completos con evidencia `archivo:línea`, P0/P1/P2/P3.
- **`MATRIZ_READINESS.md`** — tabla de hallazgos + checklist del criterio "LISTO".
- **`PLAN_DE_PR.md`** — secuencia ordenada de PRs (H1..H5) con criterio de cierre y dependencias.
- **`smoke_pre_hyperframes.py`** — arnés de readiness sintético, ejecutable.

## Veredicto
**NO LISTO.** Alcance CASO B: **3 P0** (uno reproducido como escritura arbitraria fuera del
sandbox) + **~9 P1** dispersos entre seguridad, jobs/UI, arranque e integridad del render.
Por regla, esta rama **solo** entrega la auditoría, el plan de PRs y el arnés; **no** implementa
fixes (irían en H1..H5). Bloqueos exactos en `MATRIZ_READINESS.md`.

## Cómo correr el arnés
```powershell
$env:PYTHONIOENCODING="utf-8"
.\venv\Scripts\python revision\pre-hyperframes\smoke_pre_hyperframes.py
```
- Usa `TestClient` (no abre puerto), no requiere GPU ni red.
- Prueba salud, contrato de jobs, y **probes P0** con centinelas **sintéticos** (creados y
  borrados en la misma corrida). Hoy reporta 2 BLOCKERs (P0-1, P0-3) → exit code 1.
- El E2E de render (classic/CVE/reframe/Auto/SRT/resume/editor) está **diferido** hasta cerrar
  H1-H3: con los P1-OUT abiertos, un E2E "verde" sería engañoso.

## Privacidad
- **Nunca** se abre, imprime ni versiona `input/0717_corregido.srt` ni nada bajo
  `input/`, `transcripts/`, `output/`, `studio_srt/`, `thumbs/`.
- Las probes usan datos sintéticos (`_SMOKE_TRAVERSAL_SENTINEL`, `texto-sintetico-de-prueba`).
- La evidencia de corrida se escribe en `output/revision-pre-hyperframes/` (**NO versionada**,
  cubierta por `.gitignore: output/`).

## Qué NO entra en esta fase (clasificado, no implementado)
HyperFrames, F7, Telegram/publicación, presets 6–12, detector full-range, selección manual de
caras, Multi V2, forced aligner, editor persistente, rerender selectivo, edición de SRT en UI.
Ver P3 en `AUDITORIA.md`.
