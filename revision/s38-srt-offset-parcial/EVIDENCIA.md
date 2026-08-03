# S38 — Offset explícito + alineado parcial del SRT

**Rama:** `feat/srt-offset-y-alineado-parcial`. **Base:** `373c1ab` (merge PR #30, cierre H5).
**Alcance:** motor de alineación SRT + contrato HTTP. **NO** se introduce forced aligner, WhisperX,
MFA ni ninguna dependencia nueva: cero deps añadidas, solo stdlib.

> **Privacidad.** El SRT corregido privado del usuario NO se commitea, NO se copia a `revision/`,
> NO se convierte en fixture y su texto no aparece en ningún artefacto versionado. Su **nombre**
> tampoco: los scripts reciben las rutas por CLI. Los sidecars que quedan en `output/` van **sin el
> campo `text`**. Todos los fixtures de test son sintéticos.

---

## v2 — corrección tras el rechazo visual de K

**Veredicto de K sobre la v1: RECHAZADO.** El texto era correcto; el timing dentro del cue no.
El offset de **5284 ms no se tocó** (la cobertura por bloques de 5 min va de 0.72 a 0.92 sin
tendencia: no hay drift). Se corrigieron los cuatro defectos que K midió.

Los "antes" de la tabla no son de memoria: se midieron con `auditar_ass.py` sobre el **mismo
`.ass` que K juzgó**, que seguía en disco.

| Defecto | Antes (ASS v1, tramo de 75 s) | Después |
|---|---|---|
| D1 arranque tardío | hasta **+570 ms** | **0** cues desviados (exacto, sobre los 1072) |
| D2 eventos degenerados | **45** bajo 150 ms, mínimo real **50 ms** | **0**, mínimo real **150 ms** |
| D3 solapes / duplicados | **8** solapes, **1** duplicado | **0** y **0** |
| D4 portón que no honra `min_coverage` | **329** cues tumbados con cobertura suficiente | **0** |
| % de pantalla con caption | 76.1% | **87.1%** (mismo tramo) |

### D4 — la regla REAL que estaba decidiendo

No era la cobertura. Eran **dos portones no documentados** dentro de `srt_align_partial`, ambos
introducidos por mí en la v1 y ambos residuo del portón todo-o-nada:

| Regla | Qué exigía | Cues tumbados |
|---|---|---|
| `anclas_utilizables` | que **ninguna ancla empezara antes** del cue ni se solapara con otra | 230 |
| `interpolar_tramos` | que quedara **≥1 ms por token** en cada hueco | 99 |
| (legítimo) `coverage < min_coverage` | — | 47 |

Y `_fallback_reason` no se enteraba de ninguna de las dos: publicaba `cobertura_insuficiente`
para **293** cues cuya cobertura estaba entre **0.67 y 0.89**. El sidecar mentía sobre su propia
decisión.

**Ninguna de las dos era legítima**, así que se eliminaron. `srt_eventos` **acota** las anclas al
rango del cue en vez de descartar el cue entero, y **absorbe** tokens cuando no cabe el mínimo. El
portón ahora es `min_coverage` y nada más. `min_coverage` **no se bajó** de 0.5 para maquillar
ningún número.

`_fallback_reason` también se corrigió: `cobertura_insuficiente` solo se publica cuando la
cobertura realmente no alcanza. Se añadieron `modo_parcial_desactivado` y `cue_demasiado_corto`.

> **Nota de numeración:** no se añade entrada a `DECISIONES.md` en esta rama porque **D44 ya está
> tomada** por el PR #31 (docs), abierto en paralelo. Cuando #31 se mergee, esta decisión entra
> como D45.

---

## Arquitectura

### `srt_offset.py` — el offset se DETECTA y se PROPONE, nunca se auto-aplica

Estimador puro por **anclas de token único** + mediana (resiste outliers). Devuelve `offset_ms`,
`n_anclas`, `dispersion_ms`, `confianza`, `aplicable`.

Con menos de `MIN_ANCLAS=20` anclas o `confianza < 0.80` propone **0** y `aplicable=False`. La
razón es concreta: un offset mal estimado desincroniza el video entero *en silencio*, sin error
visible; solo se descubre al ver el render.

Material real: `offset_ms=5284`, `n_anclas=566`, `dispersion_ms=221`, `confianza=0.9929`.

### `srt_eventos.py` — el reparto, con las invariantes por construcción

Concentra el layout de eventos dentro de un cue y **garantiza**:

1. `eventos[0].start_ms == cue.start_ms` y `eventos[-1].end_ms == cue.end_ms` (D1).
2. Ningún evento por debajo de `MIN_EVENTO_MS` (default **150**, configurable) (D2).
3. Eventos **contiguos**, estrictamente crecientes y sin duplicados (D3).

Un token que no alcanza el mínimo se **absorbe** en el evento anterior: pierde su resalte, nunca
su texto. Las anclas se **acotan** al rango del cue — el cue manda sobre cuándo aparece el
caption, y `_claim_window` reclama por punto medio, así que una palabra real puede desbordarlo.

Consecuencia del contrato de contigüidad: el `end_ms` de una palabra ya **no** es el de su ancla,
sino el inicio de la siguiente. Lo que se conserva del ancla es su **inicio**.

### `srt_align_partial.py` — adaptador

Traduce tokens + anclas a `AlignedCue`. Ya no decide nada: el portón vive en `srt_align`.

### Contrato HTTP

`POST /api/videos/{name}/render` gana `srt_offset_ms`, `srt_alineado_parcial`, `srt_min_coverage`.
Pedirlos con `caption_source=transcript` es **400** — no se ignoran en silencio. Sidecar **v2**
(aditivo: bloque `offset` + `summary.word_partial`).

---

## Re-medición sobre el material REAL (1072 cues)

|                    | HOY     | OFFSET  | OFFSET+PARCIAL v1 | **OFFSET+PARCIAL v2** |
|--------------------|---------|---------|-------------------|------------------------|
| coverage           | 3.65%   | 81.38%  | 81.38%            | **81.38%**             |
| cues animados      | 0       | 201     | 201               | **203**                |
| cues parciales     | n/a     | n/a     | 495               | **822**                |
| cues estáticos     | 1072    | 871     | 376               | **47**                 |

`coverage` mide anclaje de tokens; lo que mueve el modo parcial es **cuántos cues llegan a
pantalla animados**: de **0** a **1025 de 1072 (95.6%)**. Los 47 estáticos restantes son el
fallback legítimo (`coverage < 0.5`), no un rechazo escondido.

### Invariantes sobre el ASS completo (6736 eventos, los 1072 cues)

```
D1 sobre el MODELO (exacto)
  cues cuyo primer evento NO arranca en cue.start: 0
  cues cuyo ultimo evento NO cierra en cue.end   : 0

Invariantes del ASS (material completo)
  eventos                    6736
  bajo el minimo (150 ms)    0
  duracion minima real       150 ms
  solapes                    0
  duplicados                 0
  desvio de arranque         0/1072 cues fuera de +-5 ms (rejilla ASS), max 4 ms
  pantalla con caption       82.7%
  VEREDICTO: INVARIANTES OK
```

El `max 4 ms` no es un defecto del reparto: **el formato ASS guarda los tiempos en
centisegundos**, así que la rejilla es de 10 ms y redondear cuesta hasta 5 ms. Por eso el desvío
exacto se mide sobre el modelo (0) y el del ASS contra esa tolerancia.

---

## Evidencia visual para el gate de K — `output/revision-srt-parcial-v2/`

Dos tramos, cada uno con `.ass`, `.mp4` y contact sheet 3×3:

| Tramo | Qué es | Contenido | Invariantes |
|---|---|---|---|
| **A** `t0=1137.75 s` | **el mismo que K rechazó**, para comparar 1:1 | 33 cues: 30 parciales · 1 completo · 2 estáticos | OK |
| **B** `t0=1360.58 s` | zona de **cobertura baja** (bloque 15-25 min), elegida por el script | 38 cues: 30 parciales · 2 completos · 6 estáticos | OK |

- `A_mismo_tramo_que_K.mp4` · `A_mismo_tramo_que_K_contact_sheet.png`
- `B_cobertura_baja.mp4` · `B_cobertura_baja_contact_sheet.png`
- `alignment_sin_texto.json`

El render anterior sigue en `output/revision-srt-parcial/` para comparar lado a lado.

Reproducir:

```
venv\Scripts\python revision\s38-srt-offset-parcial\render_evidencia.py ^
    --srt input\<tu_srt>.srt --video input\<tu_video>.mp4 ^
    --words transcripts\<tu_video>_words.json
venv\Scripts\python revision\s38-srt-offset-parcial\medir_cobertura_real.py ^
    --srt input\<tu_srt>.srt --words transcripts\<tu_video>_words.json
venv\Scripts\python revision\s38-srt-offset-parcial\auditar_ass.py <archivo.ass>
```

---

## Verificación

- `ruff check .` → All checks passed · `ruff format --check .` → sin cambios
- `check.bat` → `===== TODO OK =====`
- Suite: **2486 passed, 4 skipped** (baseline 2410 + 76 nuevos)
- Gate de privacidad (`smoke_h4_docs --real`) → 1116 checks, **0 blockers**
- `smoke_h5_ci --real` → 16 checks, **0 fails**

Tests escritos **en rojo primero**: `test_srt_eventos.py` (22, invariantes D1-D3 del motor),
`test_srt_align_partial.py` (30, integración + D4), `test_srt_offset.py` (14),
`test_srt_offset_api.py` (13).

**Byte-identidad conservada:** sin `offset_ms` y sin `modo_parcial` la salida no cambia ni un
byte. Lo fijan `test_offset_cero_es_byte_identico` y
`test_modo_parcial_sin_bajar_min_coverage_no_cambia_nada`.

### Tests que cambiaron de contrato (y por qué)

7 tests de la v1 fijaban justo el comportamiento que K rechazó y se reescribieron:
`test_ancla_que_desborda_por_el_INICIO_cae_a_estatico` y `test_anclas_solapadas_caen_a_estatico`
se **invirtieron** (esos cues ahora se animan, era el bug); los que afirmaban
`end_ms == end_del_ancla` pasaron a afirmar `start_ms == start_del_ancla` (contigüidad).

---

## Deuda declarada

- `srt_align.py` queda por encima del límite de 400 líneas del skill `centrito-dev` (ya entraba
  con 415). La lógica nueva se puso en módulos aparte justamente para no engordarlo más; partirlo
  es un refactor con riesgo propio y no entra en este PR.
- Los 47 cues estáticos restantes tienen `coverage < 0.5` de verdad. Bajar el umbral los animaría,
  pero con más de la mitad de las palabras sin timing medido — no se hizo.
- El desvío de ±4 ms en el ASS es el suelo del formato (centisegundos). Solo se eliminaría
  cuantizando el modelo a la rejilla de 10 ms, lo que no aporta nada visible.
