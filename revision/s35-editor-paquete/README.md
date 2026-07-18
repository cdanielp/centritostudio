# S35 · PR B — Cierre visual del Editor de Paquete (Alpha 0.1)

Rama: `feat/studio-package-review-alpha` (parte de `main` con el PR A ya mergeado).

> **Estado: NÚCLEO implementado — DETENIDO en el checkpoint visual B4.5, esperando el
> veredicto de RUMBO de K antes de invertir en lo secundario (timeline barra fina,
> responsive móvil, accesibilidad, extracción de archivos).**

Este README te deja levantar el Studio en vivo con una fixture sintética y revisar el
Editor de Paquete tal como lo verá un tester, sin abrir JSON ni terminal.

## Qué es el Editor de Paquete

Vista **solo-lectura** sobre `output/paquetes/`: lee lo que el Modo Automático ya
generó (`paquete.json` + `REPORTE.md` + sidecars de Caption QA/brain) y lo presenta
para revisión humana. No edita, no re-renderiza, no toca motores.

## Cómo levantarlo (copiar/pegar desde la raíz del repo)

```powershell
# 1) Generar la fixture local (3 clips sintéticos + sidecars). No usa red.
venv\Scripts\python revision\s35-editor-paquete\gen_fixture.py

# 2) Levantar el Studio (puerto 8799 para no chocar con arranque.bat/8787)
venv\Scripts\python -m uvicorn app:app --port 8799 --log-level warning
```

Luego abre en el navegador:

- **Lista de paquetes:** http://127.0.0.1:8799/#paquetes
- **Editor con un clip LISTO (con video):** http://127.0.0.1:8799/#revision/_s35_fixture_alpha/0
- **Editor con el clip de video faltante (empty state):** http://127.0.0.1:8799/#revision/_s35_fixture_alpha/2
- **Editor con el clip REQUIERE REVISIÓN (Caption QA + todos los marcadores):**
  http://127.0.0.1:8799/#revision/_s35_fixture_alpha/1

Navegación manual: pestaña **Paquetes → "Revisar paquete"** en `_s35_fixture`, y luego
clic en cada clip de la lista izquierda.

Para borrar SOLO la fixture cuando termines (no toca paquetes reales):

```powershell
venv\Scripts\python revision\s35-editor-paquete\gen_fixture.py --clean
```

## La fixture (`_s35_fixture_alpha`)

Tres clips que cubren los estados y todos los tipos de marcador:

| # | Estado | Video | Marcadores | Notas |
|---|--------|-------|-----------|-------|
| 1 | LISTO | sí | keyword, popup | hook limpio, sin alertas |
| 2 | REQUIERE REVISIÓN | sí | 2 tramo (rango), 2 Caption QA, keyword, popup | QA 0:05 y keyword 0:05 casi simultáneos; título con comillas y `<script>` como TEXTO |
| 3 | NO PUBLICAR AÚN | **no** | keyword, popup | empty state del preview; título con acentos/ñ; la lista de marcadores igual funciona sin video |

## Qué se implementó (núcleo) en este PR

- **Lista de marcadores clicable** (B5 núcleo): cada marcador es un botón con tipo
  (Tramo/Caption QA/Keyword/Popup) + tiempo + texto; clic → mueve el video (seek). Los
  tramos muestran rango; markers simultáneos no se pisan; funciona aunque no haya video.
- **Click-to-seek** en los timestamps de Caption QA y de los avisos por tramos (B6).
- **Empty state** del preview cuando el clip no tiene MP4 (sin `<video src=null>`).
- **Etiqueta "Solo lectura"**: aprobar/rechazar se aplicarán en una fase posterior; el
  "aprobado" es solo local del navegador.
- **Deep-link con índice de clip** (`#revision/<pkg>/<idx>`) para abrir un clip concreto.
- **Fixture** `gen_fixture.py` (sin red, con `--clean` que se niega a rutas inesperadas).

La lista de paquetes, el panel de clips, el detalle (preview + score + duración + estado
+ razón), las alertas y la barra de timeline ya existían de sesiones previas; aquí se
completaron los huecos reales del núcleo.

## Evidencia visual (capturas locales, NO versionadas)

En `revision/s35-editor-paquete/screens/` (ignoradas por git vía `.git/info/exclude`):

| Archivo | Qué muestra | Resolución REALMENTE probada |
|---------|-------------|------------------------------|
| `home_1440.png` | Inicio (3 modos) | 1440×900 ✓ |
| `paquetes_1440.png` | Lista de paquetes con la fixture | 1440×900 ✓ |
| `editor_listo_1440.png` | Editor, clip LISTO, video en preview + lista de marcadores | 1440×900 ✓ |
| `editor_alertas_1440.png` | Editor, clip REVISIÓN: Caption QA + 6 marcadores | 1440×900 ✓ |
| `editor_video_faltante_1440.png` | Editor, clip sin video → empty state | 1440×900 ✓ |
| `paquetes_390.png` / `editor_390.png` | Vistas móviles | 390×844 ✓ (ver limitación) |

Capturadas con Edge headless (sin instalar nada). Honestidad: **solo se probaron 1440×900
(desktop) y 390×844 (móvil)**. NO se probaron 1280×720 ni tablets.

## Limitaciones conocidas en este punto (aún NO trabajadas — secundario, post-checkpoint)

- **Responsive móvil:** a 390px el editor NO colapsa a una columna todavía → hay scroll
  horizontal (visible en `editor_390.png`). Es trabajo secundario (B7), deferido hasta
  que K apruebe el rumbo.
- **Barra de timeline fina, accesibilidad completa, extracción `s35.css/js`:** secundario,
  pendientes.
- Orden de la lista: por nombre descendente (determinista); la fixture (`_s35_...`) queda
  al final aunque su fecha sea la más reciente.

## Checkpoint para K

Ver `CHECKLIST_VISUAL.md`. La pregunta de este checkpoint es:

> **"Checkpoint temprano: el lenguaje visual y la estructura, ¿van bien antes de seguir
> con timeline, responsive y accesibilidad?"**
