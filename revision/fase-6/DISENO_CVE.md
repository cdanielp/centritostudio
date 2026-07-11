# DISEÑO — caption_viral_engine (CVE)
**Fase:** F6 · **Sesión:** 29 (diseño, Fable) · **Fecha:** 2026-07-10
**Estado del spec fuente:** el documento íntegro de K llegó en s30 y está guardado tal cual
en `revision/fase-6/SPEC_K_CVE.md` (cierra PREGUNTAS #33). Contrastado contra este diseño:
cero contradicciones duras con las decisiones a-h; las marcas `[SPEC-K PENDIENTE]` de la
versión s29 quedaron resueltas en s30 (posiciones §5.1, marcado §7, presets 6-12 §9.1) y se
integraron los refinamientos del spec (cadena de 5 pasos §5.3, config extra §6, nota §8).
Una divergencia menor (marcas por frase vs por palabra) quedó para voto en PREGUNTAS #34.
Historial: en s29 el prompt traía el placeholder sin reemplazar y el diseño se construyó
solo sobre las decisiones a-h del arquitecto, que resultaron consistentes con el spec.

---

## 0. Qué es el CVE en una frase

Una **capa de orquestación declarativa** que convierte un nombre de preset
(`--preset keyword_punch`) en una composición concreta de los 3 subsistemas que YA existen
— efectos ASS (core_ass/styles), overlays PNG (assets_comfy/burn), efectos de video
(reframe: punch-in/stack) — sin reescribir ninguno (decisión b, regla #15, regla #19:
toda función nueva nace como herramienta del motor usable desde ambos modos).

```
                        ┌──────────────── cve.py (orquestador) ────────────────┐
  preset + config user → resolve_preset() → RenderPlan                          │
                        │   ├─ style_cfg  ──────────→ SUBSISTEMA 1: core_ass    │
                        │   ├─ keywords (reglas+brain) → marcas en groups        │
                        │   ├─ overlays  ──────────→ SUBSISTEMA 2: assets_comfy │
                        │   └─ video_fx  ──────────→ SUBSISTEMA 3: reframe      │
                        └───── fallback total: captions simples (hoy) ──────────┘
```

**Principio rector:** el engine COMPONE y CONFIGURA; los motores RENDERIZAN.
Toda extensión al motor es un campo/atributo opcional, default-off, con la ruta
por-defecto byte-idéntica a la actual (patrón probado en s28A con `pop_scale`).

---

## 1. Alcance v1 (decisión a — no reabrir)

**5 presets prioritarios** + **3 intensidades** (`minimal` / `clean` / `viral`).
Presets 6-12 e intensidades `high_energy` / `experimental`: **backlog post-v1** (§9).

| Preset | Se apoya en (decisión b) | Tecnología nueva |
|---|---|---|
| `clean_podcast` | estilo `clean` existente (aprobado por K, D19) | ninguna — solo envoltura |
| `viral_bounce` | `hormozi` + pop/rebote existentes (D20: suave+rebote) | ninguna — solo envoltura |
| `karaoke_highlight` | modo `karaoke` existente (`\kf`) | ninguna — solo envoltura |
| `keyword_punch` | `hormozi` + POP_LEVELS + marcas por-palabra | detección keywords v1 + escala por-palabra + glow aprox |
| `image_popups` | cadena de emojis generalizada (burn_video_with_emojis) | biblioteca PNG del usuario + timestamps manuales + posición |

**Rebanada vertical de s29 (BLOQUE 2 de esta sesión):** núcleo del engine + `clean_podcast`
+ `viral_bounce` + `keyword_punch` COMPLETO + CLI `--preset` + demos + tests.
`karaoke_highlight` e `image_popups`: especificados aquí, implementación en sesiones Sonnet (§10).

---

## 2. Arquitectura de módulos

```
cve.py            Orquestador: registro de presets, resolve_preset(), aplicar_engine()
                  sobre groups, fallback total. SIN lógica de render propia.
cve_keywords.py   FUNCIONES PURAS: detección determinista de keywords (reglas d),
                  merge con brain.json, parser de marcas manuales (e), fit de escala
                  contra safe zones (f). Testeable sin video ni red.
cve_presets.json  (OPCIONAL, raíz) overrides/presets nuevos del usuario — mismo patrón
                  fail-safe por-campo de styles.json. Ausente/roto → built-ins intactos.
```

Consumidores: `caption.py --preset X` (CLI) y, en sesión Sonnet, `jobs.py`/Studio
(`/api/presets` + dropdown). El Modo Automático podrá nombrar un preset en su receta
(PREGUNTAS #29.1) sin código nuevo.

**Contrato de RenderPlan** (lo que `resolve_preset()` devuelve; todo Optional con default):

```python
@dataclass
class RenderPlan:
    preset: str                # nombre resuelto
    style_cfg: StyleConfig     # listo para core_ass (via get_style + overrides)
    keywords_mode: str         # "off" | "auto" | "auto+brain" | "manual"
    kw_max_por_grupo: int      # 1 (regla del brain, se conserva)
    kw_punch_scale: int        # escala objetivo de la palabra punch (ej. 150)
    kw_glow: bool              # glow aprox en keywords (capa ASS extra)
    overlays_mode: str         # "off" | "brain" | "manual" | "brain+manual"
    avoid_faces: bool          # leer CSV de trayectoria si existe (f)
    position: str              # "bottom" | "center" | "top" (safe-zone aware)
    video_fx: dict             # {"punch_in": bool} → se PASA a reframe, no se ejecuta aquí
```

`video_fx` es informativo/declarativo en v1: el CVE no corre reframe (regla 15 — las
estaciones son independientes); el Modo Automático o el usuario deciden encadenar. El
preset solo RECOMIENDA (`keyword_punch` recomienda `punch_in: true`, deuda #20 la vota K).

---

## 3. Los 3 subsistemas y sus extensiones mínimas

### 3.1 Efectos ASS (core_ass + styles) — subsistema maduro
Ya rinde: pop con reposo + rebote (`pop_scale`/`overshoot`), keyword 122% persistente +
color, karaoke `\kf`, bounce, escalado a PlayResY, styles.json fail-safe por-campo.

**Extensiones (aditivas, default-off, ruta default byte-idéntica):**
1. **Escala por-palabra:** `core_ass` lee el campo opcional `w["punch_scale"]` (int) en cada
   palabra; si está presente, reemplaza al 122 fijo del keyword. Quien lo calcula es el
   ENGINE (cve_keywords.fit), no el motor. Sin el campo → comportamiento actual intacto.
2. **Glow aprox (`kw_glow` en StyleConfig, default False):** técnica ASS de doble capa.
   Los eventos actuales de `build_ass` nacen sin layer (default 0); con `kw_glow` ON, en
   los grupos con keyword el evento de TEXTO se emite en `layer=1` y se añade un evento
   gemelo en `layer=0` (detrás) con el MISMO texto y métricas: todas las palabras
   invisibles (`\alpha&HFF&`) excepto el keyword, que lleva relleno transparente
   (`\1a&HFF&`), borde grueso del color de acento (`\bord{6-8}\3c{accent}`) y `\blur{4-6}`
   → halo luminoso detrás de la palabra visible. Con default OFF los layers no cambian
   (ruta byte-idéntica). Ningún filtro nuevo de FFmpeg; libass lo rinde nativo.

### 3.2 Overlays PNG (assets_comfy + burn_video_with_emojis) — se generaliza
Ya rinde: cadena N overlays en un pase FFmpeg, fade 120ms, tamaño relativo, posición
"arriba del bloque de captions", cache por hash, fail-open total.

**Extensiones para `image_popups` (sesión Sonnet, §10):**
1. **Fuente de PNGs = biblioteca del usuario** (`assets/biblioteca/*.png`), no solo
   generados por ComfyUI. Resolución en cascada: manual (timestamps) → biblioteca por
   keyword → ComfyUI (cache). Cada eslabón fail-open al siguiente.
2. **Timestamps manuales:** sidecar `transcripts/{stem}_popups.json`:
   `[{"t": 12.5, "png": "biblioteca/flecha.png", "dur": 1.2, "pos": "top_right"}]`
   Entrada inválida = se omite esa entrada con log accionable (regla #16), jamás rompe.
3. **Posición paramétrica:** `burn_video_with_emojis` gana parámetro opcional de posición
   por overlay (`pos` ∈ posiciones de §5); default actual ("arriba de captions") intacto.

### 3.3 Efectos de video (reframe: punch-in 1.12, stack) — NO se toca en v1
El punch-in en keywords ya existe (`--punch-in`, opt-in, deuda #20 espera veredicto K con
renders F5 completos — que esta fase por fin produce). El CVE solo lo declara en
`video_fx` para que el orquestador de arriba (Studio/auto.py) lo encadene. Chroma de
decisión: cuando K vote #20, el preset `viral_bounce`/`keyword_punch` podrá recomendarlo ON.

---

## 4. Detección de keywords v1 (decisión d — reglas deterministas + brain)

### 4.1 Reglas (cve_keywords.py, puras, sobre los groups ya armados)
Cada regla devuelve candidatos `(group_idx, word_idx, score, regla)`; puntaje fijo por regla:

| # | Regla | Detección | Score |
|---|---|---|---|
| R1 | Números | dígitos (`\d`) o numerales en palabra ("dos".."mil", "cien", "primera"…) | 90 |
| R2 | Dinero / % | `$`, "%", "pesos", "dólares", "gratis", "por ciento" | 95 |
| R3 | Fechas | años 19xx/20xx, meses, "hoy", "mañana", "ahora" | 70 |
| R4 | Preguntas | palabra interrogativa (qué/cómo/por qué/cuándo/dónde/cuál) en grupo cuyo texto termina en `?` — se marca el sustantivo/verbo más largo del grupo, no el conector | 75 |
| R5 | Negaciones fuertes | nunca, jamás, nadie, ninguno, imposible, prohibido, error, sin (+sust) | 85 |
| R6 | Contrastes | tras "pero", "aunque", "sin embargo": se marca la SIGUIENTE palabra de contenido (el conector es stopword) | 80 |
| R7 | Repetidas | palabra de contenido (≥4 chars, no stopword) con ≥3 apariciones en el transcript → primeras 2 apariciones | 60 |

Reglas de saneo (heredadas del prompt del brain, ahora en código):
- **Stopwords nunca son keyword** (lista del brain: el, la, de, en, que, y, o, a, con…).
- **Máx 1 keyword por grupo** (gana el score mayor; empate → la palabra más larga).
- **Separación mínima:** no 2 grupos consecutivos con keyword de la MISMA regla R7
  (anti-spam de repetidas). Densidad objetivo: ≤40% de grupos con keyword.

### 4.2 Enriquecimiento desde brain.json (SIN llamadas LLM nuevas)
Si `transcripts/{stem}.brain.json` existe, sus marcas (`kw_ts` re-ancladas, mecanismo
probado de `apply_brain`) entran como candidatos con **score 100**.

**Política de merge (decidida en esta sesión, documentada aquí):**
```
manual [strong]/[big]  >  brain (score 100)  >  reglas R1-R7 (score 60-95)
```
- El merge es por grupo: se ordenan candidatos por score y se toma 1 (kw_max_por_grupo).
- El brain GANA sobre reglas porque es semántico (entiende contexto); las reglas RELLENAN
  los grupos que el brain dejó en null (estimación empírica del clip demo: el brain marcó
  ~45% de los grupos — 15/33 en videolargo_clip1; no es un límite del prompt).
- Racional de "manual gana a todo": es la intención explícita del usuario (regla #19,
  compuerta humana). Jamás se pisa una marca manual con una automática.
- `hooks`/frases de `{stem}_clips.json` NO entran en v1: el hook es una FRASE (grupo
  entero), no una palabra; marcar todo un grupo como énfasis es otra feature (backlog §9,
  "frase destacada"). Decisión: no forzar un dato de clip dentro de un mecanismo de palabra.
- Detección semántica dedicada (nueva llamada LLM con prompt de "palabra viral") → backlog.

### 4.3 Salida
`marcar_keywords(groups, brain_data|None, modo) -> groups` con `is_keyword=True` y
opcionalmente `punch_scale` por palabra. MISMO contrato que `apply_brain` (el motor ya
sabe renderizarlo) — el engine no inventa un formato nuevo.

---

## 5. Colocación y safe zones 9:16 (decisión f)

### 5.1 Constantes (cve.py, nombradas, un solo lugar)
Márgenes de UI de TikTok/Reels/Shorts sobre canvas 1080×1920 (unión conservadora de las
tres apps, fracciones del alto/ancho):

```python
SAFE_TOP_PCT    = 0.10   # username / sonido / "Siguiendo|Para ti"
SAFE_BOTTOM_PCT = 0.18   # descripción, caption de la app, barra de progreso
SAFE_RIGHT_PCT  = 0.14   # columna de acciones (like/comment/share/perfil)
SAFE_LEFT_PCT   = 0.05   # respiro simétrico mínimo
```

Zona útil resultante: x ∈ [54, 929], y ∈ [192, 1574] en 1080×1920.
**Nota de compatibilidad:** los estilos actuales (margin_pct 0.10-0.12) quedaron aprobados
por K ANTES de estas constantes; el engine NO los mueve retroactivamente (regla 15). Las
safe zones gobiernan lo NUEVO: posiciones del engine, popups de imagen y el fit de la
palabra punch. Los nombres v1 son:
`bottom` (default, = actual), `center` (y≈55% H), `top` (y = SAFE_TOP + alto de bloque),
`top_right`/`top_left` (solo overlays).

**Posiciones del spec de K (recibido s30, SPEC_K_CVE.md) mapeadas a estas constantes** —
el spec define 13 opciones de ubicación para imágenes/overlays:
- `top` / `center` / `bottom` / `left` / `right` + 4 esquinas (`top_left`, `top_right`,
  `bottom_left`, `bottom_right`) → anclas dentro de la zona útil; entran con la posición
  paramétrica de overlays (§3.2, S31). v1 ya cubre `top_right`/`top_left`.
- `auto_safe` → ya es el comportamiento por defecto del engine: todo elemento nuevo pasa
  por el fit de zona útil (§5.1) y la cadena de conflicto (§5.3). No requiere código nuevo.
- `avoid_faces` → el flag existente (§5.2).
- `behind_text` → overlay en la cadena FFmpeg ANTES del filtro `ass=` (los captions quedan
  encima). Orden de filtros, no tecnología nueva → S31.
- `full_screen_takeover` → overlay a pantalla completa; conecta con `hook_takeover` (§9.1)
  → backlog post-v1.

### 5.2 avoid_faces — leyendo el CSV del reframe (NO se corre detección nueva)
El reframe ya exporta `trayectoria_{stem}.csv` (`t, cam_center_x, face_x_asignada,
distancia, conf_asignada`; conf presente = detección viva). El engine, con
`avoid_faces=true`:
1. Busca el CSV del clip (convención: `revision/**/trayectoria_{stem}.csv` o ruta en config).
2. Si NO existe → skip con log informativo (fail-open; no es error).
3. Si existe pero NO trae la columna `conf_asignada` (es opcional en reframe.py —
   backward-compat; y `face_x_asignada` se rellena con cam_cx aun sin cara, así que sin
   conf no hay señal utilizable) → mismo camino que CSV ausente: skip con log.
4. Si existe con conf: para cada grupo con posición `center`, si hay detecciones vivas
   (conf presente) en ese rango de tiempo → la cara está en cuadro → aplica la cadena de
   conflicto (§5.3): el bloque baja a `bottom`.

**Limitación documentada v1:** el CSV solo trae X (el reframe es horizontal); no hay Y de
cara. v1 usa "hay cara en cuadro" como señal binaria por rango de tiempo — suficiente para
la regla center→bottom. Precisión vertical → backlog (§9: exige columna `face_y` nueva en
el CSV = tocar reframe, se hace cuando se abra ese motor, no antes).

### 5.3 Cadena de conflicto (reducir → mover → simplificar → desactivar → caption simple)
Para CADA elemento nuevo del engine (palabra punch, popup de imagen, bloque center).
Cadena de 5 pasos, alineada 1:1 con el fallback en cadena del spec de K (s30):

```
1. REDUCIR:     ¿cabe reduciendo escala?  punch: baja de kw_punch_scale hacia 122 en pasos
                de 10 hasta caber (ancho estimado = len(word)·fontsize·0.60·scale/100 ≤
                zona útil). popup: reduce size_pct hasta 0.12.
2. MOVER:       ¿cabe en otra posición permitida?  center→bottom (avoid_faces),
                top_right→top_left (popup fuera de zona de acciones).
3. SIMPLIFICAR: (paso del spec de K, integrado s30) el elemento pierde su ANIMACIÓN pero
                conserva el tratamiento estático: punch → escala/color sin pop; popup →
                aparece sin fade. Paso barato entre mover y desactivar; se cablea en S31
                junto con overlays — la implementación s29 (reducir→mover→desactivar)
                sigue válida como subconjunto.
4. DESACTIVAR:  el elemento pierde su tratamiento especial y cae al comportamiento base
                (punch → keyword 122% normal; popup → se omite con log). El texto NUNCA
                desaparece: desactivar quita el ADORNO, no la palabra.
5. CAPTION SIMPLE: si el conflicto es del grupo entero (no de un adorno), el grupo cae a
                caption simple = nivel 2 del fallback total (§8).
```
Cada paso se loguea (`[cve] palabra 'X' reducida a 130% para caber en safe zone`) —
regla #16: nada silencioso.

---

## 6. Config por usuario (decisión g) — esquema JSON

Un solo archivo opcional `cve_presets.json` (raíz), MISMO patrón fail-safe por-campo de
styles.json (reutiliza `_FIELD_VALIDATORS` para la sección style).
**Deslinde de nombres:** el roadmap del Modo Automático (PREGUNTAS #29.1) nombra un
futuro "recetas/presets.json POR OBJETIVO" (clips virales, clase depurada…) — es OTRO
artefacto. El del CVE se llama `cve_presets.json` precisamente para que no colisionen;
cuando #29.1 se implemente, su receta podrá REFERENCIAR un preset del CVE por nombre.

```jsonc
{
  "presets": {
    "keyword_punch": {              // override de un preset built-in (por-campo)
      "intensidad": "viral",        // minimal | clean | viral
      "style": {                    // overrides de StyleConfig — validadores de styles.py
        "font_size": 95,
        "highlight_color": "&H0000FFFF&"
      },
      "posicion": "bottom",         // bottom | center | top
      "animacion": true,            // false → pop off (solo color)
      "keywords": "auto+brain",     // off | auto | auto+brain | manual
      "overlays": false,
      "avoid_faces": true
    },
    "mi_preset": { "base": "clean_podcast", "style": { "font_size": 70 } }  // preset nuevo
  }
}
```

Garantías (idénticas a styles.json, probadas por tests de contrato):
- Archivo ausente / JSON roto / campo inválido → built-in intacto, campo por campo.
- Un preset nuevo sin `base` hereda de `clean_podcast` (el más sobrio — fallar hacia abajo).
- `styles.json` actual NO cambia de semántica: sigue gobernando ESTILOS; cve_presets.json
  gobierna PRESETS y referencia estilos por nombre. Cero colisión, cero migración.

Claves adicionales que el spec de K (s30) pide exponer, y su destino:
- `idioma` → ya existe (`--lang` del CLI); el preset no lo duplica.
- export Reels/TikTok/Shorts → el output ya es 9:16 H.264+AAC compatible con las 3 apps;
  queda como nota de documentación de usuario (S33), no como código nuevo.
- texto gigante tipo hook / efectos experimentales / captions dinámicos vs siempre abajo →
  backlog §9 (van con `hook_takeover`, intensidad `experimental` y posición por-grupo).

### 6.1 Matriz de intensidades v1

| | `minimal` | `clean` | `viral` |
|---|---|---|---|
| pop | off | suave 1.08 + rebote (D20) | del preset (punch: fuerte 1.45) |
| glow | off | off | on (si el preset lo define) |
| kw punch scale | — (122 normal) | 135 | 150 |
| overlays | off | off | on (si el preset lo define) |
| uppercase | del estilo | del estilo | del estilo |

`high_energy` / `experimental` → backlog (§9). La intensidad NUNCA enciende una capa que
el preset declara off (solo modula intensidad de lo ya activo — regla 15).

---

## 7. Marcado manual v1 (decisión e) — subconjunto

Sintaxis v1 sobre el TEXTO del grupo (editable hoy en el Editor del Studio):

| Marca | Efecto | Mapea a |
|---|---|---|
| `[strong]palabra` | keyword manual (score ∞ en el merge) | `is_keyword=True` |
| `[big]palabra` | keyword + escala punch completa | `is_keyword` + `punch_scale` |
| `[center]` (al inicio del grupo) | ese grupo se posiciona en `center` (pasa por avoid_faces) | posición por-grupo |
| timestamps de imágenes | `{stem}_popups.json` (§3.2) — no es sintaxis inline | overlay manual |

**Parser (cve_keywords.py, puro):** regex tolerante; la marca aplica a la PALABRA SIGUIENTE
inmediata. Reglas de robustez (tests de contrato):
- Marca desconocida (`[fuego]`), mal cerrada, huérfana al final del grupo, anidada o
  duplicada → se ELIMINA del texto y se ignora: el texto queda plano, el render sale.
  Jamás una excepción.
- El texto limpio (sin corchetes) es lo que va al ASS; los timestamps por-palabra no se
  alteran (la marca no es una palabra, se consume antes del mapeo texto→words).
- Sintaxis completa (spec K recibido s30): el mínimo v1 del spec son EXACTAMENTE las 3
  marcas de esta tabla + timestamps de imágenes — coincide con lo implementado. Marcas
  futuras nombradas por el spec → backlog: `[shake]…[/shake]` (vía ASS puro, §9.1),
  `[image:id]…[/image]` (dispara overlay de biblioteca al mencionar la frase, S31+),
  `[glitch]…[/glitch]` (vía compositing, §9.1). El parser v1 ya es extensible: tabla
  `MARCAS = {"strong": ..., "big": ..., "center": ...}`. La regla del spec "marca inválida
  = texto plano, jamás rompe render/export" ya es el contrato del parser (tests s29).
- **Divergencia con el spec (voto en PREGUNTAS #34):** los ejemplos del spec son SPANS con
  cierre sobre frases (`[strong]esto cambió todo[/strong]`); el parser v1 aplica la marca a
  UNA palabra (la siguiente) y un tag de cierre se elimina como marca inválida (texto sale
  plano, nada rompe). El diseño NO se cambia aquí — decisión e definió el subconjunto v1 y
  el énfasis de frase entera está en backlog ("frase destacada", §4.2/§9.2).

---

## 8. Cadena de fallback total (el contrato de supervivencia)

```
nivel 4  preset completo (keywords + glow + overlays + posiciones)
nivel 3  falla detección/marcas    → captions con estilo del preset, sin keywords nuevas
nivel 2  falla resolución preset   → get_style("hormozi") — captions simples actuales
nivel 1  falla styles.json         → built-ins (ya existe, s28A)
nivel 0  el video limpio de la estación anterior (regla 15.3 — siempre disponible)
```
Cada degradación se loguea con causa y acción (regla #16). Test de contrato por nivel.
Racional del nivel 2: se cae a `hormozi` (no a `clean`) porque es el default histórico del
CLI (caption.py) — "captions simples actuales" significa EXACTAMENTE lo que el usuario
recibe hoy sin engine. El "fallar hacia lo sobrio" de §6 aplica a presets NUEVOS sin
`base`, donde no hay comportamiento previo que preservar.

Contrato del spec de K (s30) — "si algo falla, el video nunca debe quedar sin captions;
debe volver a captions simples": lo cumplen los niveles 3→1. El nivel 0 no lo contradice —
es la garantía de ESTACIÓN (regla 15.3) para el caso en que el burn entero falle (FFmpeg
muere), un escalón por debajo del alcance del spec: sin burn no existen captions posibles
y el usuario conserva el video limpio en vez de un archivo corrupto.

---

## 9. Backlog post-v1 (especificado, NO implementar)

### 9.1 Presets 6-12 (spec de K recibido s30 — clasificados)
El spec (SPEC_K_CVE.md) nombra los presets 6-12 y su orden de implementación post-v1.
Cada uno queda clasificado en su vía técnica (criterio de viabilidad resuelto en s29):

| # | Preset (spec K) | Vía | Notas |
|---|---|---|---|
| 6 | `storytelling_cinematic` | ASS puro | frases como títulos narrativos: fades + `\move` sobrios |
| 7 | `premium_flat` | ASS puro | texto plano elegante, transiciones suaves |
| 8 | `meme_impact` | ASS puro + video_fx | texto grande directo; zoom = punch-in del reframe (declarado en `video_fx`); "cortes agresivos" son del clipper/editor, no del CVE |
| 9 | `educational_clear` | ASS puro + overlays PNG | keywords resaltadas (ya existe) + números/listas/etiquetas como cajas ASS u overlays de biblioteca |
| 10 | `glitch_cyber` | compositing | scanlines y glitch real exigen pase FFmpeg extra o Motor B; chromatic aberration tiene aprox ASS (2 capas desfasadas) |
| 11 | `hook_takeover` | ASS puro | frase gigante en los primeros 1-2s; cumple el requisito del spec "el primer segundo debe permitir un hook visual fuerte" |
| 12 | `commentary_reactor` | overlays PNG + ASS | arrows/callouts/etiquetas de la biblioteca + frases fuertes |

Ficha técnica de las 3 vías:
- **Vía ASS puro** (pop, karaoke, swipe con `\move`, cajas `\bord`+BorderStyle=3,
  subrayado (caja fina bajo la palabra vía evento extra), shake acotado (`\t` con offsets
  pequeños alternados), glow aprox (§3.1), chromatic aberration aprox (2 capas desfasadas
  1-2px en rojo/cian): viable HOY, costo bajo, misma arquitectura de extensión aditiva.
- **Vía overlays PNG** (elementos gráficos, stickers, marcos): viable HOY con la cadena
  generalizada (§3.2).
- **Vía compositing** — scanlines, glitch REAL (datamosh/desplazamiento de bloques), blur
  de región: NO viable en libass; requiere pase FFmpeg adicional con filtros
  (gblur+crop+overlay, tblend) o Motor B (HyperFrames). Ficha: "requiere compositing",
  costo un pase extra de encode por render (~igual al burn actual). Decidir motor cuando
  el spec nombre cuáles presets lo exigen.

### 9.2 Resto del backlog
- Intensidades `high_energy` / `experimental` (extienden la matriz §6.1; experimental
  puede exigir compositing).
- Detección semántica dedicada (llamada LLM propia con rúbrica de "palabra viral") —
  hoy el brain existente ya aporta la señal semántica sin costo nuevo.
- Sintaxis completa de marcado de K (`[shake]`, `[image:id]`, `[glitch]`, spans por frase
  — ver §7 y PREGUNTAS #34) + UI de marcado en el Editor del Studio.
- "Frase destacada" (hook de clips.json como grupo-énfasis, ver §4.2). El spec de K (s30)
  la confirma como requisito del sistema completo: frases hook, frases emocionales,
  momentos de giro y títulos visuales son detección a nivel FRASE, no palabra.
- `face_y` en CSV del reframe → avoid_faces con precisión vertical (§5.2).
- Popups con animación de entrada (slide/bounce del PNG — filtros FFmpeg overlay+eq).

---

## 10. Plan de sesiones Sonnet (decisión h)

| Sesión | Entregable | Criterios de cierre |
|---|---|---|
| **S30 — karaoke_highlight + Studio** | Preset `karaoke_highlight` registrado (envoltura del modo karaoke). `/api/presets` + dropdown de presets en Studio (patrón /api/styles de s28C). Selector de intensidad. Deuda #25 (poll timeout) si cabe. | Preset rinde por CLI y Studio; render karaoke byte-equivalente al actual con preset default; tests de contrato del endpoint; check.bat verde. |
| **S31 — image_popups** | Cadena generalizada: `assets/biblioteca/`, `{stem}_popups.json`, posición paramétrica en `burn_video_with_emojis` (default intacto), cascada manual→biblioteca→ComfyUI, safe zones + cadena reducir→mover→desactivar para overlays. | Demo con ≥2 PNGs de biblioteca + 1 manual sobre el clip videolargo; entrada inválida no rompe (test); ruta emojis actual byte-idéntica sin popups; frames de evidencia. |
| **S32 — marcado manual E2E** | Parser ya existe (s29); esta sesión lo cablea al Editor del Studio (las marcas se escriben en el texto del grupo y sobreviven el guardado), + `[center]` por grupo en build_ass (posición por-evento `\an`/marginv). | E2E: editar grupo con `[big]` en Studio → render con la palabra grande; marca inválida visible como texto plano en el editor pero ausente del render; tests parser+persistencia. |
| **S33 — config usuario + intensidades completas** | `cve_presets.json` end-to-end (hoy solo se especifica el esquema y el loader mínimo), matriz de intensidades completa aplicada a los 5 presets, documentación de usuario. | cve_presets.json roto/ausente → built-ins (tests por campo); preset custom del usuario rinde; matriz validada con 1 render por intensidad. |
| **S34 — validación con K** | Los 5 presets × 3 intensidades sobre 2 clips reales; paquete para-K. | Veredicto de K por preset; deudas #20 (punch-in) votable con estos renders. |

Regla para las sesiones Sonnet: este documento es la fuente de verdad; ante duda de
criterio, elegir la opción más sobria y registrar en PREGUNTAS (no reabrir decisiones a-h).

---

## 11. Reparto: rebanada vertical de s29 (BLOQUE 2) vs especificado

Nota de proceso: este documento se commitea al cierre del BLOQUE 1 (diseño); la columna
"Estado" nombra el DESTINO de cada pieza. Al cierre del BLOQUE 2 la bitácora de ESTADO.md
registra lo que realmente quedó implementado (esa es la fuente de verdad del estado).

| Pieza | Destino |
|---|---|
| cve.py: registro de presets, resolve fail-safe, fallback total | IMPLEMENTADO s29 (commit 4e94630) |
| cve_keywords.py: reglas R1-R7 + merge brain + parser marcas + fit safe-zone | IMPLEMENTADO s29 |
| Presets clean_podcast, viral_bounce (envolturas) | IMPLEMENTADO s29 |
| Preset keyword_punch completo (detección + punch_scale + glow + safe zones) | IMPLEMENTADO s29 |
| Extensión motor: punch_scale + kw_glow en `core_ass_fx.py` (nuevo, default off; core_ass re-exporta y queda en 385 líneas) | IMPLEMENTADO s29 |
| CLI `--preset` + `--intensidad` | IMPLEMENTADO s29 |
| Demos 3 presets sobre clip videolargo + 32 tests de contrato (241 total) | IMPLEMENTADO s29 (evidencia: revision/fase-6/s29_demo/) |
| avoid_faces: señal `hay_cara_en_rango` (CSV) | IMPLEMENTADO s29 la señal + tests; SIN CONSUMIDOR aún (los 3 presets usan position=bottom) — se cablea al render en S32 junto con `[center]` |
| karaoke_highlight, image_popups, Studio, cve_presets.json loader completo | SESIONES SONNET (S30-S33) |
| Presets 6-12 (spec s30, clasificados en §9.1), high_energy/experimental, compositing | BACKLOG post-v1 |
