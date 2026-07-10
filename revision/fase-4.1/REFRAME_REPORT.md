# REFRAME_REPORT.md — Fase 4.1: Validacion de Implementacion

**Actualizado:** 2026-07-09 · Sesion: 11

---

## Fix critico: pix_fmt yuv420p (sesion 11)

**Bug:** los outputs de sesion 10 tenian `pix_fmt=yuv444p / profile High 4:4:4 Predictive`.
**Causa:** el pipe rawvideo BGR24 sin fijar `-pix_fmt yuv420p` en la salida.
**Fix:** agregado `-pix_fmt yuv420p` a `_cmd_ffmpeg_pipe()` en reframe.py.

### Verificacion post-fix (los 4 clips re-renderizados)

```
videolargo_clip1_corto_9x16:     stream,High,yuv420p  ✓
videolargo_clip2_corto_9x16:     stream,High,yuv420p  ✓
videolargo_clip3_largo_9x16:     stream,High,yuv420p  ✓
pruebaedicionvideoyo_clip1_corto_9x16: stream,High,yuv420p  ✓
```

---

## Conmutacion multi-cara (sesion 11)

**Cambios vs sesion 10:**
- 2+ caras SIN turnos: WARNING (ya no ValueError) + render con cara principal
- 2+ caras CON turnos: conmutacion real; EMA independiente por segmento; CORTE SECO en t_ini exacto
- `detectar_caras_video` usa ahora `detectar_todas_caras_frame` (detecta TODAS, no solo la mejor)
- `detectar_todas_caras_frame` y `calcular_crops_por_turnos` añadidos a reframe_track.py (math puro)
- `_detectar_trayectorias_multi` añadido a reframe.py (con cv2)

---

## Validacion con input/pruebapodcast2personas.mp4

**Video:** 1920x1080, 758s (12.6 min), 60fps, AAC, mean_volume=-19.3dB

### Deteccion de caras (clip de 60s, `muestra_frames=60`)

| cara_id | center_x | primera_vez_s | score_aprox |
|---------|----------|---------------|-------------|
| 0 | 1362px | 0.000s | 0.40 |
| 1 | 719px | 0.000s | 0.24 |

Ambas caras aparecen desde el frame 0. La cara_id=1 tiene score ~0.24 (cerca del umbral 0.20).
**DATO PARA v2:** en frames donde la cara_id=1 aparece sola, su score sube a ~0.40-0.70.
El score bajo en el frame 0 se debe a la presencia de ambas caras compitiendo.

### Render CON turnos (test: alternando cada 10s)

```
turnos.json: [
  { t_ini=0.0, t_fin=10.0, cara_id=0 },  # cara derecha (x~1362)
  { t_ini=10.0, t_fin=20.0, cara_id=1 }, # cara izquierda (x~719)
  { t_ini=20.0, t_fin=30.0, cara_id=0 },
  { t_ini=30.0, t_fin=40.0, cara_id=1 },
  { t_ini=40.0, t_fin=50.0, cara_id=0 },
  { t_ini=50.0, t_fin=60.0, cara_id=1 },
]
```

Resultado: 2 caras, 6 turnos, 41.0s render (para 60s de clip), pix_fmt=yuv420p, AAC 60.010s.

### Render SIN turnos (WARNING test)

Log esperado: `[reframe] 2 caras -- cara principal; asigna turnos para conmutar`
Resultado: log correcto, render OK con cara principal en 42.6s.

### Frames de corte seco (pre/post cada switch)

Extraidos a 0.2s antes y exactamente en cada t_ini:

| Switch | Pre-frame | Post-frame |
|--------|-----------|------------|
| t=10s | podcast_switch_t10_pre.jpg | podcast_switch_t10_post.jpg |
| t=20s | podcast_switch_t20_pre.jpg | podcast_switch_t20_post.jpg |
| t=30s | podcast_switch_t30_pre.jpg | podcast_switch_t30_post.jpg |
| t=40s | podcast_switch_t40_pre.jpg | podcast_switch_t40_post.jpg |
| t=50s | podcast_switch_t50_pre.jpg | podcast_switch_t50_post.jpg |

---

## Clips de validacion primarios (sesion 10, re-renderizados sesion 11)

| Clip | Resolucion | Duracion | Deteccion cara | Render | pix_fmt |
|------|-----------|---------|----------------|--------|---------|
| videolargo_clip1_corto | 854x480 | 26.9s | ~87% | 6.0s | yuv420p |
| videolargo_clip2_corto | 854x480 | 30.4s | ~63% | 6.8s | yuv420p |
| videolargo_clip3_largo | 854x480 | 89.4s | ~75% est. | 19.7s | yuv420p |
| pruebaedicionvideoyo_clip1_corto | 2560x1440 | 31.3s | 3 det. | 12.6s | yuv420p |

**Verificacion de audio** (todos):
- `videolargo_clip1_corto`: AAC 26.920s → 9:16 AAC 26.920s ✓
- `videolargo_clip2_corto`: AAC 30.390s → 9:16 AAC 30.390s ✓
- `videolargo_clip3_largo`: AAC 89.420s → 9:16 AAC 89.420s ✓
- `podcast_test_60s`: AAC 60.010s → 9:16 AAC 60.010s ✓

---

## Casos borde confirmados (sesion 11)

| Caso | Resultado |
|------|-----------|
| pix_fmt fix | yuv420p/High en todos los 4 clips ✓ |
| 2 caras SIN turnos | WARNING log + cara principal (no falla) ✓ |
| 2 caras CON turnos | Conmutacion activada, 6 turnos, render OK ✓ |
| detectar_todas_caras_frame | Detecta ambas caras en podcast frame 0 ✓ |

---

## Tests de contrato (sesion 11)

82 tests pasando (vs 79 de sesion 10). Nuevos:
- `test_calcular_crops_por_turnos_longitud`
- `test_calcular_crops_por_turnos_corte_seco` (verifica que x_antes y x_despues difieren >100px)
- `test_calcular_crops_por_turnos_sin_datos_usa_default`

---

## Fix sesion 12 — 7 correcciones al tracker

### Cambios implementados

| Bug | Causa original | Fix |
|-----|---------------|-----|
| Deadzone rebasada | `DEADZONE_PCT × source_w` → ±288px, borde crop a ±303px | `DEADZONE_PCT=0.25 × crop_w` → ±76px |
| Recentrado erroneo | Cara perdida > patience → EMA hacia source_center (espacio vacío) | HOLD indefinido; `RECENTER_ALPHA` eliminado |
| Patience asumia 30fps | `FACE_LOST_PATIENCE=30 frames` fijo | `FACE_LOST_PATIENCE_S=1.0` × fps en runtime |
| Gate de asignacion | Asignaba por distancia absoluta desde posicion inicial de cara | Gate: salto > 20% source_w desde última pos conocida → ignorar |
| MODEL_SELECTION | N/A (Tasks API 0.10.x elimino `model_selection`) | Modelo actual: `blaze_face_short_range.tflite`. Full-range no disponible en CDN oficial. Sin cambio. |
| EMA no normalizado | `EMA_ALPHA=0.08` aplicado igual en 30fps y 60fps | `alpha_eff = 1-(1-EMA_ALPHA)^(fps/30)`: 0.080@30fps, 0.154@60fps |
| CSV de trayectoria | No existia | `revision/fase-4.1/trayectoria_{output_stem}.csv` generado en cada render |

### Tests: 85 pasando (era 82)

Nuevos: `test_cara_perdida_hold_indefinido`, `test_cara_perdida_hold_nunca_recentra`,
`test_calcular_alpha_fps_en_referencia`, `test_calcular_alpha_fps_60fps_menor` (renombrado en diagnostico s13 — el invariante era incorrecto),
`test_calcular_alpha_fps_nunca_supera_1`. Eliminados: `test_cara_perdida_supera_patience_recentra`,
`test_cara_perdida_recenter_alpha_parametrizable` (comportamiento removido).

---

## Validacion con trayectoria — sesion 12

### Criterios de exito

| Criterio | Descripcion |
|----------|-------------|
| C1 | Con cara detectada: distancia camara-cara <= 80px el 95% del tiempo |
| C2 | En noturnos: cam_center_x NUNCA en zona 900-1100 (espacio vacio entre personas) |

### Resultados

#### (a) PODCAST NOTURNOS (`podcast_test_60s_noturnos_s12.mp4`)

```
frames=3602  dur=60s  fps=60
cam_center_x rango: [942, 1362]
face_x_asignada rango: [915, 1367]
distancia media=26.6px  max=198.5px
```

| Criterio | Resultado |
|----------|-----------|
| C1 dist<=80px 95% del tiempo | **PASS** — 3570/3602 = 99.1% |
| C2 no zona 900-1100 | **FAIL** — 2421/3602 frames (67%) en zona vacia |

**Analisis del fallo C2:**

```
t=0.00s  cam=1362  face=1362  dist=0    <- tracker en cara derecha, correcto
t=1.50s  cam=1362  face=1352  dist=10   <- cara derecha, estable
t=2.00s  cam=1202  face=1072  dist=129  <- SALTO: MediaPipe detecto x=1072 (intermedio)
t=2.50s  cam=1082  face=1150  dist=67   <- tracker instalado en zona vacia
t=3.00s  cam=1082  face=1078  dist=4    <- ya no sale de la zona
...60s   cam en rango 942-1100
```

En t=2.0s, MediaPipe detecto una cara a x=1072. Distancia desde ultima conocida (x=1352):
280px < gate_w=384px (20% × 1920) → el gate ACEPTO la deteccion. Desde x=1072, el tracker
HOLD en la zona vacia durante los 58s restantes.

**Diagnostico:** la cara derecha (x≈1362) y la izquierda (x≈719) estan separadas 643px. El gate
de 384px impide saltos directos entre ellas, pero permite drift gradual a traves de la zona
intermedia si MediaPipe detecta posiciones intermedias (brazo, cuerpo, o pose angular de una
de las caras). Una vez instalado en la zona intermedia, el HOLD behavior mantiene la camara ahi.

**Esta es la limitacion fundamental del modo noturnos con 2 personas:** sin turnos asignados,
el tracker de cara unica no puede saber cual persona priorizar cuando ambas son visibles.
El fix de HOLD empeoró la recuperacion en este caso (antes, RECENTER_ALPHA al menos regresaba
al centro; ahora, el HOLD atrapa la camara donde quedo).

#### (b) PODCAST CON TURNOS (`podcast_test_60s_turnos_s12.mp4`)

```
frames=3602  dur=60s  fps=60
cam_center_x rango: [920, 1362]
distancia media=23.5px  max=198.5px
```

| Criterio | Resultado |
|----------|-----------|
| C1 dist<=80px 95% del tiempo | **PASS** — 3568/3602 = 99.1% |

#### (c) VIDEOLARGO CLIP1 — regresion 1 persona (`videolargo_clip1_corto.mp4`)

```
frames=808  dur=13.5s  fps≈60 (854x480)
cam_center_x rango: [211, 543]
distancia media=18.2px  max=99.0px
gate: gate_w=171px  91 detecciones gateadas (33% del total)
```

| Criterio | Resultado |
|----------|-----------|
| C1 dist<=80px 95% del tiempo | **PASS** — 802/808 = 99.3% |

Nota: 91 detecciones gateadas en 1-persona indica ruido de deteccion alto en 480p.
El gate protege la estabilidad (criterio 1 pasa), pero si el gate fuese mas pequeno
podria perder demasiadas detecciones validas.

### Veredicto de sesion 12

| Criterio | Estado |
|----------|--------|
| C1 (dist<=80px 95%) | PASS en los 3 videos ✓ |
| C2 (no zona vacia en noturnos) | **FAIL** — cámara 67% del tiempo en zona 900-1100 ✗ |

**F4.1 NO SE CIERRA.** Criterio C2 falla. Accion requerida: decision del arquitecto sobre
gate_w o comportamiento del tracker single-face en videos multi-persona. No parchar en caliente
(per protocolo de sesion 12).

---

---

## Sesion 13 — Ancla estatica + asignacion exclusiva

### Cambios implementados

| Cambio | Antes (s12) | Despues (s13) |
|--------|------------|---------------|
| Referencia del gate | Ultima posicion conocida del track (dinamica) | Ancla estatica = cx inicial de detectar_caras_video |
| Constante | `FACE_GATE_PCT=0.20` (gate=384px en 1920) | `GATE_ANCLA_PCT=0.15` (gate=288px en 1920) |
| Asignacion multi-cara | Independiente por cara, posible doble asignacion | Exclusiva por frame (greedy minimo-distancia) |

### Model selection — resultado definitivo (item #4)

**Modelo actual:** `blaze_face_short_range.tflite` (224KB, ~2m range)

**Modelo full-range:** La Tasks API 0.10.35 NO tiene parametro `model_selection`. `FaceDetectorOptions` solo expone `min_detection_confidence` y `min_suppression_threshold`. El modelo `blaze_face_full_range.tflite` no esta disponible en el CDN oficial de MediaPipe (HTTP 404/error al intentar descargar). No existe comparacion posible sin el archivo del modelo.

**Confianzas con short-range en podcast_test_60s (scan inicial):**

| cara_id | cx | score_aprox |
|---------|----|-------------|
| 0 | 1362px | ~0.40 |
| 1 | 719px | ~0.24 |

FACE_MIN_CONFIDENCE=0.20 sin cambio. Si se requiere full-range en el futuro, debe usarse MediaPipe Solutions legacy (<0.10) o un modelo custom.

### Geometria del ancla (1920x1080)

```
cara_id=0: ancla=1362,  zona_aceptable=[1074, 1650]
cara_id=1: ancla=719,   zona_aceptable=[431, 1007]
gap entre zonas: 67px  (1007 a 1074 = zona muerta sin asignar)
```

Gate de asignacion exclusiva: cada deteccion va al track cuya ancla esta mas cerca,
si y solo si esa distancia <= GATE_ANCLA_PCT x source_w. Una deteccion por track max.

### Validacion sesion 13

| Video | C1 (dist<=80px 95%) | C2 (zona 900-1100 <=2%) |
|-------|--------------------|-----------------------|
| PODCAST NOTURNOS | **PASS** — 99.2% | **FAIL** — 42.0% |
| PODCAST TURNOS | **PASS** — 99.3% | N/A |
| VIDEOLARGO CLIP1 | **PASS** — 99.8% | N/A |

### Trayectorias antes (s12) / despues (s13) en PODCAST NOTURNOS

```
Metrica                 s12 (last-pos 20%)    s13 (ancla 15%)    Mejora
cam_min                       942px               1082px           +140px
zona 900-1100              67.2% (2421 f)       42.0% (1514 f)     -25pp
C1 (dist<=80px)             99.1%                99.2%             +0.1pp
dist media                   26.6px               28.6px            -2px
```

### Analisis del fallo C2 en sesion 13

El drift fue corregido: cam_min pasa de 942 a 1082 (+140px). La camara ya NO visita
el espacio vacio profundo (x<1074).

Sin embargo, C2 sigue fallando. La causa ya NO es drift sino **solapamiento geometrico**:

```
Zona aceptable por ancla: [1074, 1650]
Zona prohibida por C2:    [900, 1100]
Solapamiento:             [1074, 1100] = 26px
```

La cara derecha (ancla=1362) es detectada en posiciones x=[1082-1122] durante 25s del clip
— posiciones validas segun el gate (distancias 240-280px < gate 288px). La camara correctamente
las sigue. Estas posiciones caen en el solapamiento [1074,1100], violando C2.

La distribucion de cam_center_x muestra 3 clusters del track:
- x≈1082 (cara derecha inclinada izquierda): 42% del tiempo
- x≈1175 (cara derecha central): 34% del tiempo
- x≈1362 (cara derecha inclinada derecha): 10% del tiempo

**Conclusion:** C2 falla porque el 26px de solapamiento entre la zona del ancla y la zona C2
permite que la cara derecha (al estar en su extremo izquierdo natural) viole el criterio.
Este NO es el bug de drift original. Es un problema de calibracion del gate vs el criterio.

**Opciones para el arquitecto (no parchar en esta sesion):**
1. Reducir GATE_ANCLA_PCT a 0.12 → gate=230px → zona=[1132,1650], sin solapamiento con C2
2. Redefinir C2 como "<[ancla0 - gate_ancla0]" en lugar de "<900" (zona relativa al ancla)
3. Aceptar como limitacion del modo noturnos con 2 personas (la cara derecha orbita en el rango)

---

## Sesion 13 — Diagnostico C2 (sesion de diagnostico, sin renders nuevos)

### Cruce C2 x CARA (fuente: CSV noturnos s13)

Cruce frame-a-frame de cam_center_x en [900,1100] contra face_x_asignada / distancia.
Detalle completo en `revision/fase-4.1/c2_cruce.md` y `c2_cruce_detalle.csv`.

| Metrica | Valor |
|---------|-------|
| Frames en zona C2 [900-1100] | 1514 / 3602 = 42.0% |
| De esos: dist ≤80px (cara cerca) | **1514 / 1514 = 100%** |
| De esos: dist  >80px (sin cara) | **0 / 1514 = 0%** |
| Distancia media en zona | 20.2px |
| face_x en zona | [1073.5, 1168.7]px |

Nota: confianza y area del bbox NO estan en el CSV; se obtienen del scan inicial
(cara_id=0: score≈0.40 cuando ambas caras visibles, ≈0.40-0.70 cuando sola).

**Tramos continuos >0.5s en zona C2:**

| # | t_ini | t_fin | dur | dist_media | face_x rango |
|---|-------|-------|-----|-----------|--------------|
| 1 | 2.20s | 4.63s | 2.43s | 25.7px | [1077, 1169] |
| 2 | 8.53s | 10.08s | 1.55s | 13.0px | [1074, 1166] |
| 3 | 18.43s | 22.17s | 3.73s | 18.7px | [1083, 1136] |
| 4 | 24.40s | 41.92s | 17.52s | 20.4px | [1074, 1160] |

### C2v2 — propuesta del arquitecto (para decision, no criterio oficial)

```
C2v2 = % del tiempo total con (camara en zona [900,1100]) Y (dist > 80px)
     = 0 / 3602 = 0.0%
```

**Racional:** el C2 original detectaba el bug de drift de sesion 12 (camara parqueada
en el vacio sin cara). Ese bug fue corregido. Lo que queda es la cara derecha
orbitando en su extremo izquierdo natural ([1074, 1169]), zona valida segun el
ancla. Seguir una cara real que orbita cerca de la zona C2 no es el bug original.

C2v2 separa los dos casos: C2v2=0% confirma que **no hay ningun frame donde la
camara este en zona C2 SIN una cara cercana**. El fallo C2=42% es enteramente
la cara real en su zona de movimiento natural, no drift.

Esta propuesta queda sujeta a decision del arquitecto.

### Model_selection — reporte definitivo

Detalle en `revision/fase-4.1/model_selection.md`. Resumen:

- mediapipe 0.10.35 elimino `mp.solutions` completamente; no hay API legacy
- Tasks API `FaceDetectorOptions` solo expone: `min_detection_confidence`,
  `min_suppression_threshold`, `result_callback`, `running_mode`
- modelo `blaze_face_full_range.tflite` no disponible en CDN oficial (404)
- **Comparacion model_selection=0 vs 1: IMPOSIBLE** sin downgrade de mediapipe

### Fix EMA — exponente invertido (sesion de diagnostico)

**Bug:** `calcular_alpha_fps` usaba `^(fps/fps_ref)` en lugar de `^(fps_ref/fps)`.

| fps | alpha INCORRECTO ^(fps/30) | alpha CORRECTO ^(30/fps) | efecto |
|-----|---------------------------|--------------------------|--------|
| 24 | 0.0645 | 0.0990 | camara demasiado lenta en 24fps |
| 30 | 0.0800 | 0.0800 | igual (fps=fps_ref) |
| 60 | 0.1536 | 0.0408 | camara 3.8x mas reactiva de lo tuneado |

Tau real de respuesta (sesiones 12-13 a 60fps): 0.11s (incorrecto) vs 0.41s (correcto).

**Fix aplicado:** `reframe_track.py` linea 59 + test renombrado
`test_calcular_alpha_fps_60fps_menor` (invariante corregido). 85 tests verdes.

**Renders invalidos:** todas las sesiones 12 y 13 (60fps). Los CSVs de trayectoria
y los resultados C1/C2 de esas sesiones corresponden a alpha=0.154 (3.8x mas
reactivo). C1 paso (99.1-99.8%) con el alpha incorrecto; el alpha correcto (0.041)
producira una camara mas suave — C1 necesita re-test post-fix.

---

## Sesion 14 — Re-validacion post-EMA + detector full-range

### Decisiones del arquitecto registradas

Ver `revision/fase-4.1/DECISIONES.md` para el registro completo. Resumen:
- **D1:** C2v2 reemplaza a C2 como criterio oficial (<=2%)
- **D2:** GATE_ANCLA_PCT queda en 0.15
- **D3:** Zona [900,1100] fija (no relativa al ancla)
- **D4:** short_range mantenido (full_range rechazado)
- **D5:** retune alpha/deadzone PENDIENTE (C1 cayo a 94.9% en noturnos)

### Comparativa detectores short-range vs full-range

Ejecutado sobre `podcast_test_60s` (1920x1080, 60fps, 2 caras, 1201 frames de detector).
Anchores: cara_0=1362px, cara_1=719px, gate=288px (GATE_ANCLA_PCT=0.15 x 1920).

| Metrica | short_range | full_range | delta |
|---------|-------------|------------|-------|
| conf media cara_0 | 0.4759 | 0.8247 | +0.3488 |
| conf media cara_1 | 0.4300 | 0.7346 | +0.3045 |
| pct frames det (dentro gate) | 112.6% | 119.2% | +6.7pp |
| det fuera del gate de AMBAS anclas | 73 | **135** | **+62** |

**Regla adopcion:** conf_sube=True AND det_no_baja=True AND **fuera_no_sube=False**
→ **RECHAZADO: mantener short_range**. Detalle: `revision/fase-4.1/model_selection.md`.

### Re-renders s14 (alpha corregido ^30/fps, short_range)

Clip: `input/podcast_test_60s.mp4` (60fps, 3602 frames). Alpha efectivo: 0.0408@60fps.

| Video | C1 (dist<=80px >=95%) | C2 crudo (cam en [900,1100]) | C2v2 (zona Y dist>80px <=2%) | Render |
|-------|----------------------|------------------------------|-------------------------------|--------|
| noturnos s14 | **FAIL 94.9%** | 37.4% | **PASS 0.2%** | 41.7s |
| turnos s14 | PASS 96.1% | 62.5% | PASS 0.5% | 41.6s |

#### NOTURNOS s14 — tramos continuos C2 >0.5s

| # | t_ini | t_fin | dur | dist_media | face_x rango |
|---|-------|-------|-----|-----------|--------------|
| 1 | 3.02s | 4.70s | 1.68s | 23.8px | [1077, 1191] |
| 2 | 9.13s | 10.12s | 0.98s | 23.1px | [1074, 1179] |
| 3 | 19.18s | 22.18s | 3.00s | 15.9px | [1083, 1180] |
| 4 | 25.22s | 41.98s | **16.77s** | 21.0px | [1074, 1165] |

Frames extraidos: `s14_noturnos_tramo{1-4}_t*.jpg` en `revision/fase-4.1/`.
Frame del mayor fallo C1: `s14_noturnos_c1fail_t1.95.jpg`.

#### C1 noturnos s14 — analisis del fallo

C1 = 94.9% (185/3602 frames, umbral 95%). Fallo MARGINAL pero real.

| Tramo de fallo | dur | dist_max |
|----------------|-----|----------|
| t=49.33-49.92s | 0.58s | 176px |
| t=22.17-22.63s | 0.47s | 230px |
| t=24.12-24.58s | 0.47s | 236px |
| t=10.10-10.53s | 0.43s | 116px |
| t=1.92-2.28s   | 0.37s | 256px |

Distribucion: 80-100px=86, 100-150px=56, 150-200px=29, >200px=14.

**Causa:** alpha=0.041@60fps (correcto) es 3.8x mas lento que alpha=0.154 (s13 incorrecto).
En las transiciones donde la cara salta >80px entre detecciones, la EMA tarda ~0.41s en
alcanzar la nueva posicion. Con alpha incorrecto tardaba solo ~0.11s.

**Accion requerida:** resuelta en sesion 15 con alpha adaptativo (D5). Ver seccion siguiente.

#### Comparativa alpha-viejo vs alpha-nuevo (lado a lado)

| Metrica | s13 alpha=0.154 (INCORRECTO) | s14 alpha=0.041 (CORRECTO) | delta |
|---------|------------------------------|---------------------------|-------|
| NOTURNOS C1 | 99.2% PASS | **94.9% FAIL** | -4.3pp |
| NOTURNOS C2 crudo | 42.0% | 37.4% | -4.6pp |
| NOTURNOS C2v2 | 0.0% PASS | **0.2% PASS** | +0.2pp |
| TURNOS C1 | 99.3% PASS | 96.1% PASS | -3.2pp |
| VIDEOLARGO C1 (30fps) | 99.8% PASS | 99.8% PASS (sin cambio) | 0.0pp |

Note: videolargo es 30fps — a 30fps alpha_viejo=alpha_nuevo=0.08. Sin re-render.

### Cambios de codigo sesion 14

| Archivo | Cambio |
|---------|--------|
| `models/blaze_face_full_range.tflite` | Descargado (1.03MB) para comparativa |
| `reframe_track.py:detectar_cara_frame` | Agrega campo `score` al dict retornado |
| `reframe_detect.py` | `MODEL_PATH_SHORT`, `MODEL_PATH_FULL`, `ACTIVE_MODEL_PATH`; `_crear_detector(model_path)` acepta path; `_detectar_trayectoria` y `_detectar_trayectorias_multi` retornan `(sparsa, sparsa_conf)` |
| `reframe.py` | `_aplanar_conf_por_turnos` nuevo; `_calcular_crop_secuencia` recibe y devuelve `sparsa_conf`; `_calcular_crops` devuelve 3-tupla; `_exportar_trayectoria_csv` agrega columna `conf_asignada`; log del modelo activo |
| `input/podcast_test_60s.mp4` | Creado: extract de 60s de `pruebapodcast2personas.mp4` |
| `revision/fase-4.1/model_selection.md` | Correccion del veredicto: full_range descargable y comparable; resultado: RECHAZADO |
| `revision/fase-4.1/DECISIONES.md` | Nuevo — registro de decisiones del arquitecto |

### 88 tests verdes post-cambios

---

## Sesion 15 — Retune D5: alpha adaptativo

### Decision D5 del arquitecto

Alpha adaptativo de dos regimenes. Ver DECISIONES.md D5 para especificacion completa.

```
ALPHA_BASE_LENTO  = 0.08  (tau ~0.41s @ 30fps)
ALPHA_BASE_RAPIDO = 0.28  (tau ~0.11s @ 30fps; = alpha s13 efectivo @60fps)
umbral_lento  = deadzone_half * 1.0  (en el borde de la deadzone)
umbral_rapido = deadzone_half * 3.0  (3x el borde)

podcast 1920x1080: umbral_lento=76px, umbral_rapido=228px
videolargo 854x480: umbral_lento=34px, umbral_rapido=101px
```

Invariante: error <= dz_half => ALPHA_BASE_LENTO (reposo dentro de deadzone).
Rampa lineal sin discontinuidad en los dos bordes.

### Re-renders s15 (alpha adaptativo, short_range, podcast_test_60s)

| Video | C1 (>=95%) | C2 crudo | C2v2 (<=2%) | Render |
|-------|-----------|----------|-------------|--------|
| noturnos s15 | **PASS 96.2%** | 38.2% | PASS 0.19% | 40.0s |
| turnos s15 | **PASS 97.5%** | 63.4% | PASS 0.53% | 40.1s |
| videolargo (tracking-only) | **PASS 100.0%** | N/A | N/A | — |

Primera iteracion pasa — NO fue necesario usar la pre-autorizacion (ALPHA_BASE_RAPIDO<=0.35).

### NOTURNOS s15 — tramos continuos C2 >0.5s

| # | t_ini | t_fin | dur | dist_media | face_x rango |
|---|-------|-------|-----|-----------|--------------|
| 1 | 2.73s | 4.70s | 1.97s | 21.7px | [1077, 1191] |
| 2 | 9.13s | 10.12s | 0.98s | 23.1px | [1074, 1179] |
| 3 | 19.18s | 22.18s | 3.00s | 15.9px | [1083, 1180] |
| 4 | 24.98s | 41.98s | **17.00s** | 20.9px | [1074, 1165] |

Frames: `s15_noturnos_tramo{1-4}_t*.jpg` en `revision/fase-4.1/`.

### Tabla comparativa s14 vs s15 (alpha-fijo vs alpha-adaptativo)

| Metrica | s14 alpha=0.041@60fps (fijo) | s15 adaptativo | delta |
|---------|------------------------------|----------------|-------|
| NOTURNOS C1 | 94.9% **FAIL** | **96.2% PASS** | +1.3pp |
| NOTURNOS C2 crudo | 37.4% | 38.2% | +0.8pp |
| NOTURNOS C2v2 | 0.2% PASS | **0.19% PASS** | -0.01pp |
| TURNOS C1 | 96.1% PASS | **97.5% PASS** | +1.4pp |
| TURNOS C2v2 | 0.5% PASS | 0.53% PASS | +0.03pp |
| VIDEOLARGO C1 | 99.8% (s13 val.) | **100.0%** (tracking-only) | +0.2pp |

### Correcciones de registro sesion 15

**4a. model_selection.md condicion 3:** la condicion originalmente medía detecciones
fuera del gate como "ruido" bloqueante. Esas detecciones son RECHAZADAS en runtime
por `_asignar_detecciones_a_caras` y no afectan el tracking. El verdadero rechazo
de full_range es: sin necesidad demostrada + no meter segunda variable durante el
retune (alpha adaptativo de s15). Corrected in model_selection.md.

**4b. Metrica "pct frames con det 112.6%":** era ratio detecciones/frames_detector,
no frames con al menos una detection. Desglose real:
- cara_0: 939/1201 frames = 78.2%
- cara_1: 413/1201 frames = 34.4%
- total det dentro gate = 1352, de ahi 1352/1201 = 112.6% (>100% = frames con 2 det)
Corregido en model_selection.md con tabla desglosada.

**4c. podcast_test_60s.mp4:** el archivo es `ffmpeg -t 60 -c copy` de
`input/pruebapodcast2personas.mp4` desde t=0. Es el mismo material usado en s12/s13
(ambas sesiones usaron los primeros 60s de la misma fuente). Aparece como "creado" en
s14 porque en sesiones anteriores fue creado temporalmente para los renders de prueba,
no fue rastreado por git, y fue re-creado en s14. El extract con `-c copy` es
determinista: mismo offset (0s), misma duracion (60s), mismo fuente => mismo contenido.

### Cambios de codigo sesion 15

| Archivo | Cambio |
|---------|--------|
| `reframe_track.py` | `ALPHA_BASE_LENTO`, `ALPHA_BASE_RAPIDO`, `RAMP_LENTO_FACTOR`, `RAMP_RAPIDO_FACTOR`; `calcular_alpha_adaptativo(error, dz_w, fps)`; `ema_smooth_adaptativo(positions, fps, dz_w)`; `calcular_crops_por_turnos` usa `ema_smooth_adaptativo` |
| `reframe.py` | `_calcular_crop_secuencia` usa `rt.ema_smooth_adaptativo` en lugar de `ema_smooth(targets, alpha_eff)` |
| `tests/test_contrato_reframe.py` | 10 tests nuevos: invariante reposo, monotonia, continuidad bordes, tau fps, ema_adaptativo vacio/un_elem/sin_movimiento/gran_salto |
| `revision/fase-4.1/DECISIONES.md` | D5 resuelto: alpha adaptativo + 5 opciones marcadas elegida/descartadas |
| `revision/fase-4.1/model_selection.md` | Correcciones 4a y 4b: racional correcto, metrica desglosada |
| `revision/fase-4.1/REFRAME_REPORT.md` | Esta seccion |

### 98 tests verdes post-implementacion

---

## DoD — estado al cierre de sesion 12

| Item | Estado |
|------|--------|
| 1. python reframe.py genera MP4 9:16 | OK |
| 2. Sin temblor visible (EMA + deadzone) | OK — C1 99.1-99.3% (criterio: >=95%) |
| 3. Multi-cara: conmutacion real con turnos | OK — podcast 60s, 6 switches, C1=99.1% |
| 4. Audio intacto (ffprobe) | OK — AAC exacto en todos los clips |
| 5. Sin caras: center-crop + log | OK |
| 6. Punch-ins visibles | OK — sesion 10 |
| 7. pix_fmt=yuv420p | OK |
| 8. check.bat verde | OK — 85 tests |
| 9. Smoke test caption.py intacto | OK |
| 10. WARNING 2+ caras sin turnos | OK |
| 11. CSV trayectoria por render | OK — `revision/fase-4.1/trayectoria_{stem}.csv` |
| **12. C2v2: cam en zona Y dist>80px <=2% (noturnos)** | PASS s14: 0.2% (C2 original reemplazado por C2v2, decision arquitecto D1) |
| **13. C1 >=95% con alpha adaptativo** | PASS s15: noturnos 96.2%, turnos 97.5%, videolargo 100% |

---

## Sesion 18 — Forense de fuente y causa raiz del HOLD

### Hallazgo del arquitecto

El render stack de sesion 17 mostraba la MISMA persona en ambas bandas.
Causa: `podcast_test_60s.mp4` es material EDITADO con 7 cortes de escena duros.
El scan inicial (primeros 30 frames = plano 0, 1.95s) encontro 2 caras, pero el
resto del clip es de plano unico con 1 sola cara. Las anclas quedaron invalidas
para la mayor parte del material.

### Inventario de planos (7 cortes, umbral scdet=0.25, scores>=0.877)

Ver detalle completo en `revision/fase-4.2-lite/planos_fuente.md`.

| Plano | t_ini | t_fin | dur | 2 caras reales | notas |
|-------|-------|-------|-----|----------------|-------|
| 0 | 0.00s | 1.95s | 1.95s | SI (brevemente) | scan captura anclas aqui |
| 1 | 1.95s | 22.17s | 20.22s | NO (1 cara) | cx≈1090-1123 |
| 2 | 22.17s | 24.13s | 1.96s | NO | |
| 3 | 24.13s | 41.07s | 16.94s | NO (1 cara real) | artefacto doble en borde corte |
| 4 | 41.07s | 44.62s | 3.55s | parcial | |
| 5-6 | 44.62s | 51.38s | 6.76s | NO | |
| 7 | 51.38s | 60.03s | 8.65s | NO (doble det. misma persona) | cx muy proximas |

**Conclusion:** ningun plano tiene 2 caras distintas continuas >=15s.
Fuente inadecuada para validacion de stack.

### Cruce retrospectivo: cortes vs tramos C2/HOLD de s15

| Evento | t_ini | t_fin | corte cercano | delta | causal? |
|--------|-------|-------|--------------|-------|---------|
| C2 tramo 1 | 2.73s | 4.70s | corte t=1.95s | 0.78s | posible |
| C2 tramo 2 | 9.13s | 10.12s | ninguno ±5s | >5s | NO — movimiento natural |
| C2 tramo 3 | 19.18s | 22.18s | corte t=22.17s | **0.01s** | **SI — tramo termina exactamente en corte** |
| C2 tramo 4 | 24.98s | 41.98s | cortes t=24.13 y t=41.07 | 0.85/0.91s | SI — plano nuevo genera la zona |
| HOLD t=54-60s | 54.00s | 60.03s | corte t=51.38s | 2.62s | **SI — causa raiz (ver abajo)** |

### Causa raiz del HOLD en t=54-60s (correccion del diagnostico anterior)

**Diagnostico anterior (s16):** "cara debil con 34.4% de deteccion; 6s de hold."
**Diagnostico correcto (s18):** el corte en t=51.38s introduce un plano donde la
persona esta a cx≈870-1010, FUERA del gate de ancla_0 (ancla=1362, zone=[1074,1650]).
Todas las detecciones post-corte son rechazadas por el gate => 0 detecciones validas
=> HOLD desde ~t=51.38+2.62=54s. La cara a cx=1134 vista en el diagnostico es la
posicion pre-corte holdada, no la cara en el nuevo plano.

**El descuadre NO es principalmente por deteccion debil de la cara.
Es por cortes de escena en material editado que el gate no puede manejar.**

### Accion: check automatico de cortes

Implementado en sesion 18 en `reframe.py`:
- `N_CORTES_WARN = 2`
- `_contar_cortes_escena(video_path, threshold=0.3) -> int`
- `_avisar_cortes(n)` → WARNING si n > 2
- Llamado al inicio de `reframe_clip` y `reframe_stack_clip`

112 tests (4 nuevos de umbral).

### Validacion stack — PENDIENTE

Tarea 3b aplica: K aportara fuente de toma fija con 2 personas estaticas >=15s.
Hasta entonces la validacion visual de stack esta BLOQUEADA.

---

## Sesion 19 — Precondicion, caveat C1, registro

### Fuente nueva: prueba2personasenmedio.mov

**Nota:** K subio la fuente como `.mov`; la spec decia `.mp4`. Se uso el `.mov`
(mismo nombre, distinto contenedor). Arquitecto confirmar si aplica.

**Precondicion 0a:** 854x480, HORIZONTAL, 30fps, 96s, h264/AAC. OK.

**Precondicion 0b: 3 cortes detectados (threshold=0.3):**

| # | t | score | tipo probable |
|---|---|-------|--------------|
| 1 | 0.067s | 1.000 | artefacto scdet en primer frame (siempre ocurre) |
| 2 | 54.03s | 0.663 | posible falso positivo — autoexposicion/movimiento |
| 3 | 56.70s | 0.651 | posible falso positivo — autoexposicion/movimiento |

Frames extraidos: revision/fase-4.2-lite/corte1_pre_t0.0.jpg,
corte2_pre/post_t54.0.jpg, corte3_pre/post_t56.7.jpg.

**3 > N_CORTES_WARN=2 → WARNING emitido. RENDERS PAUSADOS hasta clarificacion.**
Notas: el corte 1 (t=0.067s) es un artefacto conocido del filtro scdet. Los cortes 2 y 3
tienen scores 0.663/0.651 (vs 0.877-1.0 en material editado real). Pueden ser
falsos positivos en toma fija. El arquitecto revisa los frames y decide si proceder.

**Precondicion 0c: anclas:**
- cara_id=1: cx=269, conf_media=0.3454
- cara_id=0: cx=562, conf_media=0.4806
- Separacion: 293px < crop_w=540px (N=2 src_h=480) → INTRUSION CRUZADA esperada en stack.

### Nota de vacuidad del C-STACK s17

El resultado 100%/100% del C-STACK s17 era trivialmente garantizado:
- gate_0 = [ancla0 - 288, ancla0 + 288] = [1074, 1650]
- crop_0 = [705, 1920]  →  gate_0 ⊂ crop_0  ✓
- gate_1 = [431, 1007]
- crop_1 = [111, 1326]  →  gate_1 ⊂ crop_1  ✓

Cualquier deteccion dentro del gate esta garantizadamente dentro del crop.
El C-STACK es un tripwire, no una metrica discriminante. Valor real: evidencia visual de K.

La "discrepancia 165 vs 413 de cara_1": los 413 son detecciones en toda la fuente
(1201 frames con detector); los 165 son solo durante los turnos activos de cara_1
(t=10-20, 30-40, 50-60 = 30s). Con el denominador correcto (413), C-STACK cara_1 = 100%
de igual manera (gate_1 ⊂ crop_1).

### Caveat C1

C1 mide distancia cam vs face_x_asignada INCLUYENDO holds. En fuentes con cortes de
escena que violan la precondicion, C1 puede aprobar frames donde la cara real esta lejos:

Caso medido (t=54-60s noturnos podcast_test_60s):
- cam=1182, track_fantasma=1134 → dist=48px → C1 PASS
- cara real en cx~870-1010 del plano 7 (fuera del gate tras corte t=51.38s)
- distancia real cara_real vs cam: |1182 - 940| ~ 242px → C1 FAIL si se midiera real

Dentro de dominio (toma fija continua), holds son cortos y C1 ~= realidad.

Metrica C1v2 propuesta: medir C1 solo sobre frames con conf_asignada (deteccion viva).
Ver PREGUNTAS.md F4.2 completo para spec.

### Ledger de tests s15→s18

| Sesion | Tests finales | Delta | Nuevos |
|--------|--------------|-------|--------|
| s15 | 98 | +10 | calcular_alpha_adaptativo + ema_smooth_adaptativo (10 tests) |
| s17 | 108 | +10 | calcular_bandas_stack (9) + fuente_angosta (1) — ESTADO.md decia 107, incorrecto |
| s18 | 112 | +4 | _avisar_cortes (4) |

NOTA: ESTADO.md sesion 17 reporto "107 tests" — corregido aqui a 108 (el test de
fuente_angosta se agrego al resolver el bloqueante del revisor de s17).
