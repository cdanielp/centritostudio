# Fase 2 — Reporte Cerebro Editorial (DeepSeek) — Actualizado

## Prueba real con tacosjuan.mp4

### Configuración
- Provider: DeepSeek (`deepseek-chat`)
- Temperature: 0.3, timeout: 60s, 2 reintentos
- Video: `input/tacosjuan.mp4` — 6 grupos de subtítulo

### Resultados API (sesión original)
- Latencia: **2.48s** (primera llamada, sin caché)
- Tokens: prompt=316, completion=125, **total=441**
- Costo estimado DeepSeek: ~$0.0004 USD por video (muy económico)
- Keywords detectadas: **6 de 6 grupos**
- Emojis sugeridos: **1 de 6 grupos** (16.7%, dentro del límite 30%)

### Keywords asignadas
| Grupo | Texto | Keyword | Emoji |
|-------|-------|---------|-------|
| 0 | "Estos Tacos..." | Tacos | — |
| 1 | "me encantó, la comida..." | encantó, | — |
| 2 | "lugar se sentía muy..." | muy | — |
| 3 | "servicio fue increíble..." | fue | — |
| 4 | "tacos estaban buenos..." | buenos | — |
| 5 | "Los recomiendo..." | recomiendo | 🌮 |

---

## Rediseño de énfasis (2026-07-09 — Sesión 5)

### Problema con el diseño anterior
El tratamiento original era invisible en frames reales:
- Keyword no-activa: solo `\fscx112\fscy112` (sin color) — indistinguible del blanco
- Keyword activa: `highlight_color` genérico — igual que cualquier palabra activa

### Nuevo tratamiento (keyword_color persistente)
- **Nuevo campo `keyword_color`** en `StyleConfig` — distinto de `primary` y `highlight`
- Keyword **NO activa**: `keyword_color` + `\fscx122\fscy122` durante TODA la duración del grupo
- Keyword **activa**: mantiene `keyword_color` (NO cambia a highlight) + `\fscx122\fscy122`
- Escala keyword: **122%** (antes 112%/118%)

### Colores keyword por estilo
| Estilo | keyword_color | Color visual |
|--------|---------------|--------------|
| hormozi | `&H0047FF00` | Verde-lima brillante |
| karaoke | `&H0000FFFF` | Amarillo |
| bounce | `&H00FFFF00` | Cian |
| pms | `&H0000D7FF` | Dorado |

### Evidencia visual (nuevo diseño)

**Frame @5.0s — "SE" activa (amarillo), "MUY" keyword persistente (verde):**
- `nuevo_enfasis_persistente_t5p0.png` — CON énfasis: MUY en verde aunque SE es la activa
- `nuevo_sin_persistente_t5p0.png` — SIN énfasis: MUY en blanco normal

Esta imagen demuestra el tratamiento PERSISTENTE: la keyword mantiene su color verde
incluso cuando OTRA palabra del mismo grupo está siendo pronunciada.

**Frames de keywords activas (keyword_color al pronunciarse):**
- `nuevo_enfasis_kw_t0p72.png` — "TACOS" verde brillante @0.72s
- `nuevo_enfasis_kw_t2p18.png` — "ENCANTÓ," verde brillante @2.18s
- `nuevo_enfasis_kw_t5p68.png` — "MUY" verde brillante @5.68s
- `nuevo_enfasis_kw_t7p42.png` — "FUE" verde brillante @7.42s
- `nuevo_enfasis_kw_t9p78.png` — "BUENOS" verde brillante @9.78s
- `nuevo_enfasis_kw_t10p94.png` — "RECOMIENDO" verde brillante @10.94s

**Keywords visibles en 6 de 6 grupos** — objetivo superado (se pedía 3+).

---

## Reporte de énfasis en UI (nuevo comportamiento)
- **Con brain.json**: mensaje ámbar "Énfasis aplicado: N keywords" al terminar el render
- **Sin brain.json**: mensaje ámbar "Énfasis NO aplicado: sin brain.json (analiza primero)"
- **Log de servidor**: provider, N keywords, tokens, latencia por render

Ejemplo de log:
```
[render] Enfasis IA | deepseek kw=6 tok=441 lat=2.48s
```

---

## Deuda activa documentada

### (a) _eval_and_adjust — CORREGIDO
**Bug original:** la función retornaba al encontrar la primera unión con delta > 6dB,
dejando las demás sin evaluar. Esto causó no-convergencia en 3/3 iteraciones del demo
sintético de F3 (solo ajustaba una unión por iteración).

**Fix aplicado:** ahora procesa TODAS las uniones en cada iteración y retorna
`hubo_ajuste=True` si al menos una fue corregida.

### (b) print emoji={emjs} — SEGURO
El `emjs` en `brain.py` es un int (conteo de grupos con emoji), no una cadena emoji.
`n_emoji={n_emoji}` en el nuevo logging confirma que es un conteo ASCII-safe.
No hay riesgo de romper la consola cp1252 con la implementación actual.

---

## Prueba fail-open
- `LLM_PROVIDER=mock`: render con énfasis mock ✓
- Key inválida: 2 reintentos → error → render normal sin énfasis ✓
- Sin brain.json: mensaje explícito "Énfasis NO aplicado" en UI ✓

### brain.json commiteado en transcripts/
Ver `transcripts/tacosjuan.brain.json` (actualizado con kw_ts en Sesión 5).
