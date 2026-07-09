# MAESTRO.md — Centrito Studio
**Proyecto:** Suite local de producción de video con IA para Prompt Models Studio
**Máquina:** Windows 11 · RTX 5070 Ti 16GB · Python 3.12 · FFmpeg 8.0 · carpeta `C:\CLAUDECODE\ediciondevideo`
**Este documento es la fuente de verdad.** Se ejecuta fase por fase, en sesiones distintas si hace falta.

---

## Cómo usar este documento (para Claude Code)

1. Al iniciar cualquier sesión: lee este archivo completo y luego `ESTADO.md`.
2. **No confíes en los checkboxes de ESTADO.md a ciegas**: verifica contra el filesystem y corre el smoke test (§Reglas de oro #1) antes de continuar.
3. Ejecuta la SIGUIENTE fase incompleta, de principio a fin, siguiendo su bloque al pie de la letra.
4. Cada fase termina solo cuando su **Definition of Done (DoD)** pasa con evidencia en `revision/fase-N/`.
5. Al cerrar fase: actualiza `ESTADO.md` (checkbox + bitácora de 3 líneas), actualiza la skill del proyecto, y haz commit `fase-N: descripción`.
6. Trabaja autónomo. Ante ambigüedad: decide lo razonable, anótalo en `PREGUNTAS.md`, sigue. Nunca te bloquees esperando al usuario.

---

## Contexto: lo que YA está construido y validado (no lo rehagas)

**Pipeline CLI de captions (funcional, commiteado):**
- `caption.py` — CLI completo: `python caption.py input/video.mp4 --style hormozi --lang es`, modo batch por carpeta, `--model auto|small|medium`, `--words-per-group N`, `--out-stem`.
- `styles.py` — 4 estilos ASS validados: `hormozi` (blanco + amarillo, uppercase), `karaoke` (relleno progresivo `\kf` cian), `bounce` (naranja, escala 122%), `pms` (morado #7C3AED, bloque configurable arriba del archivo).
- Whisper: faster-whisper por **ctranslate2** (torch NO está instalado; la detección GPU usa `ctranslate2.get_cuda_device_count()`). Modelo **medium descargado localmente en `models/medium`** (se bajó con `local_dir_use_symlinks=False` para esquivar el bug de symlinks de Windows). `--model auto` usa medium local si existe.
- Rendimiento medido (RTX 5070 Ti, CUDA float16): ~3.8s por video de 15s post-warmup; transcripción ~1s; burn ~2.5s. Primera corrida de sesión: warmup largo, es normal.
- Validado con 4 videos reales (`tacosjuan`, `reel01`, `reel02`, `reel03`): 18 outputs, grids de evidencia en `revision/`, acentos/ñ/¿¡ renderizando bien.

**Hallazgos ya establecidos (úsalos como hechos):**
1. `small` ≈ `medium` en la voz del usuario (solo difiere puntuación). Medium local queda como default por costo cero.
2. Whisper transcribe "ComfyUI" como "confiwai" → **el vocabulario vía `initial_prompt` es obligatorio** (Fase 1).
3. Agrupación: 2 palabras para hooks agresivos, 4-6 auto para testimoniales. Ambos modos deben convivir.

**Centrito Studio (UI web):** se ordenó construir FastAPI + `static/index.html` único + refactor a `core.py`. **Su estado real se audita en Fase 0** — si existe, se verifica; si está incompleto, la Fase 1 lo termina.

**Decisiones de arquitectura ya tomadas (no reabrir):**
- Sin Docker en la PC. Sin React/npm para el Studio. Estado en filesystem, no BD.
- Dos motores de render: **Motor A** = ASS + FFmpeg (captions, volumen, rápido) · **Motor B** = HyperFrames (motion graphics premium, Fase 6).
- Cerebro LLM por **API con proveedor intercambiable** (DeepSeek default). Nada de LLM local: la GPU está ocupada por Whisper/render.
- Los emojis **NUNCA van como texto dentro del .ass** (libass los rompe): siempre como overlay PNG (Fase 5).

---

## Mapa del sistema (a dónde vamos)

```
                          ┌──────────── CENTRITO STUDIO (FastAPI + 1 HTML, puerto 8787) ────────────┐
                          │  Videos · Editor de transcripción · Énfasis IA · Clips · Motion · Render │
                          └──────┬────────────────────────────────────────────────────────┬─────────┘
  video ──> Whisper local ──> words.json ──> CEREBRO (DeepSeek: keywords/emoji/clips/props)
  (GPU)     medium/es              │                                                      │
                                   ▼                                                      ▼
                     MOTOR A: ASS + FFmpeg + overlays PNG                MOTOR B: HyperFrames (HTML→MP4)
                     captions Hormozi/karaoke/pms, depurador, clipper    plantillas firma kinetic-type
                                   │                                                      │
                                   └──────────────► output/ ◄─────────────────────────────┘
  Ojos y QA: plugin /watch (frames+transcript) · Reglas de motion (skill centrito-motion)
  Fase final: Telegram (equipo) → Supabase (cola) → worker en esta PC → aprobación de K
```

---

## Reglas de oro (aplican a TODAS las fases; violarlas = bug)

1. **Smoke test de arranque de sesión:** `.\venv\Scripts\python caption.py input\tacosjuan.mp4 --style hormozi --lang es --out-stem _smoke` debe terminar OK. Borra `output/_smoke*` después. Si falla, arregla ANTES de tocar la fase.
2. **Consola Windows = solo ASCII.** Nada de →, ✓, emojis ni box-drawing en `print()`: cp1252 revienta. En archivos .md/.html sí puedes usar UTF-8. Setea `PYTHONIOENCODING=utf-8` en scripts de arranque.
3. **UTF-8 explícito en todo I/O de archivos** (`encoding="utf-8"`). á é í ó ú ñ ü ¿ ¡ deben sobrevivir de punta a punta, incluidas MAYÚSCULAS acentuadas.
4. **No re-transcribir jamás lo ya transcrito.** La transcripción es cara; render y estilos son baratos. `transcripts/{video}.words.json` es la fuente de verdad reutilizable.
5. **La técnica de escape de rutas del filtro `ass=` de FFmpeg que ya funciona en `caption.py` no se cambia.** Windows + dos puntos en rutas es traicionero; si necesitas quemar .ass en otro módulo, reutiliza la misma función.
6. **Modelos/descargas HF:** siempre `local_dir_use_symlinks=False` hacia `models/`. Nunca dependas del cache con symlinks.
7. **Verificación visual obligatoria antes de dar algo por bueno:** extrae frames con ffmpeg de los momentos relevantes, ábrelos y míralos. Si hay texto cortado, fuente desproporcionada, highlight ausente o emoji mal puesto: corrige e itera (máximo 3 vueltas, documenta si no converge).
8. **Fail-open del cerebro:** si la API LLM falla o no hay key, el pipeline sigue funcionando sin énfasis/sugerencias. Nunca un render se cae por culpa del LLM.
9. **Secretos:** `.env` en `.gitignore` desde el commit 1. Nunca imprimas keys en consola ni las escribas en reportes.
10. **Compatibilidad:** la CLI `caption.py` existente no puede romperse en ninguna fase. `core.py` es la única fuente de lógica; CLI y Studio la consumen.
11. **Evidencia por fase en `revision/fase-N/`:** frames, capturas, reportes .md. Sin evidencia no hay DoD.
12. **Renders y tareas largas en el Studio = background tasks** con progreso consultable; la UI nunca se congela.
13. **Benchmark permanente:** al cierre de toda fase que cambie el output visual, renderizar `input/tacosjuan.mp4` con lo nuevo y componer una comparación de frames lado a lado contra `revision/benchmark/referencia_captions.mp4` (la versión hecha por Captions AI), guardada en `revision/fase-N/benchmark.png`. Si el archivo de referencia no existe, documentar en PREGUNTAS.md y continuar sin bloquearse.

---

## FASE 0 — Auditoría de estado + Equipamiento del agente

**Objetivo:** saber exactamente qué existe, dejar `ESTADO.md` como tracker vivo, e instalar las herramientas externas (skills/plugins) que el resto del proyecto usa.

**Pasos:**
1. Crea `ESTADO.md` con la plantilla del final de este documento. Márcalo según lo que VERIFIQUES (no según lo que digan otros .md).
2. Corre el smoke test (Regla #1). Anota tiempo.
3. Audita el Studio: ¿existen `app.py` (o `server.py`), `core.py`, `static/index.html`, `arranque.bat`? Si existen: levanta el server, prueba con curl el flujo transcribir→editar→renderizar de `tacosjuan.mp4` y anota qué funciona y qué no. El resultado decide cuánto trabajo real tiene la Fase 1.
4. Instala el plugin **/watch** (ojos de video para el agente):
   - `/plugin marketplace add bradautomates/claude-video` y luego `/plugin install watch@claude-video`.
   - Si el mecanismo de plugins no está disponible en esta versión, alternativa: `npx skills add bradautomates/claude-video -g`.
   - Verifica con un video LOCAL: `/watch output/tacosjuan_hormozi.mp4 describe qué texto aparece y en qué segundos`. No requiere API key (frames locales; el transcript ya lo tenemos nosotros).
5. Verifica Node: `node --version`. Si no existe o es <22: `winget install OpenJS.NodeJS.LTS`, reabre la terminal, re-verifica.
6. Instala las skills de **HyperFrames**: `npx skills add heygen-com/hyperframes --full-depth --yes`. Solo instalar y verificar que `/hyperframes` aparece como skill; el primer render real es en Fase 6 (descargará su Chrome headless, es normal).
7. Crea la skill `.claude/skills/centrito-motion/SKILL.md` con las **10 reglas de motion** (absorbe el craft, no instales el repo): (1) nunca interpolación lineal — springs/bezier con clamp; (2) las entradas animan 2-3 propiedades juntas (fade+rise+scale); (3) stagger de 3-6 frames entre elementos; (4) las salidas existen y son más rápidas que las entradas; (5) pila de 5 capas: fondo con drift → assets → gráficos → grade → grain+viñeta; (6) toda imagen fija lleva Ken Burns; (7) los elementos en reposo respiran (micro-movimiento sinusoidal); (8) todo timing derivado de fps, cero números mágicos; (9) un solo theme de colores/easings, nada inline; (10) render → inspeccionar frames → corregir → re-render, nunca entregar sin verificar.
8. Actualiza/crea la skill principal `.claude/skills/centrito/SKILL.md`: qué es el proyecto, comandos, arquitectura de dos motores, dónde vive cada cosa, y referencia a MAESTRO.md.

**DoD:** ESTADO.md refleja la realidad verificada · smoke test OK · `/watch` respondió correctamente sobre un mp4 local · `node --version` ≥ 22 · skills de HyperFrames instaladas · las 2 skills propias existen · commit `fase-0: auditoria y equipamiento`.

---

## FASE 1 — Centrito Studio core (terminar/verificar la UI + fixes de transcripción)

**Objetivo:** el Studio operable de punta a punta en el navegador, con las mejoras de calidad de transcripción integradas. Si la auditoría de Fase 0 mostró que ya existe parcial o totalmente, esta fase es completar los huecos y pasar el DoD — no reconstruir.

**Arquitectura obligatoria:**
- FastAPI + uvicorn en puerto 8787, sirviendo API + UN SOLO `static/index.html` (JS vanilla, CSS inline). Prohibido: React, npm, build steps, base de datos.
- `core.py` con funciones puras: `transcribe_video()`, `group_words()`, `build_ass()`, `burn_video()`, `probe_video()`. CLI y Studio consumen las MISMAS funciones.
- `arranque.bat`: activa venv, `set PYTHONIOENCODING=utf-8`, levanta uvicorn, abre el navegador. Doble click y listo.
- Branding visible: **"Centrito Studio"** en `<title>`, header y README.

**Fixes de transcripción (integrar en `core.py`):**
1. `vocabulario.txt` en raíz → contenido pasado como `initial_prompt` a Whisper. Precarga: ComfyUI, Prompt Models Studio, LoRA, LoRAs, workflow, workflows, prompt, prompts, IA, Stable Diffusion, render, nodos, checkpoint, sampler, TikTok, Reels, Shorts, Centrito. (Esto corrige el bug "confiwai" ya detectado.)
2. Agrupación por pausas naturales: además del límite de caracteres, corta grupo si hay pausa >0.4s entre palabras o la palabra termina en `. , ! ? …`. Nunca dejar una palabra huérfana como grupo final si cabe en el anterior.
3. Anti-desfase/alucinación: `condition_on_previous_text=False`, `beam_size=5`, `vad_filter=True` con `min_silence_duration_ms=300`; descartar palabras con `probability < 0.30` solo en tramos sin voz detectada.
4. Consistencia visual: fuente y márgenes SIEMPRE relativos a `PlayResY`. Un 1056x1920 y un 1080x1920 deben verse idénticos (ya hay videos reales de 1056x1920 en input/ para probarlo).

**UI — una página, 3 secciones:**
1. **Videos:** lista de `input/` con miniatura (frame @1s), duración, estado (sin transcribir / transcrito / renderizado). Drag & drop para subir. Botón Transcribir con progreso (polling `/api/status/{job}`). Si `mean_volume < -40dB`: advertencia "SIN VOZ" en vez de transcribir basura.
2. **Editor:** reproductor HTML5 arriba; debajo cada grupo como caja editable con timestamp `[mm:ss.d]`. Click en grupo → seek del video; en reproducción se resalta el grupo activo. Botón "unir con siguiente" por grupo; "Guardar" y "Restaurar original" globales. Al guardar: re-alinear texto editado contra `words.json` (mapeo directo por grupo; si cambió el conteo de palabras dentro del grupo, redistribuir timestamps proporcionalmente). NO re-transcribir.
3. **Render:** dropdown de estilo + selector "palabras por grupo: 2 / auto" + botón Renderizar (background). Al terminar: preview `<video>` + Descargar. Re-renderizar en otro estilo sin re-transcribir.

**DoD (pruebas E2E que haces tú, sin pedir nada):**
1. Vía API: subir `tacosjuan.mp4` → transcribir → editar 2 palabras → renderizar hormozi → extraer frame que PRUEBE que el texto corregido quedó quemado.
2. Renderizar el mismo contenido en las 2 resoluciones (1056x1920 y un reencode a 1080x1920) → comparar frames lado a lado: mismo tamaño visual de texto.
3. `revision/fase-1/STUDIO_REPORT.md` con capturas, tiempos y pendientes · README actualizado · commit `fase-1: centrito studio core`.

---

## FASE 2 — Cerebro editorial (DeepSeek: keywords + emojis por grupo)

**Objetivo:** convertir subtítulos planos en subtítulos con intención: el LLM marca LA palabra importante de cada grupo y sugiere emoji donde aporta. Es la capa que separa "subtítulos" de "estilo Captions AI".

**Pasos:**
1. `brain.py` con una sola función de acceso `llm(messages, json_schema_hint) -> dict`:
   - Provider por `.env`: `LLM_PROVIDER=deepseek` (default) | `anthropic` | `ollama`. Para DeepSeek: SDK OpenAI-compatible, `base_url=https://api.deepseek.com`, modelo `deepseek-chat`, `DEEPSEEK_API_KEY` desde `.env`, `response_format={"type":"json_object"}`, `temperature=0.3`, timeout 60s, 2 reintentos con backoff.
   - Crea `.env.example` documentado. `.env` real lo llena el usuario (deja instrucción en PREGUNTAS.md si falta la key).
2. Función `analizar_grupos(grupos, contexto) -> brain.json`. Prompt en español con el transcript agrupado numerado. Salida JSON estricta por grupo: `{"g": indice, "kw": indice_palabra_o_null, "emoji": "🔥"_o_null}`. Reglas dentro del prompt: máx 1 keyword por grupo; keyword = palabra con carga (número, beneficio, negación, nombre propio, verbo fuerte), nunca artículos/conectores; emoji en como máximo 30% de los grupos y solo si aporta; español mexicano.
3. Persistir en `transcripts/{video}.brain.json`. Log de tokens usados y latencia (sin exponer la key).
4. Motor A aplica: la keyword del grupo recibe `highlight_color` del estilo + escala ~115% (`\fscx115\fscy115`); si el estilo ya usa highlight por palabra activa, la keyword usa un tratamiento adicional distinguible (p. ej. color secundario del estilo o subrayado con `\bord` mayor). Los emojis se GUARDAN en brain.json pero NO se renderizan aún (eso es Fase 5) — deja el hook listo.
5. Studio: toggle "Énfasis IA" en la sección Render + en el Editor cada grupo muestra su keyword sugerida (click en otra palabra la cambia) y campo emoji editable/borrable.
6. Fail-open (Regla #8): sin key o con error de API → render normal sin énfasis, con aviso suave en UI.

**DoD:** `tacosjuan` renderizado con énfasis IA + frames evidencia comparando con/sin · `brain.json` de ejemplo commiteado · prueba de degradación limpia sin API key · costo por video anotado en el reporte (`revision/fase-2/BRAIN_REPORT.md`) · commit `fase-2: cerebro editorial`.

---

## FASE 3 — Depurador de clases (silencios y muletillas fuera, automático)

**Objetivo:** una grabación cruda de clase entra, sale limpia: sin silencios largos ni muletillas, con cortes inaudibles. Es la fase que más horas semanales devuelve (el usuario produce 1 lección/día).

**Pasos:**
1. `depurador.py` (lógica en `core.py`), que trabaja SOBRE `words.json` existente (Regla #4):
   - **Modo seguro (default):** solo comprime silencios: gaps entre palabras >0.8s se reducen a 0.25s. No toca palabras.
   - **Modo agresivo (opt-in):** además corta muletillas aisladas: `eh`, `em`, `mmm`, `ehh`, `este` — SOLO si están rodeadas de pausas ≥0.25s por ambos lados (en español "este" es palabra legítima; sin pausas alrededor NO se corta). También falsos arranques: bigrama repetido consecutivo al inicio de segmento (corta la primera instancia).
2. Generar EDL (lista de segmentos a conservar) → cortar con FFmpeg re-encodeando (filter_complex trim/atrim + concat) con crossfade de audio de 30ms en cada unión para que no truene.
3. **Loop de auto-evaluación (máx 3 iteraciones):** en cada frontera de corte, extrae 1 frame antes/después y mide con `volumedetect` un micro-tramo: si hay salto de volumen brusco (>6dB) o el frame es basura, ajusta el corte ±80ms y re-render. Documenta cada iteración.
4. Output: `output/{video}_limpio.mp4` + `revision/fase-3/DEPURADO_{video}.md` (cortes hechos, segundos ahorrados, muletillas eliminadas con timestamp).
5. Studio: en la sección Videos, botón "Depurar" con checkboxes seguro/agresivo. El video limpio entra al flujo normal (transcripción se REGENERA sobre el limpio solo si el usuario lo pide; para captions del limpio, recalcula words.json restando los tramos cortados — más barato que re-transcribir; si el desfase acumulado supera 100ms, entonces sí re-transcribe y documenta).
6. La CLI también lo expone: `python caption.py input/clase.mp4 --depurar seguro|agresivo`.

**DoD:** un video real depurado en ambos modos con reporte antes/después (duración, # cortes) · evidencia de fronteras limpias (frames + dB) · sincronía de captions sobre el video limpio verificada visualmente · commit `fase-3: depurador`.

---

## FASE 4 — Clipper viral (10 min → 3-5 shorts con captions)

**Objetivo:** de una clase o charla larga, el cerebro propone los mejores momentos, el usuario elige en el Studio, y cada clip sale cortado + con captions del estilo elegido.

**Pasos:**
1. `clipper.py`: empaqueta el transcript en texto compacto por frases con timestamps (formato tipo `[mm:ss-mm:ss] texto`), ~1 línea por segmento. Ese paquete va al cerebro.
2. Prompt de scoring (JSON estricto): devuelve hasta 8 candidatos `{"start": s, "end": s, "score": 0-100, "hook": "primera frase gancho", "titulo": "...", "razon": "..."}` con rúbrica: gancho en los primeros 2s, emoción/controversia, frase quotable, payoff completo (el clip se entiende solo), cierre natural. Duración objetivo 20-60s. Ajustar start/end a fronteras de palabra reales del words.json (el LLM aproxima; tú corriges al timestamp de palabra más cercano).
3. Selección: descartar solapes >30% (gana el score mayor), mínimo 15s de separación entre clips.
4. Corte: FFmpeg re-encode preciso (no stream-copy: los keyframes mienten). Si el video fuente es 16:9 y el flag `--vertical` está activo: center-crop a 9:16 (face-tracking queda explícitamente FUERA de v1; anótalo como mejora futura).
5. Cada clip pasa automático por Motor A con el estilo elegido y `--words-per-group 2` como default de clips (hallazgo #3), recortando su words.json al rango (sin re-transcribir).
6. Studio: sección "Clips": botón Analizar → tarjetas con score/hook/razón/duración → checkboxes → "Generar seleccionados" (background, progreso por clip).

**DoD:** correr sobre un video ≥5 min (si no hay uno en input/, concatena los 4 reales + genera relleno con edge-tts hasta superar 5 min y decláralo como sintético) · 3 clips generados con captions y títulos · `revision/fase-4/CLIPS_REPORT.md` con scores, razones y frames · costo LLM anotado · commit `fase-4: clipper`.

---

## FASE 5 — Assets: emojis como overlay PNG + puente a ComfyUI

**Objetivo:** materializar los emojis del cerebro (Fase 2) como overlays visuales de calidad, y conectar el ComfyUI local del usuario como generador de assets propios.

**Pasos:**
1. **Emojis PNG (recuerda Regla: jamás como texto en .ass):**
   - `assets/emoji/` como cache local. Descarga bajo demanda del CDN de Twemoji (fork mantenido `jdecked/twemoji` vía jsdelivr, carpeta `assets/72x72/{codepoints}.png`). Resolución de codepoints: convierte el emoji a sus codepoints en hex unidos por `-`; si el compuesto no resuelve (404), reintenta con el primer codepoint; si falla, omite el emoji y regístralo. Verifica la URL exacta con una descarga de prueba antes de cablearla.
   - Composición: overlay FFmpeg sincronizado al grupo (`enable='between(t,ini,fin)'`), posicionado ENCIMA del bloque de texto (offset relativo a PlayResY), escalado a ~1.6x la altura de fuente del estilo. Entrada con fade de alpha de 120ms. Varios emojis en un render = cadena de overlays en un solo comando.
2. **Puente ComfyUI** (`comfy.py`): POST del workflow JSON a `http://127.0.0.1:8188/prompt`, poll a `/history/{prompt_id}`, descarga del output a `assets/generados/`. Timeout 120s y error claro en UI si ComfyUI no está corriendo ("Abre ComfyUI y reintenta"). El workflow base lo define el usuario después; deja un `workflows/asset_base.json` placeholder documentado y el mecanismo probado con mock si ComfyUI está apagado.
3. Studio: pestaña "Assets": galería de `assets/` (emoji cacheados + generados), campo prompt + botón "Generar con ComfyUI", y en el Editor el emoji del grupo se elige de la galería o del picker.

**DoD:** render de `tacosjuan` con ≥2 emojis overlay correctamente puestos/temporizados (frames evidencia) · cache de emoji funcionando offline tras primera descarga · puente ComfyUI probado (real si está corriendo; si no, mock + doc) · `revision/fase-5/ASSETS_REPORT.md` · commit `fase-5: assets y emojis`.

---

## FASE 6 — Motor B: plantillas firma en HyperFrames (motion graphics)

**Objetivo:** 2 plantillas de motion graphics estilo "kinetic typography" (la referencia que le gustó al usuario: texto que ES el video, cortes al beat, b/n de alto contraste) parametrizadas para que el cerebro las llene desde un brief.

**Pasos:**
1. Workspace `motion/` con proyecto HyperFrames (`npx hyperframes init`). Primer render de prueba del template default para validar el entorno (descargará Chrome headless; paciencia y anota tiempos).
2. Diseña **plantilla 1: `centrito-kinetic`** — 8-12s, 720x1280 o 1080x1920, fondo alternando negro/blanco, palabras/frases cortas entrando una por una con springs, cortes duros al ritmo, tipografía sans black. Usa la skill `/motion-graphics` de HyperFrames como guía de construcción y **cumple las 10 reglas de `centrito-motion`**.
3. Diseña **plantilla 2: `centrito-promo`** — misma mecánica pero con colores de marca parametrizados (morado #7C3AED como acento), espacio para logo PNG y cierre con CTA.
4. Parametrización: cada plantilla es un HTML con un bloque `const PROPS = {...}` claramente aislado: `frases[]`, `colores{}`, `logo`, `duracion`, `bpm` opcional. `motion/render.py` inyecta props (reemplazo del bloque) y corre `npx hyperframes render` → `output/`.
5. `brief2props` en `brain.py`: brief de texto libre → JSON de props válido (schema en el prompt, validar campos y longitudes al recibir).
6. **QA con ojos:** tras cada render, usa `/watch` sobre el MP4 + checklist de las 10 reglas. Itera hasta que pase (máx 3 vueltas por plantilla, documenta).
7. Studio: pestaña "Motion" mínima: textarea de brief → dropdown plantilla → Renderizar (background, esto tarda más que Motor A) → preview + Descargar.

**DoD:** 2 MP4s firma renderizados desde un brief real (ej: "3 razones para aprender ComfyUI en 2026") · QA /watch aprobado con checklist · tiempos de render anotados · `revision/fase-6/MOTION_REPORT.md` con frames · commit `fase-6: motor B hyperframes`.

---

## FASE 7 — Distribución: Telegram (equipo) → Supabase (cola) → esta PC (worker) → aprobación de K

**Objetivo:** el equipo del usuario manda un video por Telegram; K aprueba con un botón; esta PC lo procesa con la GPU cuando está encendida; el resultado vuelve al chat. **Esta fase se ejecuta solo cuando F1-F4 estén en uso personal real** — si llegas aquí y el usuario no lo ha pedido explícitamente, deja el diseño listo en `docs/FASE7_DISENO.md` y márcala como "diseñada, no desplegada".

**Diseño obligatorio:**
1. **VPS (infra existente del usuario, Docker):** contenedor `telegram-bot-api` local (sube el límite de descarga de 20MB a 2GB) + bot (grammY/TS o aiogram, consistente con Sistema K). Whitelist de IDs de Telegram. Al recibir video: guarda archivo, inserta fila en Supabase `centrito_jobs` (estado `pendiente_aprobacion`), notifica a K con botones Aprobar/Rechazar (solo el ID de K puede aprobar).
2. **Supabase:** tabla `centrito_jobs` (id, chat_id, solicitante, file_url, estilo, opciones jsonb, estado: pendiente_aprobacion|aprobado|procesando|listo|error|rechazado, timestamps, result_url, error_msg). Acceso solo con service key desde bot y worker. Storage bucket para resultados.
3. **Worker Windows (`worker.py`):** poll a Supabase cada 15s por `aprobado` → descarga → `core.py` → sube resultado → estado `listo` → el bot entrega en el chat de origen. Autoarranque: Tarea Programada de Windows al logon (NO servicio: la GPU necesita sesión). Heartbeat: al arrancar/parar escribe estado de la "estación" para que el bot pueda responder "en cola, estación apagada".
4. Regla de seguridad: la PC solo hace requests SALIENTES (poll); cero puertos abiertos hacia la PC.

**DoD (si se despliega):** flujo completo demostrado con un video corto desde un Telegram del equipo hasta la entrega, con aprobación de K en medio · caso "PC apagada" probado (encola y avisa) · commit `fase-7: distribucion`.

---

## Plantilla de ESTADO.md (créala en Fase 0 y mantenla viva)

```markdown
# ESTADO — Centrito Studio
Actualizado: {fecha} · Sesión: {n}

## Fases
- [ ] F0 Auditoría + equipamiento
- [ ] F1 Studio core + fixes transcripción
- [ ] F2 Cerebro editorial (DeepSeek)
- [ ] F3 Depurador de clases
- [ ] F4 Clipper viral
- [ ] F5 Assets: emojis PNG + ComfyUI
- [ ] F6 Motor B: HyperFrames
- [ ] F7 Distribución Telegram (diseñada: [ ] · desplegada: [ ])

## Herramientas del agente
- [ ] Plugin /watch operativo
- [ ] Skills HyperFrames instaladas (Node >= 22)
- [ ] Skill centrito-motion (10 reglas)
- [ ] Skill centrito (principal) al día

## Bitácora (3 líneas por sesión: qué se hizo, qué quedó, próximo paso)
- {fecha}: ...
```

---

## Al terminar CUALQUIER sesión de trabajo

1. ESTADO.md actualizado con bitácora.
2. Commits limpios por fase (nunca trabajo sin commitear al cerrar).
3. Si una fase quedó a medias: deja en la bitácora el punto EXACTO de continuación y qué archivo estabas tocando.
4. Resumen al usuario: qué se construyó, evidencia (rutas de frames/reportes), decisiones tomadas, y las preguntas de PREGUNTAS.md que necesitan su voto — máximo 3, formuladas como binarias.
