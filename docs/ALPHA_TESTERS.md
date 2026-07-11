# Centrito Studio — Guía para testers (Alpha 0.1)

Gracias por probar el Alpha. Esto es software en construcción: lo que más nos sirve
es que lo uses con TUS videos reales y nos digas exactamente dónde se sintió mal.

## 1. Qué es Centrito Studio

Una fábrica local de clips virales: le das un video con voz en español y te devuelve
un **paquete de clips verticales con captions animados**, listo para que TÚ revises
y publiques. Todo corre en esta PC (nada se sube a la nube; el único servicio externo
opcional es la IA de análisis). No es un editor de video genérico: es una fábrica con
opinión — tú revisas el resultado, no editas timeline.

## 2. Qué puedes probar

- **Modo Automático** (la prueba principal): video entra → paquete de clips sale.
- **Modo Creador**: las herramientas por separado — transcribir, editar texto,
  depurar silencios, generar clips, reencuadrar a vertical, renderizar captions
  con estilos y presets virales.
- **Caption QA** (nuevo): detector de palabras mal transcritas ("confeti UI" en vez
  de "ComfyUI") con corrección opcional.

## 3. Cómo arrancar la app

1. Doble click en `arranque.bat` (raíz del proyecto).
2. Se abre el navegador en `http://127.0.0.1:8787` con **Centrito Studio**.
3. Si no abre solo: abre esa dirección a mano en Edge/Chrome.

## 4. Qué tipo de videos sirven

- **Sirven**: clases, charlas a cámara, podcasts, grabaciones OBS con voz clara en
  español. Horizontal (16:9) o vertical. Idealmente 2 a 60 minutos.
- **Aún flojos** (puedes probarlos, pero avisa que son de estos): grabaciones de
  pantalla sin cámara (el reencuadre centra fijo), videos con 2+ personas en cuadro
  todo el tiempo (sigue a una sola), audio con música fuerte o sin voz.
- Deja tu video en la carpeta `input/` o súbelo arrastrándolo a la pestaña Videos.

## 5. Cómo usar el Modo Automático

1. Pestaña **"Modo Automático"**.
2. Elige tu video y el objetivo **"Clips virales"**.
3. Espera: transcribe → analiza con IA → corta clips → reencuadra a vertical →
   quema captions. Un video de 1 hora tarda unos minutos; verás el progreso por etapa.
4. Al final te dice dónde quedó el paquete.

## 6. Qué revisar en el paquete final

El paquete queda en `output/paquetes/{tu_video}_{fecha}/` y trae:

- Los **clips finales** (MP4 verticales 1080x1920 con captions).
- **`REPORTE.md`**: ábrelo SIEMPRE. Ahí está el resumen por clip: score de la IA,
  por qué eligió ese momento, avisos de calidad por tramos ("revisa 0:16-0:31: 2
  personas en cuadro"), y las alertas de **Caption QA** (palabras posiblemente mal
  transcritas, cuántas se aplicaron y cuántas quedan pendientes de tu revisión).
- Regla de oro: **nada se publica sin revisión humana** — el paquete es un borrador
  bueno, tú tienes la última palabra.

## 7. Qué errores reportar (y cómo)

Repórtanos con: qué video era (o mándalo), qué botón tocaste, qué esperabas y qué
pasó. Captura de pantalla si hay mensaje de error. Nos interesa especialmente:

- La app se congela o un progreso se queda pegado sin mensaje.
- Un render falla o sale un MP4 corrupto/negro.
- Captions desincronizados, texto cortado o palabras gigantes fuera de pantalla.
- El reencuadre pierde a la persona o "tiembla".
- Caption QA corrige algo que estaba BIEN (falso positivo) — esto es oro, avísanos.
- Un mensaje de error que no te dice qué hacer a continuación.

## 8. Dónde quedan los outputs

| Qué | Dónde |
|---|---|
| Paquetes del Modo Automático | `output/paquetes/{video}_{fecha}/` |
| Renders sueltos (pestaña Render) | `output/` |
| Clips cortados sin captions | `output/clips/` |
| Transcripciones y análisis | `transcripts/` |
| Alertas de Caption QA | `transcripts/{video}_caption_alerts.json` |

## 9. Qué NO esperar todavía (Alpha)

- **Publicación automática** a TikTok/Reels/Shorts: no existe; publicas a mano.
- **Editor visual / timeline**: no lo habrá — no es ese producto.
- Otros idiomas: por ahora español.
- Multi-persona perfecto: con 2+ caras sigue a una sola (aviso en el reporte).
- Grabaciones de pantalla: encuadre centrado fijo, sin seguimiento.
- Emojis IA requieren ComfyUI corriendo local; si no está, salen sin emojis (normal).
- Corrección total de transcripción: Caption QA solo autoaplica lo que es seguro;
  el resto te lo deja como alerta a propósito.

---

## Checklist de prueba (marca lo que SÍ funcionó)

- [ ] El video carga en la pestaña Videos (miniatura + duración visibles)
- [ ] El Modo Automático genera un paquete completo sin errores
- [ ] Los captions se ven y están sincronizados con la voz
- [ ] El reencuadre vertical mantiene a la persona en cuadro
- [ ] El `REPORTE.md` se entiende sin ayuda (scores, avisos, telemetría)
- [ ] Caption QA reporta alertas en el reporte (y `_caption_alerts.json` existe)
- [ ] Los popups/emojis (si los activaste) no tapan la cara ni los captions
- [ ] La keyword manual (si probaste `{video}_keywords.json`) se destacó en el render
- [ ] La carpeta final es clara: encontraste tus clips sin buscar

Cualquier casilla que NO puedas marcar es exactamente lo que queremos saber.
