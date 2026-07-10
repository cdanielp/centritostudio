# DISENO_REFRAME.md — Fase 4.1: Reframe Vertical (16:9 → 9:16)

## Contexto

Los clips del clipper (F4) salen en 16:9 (formato del video fuente). Su destino primario
(Reels, TikTok, Shorts) es 9:16. Esta fase cierra ese ciclo: toma un clip de `output/clips/`
y produce un MP4 1080×1920 con encuadre dinámico que sigue al hablante.

**Orden del pipeline confirmado:** clipper → reframe (9:16 + punch-ins) → captions

**Decisiones ya tomadas por el arquitecto (no reabrir):**

1. Detección: MediaPipe face detection, cada 3-5 frames + interpolación entre detecciones
2. Suavizado: EMA sobre posición + DEADZONE ~30% del ancho fuente
3. Punch-ins: zoom 110-115% en cada keyword del brain, 3-4 frames de transición suave
4. Multi-cara: asignación MANUAL con `{clip}_turnos.json`; transición entre hablantes = CORTE SECO
5. Input genérico; caso primario: clips de `output/clips/`
6. Si falta `{clip}_brain.json`: llamar brain UNA vez y persistir; log "brain generado/reutilizado"
7. Las captions se renderizan SOBRE el video ya reencuadrado

---

## §1 Estrategia de render

**Decisión: OpenCV frame-by-frame + pipe a FFmpeg para encoding H.264**

### Opciones evaluadas

| Opción | Calidad | Velocidad | Complejidad | Veredicto |
|--------|---------|-----------|-------------|-----------|
| FFmpeg `zoompan` | Media (artefactos de re-sampling) | Alta | Alta (macros de filtro crípticas) | Descartada |
| FFmpeg `crop` + `sendcmd` | Alta | Alta | Muy alta (archivo por frame, difícil debuggear) | Descartada |
| **OpenCV read + Python crop + pipe a FFmpeg** | Alta | Aceptable | Media | **Elegida** |

### Justificación

1. **Integración natural con MediaPipe**: ambos trabajan con arrays numpy/BGR; no hay conversión de formato
2. **Control por frame de la ventana de crop**: necesario para punch-ins (el crop_w varía frame a frame)
3. **Audio preservado sin re-encode**: `ffmpeg -i {input} ... -map 1:a -c:a copy` toma el audio del fuente original
4. **Mismo encoder del pipeline**: H.264 CRF=18 -preset fast, coherente con clipper y captions
5. **Performance estimada** para clips 20-100s a 30fps:
   - 600-3000 frames total
   - Detección cada 3 frames: 200-1000 llamadas MediaPipe (~10ms c/u en CPU) = 2-10s
   - Crop + resize numpy: ~3ms/frame × 3000 = ~9s
   - Total estimado: 20-40s para 100s de clip (~3:1 real-time, aceptable en workflow offline)

### Comando FFmpeg (esquema del render)

```
ffmpeg -y -loglevel error
  -f rawvideo -pix_fmt bgr24 -s 1080x1920 -r {fps} -i pipe:0
  -i {input_video_original}
  -map 0:v -map 1:a
  -c:v libx264 -crf 18 -preset fast -pix_fmt yuv420p
  -c:a copy
  -movflags +faststart
  {output_9x16.mp4}
```

El proceso de Python escribe frames BGR crudos al stdin del proceso FFmpeg. El audio viene del
`-i {input_video_original}` con `-map 1:a -c:a copy` — intacto, sin re-encode.

**FIX sesion 11:** `-pix_fmt yuv420p` es OBLIGATORIO en los argumentos de salida. Sin el,
el raw BGr24 del pipe produce `yuv444p / High 4:4:4 Predictive`, incompatible con moviles,
Windows Media Player y plataformas de social media. Verificado con ffprobe.

---

## §2 Geometría de crop

### Relación de aspecto

- **Fuente**: 16:9 (ej. 1920×1080 o 1280×720)
- **Destino**: 9:16 — siempre 1080×1920 (máxima calidad para Reels; FFmpeg hace upscale lanczos si fuente es 720p)
- **Ventana de crop**: `crop_w = source_h × 9 // 16` (ej. 607px para source_h=1080)
- **Tracking solo horizontal**: Y=0 siempre (crop de ancho completo vertical); solo X varía
- La ventana (607×1080) se escala a (1080×1920) **por OpenCV** con `cv2.INTER_LANCZOS4`
  (corrección voto #15: el pipe recibe frames ya escalados; `-s` en FFmpeg es solo referencia de dimensión)

### Parámetros calibrables (constantes al inicio de `reframe_track.py`)

| Constante | Valor | Rango sensato | Descripción |
|-----------|-------|---------------|-------------|
| `EMA_ALPHA` | 0.08 | 0.03–0.20 | Suavizado EMA a 30fps; se normaliza por fps en runtime |
| `DEADZONE_PCT` | 0.25 | 0.10–0.40 | Zona muerta como fracción de **crop_w** (s12; antes 0.30×source_w) |
| `DETECT_EVERY_N` | 3 | 1–5 | Frecuencia de detección (fotogramas entre llamadas a MediaPipe) |
| `GATE_ANCLA_PCT` | 0.15 | 0.10–0.20 | Radio del ancla estática por track (s13; antes FACE_GATE_PCT=0.20 de última pos) |
| `PUNCH_ZOOM` | 1.12 | 1.08–1.18 | Factor de zoom punch-in (112% = crop 11% más estrecho) |
| `PUNCH_TRANS_FRAMES` | 4 | 2–8 | Fotogramas de rampa entrada/salida del punch-in |

**Constantes eliminadas en sesión 12:** `FACE_LOST_PATIENCE=30` (fijo, asumía 30fps),
`RECENTER_ALPHA=0.05` (flujo de recentrado eliminado), `FACE_LOST_PATIENCE_S=1.0` (declarada
pero nunca consumida — eliminada como letra muerta).

**Constante renombrada en sesión 13:** `FACE_GATE_PCT=0.20` (gate de última posición)
→ `GATE_ANCLA_PCT=0.15` (gate de ancla estática — ver corrección de ancla abajo).

### Deadzone — corrección sesión 12

```
deadzone_w = DEADZONE_PCT × crop_w   (ej. ~152px para crop_w=607px en fuente 1080p)
```

**Bug original:** `deadzone_w = 0.30 × source_w = 576px` (half = 288px). Para source_w=1920 el borde
del crop está a sólo ~303px del centro. Una cara a 13px del borde del crop quedaba dentro de
tolerancia → cámara aparcada 51/60s en zona vacía (x≈1072, entre dos personas).

**Fix:** `deadzone_w = 0.25 × crop_w ≈ 152px` (half ≈ 76px). Cara a más de 76px del centro del crop
activa el movimiento.

El encuadre solo se mueve si `|face_center_x − crop_center_x| > deadzone_w / 2` (~76px).
Cara quieta dentro de la deadzone = cámara completamente inmóvil.
Este es el **criterio de calidad #1**: si el encuadre tiembla con una persona estática, la fase falla.

### Cara perdida — corrección sesión 12

**Comportamiento anterior (bug):** al superar `FACE_LOST_PATIENCE` frames sin cara, la cámara
iniciaba EMA gradual hacia `source_center_x` (RECENTER_ALPHA). En un podcast de 2 personas,
`source_center_x = 960` = zona vacía entre los hablantes → cámara se iba al espacio vacío.

**Comportamiento corregido:** cara perdida = **HOLD indefinido** en la última posición conocida.
El único `source_center_x` inicial se usa si *nunca* se detectó cara (center-crop directo,
manejado antes de llamar a `manejar_cara_perdida`).

### Gate de ancla estática — corrección sesión 13

**Bug anterior (s12):** gate medía `|new_x - last_known_x| > 20% source_w`. Con referencia
dinámica (última posición conocida), el tracker podía derivar gradualmente de ancla=1362 hasta
x=942 en pasos menores al umbral (trinquete gradual).

**Fix:** ancla estática fija por track = `cara["center_x"]` del escaneo inicial
(`detectar_caras_video`). Cada detección se asigna al track cuya ancla esté más cerca,
solo si la distancia al ancla ≤ `GATE_ANCLA_PCT × source_w`. Referencia NUNCA se mueve.

**Asignación exclusiva:** una detección → un track (el de ancla más cercana dentro del gate).
Implementado como matching greedy (menor distancia primero) para evitar doble asignación.

```
GATE_ANCLA_PCT = 0.15  →  gate = 288px para source_w=1920

Cara 0 (ancla=1362): zona_aceptable = [1074, 1650]
Cara 1 (ancla= 719): zona_aceptable = [431,  1007]
Gap entre zonas: 67px (espacio sin asignar)
```

**Limitación documentada de dominio:** hablante que abandona su radio (se levanta, camina
>288px de su ancla) = cara perdida → HOLD. Aceptable para clips ≤100s de conversación
en cámara fija. Para eventos de movimiento amplio, aumentar `GATE_ANCLA_PCT` o redefinir
el ancla manualmente en `_turnos.json`.

**Solapamiento residual — nota historica:** la zona aceptable del track [1074,1650] se
solapa 26px con el rango [900-1100]. El cruce C2xCARA de sesion 14 confirmo que en el
100% de frames donde la camara entra en esa zona hay una cara a <=20px: no es drift.
El criterio C2 fue REEMPLAZADO por C2v2 (decision del arquitecto, sesion 14).

### Alpha EMA normalizado por FPS — corregido sesión 14

```
alpha_eff = 1 - (1 - EMA_ALPHA)^(30 / fps)   [CORRECTO — sesion 14]
```

Sesiones 12-13 usaban `^(fps/30)` (invertido): a 60fps daba alpha=0.154 (camara 3.8x
mas reactiva que el valor tuneado). La formula correcta mantiene tau constante en
segundos (~0.41s) para cualquier fps.

| fps | alpha_eff correcto | tau real |
|-----|--------------------|----------|
| 24  | 0.0990 | 0.42s |
| 30  | 0.0800 | 0.42s |
| 60  | 0.0408 | 0.41s |

`EMA_ALPHA = 0.08` es la referencia a 30fps. Con la correccion, a 60fps alpha=0.041 en
lugar de 0.154. Esto produce una camara mas suave — C1 cae a 94.9% en noturnos (bajo el
umbral 95%): retune pendiente de decision del arquitecto (sesion 14).

### Punch-in — detalle

Al frame correspondiente al inicio de una keyword del brain:
- La ventana de crop se estrecha: `punch_crop_w = crop_w // PUNCH_ZOOM`
- Rampa de entrada: interpolación lineal de `crop_w → punch_crop_w` en `PUNCH_TRANS_FRAMES` frames
- Rampa de salida: interpolación inversa al terminar la keyword
- El centro del punch-in = center_x de la cara (no el centro del frame)
- Activación: opt-in con flag `--punch-in` (desactivado por default — ver PREGUNTAS #14)

---

## §3 Pipeline de suavizado completo

```
Frames del video (OpenCV)
         │
         ▼ (cada DETECT_EVERY_N frames)
MediaPipe face detection ──► face_center_x o None  (diccionario sparso {frame_idx: float})
         │
         ▼ interpolar_detecciones(sparsa, total_frames)
Lista [float | None] por frame   (lineal entre detecciones; None en extremos sin datos)
         │
         ▼ manejar_cara_perdida(raw, source_center_x)
Lista [float] por frame
  └── hold en ultima posicion conocida (indefinido — s12 elimino patience y RECENTER_ALPHA)
         │
         ▼ aplicar_deadzone_secuencia(face_centers, deadzone_w)
Lista de targets [float]   (el target solo cambia si la cara sale de la zona muerta)
         │
         ▼ ema_smooth(targets, EMA_ALPHA)
Lista smooth [float]   (la posición de cámara efectiva)
         │
         ▼ calcular_ventana_crop(smooth_x, source_w, source_h) — por frame
Lista de (x, y, w, h) por frame
         │
         ▼ _aplicar_punch_ins(crop_frames, brain_data, fps)   [si --punch-in]
Lista final de (x, y, w, h) con w variable en keywords
         │
         ▼ OpenCV crop + resize (1080×1920) → pipe stdin FFmpeg
output/clips/{stem}_9x16.mp4
```

---

## §4 Manejo de casos borde

| Caso | Comportamiento | Log explícito |
|------|---------------|---------------|
| Cara perdida (cualquier duración) | Hold en última posición conocida indefinidamente | — |
| Sin caras en todo el video | Center-crop (`x = source_w//2 − crop_w//2`) sin fallar | `"no se detectaron caras — center-crop aplicado"` |
| 2+ caras, sin turnos | **WARNING** + render con cara principal (sesion 11: ya no es error) | `"N caras -- cara principal; asigna turnos para conmutar"` |
| 2+ caras, con turnos | Conmutacion real con CORTE SECO en frame exacto de cada t_ini | `"N caras con turnos -- conmutacion activada (M turnos)"` |
| Bbox parcialmente fuera de frame | Clamp del bbox a (0, source_w) antes del cálculo | — |
| Clip sin `{clip}_brain.json` (para punch-ins) | Llamar brain UNA vez y persistir junto al clip | `"brain generado"` o `"brain reutilizado"` |
| Punch-in sin keywords en brain | Reframe normal sin punch-ins (no falla) | — |
| Corte entre hablantes (multi-cara) | CORTE SECO en el frame exacto de `t_ini` del nuevo turno | — |

---

## §5 Formato del archivo de turnos

**Ruta:** `transcripts/{stem}_turnos.json`

```json
{
  "version": 1,
  "fuente": "videolargo_clip1_corto.mp4",
  "caras": [
    {
      "id": 0,
      "thumb": "thumbs/videolargo_clip1_corto_cara0.jpg",
      "primera_vez_s": 0.33
    },
    {
      "id": 1,
      "thumb": "thumbs/videolargo_clip1_corto_cara1.jpg",
      "primera_vez_s": 1.0
    }
  ],
  "turnos": [
    {"t_ini": 0.0, "t_fin": 12.5, "cara_id": 0},
    {"t_ini": 12.5, "t_fin": 28.0, "cara_id": 1}
  ]
}
```

**Semántica:**
- `caras`: detectadas en el muestreo inicial (primeros `muestra_frames=30` fotogramas)
- `turnos`: intervalos de tiempo asignados a cada cara, sin solapamiento, cubren el clip completo
- Frame sin turno asignado → `cara_id=0` (fallback; se loguea explícitamente)
- Transición entre turnos: **CORTE SECO** en el frame exacto del `t_ini` del nuevo turno

**Cuándo se crea:**
- 1 cara detectada: no se crea (pipeline automático completo)
- 2+ caras: requerido antes de renderizar; el Studio guía su creación
- Si el usuario no asigna turnos con 2+ caras: fallo accionable, no fallback silencioso

---

## §6 UI de turnos en el Studio (mínimo viable)

Panel en la pestaña **Clips** (existente), sección "Reencuadrar 9:16":

**Caso: 1 cara detectada**
```
[✓ 1 hablante detectado — reencuadre automático]
[Botón: Generar 9:16]
```

**Caso: 2+ caras detectadas**
```
Caras detectadas:
  [🖼 Cara A]   [🖼 Cara B]

Asignar turnos:
  t_ini   t_fin   Hablante
  0:00    0:12    [Cara A ▾]
  0:12    0:28    [Cara B ▾]
  [+ Añadir turno]

[Guardar turnos] → persiste _turnos.json → habilita [Generar 9:16]
```

- Los thumbnails se extraen del primer frame donde aparece cada cara
- Si el usuario pulsa "Generar 9:16" sin guardar turnos habiendo 2+ caras: aviso en rojo
- Validación mínima: los turnos no deben solaparse; el gap entre turnos (si hay) usa cara_id=0

---

## §7 Estructura de módulos

```
reframe.py          (≤400L)  Orquestación + CLI  [estado: sesion 11]
  Constantes: TRANSCRIPTS_DIR, THUMBS_DIR, SUFFIX_9X16, OUTPUT_W/H, etc.
  reframe_clip(input_path, output_path, turnos, brain_data, punch_in) → dict
  detectar_caras_video(video_path, muestra_frames) → list[dict]   [usa detectar_todas_caras_frame]
  extraer_thumb_cara(frame, bbox, out_path) → Path
  _detectar_trayectoria(video_path, total_frames) → dict[int, float]
  _detectar_trayectorias_multi(video_path, total_frames, caras) → dict[int, dict[int, float]]
  _calcular_crops(input_path, caras, turnos_list, fps, total_frames, src_w, src_h) → list
  renderizar_reframe(input_path, crop_frames, output_path, fps, has_audio) → float
  _cargar_o_generar_brain(clip_path) → dict | None
  CLI: python reframe.py {clip.mp4} [--layout tracking|stack] [--turnos ...] [--punch-in]
  Stack: reframe_stack_clip + renderizar_stack (sesion 17)

reframe_track.py    Deteccion + matematicas puras  [estado: sesion 17]
  Constantes: EMA_ALPHA, DEADZONE_PCT, DETECT_EVERY_N, FACE_MIN_CONFIDENCE, etc.
  calcular_ventana_crop(face_center_x, source_w, source_h) → (x, y, w, h)
  ema_smooth(positions, alpha) → list[float]
  aplicar_deadzone(face_x, current_target, deadzone_w) → float
  aplicar_deadzone_secuencia(face_centers, deadzone_w) → list[float]
  interpolar_detecciones(sparsa, total_frames) → list[float | None]
  manejar_cara_perdida(raw_centers, patience, source_center_x) → list[float]
  cara_en_frame(frame_idx, fps, turnos) → int
  calcular_crops_por_turnos(sparsa_multi, turnos_list, fps, total_frames, ...) → list  [sesion 11]
  detectar_cara_frame(frame, detector) → dict | None
  detectar_todas_caras_frame(frame, detector) → list[dict]  [sesion 11]
```

**Criterio de división:** todo lo que sea matemáticas puras (sin I/O, sin OpenCV, sin MediaPipe
en import-time) vive en `reframe_track.py` y es testeable sin video. Todo lo que toca archivos,
procesos externos o hardware vive en `reframe.py` y es stub hasta la sesión de implementación.

---

## §8 Audio — verificación de preservación

El reframe **no toca el audio**. El comando FFmpeg del §1 usa `-map 1:a -c:a copy` tomando el
audio del clip fuente (segundo `-i`). El stream de audio ya fue copiado sin re-encode por el
clipper en F4 (`-c:a copy`).

**Verificación en DoD:**
```powershell
ffprobe -v error -show_entries stream=codec_name,duration -select_streams a -of csv output\clips\clip_9x16.mp4
# Debe mostrar: codec_name y duración idéntica al source
```

---

## §9 Dependencia nueva

```
mediapipe==0.10.35
```

Detector de caras en CPU sin torch — coherente con gotcha #6 (torch NO está instalado en el venv).
Versión diseñada: 0.10.14 (no disponible en pip). Versión instalada real: **0.10.35**.
Ver PREGUNTAS #18 para detalle del cambio de API (Solutions → Tasks API).

```powershell
.\venv\Scripts\pip install "mediapipe>=0.10.0"
# Instala 0.10.35 (la más reciente disponible)
```

**IMPORTANTE:** 0.10.x eliminó `mp.solutions.face_detection`. Se usa la Tasks API:
```python
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision
# Modelo: models/blaze_face_short_range.tflite (descargado automáticamente en primera ejecución)
```

---

## §10 DoD de implementación (para la sesión siguiente)

1. `python reframe.py output/clips/clip.mp4` genera `output/clips/clip_9x16.mp4`
2. Encuadre sigue al hablante sin temblor visible: EMA + deadzone funcionando
3. Con 2+ caras: fallo accionable si no hay `_turnos.json`; reencuadre correcto si los hay
4. Audio intacto: misma duración, mismo codec (`ffprobe` verifica)
5. Sin caras: center-crop + log explícito (no falla)
6. Con `--punch-in`: zoom visible en frames de keywords vs sin flag
7. `revision/fase-4.1/REFRAME_REPORT.md` con frames comparativos (16:9 vs 9:16)
8. `check.bat` verde (incluye los tests de contrato de reframe)
9. Smoke test `caption.py` intacto

---

## Decisiones delegadas al diseñador (resueltas en esta sesión)

Todas las decisiones de los §1–§9 fueron tomadas en esta sesión de diseño con justificación.
Las PREGUNTAS #14–#17 quedan abiertas para el arquitecto antes de implementar.

---

## §8 Modo Stack (F4.2-LITE, sesion 17)

Alternativa al face tracking para podcasts N=2/3. Crops ESTATICOS calculados una vez del
scan inicial, apilados verticalmente en 1080x1920. Sin EMA, sin turnos, sin hold.

### Geometria de bandas

```
N=2 -> banda 1080x960 por cara
  crop_w = src_h * (1080/960) = src_h * 1.125
  ejemplo 1920x1080: crop_w=1215px, max_x=705px

N=3 -> banda 1080x640 por cara
  crop_w = src_h * (1080/640) = src_h * 1.6875
  ejemplo 1920x1080: crop_w=1822px, max_x=98px

Escalado: INTER_AREA si crop_w > 1080, INTER_LANCZOS4 si crop_w < 1080
Orden vertical: izquierda->derecha segun center_x de cada ancla
Los crops PUEDEN solaparse en la fuente: correcto por diseno.
```

### N=1 o N>=4

Error: "stack requiere 2-3 caras detectadas; usa el modo seguimiento"

### Validacion podcast_test_60s 1920x1080 (sesion 17)

| Criterio | Valor |
|----------|-------|
| Resolucion output | 1080x1920 |
| pix_fmt | yuv420p |
| Audio | AAC 60.01s |
| C-STACK cara_0 crop=[705,1920] | 934/934 = 100% |
| C-STACK cara_1 crop=[111,1326] | 165/165 = 100% |
| Render | 39.1s |
