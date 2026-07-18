# Checklist visual para K — S35 Editor de Paquete (checkpoint B4.5)

> Este es el **checkpoint temprano**. El agente se detuvo aquí a propósito: quiere tu
> visto bueno de RUMBO **antes** de invertir en timeline fina, responsive móvil y
> accesibilidad. Revisa el **desktop** (1440×900); lo móvil aún NO está trabajado.

Levanta el Studio con los comandos del `README.md` y recorre esto:

## HOME  (`#home`)
- [ ] Se entienden los tres modos (Automático genera / Editor revisa / Creador controla).
- [ ] Jerarquía clara, sin información técnica de más.

## PAQUETES  (`#paquetes`)
- [ ] Aparece `_s35_fixture` con fecha, cantidad de clips y resumen.
- [ ] Los estados por clip se leen (LISTO / REQUIERE REVISIÓN / NO PUBLICAR AÚN).
- [ ] El botón "Revisar paquete" abre el Editor con ese paquete.

## EDITOR — clip LISTO  (`#revision/_s35_fixture_alpha/0`)
- [ ] Lista de clips a la izquierda con estado por clip; el seleccionado se distingue.
- [ ] El video se reproduce en el preview (patrón de prueba en movimiento).
- [ ] Score, duración, estado y razón se entienden.
- [ ] Bloque **Marcadores**: keyword y popup como filas clicables; clic lleva el video
      a ese punto.
- [ ] Recomendación del paquete visible; "Abrir REPORTE.md" abre el reporte.

## EDITOR — clip REQUIERE REVISIÓN  (`#revision/_s35_fixture_alpha/1`)
- [ ] Alertas de Caption QA con timestamp clicable (0:03, 0:05) → seek.
- [ ] Calidad por tramos con sus rangos, timestamp clicable → seek.
- [ ] **Marcadores (6)**: se ven los 4 tipos (Tramo con rango, Caption QA, Keyword,
      Popup); los dos marcadores casi simultáneos (0:05) NO se pisan.
- [ ] El título con `<script>...</script>` aparece como **texto**, no se ejecuta.

## EDITOR — clip de video faltante  (`#revision/_s35_fixture_alpha/2`)
- [ ] En vez del video se ve el mensaje "Video no disponible para este clip." (no roto).
- [ ] Estado NO PUBLICAR AÚN; el resto del detalle sigue visible.
- [ ] NO aparece el botón "Descargar clip" (no hay binario); la lista de marcadores
      igual funciona.

## SEGURIDAD VISUAL
- [ ] No aparecen rutas absolutas del sistema (C:\...).
- [ ] `<script>` como texto (arriba).
- [ ] (Opcional) En el navegador, pedir la URL del video y cambiar el nombre por
      `paquete.json` da 404 — el confinamiento del PR A (no expone internos).

## LO QUE AÚN NO DEBES JUZGAR (secundario, pendiente de tu visto bueno)
- Responsive móvil (a 390px hoy hay scroll horizontal — ver `editor_390.png`).
- Barra de timeline fina, accesibilidad completa, extracción de `s35.css/js`.

---

### Pregunta del checkpoint

**El lenguaje visual y la estructura, ¿van bien antes de seguir con timeline,
responsive y accesibilidad?**

- Si **sí (rumbo aprobado)** → el agente continúa autónomo con lo secundario y abre el PR.
- Si **hay que corregir el rumbo** → dime qué y lo ajusto antes de invertir en lo demás.
