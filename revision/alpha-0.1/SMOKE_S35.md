# Smoke visual S35 — Editor de Paquete + UI premium (Alpha 0.1)

Fecha: 2026-07-11 · Servidor: FastAPI puerto 8799 (headless Edge) · Sin tocar motores.

## Qué se verificó

1. **Los 3 modos + navegación existen**: `Inicio · Automático · Editor · Creador ·
   Paquetes · Ajustes` (todos los `showTab(...)` presentes en el HTML servido).
2. **Editor de Paquete carga un paquete real** (`mariosoto_20260711-1316`, 3 clips).
3. **Preview de video funciona**: `GET .../mariosoto_clip1_corto_9x16_hormozi.mp4` → 200;
   el `<video>` se reproduce en el panel derecho.
4. **REPORTE.md accesible**: `GET .../REPORTE.md` → 200.
5. **Estados / alertas / tramos se muestran**: semáforo por clip (REQUIERE REVISION),
   alerta Caption QA `0:24 "mira"` (resuelta del sidecar), 2 tramos con aviso.
6. **Timeline de revisión**: markers de tramos (2), Caption QA (1), keywords (15),
   popups (2), leídos de los sidecars; clic-para-seek.
7. **Guard de path traversal**: `GET /api/paquetes/..%2f..` → 404.

## Capturas (revision/alpha-0.1/ui/)

| Archivo | Vista |
|---|---|
| `01_inicio.png` | Dashboard/cockpit (hero + cards de modo + capacidades) |
| `02_automatico.png` | Modo Automático en 5 pasos |
| `03_editor_paquete.png` | Editor de Paquete (preview + estado + alertas + tramos + timeline + recomendación) |
| `04_creador.png` | Modo Creador (10 herramientas en cards) |
| `05_paquetes.png` | Lista de paquetes con semáforo de estados |

## Resultado

Todo verde. Ninguna vista rompe; las herramientas existentes siguen accesibles desde
Creador. `check.bat` en verde (349 tests + ruff + formato). No se tocó reframe,
clipper, depurador, brain, core ni render.
