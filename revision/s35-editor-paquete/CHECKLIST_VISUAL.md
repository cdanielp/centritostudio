# Checklist visual final para K — S35 Editor de Paquete

> El checkpoint temprano B4.5 ya lo aprobaste (con correcciones, todas aplicadas). Esta es
> la revisión **final**. Levanta el Studio con los comandos del `README.md` y recorre esto.
> Desktop es prioritario; móvil, si quieres, con las devtools del navegador a 390px.

## HOME (`#home`)
- [ ] Tres modos entendibles, jerarquía clara, sin tecnicismos de más.

## PAQUETES (`#paquetes`)
- [ ] El paquete más reciente aparece **primero** (`_s35_fixture`, 20260717, arriba).
- [ ] Cada tarjeta muestra fecha, cantidad de clips, resumen y estados legibles.
- [ ] CTA visible "Revisar paquete →"; la tarjeta entera abre el Editor (y es un botón).
- [ ] Empty state claro si no hay paquetes.

## EDITOR — clip LISTO (`#revision/_s35_fixture_alpha/0`)
- [ ] **Preview vertical (9:16) como elemento principal**, centrado, sin deformar; el video
      reproduce (patrón de prueba en movimiento).
- [ ] Estado, Score IA (con tooltip), duración y razón se entienden.
- [ ] Marcadores keyword/popup como filas clicables; click lleva el video a ese punto.
- [ ] Timeline compacto debajo; recomendación visible; "Abrir REPORTE.md" abre el reporte.
- [ ] Acción dice "Marcar como revisado en esta sesión" y avisa que **no se guarda**.

## EDITOR — clip REQUIERE REVISIÓN (`#revision/_s35_fixture_alpha/1`)
- [ ] Alertas de Caption QA con timestamp clicable (0:03, 0:05) → seek.
- [ ] Calidad por tramos con rangos, timestamp clicable → seek.
- [ ] Marcadores (6): los 4 tipos (Tramo con rango, Caption QA, Keyword, Popup); los dos de
      0:05 NO se pisan; con teclado (Tab + Enter/Espacio) también hacen seek.
- [ ] El título con `<script>...</script>` aparece como **texto**, no se ejecuta.

## EDITOR — clip de video faltante (`#revision/_s35_fixture_alpha/2`)
- [ ] "Video no disponible para este clip." en la huella del preview (no roto).
- [ ] NO aparece "Descargar clip"; la lista de marcadores igual funciona.

## MÓVIL (390px, con devtools)
- [ ] Sin scroll horizontal; contenido legible; video no desborda; selector accesible;
      lista de clips y marcadores usables; botones tocables.

## SEGURIDAD VISUAL
- [ ] `<script>` como texto; no se ejecuta HTML; no hay rutas absolutas del sistema.
- [ ] (Opcional) pedir la URL del video del paquete y cambiar el nombre por `paquete.json`
      da 404 (confinamiento del PR A).

## Evidencia adjunta (en `screens/`, no versionada)
`home_1440`, `paquetes_1440`/`_1280`, `editor_listo_1440`, `editor_alertas_1440`,
`editor_timeline_1440`, `editor_video_faltante_1440`, `editor_1280`, `paquetes_390`,
`editor_390`. (Ver nota de resoluciones en el README: móvil capturado a ~492px CSS por
límite del headless; ausencia de scroll horizontal verificada por medición.)

---

Si apruebas, el PR queda listo para **merge por K** (el agente NO lo mergea).
