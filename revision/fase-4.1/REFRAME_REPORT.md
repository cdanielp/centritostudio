# REFRAME_REPORT.md — Fase 4.1: Validacion de Implementacion

**Fecha:** 2026-07-09 · Sesion: 10

---

## Clips procesados

| Clip | Resolucion fuente | Duracion | Deteccion cara | Tiempo render |
|------|-------------------|---------|----------------|---------------|
| videolargo_clip1_corto | 854×480 | 26.9s | 87% (234/270) | 6.0s |
| videolargo_clip2_corto | 854×480 | 30.4s | 63% (193/304) | 7.1s |
| videolargo_clip3_largo | 854×480 | 89.4s | estimado ~75% | 20.4s |
| pruebaedicionvideoyo_clip1_corto | 2560×1440 | 31.3s | 3 "caras" (multi-cara disparado) | 12.1s (con turnos manuales) |

**Todos los outputs:** 1080×1920 (9:16), codec H.264, AAC copiado.

---

## Verificacion de audio (§8 DoD)

Todos los clips verificados con `ffprobe`:
- `videolargo_clip1_corto`: AAC 26.920000s → 9:16 AAC 26.920000s ✓
- `videolargo_clip2_corto`: AAC 30.390000s → 9:16 AAC 30.390000s ✓
- `videolargo_clip3_largo`: AAC 89.420000s → 9:16 AAC 89.420000s ✓

El audio pasa intacto con `-map 1:a -c:a copy`. Duracion exacta al millisegundo.

---

## Casos borde disparados

| Caso | Clip | Resultado |
|------|------|-----------|
| 3 "caras" detectadas en screen recording | pruebaedicionvideoyo | ValueError accionable + log exacto |
| Multi-cara con turnos manuales | pruebaedicionvideoyo (forzado) | Reframe OK en 12.1s |
| Face tracking en video 854×480 (baja res) | clips videolargo | Umbral bajado a 0.20 (era 0.5) |
| Brain generado para punch-in | pruebaedicionvideoyo | 9 keywords detectadas, brain.json persistido |
| Punch-ins aplicados | pruebaedicionvideoyo_9x16_punch | 9 punch-ins en 12.3s |

**Nota sobre FACE_MIN_CONFIDENCE:** se calibro de 0.5 a 0.20 durante la implementacion. Los
clips de clase (854×480) son screen recordings con la cara del instructor a baja resolucion;
el detector necesita umbral mas bajo. Registrado en reframe_track.py como constante calibrable.

---

## Validacion multi-cara con test de contrato

El codigo de corte seco entre hablantes se valida via `test_cara_en_frame_corte_seco_exacto`:
- Frame 374 (t=12.467s) → cara_id=0
- Frame 375 (t=12.5s exacto) → cara_id=1 (corte seco verificado)
Validacion visual multi-cara pendiente de video real con 2 personas (anotado en ESTADO.md).

---

## Performance real (clips 854×480)

- Deteccion: ~270 llamadas × ~5ms en CPU = ~1.4s
- Render: 808 frames × crop + LANCZOS4 resize (270→1080) = ~4.6s
- Total: ~7.5s para clip de 26.9s (~3.6x real-time)

Para clip largo (89.4s, 2683 frames): 24.3s total (~3.7x real-time). Estimacion del diseno
era 3:1, la medicion real es 3.6:1 — dentro del rango aceptable para workflow offline.

---

## Frames de evidencia

### Formato de frames: {clip}_{src|9x16}_t{%}.jpg
- `videolargo_clip1_corto_src_t50.jpg` vs `videolargo_clip1_corto_9x16_t50.jpg`
- `videolargo_clip2_corto_src_t50.jpg` vs `videolargo_clip2_corto_9x16_t50.jpg`
- `videolargo_clip3_largo_src_t50.jpg` vs `videolargo_clip3_largo_9x16_t50.jpg`
- `pruebaedicionvideoyo_clip1_corto_src_t50.jpg` vs `pruebaedicionvideoyo_clip1_corto_9x16_t50.jpg`
- `pruebaedicionvideoyo_clip1_corto_punch_t50.jpg` (con punch-in activado)

---

## Pendientes — veredicto humano requerido

1. **Temblor del encuadre**: el criterio de calidad #1 es visual — solo el arquitecto puede
   aprobarlo mirando los videos 9:16 generados. Los clips estan en `output/clips/*_9x16.mp4`.
2. **Posicion del encuadre**: verificar que la cara queda centrada (no cortada por arriba/abajo).
3. **Punch-ins**: verificar que el zoom en keywords no se ve abrupto. Clip de prueba:
   `output/clips/pruebaedicionvideoyo_clip1_corto_9x16_punch.mp4`
4. **Validacion visual multi-cara**: no disponible con los clips actuales (todos 1 persona).

---

## DoD — estado al cierre de sesion 10

| Item | Estado |
|------|--------|
| 1. python reframe.py genera MP4 9:16 | OK - 4 clips generados |
| 2. Sin temblor visible (EMA + deadzone) | PENDIENTE — veredicto del arquitecto |
| 3. Multi-cara: error accionable / reencuadre con turnos | OK - ambos validados |
| 4. Audio intacto (ffprobe) | OK - 3/3 clips AAC exacto |
| 5. Sin caras: center-crop + log | OK - videolargo_clip1 primera ejecucion |
| 6. Punch-ins visibles | OK - 9 keywords en clip 2560x1440 |
| 7. REFRAME_REPORT.md con frames | OK - este documento |
| 8. check.bat verde (79 tests) | OK |
| 9. Smoke test caption.py intacto | OK - 5.7s, 34 eventos ASS |
