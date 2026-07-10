# MODEL_SELECTION — Reporte definitivo

**Fecha:** 2026-07-09 · Sesion 14 (correccion del veredicto de sesion 13)

---

## Correccion del veredicto anterior

La sesion 13 declaró la comparacion imposible porque Tasks API no tiene el parametro
`model_selection`. Ese veredicto era incorrecto: en Tasks API el modelo se elige por
`model_asset_path`, no por un flag. El modelo full-range SI existe en el CDN oficial:

```
https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_full_range/float16/1/blaze_face_full_range.tflite
```

Descargado a `models/blaze_face_full_range.tflite` (1,083,786 bytes, ~1.03MB) en sesion 14.

---

## Comparativa sobre podcast_test_60s (1920x1080, 60fps, 60s, 2 caras)

Configuracion: anclas cara_id=0 @ x=1362, cara_id=1 @ x=719.
Gate = GATE_ANCLA_PCT x SRC_W = 0.15 x 1920 = 288px.
Detector corre cada DETECT_EVERY_N=3 frames => 1201 frames analizados.

| Metrica | short_range | full_range | delta |
|---------|-------------|------------|-------|
| conf media cara_0 | 0.4759 | 0.8247 | +0.3488 |
| conf media cara_1 | 0.4300 | 0.7346 | +0.3045 |
| frames con det cara_0 / 1201 | 939 (78.2%) | 937 (78.0%) | -0.2pp |
| frames con det cara_1 / 1201 | 413 (34.4%) | 495 (41.2%) | +6.8pp |
| det dentro gate (ambas caras) | 1352 (112.6%) | 1432 (119.2%) | +6.6pp |
| det fuera del gate de AMBAS anclas | 73 | 135 | +62 |

**Nota "pct 112.6%":** esta metrica es `(det_cara0 + det_cara1) / frames_detector`, no
`frames con al_menos_una_det`. Supera 100% porque en muchos frames se detectan AMBAS
caras simultaneamente. Desglose por track:
- cara_0 (ancla 1362): 939/1201 = 78.2% de frames del detector con deteccion
- cara_1 (ancla 719): 413/1201 = 34.4% de frames del detector con deteccion

---

## Regla de adopcion (pre-autorizada por el arquitecto)

Adoptar full-range SI:
1. confianza media sube ← CUMPLE (+0.35 en ambas caras)
2. pct frames con deteccion no baja mas de 1pp ← CUMPLE (+6.6pp en total)
3. detecciones fuera del gate de ambas anclas NO suben ← **FALLA** (73 -> 135, +62)

**Condicion 3 FALLA => MANTENER short_range.**

---

## Correccion del racional (sesion 15)

La condicion 3 fue interpretada como bloqueante porque las det. fuera del gate
"generan ruido". Eso es impreciso: las detecciones fuera del gate son RECHAZADAS
por `_asignar_detecciones_a_caras` y NO afectan el runtime ni el tracking.

**El verdadero racional para mantener short_range:**
- Sin necesidad demostrada: short_range ya da C1 96%+ con el alpha adaptativo
- No meter segunda variable durante el retune de alpha (sesion 15)
- full_range queda disponible en `models/` para futuros upgrades con escenas de
  mayor distancia o sin ruido de cuerpos de fondo

La condicion 3 original medida ruido inofensivo; el rechazo de full_range se
mantiene por razon tecnica distinta. No es reversion de la decision — es claridad
del porqué.

---

## Conclusion

**Detector activo: `blaze_face_short_range.tflite` (sin cambio)**

`ACTIVE_MODEL_PATH = MODEL_PATH_SHORT` en `reframe_detect.py`.

La constante `MODEL_PATH_FULL` esta disponible para futuras pruebas con escenas
de mayor distancia o sin personas de fondo.
