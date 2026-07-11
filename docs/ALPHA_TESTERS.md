# Centrito Studio — Guía para testers (Alpha 0.1)

Gracias por probar el Alpha. Esto es software en construcción: lo que más nos sirve
es que lo uses con TUS videos reales y nos digas exactamente dónde se sintió mal.

## 1. Qué es Centrito Studio

Una fábrica local de clips virales: le das un video con voz en español y te devuelve
un **paquete de clips verticales con captions animados**, listo para que TÚ revises
y publiques. Todo corre en esta PC (nada se sube a la nube; el único servicio externo
opcional es la IA de análisis). No es un editor de video tipo CapCut: no hay timeline
multipista ni cortes manuales. Es una fábrica con opinión + una mesa de revisión.

### Los 3 modos (esto es nuevo en Alpha 0.1)

Al abrir la app caes en **Inicio**, un tablero con 3 tarjetas:

1. **Modo Automático** — *genera*. Video entra → paquete de clips sale.
2. **Editor de Paquete** — *revisa*. Abre un paquete ya generado y mira clip por clip
   qué salió bien y qué revisar (estados, alertas, timeline). NO edita el video: es
   una vista de revisión sobre lo que ya se produjo.
3. **Modo Creador** — *controla*. Las herramientas sueltas con control fino
   (transcribir, clipper, reframe, stack, captions, Caption QA, depurador…).

Regla mental: **Automático genera · Editor revisa · Creador controla.**

## 2. Qué puedes probar

- **Modo Automático** (la prueba principal): video entra → paquete de clips sale.
- **Editor de Paquete** (nuevo): revisa el paquete sin abrir archivos ni JSON.
- **Modo Creador**: las herramientas por separado — transcribir, editar texto,
  depurar silencios, generar clips, reencuadrar a vertical, renderizar captions
  con estilos y presets virales.
- **Caption QA**: detector de palabras mal transcritas ("confeti UI" en vez de
  "ComfyUI") con corrección opcional.

## 3. Cómo arrancar la app

1. Doble click en `arranque.bat` (raíz del proyecto).
2. Se abre el navegador en `http://127.0.0.1:8787` con **Centrito Studio** en **Inicio**.
3. Si no abre solo: abre esa dirección a mano en Edge/Chrome.
4. Navega con la barra de arriba: **Inicio · Automático · Editor · Creador · Paquetes · Ajustes**.

## 4. Qué tipo de videos sirven

- **Sirven**: clases, charlas a cámara, podcasts, grabaciones OBS con voz clara en
  español. Horizontal (16:9) o vertical. Idealmente 2 a 60 minutos.
- **Aún flojos** (puedes probarlos, pero avisa que son de estos): grabaciones de
  pantalla sin cámara (el reencuadre centra fijo), videos con 2+ personas en cuadro
  todo el tiempo (sigue a una sola), audio con música fuerte o sin voz.
- Sube tu video desde **Creador → Biblioteca de videos** (arrástralo) o déjalo en `input/`.

## 5. Cómo usar el Modo Automático

Ahora es un flujo de **5 pasos** en la pestaña **Automático**:

1. **Elige el video.**
2. **Elige el objetivo** ("Clips virales").
3. **Qué incluye el paquete**: verás las etapas fijas (reframe, captions, Caption QA,
   reporte). No se configuran aquí — es solo para que sepas qué vas a recibir.
4. **Genera el paquete.** Verás el progreso por etapa (transcribe → analiza IA → corta
   → reencuadra → captions). Un video de 1 hora tarda unos minutos.
5. **Revisa en el Editor.** Al terminar aparece un botón **"Abrir en el Editor de
   Paquete"** — úsalo; ahí revisas todo sin buscar archivos.

## 6. El Editor de Paquete (la mesa de revisión)

Entra por **Editor** (o por el botón del paso 5, o desde **Paquetes**). A la izquierda
eliges el paquete y ves sus clips; al seleccionar uno, a la derecha aparece:

- **Preview del clip** (se reproduce ahí mismo).
- **Estado** del clip (semáforo, ver §7), **score de IA** y **duración**.
- **Alertas Caption QA** con timestamp, palabra detectada → sugerencia y confianza.
- **Calidad por tramos** (dónde el reframe pudo perder a la persona, etc.).
- **Timeline de revisión**: una barra con marcas de colores —
  naranja = tramos con aviso, cian = Caption QA, amarillo = keywords, morado = popups.
  Clic en la barra mueve el video a ese punto.
- **Recomendación del paquete** (qué revisar, qué tramos mirar, cuál es más publicable).
- **Botones**: descargar clip, copiar ruta, abrir `REPORTE.md`, y **marcar como
  aprobado** (queda guardado en tu navegador, no toca los archivos).

El Editor NO recalcula nada: solo muestra lo que el Modo Automático ya escribió.

## 7. Cómo leer los estados de un clip

Cada clip trae un **semáforo** para decidir rápido:

| Estado | Qué significa | Qué hacer |
|---|---|---|
| **LISTO** | Sin avisos de encuadre ni alertas de subtítulos pendientes | Puedes publicar tras un vistazo |
| **LISTO CON AVISO** | El video está bien, pero Caption QA marcó texto a revisar | Revisa las alertas de subtítulos |
| **REQUIERE REVISIÓN** | Hay tramos de encuadre/seguimiento que un humano debe ver | Mira los tramos marcados en el timeline |
| **NO PUBLICAR AÚN** | No hay métricas de ese clip (reutilizado, sin re-render) | No lo publiques a ciegas; regenéralo si dudas |

## 8. Cómo interpretar Caption QA

Caption QA busca palabras que Whisper probablemente transcribió mal. Cada alerta trae:

- **timestamp** (dónde ocurre), **palabra detectada → sugerencia**, y **confianza**
  (alta / media / baja).
- En el Modo Automático las alertas son **solo lectura**: se listan pero NO se aplican
  al video (por eso salen como "pendiente"). Tú decides si vale la pena corregir.
- **Confianza alta** = candidata segura; **media/baja** = puede ser un falso positivo.
- Si QA marca una palabra que estaba BIEN, eso es **oro** para nosotros: avísanos.

## 9. Qué errores reportar (y cómo)

Repórtanos con: qué video era (o mándalo), qué modo/botón tocaste, qué esperabas y qué
pasó. Captura de pantalla si hay mensaje de error. Nos interesa especialmente:

- La app se congela o un progreso se queda pegado sin mensaje.
- Un render falla o sale un MP4 corrupto/negro.
- El Editor no abre un paquete, no reproduce el clip, o muestra estados raros.
- Captions desincronizados, texto cortado o palabras gigantes fuera de pantalla.
- El reencuadre pierde a la persona o "tiembla".
- Caption QA corrige/marca algo que estaba BIEN (falso positivo).
- Un mensaje de error que no te dice qué hacer a continuación.
- **Un botón que esperabas encontrar y no estaba.**

## 10. Dónde quedan los outputs

| Qué | Dónde |
|---|---|
| Paquetes del Modo Automático | `output/paquetes/{video}_{fecha}/` |
| Reporte legible de cada paquete | `output/paquetes/{video}_{fecha}/REPORTE.md` |
| Renders sueltos (Creador → Captions) | `output/` |
| Clips cortados sin captions | `output/clips/` |
| Transcripciones y análisis | `transcripts/` |
| Alertas de Caption QA | `transcripts/{video}_caption_alerts.json` |

## 11. Qué NO esperar todavía (Alpha)

- **Publicación automática** a TikTok/Reels/Shorts: no existe; publicas a mano.
- **Editor de video / timeline multipista / cortes manuales**: no lo habrá — no es ese
  producto. El "Editor" de Centrito es de REVISIÓN, no de edición.
- Otros idiomas: por ahora español.
- Multi-persona perfecto: con 2+ caras sigue a una sola (aviso en el reporte).
- Grabaciones de pantalla: encuadre centrado fijo, sin seguimiento.
- Emojis/popups IA requieren ComfyUI corriendo local; si no está, salen sin emojis (normal).
- Corrección total de transcripción: Caption QA solo autoaplica lo seguro (y en el
  Modo Automático ni eso — solo reporta); el resto te lo deja como alerta a propósito.

---

## Checklist de prueba (marca lo que SÍ funcionó)

- [ ] El video carga en Creador → Biblioteca (miniatura + duración visibles)
- [ ] El Modo Automático genera un paquete completo sin errores
- [ ] El botón "Abrir en el Editor" te llevó al paquete recién generado
- [ ] En el Editor: el preview del clip se reproduce
- [ ] Los estados, alertas y tramos se muestran y se entienden
- [ ] Los captions se ven y están sincronizados con la voz
- [ ] El reencuadre vertical mantiene a la persona en cuadro
- [ ] El `REPORTE.md` se entiende sin ayuda (scores, avisos, telemetría)

## Preguntas para tu feedback (respóndelas con tus palabras)

1. ¿El **flujo** de punta a punta fue claro?
2. ¿El **Editor** te ayudó de verdad a revisar, o fue estorbo?
3. ¿Los **clips** sirven para publicar?
4. ¿Los **captions** se ven bien?
5. ¿El **reporte** se entiende?
6. ¿Las **alertas** de Caption QA son útiles?
7. ¿La **UI** se siente premium o confusa?
8. ¿Qué **botón** esperabas encontrar y no estaba?

Cualquier casilla que NO puedas marcar, o cualquier "no" arriba, es exactamente lo
que queremos saber.
