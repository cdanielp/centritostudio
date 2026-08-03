# S41 — Exponer el modo parcial y el offset

Rama `feat/exponer-modo-parcial-srt`, sobre `main` con S40 mergeado (`1175e04`).

> **Privacidad.** La captura del gate visual se hizo con un SRT y un transcript **sintéticos**
> asociados a `input/test_9_16.mp4` (el fixture que ya vive en el repo), no con material de K.
> Los artefactos se retiraron después de capturar; ningún archivo privado quedó versionado.

---

## 1. El problema

`srt_modo_parcial` existía solo como parámetro de la API, con default OFF. Consecuencia: todo
lo que se construyó y se aprobó visualmente en **D45** (alineado parcial), **D47** (gate de
ancla real) y **D48** (sin resalte en conectores) era **inalcanzable** desde la CLI y desde el
Studio. Un render con SRT desde la UI salía con el comportamiento viejo.

## 2. El flag era inerte, no solo invisible

Al cablear el control apareció algo que no estaba en el alcance y que lo cambia: **activar el
modo parcial no hacía nada por sí solo.**

El único portón por cue es `min_coverage`, y su default es `1.0` — que exige anclar TODOS los
tokens, o sea exactamente la ruta histórica. Medido:

```
modo_parcial=True  min_coverage=None  -> word_partial=0  fallback=1
modo_parcial=True  min_coverage=1.0   -> word_partial=0  fallback=1
modo_parcial=True  min_coverage=0.5   -> word_partial=1  fallback=0
```

Entregar la casilla sin resolver esto habría sido entregar un control que no hace nada. Por eso
`srt_caption.umbral_por_defecto()` usa `srt_align.MIN_COVERAGE_PARCIAL = 0.5` cuando se pide
modo parcial **sin** umbral explícito. 0.5 es el valor con el que se midió y se aprobó la
evidencia de D45/D47/D48 sobre material real (822 cues parciales de 1072). Un `min_coverage`
explícito sigue mandando.

**Efecto en la API:** un cliente que ya mandara `srt_alineado_parcial=true` sin `min_coverage`
pasa de recibir la salida histórica a recibir cues parciales de verdad. Es el cambio que hace
que el parámetro signifique lo que dice; el default del parámetro (`False`) no se toca.

## 3. Lo que se expone

| Superficie | Control |
|---|---|
| CLI | `--srt-parcial`, `--srt-offset MS`, `--srt-min-coverage F` |
| Studio | casilla **«Alineado parcial de cues»** en el render con SRT, **default ACTIVADO** |
| Studio | tarjeta del desfase propuesto + botón **«Aplicar desfase»** |
| API | `GET /srt/view` devuelve `offset_propuesto`; el resumen del job reporta modo, umbral y offset aplicado |

**Guardas de la CLI** (error de usuario, no algo que se ignore callado): los tres flags exigen
`--srt`; el offset se acota a ±1 h (el mismo límite que valida la API); `--srt-min-coverage`
debe estar en 0.0–1.0 **y** exige `--srt-parcial`, porque sin modo parcial el umbral no cambia
una sola salida.

## 4. El offset se propone, nunca se aplica solo

D45 lo dejó dicho: un offset mal estimado desincroniza el video entero **en silencio** y solo
se descubre al ver el render. Así que el estimador informa y quien mira decide, en las tres
superficies:

- **View model** — `offset_propuesto` con `offset_ms`, `n_anclas`, `dispersion_ms`, `confianza`
  y `aplicable`. Fail-open: sin timings válidos, o si el estimador se rompe, es `null` (y deja
  rastro en consola: un fallo mudo dejaría la UI diciendo «sin propuesta» para siempre).
- **UI** — lo muestra con su evidencia y un botón. Mientras no se acepte, el render va sin
  desplazar.
- **CLI** — lo imprime siempre, y si difiere del aplicado dice el flag exacto:

```
[srt] 25 cues | 0 word-aligned | 0 parciales | 25 fallback | cobertura 0.00
[srt] modo: solo cues completos | umbral por cue 1.0 | offset aplicado 0 ms
[srt] offset propuesto: 2000 ms (anclas 25, confianza 1.0, aplicable True)
[srt] no se aplica solo: para usarlo, repite con --srt-offset 2000
```

Smoke real de la CLI sobre el fixture, tres corridas:

| Flags | Resultado |
|---|---|
| (ninguno) | 0 word-aligned, 25 fallback, cobertura 0.00 — y la propuesta impresa |
| `--srt-offset 2000` | 25 word-aligned, cobertura 1.00, «ya aplicado» |
| `--srt-offset 2000 --srt-parcial` | modo parcial, umbral por cue **0.5** |

## 5. La invariante de D45 en la UI

Aceptar un offset y renderizar **otro** es el mismo fallo silencioso que D45 vino a evitar. Lo
aceptado caduca en cuanto deja de pertenecer a esta propuesta:

- llega una propuesta distinta → caduca;
- desaparece la propuesta (SRT retirado, timings rotos) → caduca;
- se cambia de video, **también por `openRender()`**, que fija el `<select>` a mano y no
  dispara el `onchange` → caduca;
- el `GET /srt/view` falla → caduca (mejor sin offset que con uno que quizá ya no corresponde).

Los dos últimos son bloqueantes que encontró la revisión: `openRender()` arrastraba el desfase
del video anterior y el `catch` de `refresh()` dejaba la tarjeta diciendo «Se aplicará al
renderizar» con un número caduco. Ambos con test que los reproduce (rojo antes del fix).

### 5.1 La tercera puerta, y por qué se cerró la clase entera

K miró la captura y preguntó: el selector dice «— Elegir video —» mientras la tarjeta muestra
propuesta y badge de aceptado, ¿artefacto o se puede aceptar un desfase sin video?

**Era artefacto de la captura Y un agujero real.** `populateSelects()` (línea 1325) reescribe el
`innerHTML` del `<select>`, lo que **descarta la selección** sin pasar por el `onchange`. En la
captura eso ocurrió después de mi inyección; en el uso real ocurre cada vez que se recarga la
lista de videos. El estado del panel sobrevivía, y con él la tarjeta afirmando algo sobre un
video que ya no estaba elegido. Medido con el test llamando a la función real:
`srt_offset_ms` de otro video **sí viajaba** en el render.

Arreglarlo caducando en cada puerta habría sido el tercer parche del mismo tipo. Así que el
desfase pasa a **llevar encima el video al que pertenece** (`{video, ms}`) y:

- `startRender` solo lo manda si `aceptado.video === el video que se está renderizando`;
- `_pintarOffset` oculta la tarjeta si la propuesta no es del video seleccionado.

Ninguna puerta —presente o futura— puede saltárselo, porque ya no depende de que alguien se
acuerde de avisar. `populateSelects()` avisa igual (`srtPanel.onListaVideos()`), pero solo para
repintar: la corrección de fondo es la invariante, no el aviso.

**El stub del DOM mentía.** El primer intento de test pasaba por la razón equivocada: el
`makeEl` del arnés guardaba `innerHTML` y `value` como propiedades independientes, así que
reescribir el `<select>` no borraba la selección como sí hace el navegador. Se corrigió el stub
(`innerHTML` de un `*-select` ahora resetea `value`) y el test pasó a fallar de verdad antes del
fix.

## 6. Gate visual — `revision/s41-exponer-modo-parcial/`

| Captura | Qué muestra |
|---|---|
| `render_srt.png` | Fuente = SRT: la casilla **marcada por defecto** con su explicación, y la propuesta real del backend: «Desfase detectado: **2.00 s** (25 anclas · confianza 1.00). No se aplica solo: decides tú» + botón *Aplicar desfase* |
| `render_srt_offset_aceptado.png` | Tras el clic: badge **«Se aplicará al renderizar»** + botón *Quitar desfase* |

Los números salen del backend real (`GET /srt/view`), no están maquillados. Los controles
incompatibles con SRT siguen deshabilitados, como fijó S36-C2B.

## 7. Reglas duras

- **Ruta clásica sin SRT byte-idéntica** — arnés de S39/S40 contra `main`: **0 diferencias** en
  90 combinaciones × 2 corpus (sintético y transcript real de 6736 words), revalidado después
  de las correcciones de la revisión. Hueco declarado: el arnés cubre el `.ass`, no el parsing
  ni los exit codes de la CLI; eso lo cubren los tests nuevos.
- **La API mantiene su default OFF** — `srt_alineado_parcial: bool = False` y sus validaciones
  de rango no se tocan. Lo que cambia es que la UI manda el parámetro explícito (`true`/`false`,
  siempre, para que quede en el registro del job).
- **Test rojo primero** — 10/11 en rojo en la CLI, 7/7 en la propuesta de offset, 9/12 en la UI,
  y 2 más para reproducir los bloqueantes de la revisión antes de arreglarlos.

## 8. Lo que encontró la revisión

Seis bloqueantes de la primera revisión, más tres puntos de K sobre la pantalla, todos
corregidos. De K:

- **Em dash fuera del texto visible** (regla del proyecto): «No se aplica solo: decides tú».
  Hay test que recorre el bloque del desfase y falla si aparece uno.
- **Idioma unificado**: el texto decía «Desfase» y el botón «Aplicar offset». Ahora *Aplicar
  desfase* / *Quitar desfase*. En la CLI se conserva «offset» porque nombra el flag
  (`--srt-offset`), que es lo que hay que teclear.
- **El selector vacío con la tarjeta activa**: era artefacto de la captura y agujero real (§5.1).

De la primera revisión:

1. `openRender()` arrastraba el offset aceptado de otro video (§5).
2. El `catch` de `refresh()` dejaba un offset caduco vivo (§5).
3. Un em dash en un `print` de la ruta `--srt`: la consola de Windows no siempre es cp1252 y
   `cp437`/`cp850` lo revientan a media corrida. Hay test que exige ASCII en esos mensajes.
4. `--srt-min-coverage 0.0` sin `--srt` pasaba callado por usar truthiness en vez de
   `is not None`.
5. `--srt-min-coverage` sin `--srt-parcial` se aceptaba y no hacía nada.
6. Faltaban EVIDENCIA, **D49** y bitácora.

El hueco que dejó pasar 1 y 2: el arnés inyectaba `offsetAceptado` directo, así que ningún test
ejecutaba `aplicarOffset`/`_guardarOffset`. Ahora hay un modo `offset_ciclo` que corre el ciclo
real y 7 tests sobre la invariante.

## 9. Verificación

- Suite: **2618 passed, 4 skipped** (base S40: 2561/4 → **+57** tests).
- `ruff check` / `ruff format --check` / `check.bat` verdes.
- Byte-identidad clásica: 0 diferencias en 180 combinaciones.
- Smoke real de la CLI (3 corridas) y capturas del Studio con backend real.

## 10. Lo que este PR NO hace

- **No toca Auto.** `start_auto` no acepta el parámetro y `auto.py` sigue llamando al alineador
  sin modo parcial: con el MISMO SRT, Auto queda estricto mientras Render viene con parcial ON.
  Es una inconsistencia de producto conocida, no un bug; queda para decidir aparte.
- No cambia el default de la API ni sus validaciones.
- No expone `min_coverage` en la UI: la casilla usa el valor aprobado y el ajuste fino vive en
  la CLI y en la API.
