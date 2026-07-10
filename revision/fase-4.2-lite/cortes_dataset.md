# Dataset de cortes de escena — calibracion del check automatico

Dataset etiquetado para calibrar N_CORTES_WARN y umbrales futuros.
Generado con: `ffmpeg -vf select='gt(scene,0.3)',metadata=print:file=-`

---

## Fuente 1: podcast_test_60s.mp4 (material editado, 1920x1080, 60fps)

**Tipo de fuente:** podcast multicamara editado (confirmado por arquitecto s18)
**Resultado esperado:** CHECK WARN (es material editado)

| t | score | tipo real | etiqueta |
|---|-------|-----------|---------|
| 1.95s | 0.878 | corte real (plano A→plano B, personas distintas) | REAL |
| 22.17s | 0.879 | corte real | REAL |
| 24.13s | 0.884 | corte real | REAL |
| 41.07s | 1.000 | corte real | REAL |
| 44.62s | 0.885 | corte real | REAL |
| 49.33s | 0.886 | corte real | REAL |
| 51.38s | 1.000 | corte real | REAL |

**Total cortes reales (score>=0.3):** 7
**Score minimo de cortes reales en esta fuente:** 0.878

---

## Fuente 2: prueba2personasenmedio.mov (podcast multicamara 480p, 854x480, 30fps)

**Tipo de fuente:** podcast multicamara editado (confirmado por arquitecto s19)
**Resultado esperado:** CHECK WARN (es material editado)

| t | score | tipo real | etiqueta |
|---|-------|-----------|---------|
| 0.067s | 1.000 | artefacto primer frame (scdet siempre dispara aqui) | ARTEFACTO |
| 54.03s | 0.663 | corte real — plano abierto a close-up hablante izquierdo, cambia encuadre y decoracion | REAL |
| 56.70s | 0.651 | corte real — regresa al plano abierto | REAL |

**Total cortes reales (excluyendo artefacto t<1s):** 2
**Score minimo de cortes reales en esta fuente:** 0.651

---

## Fuente 3: stack_test_estatico.mp4 (extracto plano continuo, t=1.0-~49.5s)

**Tipo de fuente:** segmento de toma fija (extraido de fuente 2, sin cortes)
**Resultado esperado:** CHECK PASS (0 cortes reales)

| t | score | tipo real | etiqueta |
|---|-------|-----------|---------|
| (ninguno detectado) | — | — | — |

**Total cortes reales (filtrado t<1s):** 0 — PASS ✓

---

## Observaciones de calibracion

**El score NO filtra confiablemente:**
- Cortes reales en fuente 1 (mismo set/paleta diferente): score 0.877-1.0
- Cortes reales en fuente 2 (mismo set, planos distintos de la misma escena): score 0.651-0.663
- Conclusion: un umbral de score 0.7 habria filtrado los cortes reales de fuente 2

**El unico filtro confiable confirmado es el temporal:**
- t < 1.0s: SIEMPRE artefacto de scdet (primer frame, score=1.0)
- t >= 1.0s: puede ser corte real (score varia 0.65-1.0)

**N_CORTES_WARN=2 con filtro t<1s:**
- Fuente 1: 7 cortes reales → WARN ✓
- Fuente 2: 2 cortes reales → WARN ✓ (limite exacto — arquitecto puede subir a N_CORTES_WARN=1 para ser mas estricto)
- Fuente 3: 0 cortes reales → PASS ✓

**Evolucion del check automatico:**
| Sesion | Implementacion | Comportamiento con fuente 2 |
|--------|---------------|-----------------------------|
| s18 | count("pts_time:") con threshold=0.3 | 3 (incluye artefacto) → FALSE WARN |
| s20 | _filtrar_artefactos_cortes(t>=1.0s) | 2 (solo reales) → WARN correcto |
