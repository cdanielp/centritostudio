# S35 · PR B — Cierre visual del Editor de Paquete (Alpha 0.1)

Rama: `feat/studio-package-review-alpha` (parte de `main` con el PR A ya mergeado).

> **Estado: implementada — pendiente del ojo (revisión visual final) de K.**
> El checkpoint temprano B4.5 fue APROBADO por K con correcciones obligatorias; este
> PR ya las incorpora. NO se mergea hasta el veredicto visual final de K.

Vista **solo-lectura** sobre `output/paquetes/`: lee lo que el Modo Automático ya
generó (`paquete.json` + `REPORTE.md` + sidecars QA/brain) y lo presenta para revisión
humana. No edita, no re-renderiza, no toca motores.

## Cómo levantarlo (copiar/pegar desde la raíz del repo)

```powershell
venv\Scripts\python revision\s35-editor-paquete\gen_fixture.py
venv\Scripts\python -m uvicorn app:app --port 8799 --log-level warning
```

URLs (deep-link por hash):
- **Lista de paquetes:** http://127.0.0.1:8799/#paquetes
- **Editor, clip LISTO (con video):** http://127.0.0.1:8799/#revision/_s35_fixture_alpha/0
- **Editor, clip REQUIERE REVISIÓN (Caption QA + 6 marcadores):** http://127.0.0.1:8799/#revision/_s35_fixture_alpha/1
- **Editor, clip de video faltante (empty state):** http://127.0.0.1:8799/#revision/_s35_fixture_alpha/2

Borrar SOLO la fixture al terminar: `venv\Scripts\python revision\s35-editor-paquete\gen_fixture.py --clean`

## La fixture (`_s35_fixture_alpha`)

| # | Estado | Video | Marcadores | Notas |
|---|--------|-------|-----------|-------|
| 1 | LISTO | sí | keyword, popup | hook limpio, sin alertas |
| 2 | REQUIERE REVISIÓN | sí | 2 tramo (rango), 2 Caption QA, keyword, popup | QA 0:05 y keyword 0:05 casi simultáneos; título con comillas y `<script>` como TEXTO |
| 3 | NO PUBLICAR AÚN | **no** | keyword, popup | empty state; título con acentos/ñ; la lista de marcadores funciona sin video |

## Correcciones de K aplicadas (checkpoint B4.5)

1. **Preview vertical como elemento principal:** caja 9:16 determinista (`aspect-ratio`),
   `object-fit:contain`, centrada, ~62–70vh de alto en desktop, sticky, sin deformar ni
   recortar; un solo video a la vez. Empty state comparte esa huella vertical.
2. **Responsive real:** a <=900px el editor se apila (selector → clips → video → estado →
   alertas/tramos → marcadores → timeline → recomendación → acciones); el sidebar pasa
   arriba, la nav superior usa scroll horizontal controlado, botones >=44px. Sin scroll
   horizontal global (ver nota de verificación abajo).
3. **Acción de aprobación:** ahora "Marcar como revisado en esta sesión" / "Revisado
   (quitar)" con `aria-pressed` y aviso "**no se guarda** — no modifica el paquete".
4. **Jerarquía:** video → estado/score/duración/razón → alertas → marcadores → timeline
   compacto → recomendación → acciones.
5. **Copy para testers:** "Sin elementos visuales adicionales" / "N elemento(s) visual(es)"
   en vez de "overlays"; "Copiar ubicación"; "Score IA" con tooltip; títulos de clip a 2
   líneas con `title` accesible y quiebre de tokens largos (no truncado destructivo).
6. **Paquetes:** orden por `meta.fecha` **descendente** (fallback determinista por id);
   el más reciente primero; CTA visible "Revisar paquete →"; tarjeta-botón accesible;
   badges agrupados con conteo cuando hay muchos clips.
7. **Timeline y marcadores:** lista clicable con tipo/tiempo/texto (tramo con rango),
   simultáneos no se pisan, seek por click **y teclado** (son `<button>`), leyenda,
   fallback como lista sin video/duración, sin división por cero; barra compacta debajo.
8. **Accesibilidad:** `<button>` reales, `:focus-visible` visible, `aria-label`/`aria-current`,
   estados con texto (no solo color), Enter/Espacio activan marcadores, sin quitar outline.

## Evidencia visual (capturas locales, NO versionadas)

En `revision/s35-editor-paquete/screens/` (ignoradas por git):
`home_1440`, `paquetes_1440`, `editor_listo_1440`, `editor_alertas_1440`,
`editor_timeline_1440`, `editor_video_faltante_1440`, `paquetes_1280`, `editor_1280`,
`paquetes_390`, `editor_390`.

**Honestidad sobre resoluciones (léelo):** Edge headless en este equipo (Windows a 125%)
fija un viewport CSS mínimo de ~492px, así que las capturas "390" se tomaron a ~492px CSS
(rango móvil, reglas responsive activas) — muestran el layout apilado real sin recortes.
La ausencia de scroll horizontal a móvil se **verificó por medición**
(`document.documentElement.scrollWidth == window.innerWidth`, sin overflow). El píxel-perfect
a 390px exacto NO se pudo capturar en este headless; K puede confirmarlo en vivo con las
devtools del navegador. Desktop 1440 y 1280 sí se probaron (con el mismo factor de escala).

## Limitaciones / deuda (ver PREGUNTAS.md)

- Extracción de `static/s35.css` / `s35.js`: **diferida** (riesgo de romper otras pestañas
  frente a beneficio bajo; el monolito no creció de forma relevante).
- Aprobar/rechazar **persistente** (server-side) y edición conjunta QA/keywords: fase
  posterior. Hoy "revisado" es solo local del navegador.
- La barra de timeline es una ayuda de mouse; el camino accesible por teclado es la lista.

## Qué debe revisar K

`CHECKLIST_VISUAL.md`. Este es el **ojo final**: si aprueba, el PR queda listo para merge
(lo hace K, no el agente).
