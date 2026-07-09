# DISEÑO — Clipper Viral (Fase 4)

**Sesión de diseño:** 2026-07-09 · Sesión 6
**Estado:** diseño aprobable — implementación en sesión posterior
**Decisiones del arquitecto (cerradas, no se reabren):** dos etapas DeepSeek (segmentación semántica + scoring JSON estricto) · tipos CORTO (20-40s, obj 30s) y LARGO (55-100s, obj 60-90s) · máx 3 clips sobre umbral · clips SIN captions vía EDL+FFmpeg a `output/clips/` · pesos Hook 30 / Autocontenido 25 / Densidad 20 / Cierre 15 / Duración 10.

---

## 1. Orden del pipeline (decisión: depurar ANTES del clipper)

```
video crudo → depurador (recomendado) → words.json del limpio → CLIPPER → clips sin captions
                                                                     ↓
                                              usuario elige estilo → pipeline captions por clip
```

**Por qué depurar antes y no después:**

1. **El scoring evalúa lo que el espectador verá.** Silencios de 2s y muletillas destruyen un hook; puntuar el video crudo produce scores que no corresponden al clip final. Puntuar el limpio = puntuar el producto real.
2. **Costo y drift.** Depurar después del corte obligaría a N pases de depurador (uno por clip) con N recálculos de words.json y N oportunidades de drift. Depurar antes es 1 pase.
3. **La maquinaria ya existe y es coherente.** El depurador produce el par `{video}_limpio.mp4` + `{video}_limpio_words.json` sincronizados entre sí (F3 cerrada). El clipper consume cualquier par (mp4, words) coherente sin lógica extra.

**Consecuencias:**
- Los clips cortados **NO** pasan por el depurador (ya vienen limpios).
- El clipper **no fuerza** el orden: opera sobre el par que le den. La UI sugiere el orden: si existe `{video}_limpio.mp4` + su words, lo preselecciona.

---

## 2. Unidad atómica: la FRASE (cómo la segmentación referencia el transcript)

**Requisito del arquitecto:** el segmento debe mapear a timestamps exactos sin ambigüedad, vía índices de palabra globales de words.json (como el re-anclado kw_ts del brain).

**Decisión: indirección de una capa — el LLM elige índices de FRASE; cada frase conoce sus índices de PALABRA globales.** El requisito se cumple (mapeo determinista frase → palabra → timestamp) con mucha más robustez:

- El LLM elige entre ~300 unidades discretas que ve textualmente, en vez de hacer aritmética sobre ~9,600 posiciones de palabra. Un índice de palabra off-by-N corta a mitad de palabra; un índice de frase equivocado produce, en el peor caso, una frontera de idea imperfecta — que la etapa de scoring castiga y filtra.
- Las fronteras de frase son fronteras naturales del habla (puntuación/pausa): un clip nunca arranca ni termina a mitad de oración.

**Construcción de frases** (`clipper.build_frases`, determinista, sin LLM):

```python
# Frase = {"idx": int, "wi": int, "wf": int, "s": float, "e": float, "text": str}
#   wi/wf = índices GLOBALES (primera/última palabra) dentro de words.json
```

Reglas de corte de frase: puntuación final (`. ! ? …`) · pausa > `FRASE_PAUSA_S = 0.7s` · tope forzado `FRASE_MAX_WORDS = 30` (Whisper a veces no puntúa tramos largos). Umbral de pausa 0.7s (no el 0.4s de group_words): la frase es unidad de IDEA, no de subtítulo — cortes más laxos producen unidades más legibles para el LLM.

**Mapeo determinista de un segmento (f_ini, f_fin) a tiempos de corte:**

```
wi = frases[f_ini]["wi"]        wf = frases[f_fin]["wf"]
start = max(words[wi-1]["e"] + 0.05, words[wi]["s"] - PAD_INI)   # PAD_INI = 0.15s
end   = min(words[wf+1]["s"] - 0.05, words[wf]["e"] + PAD_FIN)   # PAD_FIN = 0.35s
```

El padding da aire para que no se coma la primera/última sílaba, acotado por la palabra vecina real (relevante: el depurador comprime gaps a 0.25s, el pad nunca puede invadir la palabra siguiente).

---

## 3. Etapa A — Segmentación semántica

### 3.1 Prompt (constante `_PROMPT_SEG` en clipper_brain.py)

System: `Eres editor senior de clips virales en espanol. Respondes SOLO con JSON valido, sin texto adicional.`

User (formato con `{max_seg}`, `{ctx}`, `{frases}`):

```
Recibes la transcripcion de "{ctx}" dividida en frases numeradas.
Tu tarea es SEGMENTAR: encontrar tramos que sean unidades de idea completa
(planteamiento -> desarrollo -> remate) y clasificarlos.

Tipos:
- "corto": punchline o gancho rapido que se consume en ~20-40 segundos.
- "largo": explicacion completa de UNA idea en ~55-100 segundos.

Reglas:
- Un segmento empieza donde ARRANCA la idea, nunca a mitad de otra idea.
- Un segmento debe entenderse sin ver el resto de la clase.
- Un "corto" puede vivir dentro de un "largo" (solape permitido entre candidatos).
- Usa la duracion de cada frase para acercarte al rango del tipo.
- Maximo {max_seg} segmentos. Si ningun tramo es digno, devuelve lista vacia.
- Usa SOLO los indices de frase dados. No inventes indices.

Frases (indice | inicio mm:ss | dur s | texto):
{frases}

JSON: {{"segments":[{{"f_ini":int,"f_fin":int,"tipo":"corto"|"largo","tema":"resumen 5 palabras"}},...]}}
```

Cada línea de `{frases}`: `[f042] (03:41, 4.2s) texto de la frase`. El inicio absoluto y la duración por frase permiten al LLM sumar hacia el rango objetivo sin emitir timestamps (que no le pedimos jamás).

`max_seg = 8` por chunk (mismo espíritu que los "hasta 8 candidatos" del MAESTRO).

### 3.2 Esquema de respuesta y validación

```json
{"segments": [{"f_ini": 12, "f_fin": 19, "tipo": "corto", "tema": "por que fallan los prompts"}]}
```

`clipper_brain.validar_segmentacion(raw, n_frases) -> list[dict]` — **nunca lanza**:
- `raw` no-dict o sin lista `segments` → `[]`.
- Por item: `f_ini`/`f_fin` enteros exactos (bool rechazado; float solo si `.is_integer()`), `0 <= f_ini <= f_fin < n_frases`, `tipo in {"corto","largo"}`. Item inválido → se descarta y se cuenta (log).
- `tema` es cosmético: si falta o no es str, default `"(sin tema)"` — no tira el candidato.

Estricto en campos estructurales (índices, tipo), laxo en cosméticos: mismo criterio anti-fail-open de brain.py pero sin dejar pasar nada que pueda producir un corte inválido.

### 3.3 Chunking con solape (transcripts de 40-60 min)

Densidad medida en videos reales del proyecto: **2.66 palabras/s** (242 palabras / 90.9s en `pruebaparaedicion`). Una clase de 60 min ≈ 9,600 palabras ≈ ~15k tokens de prompt — cabe en el contexto de deepseek-chat (64k), pero la calidad de segmentación degrada con prompts muy largos y el chunking mantiene la atención local.

```
CHUNK_WORDS   = 2500   # ~15.6 min de voz por chunk (~4.5k tokens de prompt)
OVERLAP_WORDS = 300    # ~113 s de voz
```

**Justificación del solape:** el clip más largo posible dura 100s ≈ 266 palabras. Con solape de 300 palabras, **cualquier candidato que cruce una frontera de chunk queda completo en al menos un chunk** — nunca se pierde un candidato por partición. Videos ≤ `CHUNK_WORDS` (todo lo actual en input/) van en 1 chunk, cero overhead.

- Los chunks se parten en fronteras de FRASE (nunca a mitad de frase).
- Los índices de frase son **globales** en todos los chunks: no hay traducción de índices al unir resultados.
- **Dedup post-unión** (`clipper.dedup_segmentos`): dos segmentos son duplicados si el IoU de sus rangos de palabra > 0.6; sobrevive el que quede más "interior" a su chunk (más lejos de los bordes) — es el que el LLM vio con más contexto; empate → el primero.

### 3.4 Filtro de duración pre-scoring

Antes de gastar tokens en la etapa B, cada segmento validado se mide con timestamps reales:
- Duración fuera del rango de su tipo pero dentro del rango del OTRO tipo → se reclasifica (con nota).
- Fuera de ambos rangos → se descarta (registrado en clips.json como `descartado: "duracion"`).

---

## 4. Etapa B — Scoring

### 4.1 Decisión clave: el LLM puntúa 4 criterios; la duración y el total los calcula Python

El LLM es malo para aritmética y excelente para juicio. Por eso:
- El LLM emite SOLO los 4 subscores subjetivos: `hook`, `autocontenido`, `densidad`, `cierre` (0-100 cada uno).
- `ajuste de duración` (10%) es **determinista** — la duración exacta se conoce por timestamps; no se le pregunta a un LLM lo que el código sabe.
- El **score total NUNCA lo calcula el LLM**: `clipper.calcular_score_total` aplica los pesos en Python. Un LLM que "redondea bonito" su propio promedio no puede inflar un clip al top-3.

```python
PESOS = {"hook": 0.30, "autocontenido": 0.25, "densidad": 0.20, "cierre": 0.15, "duracion": 0.10}

def score_duracion(dur_s, tipo):   # 100 en el objetivo, 50 en los bordes del rango, 0 fuera
def calcular_score_total(subscores, dur_s, tipo) -> int   # suma ponderada, round()
```

Objetivo de duración: corto obj=30s (rango 20-40), largo obj=75s (punto medio del objetivo 60-90 del arquitecto; rango 55-100).

### 4.2 Prompt (constante `_PROMPT_SCORE`)

System: `Eres jurado experto de clips virales en espanol. Respondes SOLO con JSON valido, sin texto adicional.`

User (formato con `{candidatos}`):

```
Recibes candidatos a clip extraidos de una clase. Puntua CADA candidato
en 4 criterios independientes, 0-100 cada uno:

- "hook": las primeras ~10 palabras generan tension, pregunta o promesa POR SI SOLAS.
  90+ = imposible dejar de ver. 50 = neutro. <30 = arranque plano o administrativo.
- "autocontenido": se entiende sin contexto externo. Penaliza fuerte "como vimos antes",
  "esto que mencione", pronombres sin antecedente, referencias a material no visible.
- "densidad": ensena o revela algo concreto (dato, tecnica, numero, contraste, error comun).
- "cierre": termina en punchline, dato o llamada clara. Penaliza si se desvanece
  o corta a mitad de argumento.

Ademas por candidato:
- "titulo": 4-8 palabras estilo redes, sin comillas ni emojis.
- "razon": UNA linea (<120 caracteres): por que funciona (o por que no).

NO calcules promedios ni score total: eso lo hace el sistema.
Se estricto: en una clase normal la mayoria de los candidatos merece <60 en hook.

Candidatos (indice | tipo | duracion | texto completo):
{candidatos}

JSON: {{"clips":[{{"c":int,"hook":int,"autocontenido":int,"densidad":int,"cierre":int,"titulo":str,"razon":str}},...]}}
```

La instrucción "sé estricto" ancla la distribución: sin ella, los LLM puntúan todo 70-85 y el umbral pierde sentido.

**Batching:** `SCORING_BATCH = 12` candidatos por llamada (un largo de 100s ≈ 266 palabras; 12 candidatos ≈ 3.2k palabras ≈ 5k tokens — foco de atención razonable y JSON de salida corto).

### 4.3 Esquema de respuesta y validación

```json
{"clips": [{"c": 0, "hook": 82, "autocontenido": 71, "densidad": 65, "cierre": 88,
            "titulo": "El error que arruina tus prompts", "razon": "Hook con pregunta directa y cierre con dato."}]}
```

`clipper_brain.validar_scoring(raw, n_candidatos) -> list[dict]` — **nunca lanza**:
- Estructura no-dict / sin lista `clips` → `[]`.
- `c`: entero exacto en `[0, n_candidatos)`; duplicado → se descarta el segundo (gana la primera aparición).
- Subscores: numéricos en `[0, 100]` (float se redondea a int — un `85.5` del LLM no tira el candidato; un `101` o `"alto"` sí).
- `titulo`/`razon` cosméticos: defaults `"Clip sin titulo"` / `"(sin razon)"`, truncados a 80/160 chars.
- Candidatos que el LLM omitió → quedan sin score → descartados con log (no se inventan scores).

### 4.4 Manejo de fallo (patrón brain.py, endurecido)

Por llamada LLM (ambas etapas):
1. Intento 1 → error de transporte/JSON → backoff 1.5s → intento 2 (igual que brain.py).
2. Si la respuesta parsea pero la validación descarta TODO → **1 reintento semántico**: se reenvía con una línea extra: `Tu respuesta anterior fue invalida ({motivo}). Responde SOLO el JSON del esquema.`
3. Si tras eso no hay items válidos → la etapa devuelve `[]` y el clipper termina con `{"clips": [], "error": "<mensaje accionable>"}`.

**El fail-open del render (regla #8) no aplica aquí tal cual: en el clipper el LLM ES la feature.** La traducción correcta de la regla es: nunca crashear, nunca inventar clips, siempre mensaje accionable ("DEEPSEEK_API_KEY no configurada", "El LLM no devolvió candidatos válidos tras 2 intentos"). Sin key → se detecta ANTES de leer el video y se avisa de inmediato.

### 4.5 Telemetría (log de provider/tokens/latencia/costo)

Cada llamada registra `{provider, etapa, chunk, tokens{prompt,completion,total}, latency_s, costo_usd}`. Costo estimado con constantes al inicio de clipper_brain.py (`PRECIO_INPUT_USD_M = 0.27`, `PRECIO_OUTPUT_USD_M = 1.10` — deepseek-chat cache-miss; **verificar precios vigentes en la sesión de implementación**). La telemetría agregada se persiste en `clips.json` y se imprime (solo ASCII) al estilo `[clipper] OK deepseek | seg 4 llamadas | score 2 llamadas | 31k tok | $0.012 | 18.4s`.

Estimación para clase de 60 min: segmentación 4 chunks ≈ 18k in + 2k out; scoring 2-3 batches ≈ 10k in + 2k out. **≈ USD 0.012 por clase** (< $0.02 con margen).

---

## 5. Selección final

Entrada: candidatos con score total. Reglas (en orden):
1. `SCORE_MIN = 60` — se mantiene la propuesta del arquitecto. Fundamento: con la duración aportando máximo 10 puntos deterministas, pasar 60 exige promediar ≥ ~56 en los 4 criterios LLM bajo un prompt calibrado a "estricto" — un clip mediocre no llega. **Plan de calibración:** en la sesión de implementación se corre sobre una clase real y se inspecciona la distribución; ajuste de ±5 se documenta en PREGUNTAS.md si hace falta.
2. Orden por score desc. Greedy: se acepta un candidato si (a) solape < 30% del más corto con TODO aceptado — si no, gana el score mayor (ya aceptado); (b) separación ≥ 15s con todo aceptado (clips pegados canibalizan audiencia).
3. Máximo `MAX_CLIPS = 3`. Mezcla de tipos libre: **ranking único puro, el score manda** (puede salir 3 cortos y 0 largos) — pregunta binaria al arquitecto por si prefiere cuota por tipo.
4. Si 0 pasan el umbral: no se corta nada; los "casi" (score 50-59) se reportan en clips.json y UI como visibilidad ("el mejor llegó a 54/100").

---

## 6. Corte y outputs

**Corte:** reuso de la maquinaria EDL de depurador.py (decisión del arquitecto). Un clip = EDL de un solo segmento `[(start, end)]` → mismo `filter_complex trim/atrim + concat` re-encodeando (los keyframes mienten; nunca stream-copy). En la sesión de implementación se promueve un alias público de 1 línea: `depurador.run_edl = _run_edl` (el clipper no importa privados).

`--vertical` (center-crop 16:9 → 9:16): mencionado en MAESTRO, **propuesta: posponer a F4.1** (pregunta binaria al arquitecto). Face-tracking sigue explícitamente fuera.

**Outputs por corrida:**

```
output/clips/{video}_clip1_corto.mp4          # n=1..3 orden por score desc, SIN captions
output/clips/{video}_clips.json               # metadata completa de la corrida
transcripts/{video}_clip1_corto_words.json    # words del clip RE-BASADAS a t=0 (regla #4)
transcripts/{video}_clip1_corto_groups.json   # grupos listos para render en Studio
```

`clips.json` contiene: por clip `{archivo, tipo, start, end, dur_s, wi, wf, score, subscores, score_duracion, titulo, razon, tema}`; candidatos descartados con motivo (`score_bajo | solape | duracion | llm_omitido`); telemetría agregada; timestamp y versión del diseño.

**Integración con captions (clips salen SIN captions por decisión del arquitecto):**
- **Studio:** al existir `{clip}_words.json` + `{clip}_groups.json`, el clip aparece como video ya transcrito → Render directo con cualquier estilo (`--words-per-group 2` default de clips, hallazgo #3). Cero re-transcripción.
- **CLI:** `caption.py` hoy siempre re-transcribe (~1-2s para un clip de 30-90s en GPU). Que prefiera el transcript existente toca la CLI (regla #10) → pregunta binaria al arquitecto.

---

## 7. Estructura de módulos

Se confirma la propuesta `clipper.py` + `clipper_brain.py` (ambos ≤ 400 líneas, estimados 300/230):

```
clipper.py        Orquestación pura (sin red): build_frases, chunk_frases, dedup_segmentos,
                  score_duracion, calcular_score_total, seleccionar_clips, cortar_clip,
                  exportar_transcript_clip, generar_clips (entry point)
clipper_brain.py  Todo lo LLM: prompts, esquemas, validar_segmentacion, validar_scoring,
                  segmentar_transcript, puntuar_candidatos, telemetría/costo
```

Reusos (cambios de 1-2 líneas en sesión de implementación, documentados aquí para no sorprender):
- `brain.py`: alias público `chat_json = _dispatch` — clipper_brain reusa el dispatch de providers (deepseek/mock) sin duplicar (regla anti-duplicación) ni importar privados.
- `depurador.py`: alias público `run_edl = _run_edl`.
- `jobs.py`: nuevo worker `run_clips` (mismo patrón que `run_depurar`).
- `caption.py`: flag `--clips cortos|largos|ambos` (paralelo a `--depurar`).

Firma del entry point:

```python
def generar_clips(video_path: Path, words: list[dict], tipos: str = "ambos") -> dict:
    """Pipeline completo. Devuelve el dict de clips.json (clips, descartados, telemetria)."""
```

`tipos` filtra QUÉ se pide en segmentación (el prompt omite el tipo no deseado) — no se puntúa lo que no se va a entregar.

---

## 8. UI mínima en Studio (sección "Clips")

Cuarta sección de `static/index.html` (todo en español, colores/branding actuales):

- Por video transcrito: **selector de tipo** (`Cortos · Largos · Ambos`, default Ambos) + botón **"Generar clips"** → `POST /api/clips/{name}` `{"tipos": "ambos"}` → job en background (patrón jobs.py). Progreso con mensajes por etapa: `Segmentando (chunk 2/4)... · Puntuando 14 candidatos... · Cortando clip 2/3...`.
- Si existe `{video}_limpio.mp4`, la UI lo preselecciona como fuente con nota "usando versión depurada".
- **Resultados: una tarjeta por clip** con miniatura, badge de tipo, duración, **score grande (74/100)**, título sugerido y la **razón en una línea**. Botones: Preview (`<video>`) · Descargar. Nota fija: "Los clips salen sin captions — pásalos por Render con el estilo que quieras".
- **0 clips sobre umbral:** mensaje honesto con el mejor casi-candidato: `Ningún segmento superó 60/100. El mejor llegó a 54: "..." — puedes bajar el umbral en la próxima corrida.`
- Errores LLM: banner ámbar accionable (mismo tratamiento que el fail de énfasis IA).

Endpoints: `POST /api/clips/{name}` (lanza job) · `GET /api/status/{job}` (existente) · `GET /api/clips/{name}` (lee clips.json si existe).

---

## 9. Resumen de decisiones tomadas en esta sesión

| # | Decisión | Sección |
|---|----------|---------|
| 1 | Depurar ANTES del clipper; los clips no se re-depuran | §1 |
| 2 | Frase como unidad atómica; LLM emite índices de frase, mapeo determinista a palabra global → timestamp | §2 |
| 3 | Chunking 2500 palabras / solape 300 (> clip máximo) con índices globales; dedup por IoU > 0.6 | §3.3 |
| 4 | LLM puntúa 4 criterios; duración y total ponderado los calcula Python (LLM jamás suma) | §4.1 |
| 5 | SCORE_MIN=60 se mantiene, con plan de calibración en implementación | §5 |
| 6 | Validación estricta en campos estructurales, laxa en cosméticos; retry técnico + retry semántico; nunca inventar clips | §4.4 |
| 7 | Módulos clipper.py + clipper_brain.py; reuso vía alias públicos de brain._dispatch y depurador._run_edl | §7 |
| 8 | Clips emiten words/groups re-basados para captions sin re-transcribir | §6 |
| 9 | Ranking único por score (sin cuota por tipo) — a validar con arquitecto | §5 |
| 10 | --vertical pospuesto a F4.1 — a validar con arquitecto | §6 |

**Preguntas abiertas para el arquitecto:** ver PREGUNTAS.md §9-11 (3 binarias).
