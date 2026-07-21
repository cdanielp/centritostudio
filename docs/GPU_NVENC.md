# Codificación de video con NVIDIA NVENC

Esta fase mueve la **codificación H.264** del pipeline de la CPU (`libx264`) a la GPU NVIDIA
(`h264_nvenc`), con **fallback automático a CPU**. Acelera el encode sin cambiar el resultado
audiovisual.

## Qué se acelera y qué NO

| Etapa | Motor | Cambia en esta fase |
|---|---|---|
| Transcripción (Whisper / faster-whisper) | **CUDA** (ctranslate2) | No — ya usaba GPU, es independiente de NVENC |
| **Codificación de video H.264** | **NVIDIA NVENC** o CPU libx264 | **Sí** — esta fase |
| Filtros (ass, trim/concat, overlays, FX) | CPU (libavfilter) | No |
| Reframe: lectura, detección facial, crop, resize LANCZOS4, tracking | CPU (OpenCV) | No |
| Audio | `-c:a copy` / `-c:a aac` intactos | No |

> **CUDA de Whisper ≠ NVENC.** Son dos usos distintos de la GPU: CUDA acelera la *transcripción*
> (cómputo de tensores); NVENC acelera la *codificación de video* (bloque de hardware dedicado
> ASIC en la GPU). Tener uno no implica el otro. **No** afirmamos “todo en GPU”: reframe,
> detección facial, libass y audio siguen en CPU.

## Modos

Configurable en **Ajustes → Codificación de video** (o vía `CENTRITO_VIDEO_ENCODER`):

- **`auto`** (default): usa NVENC si está disponible y funcional; si no, CPU. Nunca falla por
  ausencia de NVENC. Si NVENC no logra *inicializar* a mitad de un encode, cae a CPU **una vez**.
- **`nvenc`**: fuerza NVENC. Si no está disponible, el job se **rechaza con 503 antes de crearse**
  (no cae silenciosamente a CPU).
- **`cpu`**: siempre `libx264`. Argumentos byte-idénticos a los históricos (compatibilidad máxima).

La preferencia de la UI se guarda en `localStorage` y se re-aplica al backend al cargar. El
backend es la **autoridad**: mantiene el modo en memoria y solo afecta a **jobs nuevos** (los
jobs activos conservan su instantánea inmutable). `CENTRITO_VIDEO_ENCODER` define el default
antes de la preferencia de UI; un valor inválido cae a `auto` con aviso local saneado.

## Requisitos

1. GPU NVIDIA con NVENC (Maxwell 2ª gen o superior; probado en RTX 5070 Ti, driver 610.62).
2. Driver NVIDIA funcional.
3. FFmpeg compilado **con** `h264_nvenc` (los builds de gyan.dev / BtbN lo incluyen).

## Cómo comprobar tu entorno

```powershell
# 1) ¿FFmpeg trae el encoder NVENC compilado?
ffmpeg -hide_banner -encoders | Select-String h264_nvenc

# 2) ¿Qué opciones soporta tu build?
ffmpeg -hide_banner -h encoder=h264_nvenc

# 3) Micro-prueba real (256x256, 1s): rc 0 = NVENC funcional
ffmpeg -hide_banner -loglevel error -f lavfi -i color=c=black:s=256x256:d=1:r=30 -an `
  -c:v h264_nvenc -preset p4 -tune hq -rc vbr -cq 18 -b:v 0 -pix_fmt yuv420p prueba.mp4

# 4) Diagnóstico dentro de la app
GET /api/system/video-encoder      # {requested, selected, encoder, nvenc:{available,message}}
GET /api/system/capabilities       # incluye capacidad "nvenc" (su ausencia NO degrada la app)
```

## Detección real (no basta con “hay GPU NVIDIA”)

`video_encoder.detect_nvenc()` distingue cuatro estados y **cachea** el resultado por proceso
(refrescable para tests/diagnóstico):

1. **FFmpeg no instalado** → “FFmpeg no esta instalado.”
2. **FFmpeg sin `h264_nvenc`** → “Esta instalacion de FFmpeg no incluye h264_nvenc.”
3. **`h264_nvenc` listado pero el runtime no inicializa** (driver) → “NVIDIA NVENC esta incluido
   en FFmpeg, pero no pudo inicializarse. Revisa el driver NVIDIA.”
4. **NVENC funcional** → “NVIDIA NVENC disponible.”

El paso 3→4 se decide con un **micro-probe real** (codifica 1s de 256×256 sin audio a un temporal
del sistema, valida returncode + archivo no vacío, limpia siempre). Se usa 256×256 porque NVENC
rechaza dimensiones menores. No requiere `nvidia-smi`, no usa red y no escribe en `input/`/`output/`.

## Parámetros elegidos (validados localmente)

| Perfil | CPU (libx264) | NVENC (h264_nvenc) |
|---|---|---|
| **quality** (depuración, captions, overlays) | `-preset medium -crf 18` | `-preset p5 -tune hq -rc vbr -cq 18 -b:v 0 -pix_fmt yuv420p` |
| **fast** (reframe) | `-crf 18 -preset fast` | `-preset p4 -tune hq -rc vbr -cq 18 -b:v 0 -pix_fmt yuv420p` |

Los argumentos CPU son **byte-idénticos** a los históricos (tests de contrato lo fijan). El audio
(`-c:a aac -b:a 128k` en depurador; `-c:a copy` en el resto), la resolución, el FPS, el mapeo de
streams y `-movflags +faststart` **no cambian**.

## Fallback (solo modo auto)

Si NVENC falla al **inicializar** (driver caído, sesión no disponible, dimensión < mínimo), el
modo `auto` reintenta **una sola vez** en CPU: limpia el parcial NVENC, usa un temporal nuevo,
valida y publica atómicamente (`os.replace`) — un fallo nunca deja el nombre final apuntando a un
parcial, ni borra un final válido anterior. Se marca `fallback_used=true` y se informa: “NVENC no
pudo completar la codificacion; se uso CPU.”

**No** hay fallback ante errores de input/filtro/ASS/EDL/audio: esos también fallarían en CPU, así
que se propagan saneados (sin stderr ni rutas). El modo `nvenc` explícito **nunca** cae a CPU.

### Publicación atómica (depurador, captions, overlays y reframe)

Todas las rutas de encode publican **atómicamente** vía `media_integrity`: FFmpeg escribe a un
temporal único en `.render_tmp` (mismo volumen), se valida con `verificar_video`, y solo tras el
éxito se hace `os.replace` al nombre final. Reframe **tracking y stack** comparten este contrato
(`publicar_si_ok`): el intento NVENC y el fallback CPU usan temporales **distintos**, un intento
fallido borra solo su temporal, y el **final anterior válido se conserva** hasta el `os.replace`
(y sigue intacto si ambos intentos fallan). No quedan temporales ni se publican archivos de 0 bytes.

### Submagic: remoto con pre-reframe local opcional

Submagic edita en la **nube**, pero con `reframe=true` sobre un video **horizontal** hace un
**reframe local** (encode 9:16) antes del upload. El guard de encoder es **condicional**: el
endpoint calcula si habrá encode local y solo entonces exige NVENC en modo `nvenc` explícito (503
antes del job, sin iniciar el upload). Ya vertical o `reframe=false` → sube el original sin
codificar y la ruta remota funciona en cualquier modo. Ese reframe local respeta auto/nvenc/cpu y
usa el snapshot inmutable del job.

## Benchmarks (fixture sintético 1080p 20s, RTX 5070 Ti)

Fixture `mandelbrot` (alto detalle + movimiento, estructurado). CPU `libx264 medium` vs NVENC `p5`:

| Pipeline | CPU | NVENC | Speedup | SSIM CPU/NVENC |
|---|---|---|---|---|
| Encode puro | 7.95s | 1.86s | **4.27x** | 0.967 |
| Depuración | 5.06s | 2.01s | **2.52x** | 0.965 |
| Captions | 7.88s | 1.94s | **4.06x** | 0.967 |
| Captions + overlay | 6.92s | 2.09s | **3.32x** | 0.994 |
| Reframe (pipe) | 10.21s | 7.19s | **1.42x** | 0.992 |

Criterios (todos cumplidos): H.264, audio presente, dimensiones y FPS idénticos, Δduración ≤ 1
frame/50 ms, Δinicio A/V ≤ 50 ms, integridad PASS, SSIM ≥ 0.95, speedup ≥ 1.25x.

> **SSIM** mide *paridad de calidad* CPU↔NVENC, no identidad de bytes (son codificaciones
> distintas). **Reframe** rinde 1.42x porque el cuello de botella es la lectura/resize OpenCV en
> CPU (el encode sí se acelera). En contenido trivial el speedup de pipeline baja porque libx264
> codifica patrones de baja entropía casi instantáneo; sobre contenido real (alta entropía
> estructurada) la ventaja de NVENC es la mostrada arriba.

## Errores habituales

- **“Esta instalacion de FFmpeg no incluye h264_nvenc.”** → tu FFmpeg no trae NVENC compilado.
  Instala un build con NVENC (gyan.dev/BtbN) o usa modo `cpu`.
- **“…no pudo inicializarse. Revisa el driver NVIDIA.”** → el encoder está compilado pero el
  driver/runtime no responde. Actualiza el driver NVIDIA. El modo `auto` seguirá funcionando en CPU.
- **Job rechazado con 503 en modo `nvenc`** → forzaste NVENC sin GPU disponible. Cambia a `auto`
  o `cpu`.

## Limitaciones

- Reframe, detección facial, crops, LANCZOS4, libass, FX y audio siguen en CPU (fuera de alcance).
- El speedup depende del contenido: mayor en encode puro/captions, menor en reframe (I/O CPU).
- Esta fase **no** toca H4/H5 ni HyperFrames/F7.
