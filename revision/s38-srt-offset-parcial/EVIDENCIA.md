# S38 — Offset explícito + alineado parcial del SRT

**Rama:** `feat/srt-offset-y-alineado-parcial`. **Base:** `373c1ab` (merge PR #30, cierre H5).
**Alcance:** motor de alineación SRT + contrato HTTP. **NO** se introduce forced aligner, WhisperX,
MFA ni ninguna dependencia nueva: cero deps añadidas, solo stdlib.

> **Privacidad.** El SRT corregido privado del usuario NO se commitea, NO se copia a `revision/`, NO se
> convierte en fixture y su texto no aparece en ningún artefacto versionado. Los sidecars que
> quedan en `output/` van **sin el campo `text`**. Todos los fixtures de test son sintéticos.

---

## El problema (medido en la auditoría del 2026-08-03, no re-derivado aquí)

1. Desfase **constante de +5.28 s** entre el SRT corregido y el timeline del transcript limpio
   (567 anclas, 99.3% dentro de ±1 s de la mediana).
2. `srt_align.py:306` marcaba `cue_fallback` si `n_matched != n_tok` — todo-o-nada, ignorando
   `min_coverage`.

Resultado: **3.65% de cobertura y CERO cues animados** sobre material cuyo texto coincide en un
95% con el audio.

---

## Lo que se implementó

### 1. `srt_offset.py` — el offset se DETECTA y se PROPONE, nunca se auto-aplica

Estimador puro por **anclas de token único**: un token que aparece exactamente una vez en el SRT
y una vez en el transcript es un par sin ambigüedad. La **mediana** de las diferencias resiste
outliers.

Devuelve `OffsetEstimate(offset_ms, n_anclas, dispersion_ms, confianza, aplicable, metodo, motivo)`.

**Por qué no se auto-aplica:** un offset mal estimado desincroniza el video entero *en silencio*,
sin error visible; el usuario solo lo descubre al ver el render. Por eso:

- sin `offset_ms` explícito el comportamiento es **byte-idéntico** al histórico;
- con menos de `MIN_ANCLAS=20` anclas o `confianza < 0.80`, la propuesta devuelve `offset_ms=0`
  y `aplicable=False`, para que nadie desplace nada por accidente.

Medición sobre el material real: `offset_ms=5284`, `n_anclas=566`, `dispersion_ms=221`,
`confianza=0.9929`, `aplicable=True`.

### 2. `srt_align_partial.py` — cues parcialmente alineados

El portón por cue pasa a **honrar `min_coverage`** en vez de exigir el 100%. Reglas duras:

1. Un token anclado **jamás se mueve**: conserva su timing real, al ms.
2. Los tokens sin ancla se reparten **uniformemente** en el hueco entre sus vecinos anclados.
3. Nada **interpolado** sale del rango del cue.
4. **Monotonía estricta**: cada palabra empieza donde terminó la anterior o después.
5. Si el hueco no da ni 1 ms por token → **no se inventa nada**, cae a `cue_fallback` estático.
6. Un cue **sin ninguna ancla** sigue cayendo a estático honesto.

**Decisión de borde, tomada con evidencia.** `_claim_window` reclama por punto MEDIO, así que una
palabra real puede desbordar el cue por cualquiera de los dos lados. Los dos lados **no** son
equivalentes:

| Desborde | Qué pasa al pintar | Decisión |
|---|---|---|
| Por el **final** | `core_ass.build_ass:265` cierra el evento de la última palabra en `group["end"]`: el exceso se recorta solo | **Se acepta** |
| Por el **inicio** | El caption aparecería ANTES de su cue y podría solaparse con el cue anterior (dos líneas en pantalla) | **Se rechaza** → estático |

Rechazar los dos costaba **154 cues reales** del material de K sin ganar nada.

### 3. Contrato HTTP

`POST /api/videos/{name}/render` gana `srt_offset_ms`, `srt_alineado_parcial` y `srt_min_coverage`.
Pedirlos con `caption_source=transcript` es **400**, no se ignoran en silencio: quien manda un
offset espera que se aplique. Tope `±3 600 000 ms`; `min_coverage` en `[0.0, 1.0]`.

El resumen público del job y el sidecar (**v2**, aditivo) publican lo **aplicado** y, aparte, la
**propuesta** del estimador: `offset_ms`, `n_anclas`, `dispersion_ms`, `confianza`, `aplicable`.

---

## Tabla comparativa — material REAL (SRT corregido privado + su transcript limpio, 1072 cues)

|                    | HOY     | OFFSET  | OFFSET+PARCIAL |
|--------------------|---------|---------|----------------|
| coverage           | 3.65%   | 81.38%  | **81.38%**     |
| cues animados      | 0       | 201     | **201**        |
| cues parciales     | n/a     | n/a     | **495**        |
| cues estáticos     | 1072    | 871     | **376**        |

`coverage` mide anclaje de tokens, así que el modo parcial no la mueve: lo que mueve es **cuántos
cues llegan a pantalla con animación**. De **0 a 696 de 1072 (64.9%)**.

Reproducir (las rutas se pasan por CLI; el nombre del archivo privado no se versiona):

```
venv\Scripts\python revision\s38-srt-offset-parcial\medir_cobertura_real.py ^
    --srt input\<tu_srt_corregido>.srt --words transcripts\<tu_video>_words.json
```

### Por qué siguen 376 estáticos

| Causa | Cues |
|---|---|
| Ancla que **empieza** antes del cue (rechazo deliberado, ver tabla de borde) | 219 |
| Cobertura < 0.5 o cero anclas (fallback honesto, correcto) | 47 |
| Anclas solapadas entre sí | 21 |
| Sin hueco para interpolar | 13 |
| Resto (`sustitucion_poco_similar`, `non_monotonic_timings`) | 76 |

---

## Evidencia visual para el gate de K

- **Video:** `output/revision-srt-parcial/evidencia_srt_parcial.mp4` (75 s, 1920×1080, H.264+AAC)
- **Contact sheet:** `output/revision-srt-parcial/contact_sheet.png` (3×3)
- **Sidecar sin texto:** `output/revision-srt-parcial/alignment_sin_texto.json`

El tramo **no se eligió a mano**: `_mejor_tramo` busca la ventana de 75 s con más cues parciales,
que es justo lo que hay que poder juzgar. Tramo `t0=1137.8 s`, 35 cues:
**23 parciales · 11 estáticos · 1 completo**.

**Lo que K tiene que decidir:** ¿un cue parcialmente animado (unas palabras con timing real, el
resto repartido en el hueco) se ve bien, o se nota el relleno y se ve roto?

Reproducir: `venv\Scripts\python revision\s38-srt-offset-parcial\render_evidencia.py`

---

## Verificación

- `ruff check .` → All checks passed
- `ruff format --check .` → sin cambios
- `check.bat` → `===== TODO OK =====`
- Suite: **2461 passed, 4 skipped** (baseline 2410 + 51 nuevos)
- Tests nuevos: `tests/test_srt_offset.py` (14), `tests/test_srt_align_partial.py` (24),
  `tests/test_srt_offset_api.py` (13). Escritos **en rojo primero**.

**Contratos de byte-identidad conservados:** sin `offset_ms` y sin `modo_parcial` la salida no
cambia ni un byte. `test_offset_cero_es_byte_identico` y
`test_modo_parcial_sin_bajar_min_coverage_no_cambia_nada` lo fijan; los 2410 tests previos siguen
verdes sin tocarse (salvo el contrato del sidecar, que sube a v2 de forma aditiva).

## Deuda declarada

- `srt_align.py` queda en **427 líneas**, por encima del límite de 400 del skill `centrito-dev`
  (ya entraba con 415). La lógica nueva se puso en módulos aparte justamente para no engordarlo
  más; partirlo es un refactor con riesgo propio y no entra en este PR.
- Los 219 cues rechazados por desborde inicial son recuperables si se decide desplazar la ventana
  del cue al span real de sus anclas. **No se hizo aquí:** cambia cuándo aparece el caption y eso
  necesita el mismo gate visual de K.
