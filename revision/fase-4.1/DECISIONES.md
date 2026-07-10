# DECISIONES.md — F4.1 Reframe Vertical

Registro de decisiones del arquitecto. No reabrir los items marcados [FIRME].

---

## D1 — C2v2 reemplaza a C2 como criterio oficial [FIRME]

**Sesion:** 14
**Decision:** C2v2 es criterio oficial para noturnos.

```
C2v2 = % del tiempo total con (camara en zona [900,1100]) Y (distancia cara > 80px) <= 2%
```

**Racional:** el C2 original cazaba camara parqueada en el vacio sin cara. El cruce C2xCARA
de sesion 14 confirmo que en el 100% de frames donde la camara entra en [900,1100], hay una
cara a <=20px de distancia (no hay ningun frame de camara en el vacio). El C2=42% era
enteramente la cara derecha orbitando en su extremo izquierdo natural. Seguir una cara real
que orbita cerca de la zona no es el bug original.

**Referencia:** revision/fase-4.1/c2_cruce.md

---

## D2 — GATE_ANCLA_PCT queda en 0.15 [FIRME]

**Sesion:** 14
**Decision:** no bajar a 0.12 para eliminar solapamiento geometrico con zona C2.

**Racional:** reducir el gate rechazaria detecciones reales en [1074,1100], empeorando
el tracking de la cara derecha cuando se inclina hacia el centro. El product es peor.
La adopcion de C2v2 hace que este solapamiento sea irrelevante para el criterio de calidad.

---

## D3 — Zona C2 [900,1100] fija (no relativa al ancla) [FIRME]

**Sesion:** 14
**Decision:** la zona C2 no se redefine como relativa al ancla.

**Racional:** con C2v2 como criterio, la zona fija es solo referencia para el caso de drift.
El criterio ya distingue si hay cara o no en esa zona.

---

## D4 — Detector: short_range (full_range rechazado) [FIRME]

**Sesion:** 14
**Decision:** mantener `blaze_face_short_range.tflite` como detector activo.

**Racional:** la comparativa sobre podcast_test_60s mostro que full_range aumenta
detecciones fuera del gate de ambas anclas de 73 a 135 (+62), violando la regla de
adopcion pre-autorizada (condicion 3: fuera_gate no debe subir).
La mejora de confianza (+0.35) no compensa el ruido extra.

**Referencia:** revision/fase-4.1/model_selection.md

---

## D6 — CIERRE FORMAL F4.1 [FIRME — sesion 16]

**Sesion:** 16
**Decision:** F4.1 Reframe Vertical CERRADA.

**Veredicto numerico (criterios de aceptacion):**
- C1 dist<=80px >=95%: PASS x3 — noturnos 96.2%, turnos 97.5%, videolargo 100% (tracking-only)
- C2v2 (cam en [900,1100] Y sin cara <=80px) <=2%: PASS — noturnos 0.19%, turnos 0.53%
- Multi-cara con turnos: PASS — evidencia en `revision/fase-4.1/trayectoria_podcast_test_60s_turnos_s15.csv`
  (97.5% C1, 6 switches, renders CON turnos). Frames de corte seco: podcast_switch_t*_pre/post.jpg.
  (Nota s16: el paquete de cierre citaba s15_noturnos_tramo*.jpg — esos son frames del modo
  noturnos sin turnos; la evidencia de conmutacion real esta en los archivos de turnos).
- Tests: 98 pasando (ruff limpio)
- Decisiones D1-D5: todas FIRMES

**Veredicto visual de K:** APROBADO 90/100 (desde 70/100 en s12)
- Observacion: descuadre visible en reposo (~t=57s, cara cargada a la izquierda) en modo
  noturnos. Diagnostico: cam=1182, face=1134, dist=48px, regimen=LENTO, 100% HOLD en
  t=54-60s. La cara esta dentro de la deadzone (48px < 76px dz_half) y sin detecciones en
  ese tramo — la camara no puede corregir. No bloquea el cierre; deuda registrada en
  PREGUNTAS.md.
- Modo turnos: sin observaciones.

**Punch-in:** PENDIENTE DE VEREDICTO EDITORIAL. Feature congelada en opt-in default off.
Ver PREGUNTAS.md para el trigger del veredicto.

---

## D5 — Alpha adaptativo de dos regimenes [FIRME — sesion 15]

**Sesion:** 15
**Decision del arquitecto:** alpha adaptativo segun |error camara→target| por frame.

**Parametros elegidos:**
- `ALPHA_BASE_LENTO = 0.08` (tau ~0.41s @ 30fps) — reposo y movimientos suaves
- `ALPHA_BASE_RAPIDO = 0.28` (tau ~0.11s @ 30fps; equivale alpha efectivo s13 @60fps)
- `RAMP_LENTO_FACTOR = 1.0` → umbral_lento = deadzone_half × 1.0 (en el borde de la deadzone)
- `RAMP_RAPIDO_FACTOR = 3.0` → umbral_rapido = deadzone_half × 3.0

Umbrales en pixeles (fuente 1920x1080, dz_half=76px):
  umbral_lento = 76px, umbral_rapido = 228px

Umbrales en pixeles (fuente 854x480, dz_half=34px):
  umbral_lento = 34px, umbral_rapido = 101px

**Invariante garantizado:** error <= dz_half => ALPHA_BASE_LENTO (camara en reposo
dentro de la deadzone JAMAS entra al regimen rapido).

**Resultados s15:**
- NOTURNOS C1: 96.2% PASS (era 94.9% FAIL en s14)
- TURNOS C1: 97.5% PASS (era 96.1%)
- C2v2: 0.19% / 0.53% PASS
- VIDEOLARGO C1: 100.0% (sin render, solo tracking)
Primera iteracion pasa — NO se uso la pre-autorizacion de subir a 0.35.

**Opciones descartadas (propuestas en s14):**
1. ~~Aumentar EMA_ALPHA a 0.12~~ — alpha fijo mas alto introduce temblor en toda la secuencia,
   no solo en los saltos. El adaptativo aísla el regimen rapido a errores grandes.
2. ~~Aumentar DEADZONE_PCT a 0.30~~ — reduce la sensibilidad en general; el problema era
   la reactividad insuficiente en saltos, no la sensibilidad de la deadzone.
3. ~~Aceptar C1=94% (bajar umbral)~~ — el arquitecto rechazo bajar el criterio.
4. ~~Alpha diferente por fps con deadzone mayor~~ — la normalizacion ^(30/fps) ya resuelve
   la diferencia de fps. El adaptativo es una solucion mas limpia que dos constantes por fps.
5. ~~Re-evaluar solo en modo noturnos~~ — el adaptativo mejora ambos modos sin penalizar ninguno.
