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
ffmpeg
  -f rawvideo -pix_fmt bgr24 -s 1080x1920 -r {fps} -i pipe:0
  -i {input_video_original}
  -map 0:v -map 1:a
  -c:v libx264 -crf 18 -preset fast
  -c:a copy
  -movflags +faststart
  {output_9x16.mp4}
```

El proceso de Python escribe frames BGR crudos al stdin del proceso FFmpeg. El audio viene del
`-i {input_video_original}` con `-map 1:a -c:a copy` — intacto, sin re-encode.

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

| Constante | Valor inicial | Rango sensato | Descripción |
|-----------|--------------|---------------|-------------|
| `EMA_ALPHA` | 0.08 | 0.03–0.20 | Suavizado EMA: menor = más suave y lento, mayor = más reactivo |
| `DEADZONE_PCT` | 0.30 | 0.15–0.45 | Zona muerta como fracción de source_w |
| `DETECT_EVERY_N` | 3 | 1–5 | Frecuencia de detección (fotogramas entre llamadas a MediaPipe) |
| `FACE_LOST_PATIENCE` | 30 | 15–60 | Fotogramas sin cara antes de iniciar recentrado gradual |
| `PUNCH_ZOOM` | 1.12 | 1.08–1.18 | Factor de zoom punch-in (112% = crop 11% más estrecho) |
| `PUNCH_TRANS_FRAMES` | 4 | 2–8 | Fotogramas de rampa entrada/salida del punch-in |
| `RECENTER_ALPHA` | 0.05 | 0.02–0.10 | EMA hacia centro cuando cara perdida > patience |

### Deadzone — detalle

```
deadzone_w = DEADZONE_PCT × source_w   (ej. 576px para source_w=1920)
```

El encuadre solo se mueve si `|face_center_x − crop_center_x| > deadzone_w / 2` (288px).
Cara quieta dentro de la deadzone = cámara completamente inmóvil.
Este es el **criterio de calidad #1**: si el encuadre tiembla con una persona estática, la fase falla.

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
         ▼ manejar_cara_perdida(raw, patience, source_center_x)
Lista [float] por frame
  ├── ≤ patience: último center_x conocido (cámara quieta)
  └── > patience: EMA gradual hacia source_center_x (RECENTER_ALPHA)
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
| Cara perdida ≤ `FACE_LOST_PATIENCE` frames | Mantener última posición conocida | — |
| Cara perdida > `FACE_LOST_PATIENCE` frames | EMA gradual hacia center-crop | `"cara perdida en frame {n}, recentrando"` |
| Sin caras en todo el video | Center-crop (`x = source_w//2 − crop_w//2`) sin fallar | `"no se detectaron caras — center-crop aplicado"` |
| 2+ caras, sin `{clip}_turnos.json` | Fallo con mensaje accionable (no excepción silenciosa) | `"2 caras detectadas en {clip} — asigna turnos en el Studio"` |
| 3+ caras, con `_turnos.json` | Misma lógica que 2 caras; turnos soporta N caras | `"3 caras detectadas, usando turnos.json"` |
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
reframe.py          (≤400L)  Orquestación + CLI
  Constantes: CLIPS_DIR, TRANSCRIPTS_DIR, THUMBS_DIR, SUFFIX_9X16
  reframe_clip(input_path, output_path, turnos, brain_data, punch_in) → dict
  detectar_caras_video(video_path, muestra_frames) → list[dict]
  extraer_thumb_cara(frame, bbox, out_path) → Path
  cargar_o_crear_turnos(video_path, caras) → tuple[dict | None, bool]
  renderizar_reframe(input_path, crop_frames, output_path, fps) → float
  _cargar_o_generar_brain(clip_path) → dict | None
  CLI: python reframe.py {clip.mp4} [--turnos {turnos.json}] [--punch-in]

reframe_track.py    (≤400L)  Detección + matemáticas puras
  Constantes calibrables: EMA_ALPHA, DEADZONE_PCT, DETECT_EVERY_N, etc.
  calcular_ventana_crop(face_center_x, source_w, source_h) → (x, y, w, h)
  ema_smooth(positions, alpha) → list[float]
  aplicar_deadzone(face_x, current_target, deadzone_w) → float
  aplicar_deadzone_secuencia(face_centers, deadzone_w) → list[float]
  interpolar_detecciones(sparsa, total_frames) → list[float | None]
  manejar_cara_perdida(raw_centers, patience, source_center_x) → list[float]
  detectar_cara_frame(frame, detector) → dict | None  [stub — requiere mediapipe]
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
