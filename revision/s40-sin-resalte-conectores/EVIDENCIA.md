# S40 — Sin resalte en conectores

Rama `feat/stopwords-sin-resalte`, sobre `main` con S39 ya mergeado (`f4e7999`).

> **Privacidad.** Los scripts reciben las rutas por CLI, no copian el SRT y no imprimen su
> texto. Los renders viven en `output/`, que está en `.gitignore`. Las únicas palabras del
> material citadas aquí son conectores del castellano (`un`, `que`) que aparecen en los
> frames de comparación.

---

## 1. Qué se arregla

En el caption word-by-word **todas** las palabras reciben su turno de resalte: color, relleno
de karaoke y pop. Cuando a la que le toca el turno es "que", "un", "de" o "la", ese resalte no
comunica nada — es ruido con la misma intensidad visual que una palabra que sí importa.

Medido sobre los cuatro `.ass` entregados en S39: el resalte cae en palabra vacía **el 52.7%
de las veces en el tramo 2 y el 53.0% en el tramo 3** (53.2% y 55.9% si se ignora el acento),
idéntico con gate y sin gate — el gate de S39 decide dónde va el *punch* del CVE, no quién
recibe el resalte ordinario.

> **Nota sobre la cifra.** K midió 40% y 36% a mano; el medidor automático da 52.7% y 53.0%.
> La diferencia es la **lista**, no el método: las palabras más frecuentes coinciden
> exactamente (`que, un, es, la, a, de, con, como`) y `SIN_RESALTE` incluye además auxiliares y
> demostrativos ("está", "esta", "lo", "no"). Contra la lista histórica pelada
> (`STOPWORDS_BASE`) da 46.8% / 46.5%. El medidor publica su criterio y es reejecutable, así
> que la cifra de partida se puede discutir sobre datos.

## 2. La regla

Una palabra que llega a **activa** y está en `stopwords_es.SIN_RESALTE` se pinta con el
**estilo base**: sin `\c`, sin `\kf`, sin pop. Y:

- **su tiempo NO se toca** — el evento sigue existiendo con exactamente la misma ventana;
- **una `is_keyword` jamás se apaga**, esté o no en la lista (el énfasis del engine manda);
- **el gemelo de glow usa el mismo criterio**, vía un predicado único `_sin_resalte`. Si cada
  capa decidiera por su cuenta, el glow escalaría una palabra que el texto dejó plana y las
  dos capas se descuadrarían (es el bug que costó la sesión 47 de F6);
- **`cve_keywords.STOPWORDS` no se toca**: sigue siendo el mismo objeto que
  `stopwords_es.STOPWORDS_BASE`, congelado por test desde S39.

## 3. La lista es dato

`stopwords_es.SIN_RESALTE` = `STOPWORDS_BASE` + pronombres + preposiciones + auxiliares +
demostrativos. La ampliación quedó partida en bloques con nombre (`_PRONOMBRES`,
`_PREPOSICIONES`, `_AUXILIARES`, `_DEMOSTRATIVOS`, `_ADVERBIOS`, `_MULETILLAS`) para que
componer una lista sea elegir bloques, no reescribir palabras. `STOPWORDS_ES` (la del gate de
S39) no cambió ni un término.

**Fuera a propósito**, y esto es una decisión de estilo que conviene mirar con el render
delante:

| Bloque | Ejemplos | Por qué se deja resaltar |
|---|---|---|
| `_ADVERBIOS` | solo, siempre, casi, ya | "**SOLO** hoy" tiene que poder golpear |
| `_MULETILLAS` | cosa, gente, forma, vez | son sustantivos; apagarlos es opinión, no gramática |

El medidor reporta **tres** porcentajes (§4) para que ese residuo sea visible y se decida con
números, no de memoria.

## 4. Resultado — mismos dos tramos que juzgó K

`revision/s40-sin-resalte-conectores/render_evidencia.py`, mismo material, mismo offset
(5284 ms), mismo `min_coverage`, mismo preset `keyword_punch` con densidad `alta`, y el gate de
S39 activo **en las dos versiones**. Lo único que cambia entre A y B es `resaltar_conectores`.

El medidor publica **tres lecturas** del mismo dato, de la más estricta a la más laxa:
`%regla` aplica el mismo predicado que el render (respeta la tilde diacrítica); `%sin tilde`
ignora el acento y cuenta "qué" como "que" — la lectura más dura, y probablemente la que se
usó a mano; `%ampliada` ignora el acento y usa la lista completa, o sea incluye los adverbios
y muletillas que se dejaron fuera a propósito.

| `.ass` | resaltes | **%regla** | %sin tilde | %ampliada |
|---|---|---|---|---|
| `tramo2_A_con_resalte` | 205 | **52.7%** | 53.2% | 55.6% |
| `tramo2_B_sin_resalte` | 97 | **0.0%** | 1.0% | 6.2% |
| `tramo3_A_con_resalte` | 202 | **53.0%** | 55.9% | 56.9% |
| `tramo3_B_sin_resalte` | 95 | **0.0%** | 6.3% | 8.4% |

**0.0% exacto**, no "cerca de 0". Y el residuo está identificado palabra por palabra, no
estimado: lo que sigue contando como vacío si se ignora el acento es **`MÁS`(3), `CÓMO`(1),
`QUÉ`(1), `TÚ`(1)** — las seis son formas acentuadas que deliberadamente NO son conectores
(§4.1). El residuo de `%ampliada` son los adverbios y muletillas de §3.

### 4.1 La tilde diacrítica no es ortografía, es otra palabra

`normalizar` borra acentos para comparar contra los sets. Sin un caso especial, la supresión
apagaba justo la versión que carga el significado:

| átono (conector) | tónico (con carga) |
|---|---|
| que, si, mas, tu, el, mi, se, te, de, aun | **qué, sí, más, tú, él, mí, sé, té, dé, aún** |
| como, cuando, donde, cual, quien, cuanto | **cómo, cuándo, dónde, cuál, quién, cuánto** |

`stopwords_es.CON_TILDE_DIACRITICA` compara la forma **con acentos** antes de normalizar. Es
lo que hace que "¿**QUÉ** es lo más caro?" siga golpeando donde debe.

**El dato que hay que mirar con ojos, no con tabla:** los resaltes bajan de 205 a 97 y de 202 a
95. Aproximadamente **la mitad de las palabras ya no destaca nada** al pasar. Esa es la
pregunta del gate visual: ¿el caption respira mejor, o pierde ritmo?

### Las keywords no se tocaron

Conteo de escalas en el `.ass` del tramo 3, A vs B:

| escala | qué es | A | B |
|---|---|---|---|
| `fscx121/108` | pop ordinario de la palabra activa | 200 | **87** |
| `fscx130` | keyword persistente | 10 | **10** |
| `fscx140` / `fscx157` | punch del CVE + su rebote | 2 / 2 | **2 / 2** |

Baja el ruido, el énfasis queda intacto.

### Frames

`output/revision-sin-resalte/`: `frame_A_conector_UN.png` vs `frame_B_conector_UN.png` y
`frame_A_conector_QUE.png` vs `frame_B_conector_QUE.png`. Mismo evento
(`0:00:02.62 → 0:00:02.80`), mismo texto, mismo layout; en A la palabra vacía brilla en
amarillo, en B pasa en blanco como el resto de la línea.

### 4.2 El caso karaoke: quitar el tag rompía la línea entera

La revisión lo cazó con un quemado real de FFmpeg, contando píxeles. En modo karaoke `\kf` no
es decoración: **es lo que hace que libass trate la línea como karaoke**. Las palabras que
todavía no llegan se pintan con `SecondaryColour` (rojo en el estilo karaoke clásico).

Las dos salidas obvias fallan, y ninguna se veía en el `.ass`:

| Salida | Qué pasa | px de `SecondaryColour` en el evento del conector |
|---|---|---|
| sin ningún `\kf` (primera versión) | libass deja de ver karaoke y repinta en base **toda** la línea | 14664 → **0** |
| `\kf0` (segundo intento) | el cursor no avanza; da la línea por cantada | 14664 → **0** |
| **`\kf<dur real>` + `\2c`/`\2a` = color base** | el cursor avanza, el barrido es invisible | 14664 → **13858** |

Los ~800 px de diferencia que quedan son **el conector mismo**, que ya no se tiñe a medio
barrido; las palabras futuras conservan su color exacto (en el evento sin conector activo:
12888 vs 12888, idéntico). Hay que copiar también el **alpha**: el blanco del estilo karaoke
es semitransparente (`&H99FFFFFF`), así que igualar solo el RGB dejaba media palabra más
brillante que la otra — se vio en el frame, no en el `.ass`.

Fuera de karaoke el conector va como texto pelado, sin ningún tag.

## 5. La escotilla, probada

`resaltar_conectores=True` reproduce el render histórico **byte por byte**. No es una promesa:
el arnés de S39 ganó un flag `--historico` y se corrió contra `main`:

| Corpus | Combinaciones | `--historico` vs `main` | default vs `main` |
|---|---|---|---|
| sintético | 90 | **0 diferencias** | difiere (es el objetivo) |
| transcript real (6736 words) | 90 | **0 diferencias** | difiere (es el objetivo) |

El campo está en la allowlist de `styles.filtrar_overrides_validos`, así que se puede fijar
desde `styles.json` o desde `cve_presets.json` por estilo, sin tocar código.

## 6. Por qué el default es el comportamiento NUEVO

Es lo que se pidió, y una escotilla que hay que activar a mano no baja ningún porcentaje. La
convención del proyecto (regla #15: no se borra un nivel, se agrega) se respeta al revés de lo
habitual: el comportamiento viejo **sigue disponible y probado**, solo que ya no es el default.
Si el gate visual lo rechaza, revertir es cambiar un `False` por un `True`.

## 7. Lo que encontró la revisión

Dos bloqueantes, ambos verificados con ejecución real (no lectura):

1. **El karaoke se rompía entero** (§4.2). El `.ass` se veía razonable; el defecto solo
   aparece al quemar y contar píxeles. Corregido y con tres tests: relleno invisible, sintaxis
   de línea preservada en todos los eventos, y duración del `\kf` idéntica a la histórica.
2. **Faltaba la decisión registrada.** El cambio invierte un default de render y S39 sentó el
   precedente de registrar la decisión en el mismo commit. Añadido **D48** + bitácora en
   `ESTADO.md`.

Y un riesgo no bloqueante que resultó ser un defecto real: **la tilde diacrítica** (§4.1). Sin
tratarla, la supresión apagaba "QUÉ", "SÍ", "MÁS" y "TÚ" — exactamente las formas con carga.
Corregido, con test que recorre los ocho pares átono/tónico.

También se cubrió el hueco de tests que señaló: `test_spans_glow_align.py` marca todas las
palabras como keyword, así que ningún test ejercitaba un conector en la capa de glow. Ahora hay
uno que recorre 4 animaciones × 2 pop × 2 overshoot × cada posición activa y exige que las dos
capas coincidan en llevar (o no) animación de escala.

Quedan anotados, sin actuar: el campo no se expone en CLI ni Studio (es de estilo, no de
render); `core_ass.py` sigue sobre el límite de 400 líneas (preexistente, +9 en este PR); y el
arnés de S39 ahora necesita `--historico` para reproducir los hashes con los que se firmó S39
(documentado en su docstring).

## 8. Verificación

- Suite: **2561 passed, 4 skipped** (base S39: 2538/4 → **+23** tests).
- `ruff check` / `ruff format --check` / `check.bat` verdes.
- Escotilla histórica: 0 diferencias contra `main` en 180 combinaciones, revalidada después de
  cada corrección.
- Renders reales quemados con FFmpeg sobre el video depurado, con el guard de procedencia D46
  activo; más un quemado sintético sobre fondo negro para contar los píxeles del karaoke.
- Ningún test existente tuvo que reescribirse.

## 9. Lo que este PR NO hace

- No toca `cve_keywords.STOPWORDS` ni `STOPWORDS_ES` (la lista del gate de S39).
- No toca timings, ni el reparto de eventos, ni el gate de anclas reales.
- No apaga adverbios ni muletillas (ver §3), ni las formas con tilde diacrítica (§4.1):
  ambas cosas quedan medidas como residuo, no escondidas.
- No expone el flag en la CLI ni en la UI — es un campo de estilo, no una opción de render.
