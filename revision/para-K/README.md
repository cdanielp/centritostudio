# Para K — Sesión 26 · Qué ver y qué responder

Cuatro veredictos. Cada uno trae la ruta exacta del archivo y la pregunta concreta.
Responde con el número — no hace falta más.

---

## 1. Reframe: ¿EMA o ESCENAS? (decide el default del producto)

**Ver, en este orden:**
- `output/pruebaparaedicion_EMA_9x16.mp4` (tracker viejo, F4.1)
- `output/pruebaparaedicion_ESCENAS_9x16.mp4` (tracker nuevo, F4.2-CORTES, hoy default)

**Contexto:** este video tiene 3 cortes de escena. El tracker viejo (EMA) perdía a la
persona después de cada corte (quedaba "enfocando el vacío" unos segundos). El nuevo
(ESCENAS) reinicia el encuadre en cada corte.

**Responde:**
- 1a. ¿Cuál se ve mejor en general? (EMA / ESCENAS)
- 1b. ¿El nuevo ya NO pierde a la persona después de los cortes? (sí / no, y en qué segundo si la pierde)

## 2. Emojis v2: ¿ya parece emoji de app?

**Ver:** `output/tacosjuan_hormozi_emojis.mp4` (render s25, sticker taco con
transparencia real, centrado arriba de los captions — frame de referencia:
`revision/inventario/frames/tacos_emoji_t1.2.png`)

**Responde:**
- 2a. ¿El sticker ya parece emoji de app? (sí / no — y qué le falta si no)
- 2b. El sticker queda sobre el cuerpo de la persona en este video. ¿Molesta o está bien?

## 3. Clips E2E (RUTA A): nota /100

**Ver:**
- `output/pruebaparaedicion_clip1_corto_9x16_hormozi_emojis.mp4` (32.9s, score IA 81)
- `output/pruebaparaedicion_clip2_corto_9x16_hormozi_emojis.mp4` (34.7s, score IA 72)

**Contexto:** pipeline completo automático sin tocar nada a mano: transcripción →
IA elige los momentos → corte → reencuadre vertical → captions hormozi. Costó $0.0015 USD
de API y ~2.5 min de máquina. (Estos clips NO llevan punch-ins: siguen apagados por
default, pendiente tu veredicto con los renders de F5.)

**Responde:**
- 3a. Nota /100 a cada clip como "publicable en Reels/TikTok tal cual".
- 3b. ¿Los momentos que eligió la IA son los que tú habrías elegido?

## 4. Stack con captions (RUTA B): ¿publicable?

**Ver:** `output/podcast2p_stack60_s26_stack_9x16_hormozi.mp4` (60s del podcast de
2 personas, formato apilado ella-arriba / él-abajo, captions hormozi)

**Contexto honesto:** los primeros ~36s son plano abierto y el stack funciona bien.
Después hay un corte a close-up y AMBAS bandas muestran a la misma persona — esa es la
limitación conocida (multi v2, ya registrada como prioridad). Evalúa las dos partes.

**Responde:**
- 4a. La parte buena (0:00-0:36): ¿publicable? (sí / no)
- 4b. ¿Te sirve que el sistema te avise "este tramo sí, este tramo no" mientras multi v2 no existe?

---

## Materiales que necesitamos de ti (con nombre, formato y carpeta destino)

| # | Qué | Formato | Dónde dejarlo |
|---|---|---|---|
| M1 | 2-3 videos COMPLETOS de tipos DISTINTOS que representen lo que quieres procesar (no solo clases: ej. un tutorial con tu webcam activa, un vlog de celular, algo ya vertical) | .mp4/.mov originales, sin comprimir por WhatsApp | `input/` |
| M2 | Logo PMS con fondo transparente + códigos de color de marca (hex) | PNG transparente ≥1000px + un .txt con los hex | `assets/marca/` |
| M3 | Confirmar si `input/reel01-03.mp4` son TUS referencias de estilo de captions. Si no lo son: 3-5 links o archivos de reels cuyo estilo de captions quieres copiar | links o .mp4 | `input/referencias-estilo/` |
| M4 | Keywords: NO te pedimos lista — ya generamos borrador de 47 en `assets/keywords_draft.json` desde tus transcripciones. Solo tacha las que no sirvan y aprueba el resto | editar el .json o dictar "quita X, Y" | `assets/keywords_draft.json` |
| M5 | Telegram (F7): ¿a qué canal/grupo llegan los clips terminados y quién aprueba antes de publicar? (IDs o @nombres) | mensaje | — |
