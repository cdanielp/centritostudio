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

## DoD — estado al cierre de sesion 11

| Item | Estado |
|------|--------|
| 1. python reframe.py genera MP4 9:16 | OK - 5 clips generados (4 primarios + podcast) |
| 2. Sin temblor visible (EMA + deadzone) | PENDIENTE — veredicto del arquitecto |
| 3. Multi-cara: conmutacion real con turnos | OK - podcast 60s, 6 switches |
| 4. Audio intacto (ffprobe) | OK - todos los clips AAC exacto |
| 5. Sin caras: center-crop + log | OK - videolargo_clip1 primera ejecucion sesion 10 |
| 6. Punch-ins visibles | OK - 9 keywords en sesion 10 |
| 7. pix_fmt=yuv420p en todos los outputs | OK - verificado con ffprobe ✓ |
| 8. check.bat verde (82 tests) | OK |
| 9. Smoke test caption.py intacto | OK - sesion 10 |
| 10. WARNING en lugar de error para 2+ caras sin turnos | OK - log verificado |

F4.1 NO se cierra hasta veredicto visual del arquitecto.
