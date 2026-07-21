# NVENC — Inventario de codificación de video (fase GPU pre-HyperFrames)

Base exacta: `b59989f11a8a77cc8925ca066e7aaf1e8908a855` (merge PR #27, cierre H3).

Inventario de **toda** operación FFmpeg/ffprobe del pipeline, clasificada por su relación con la
codificación H.264. Objetivo de la fase: mover a NVIDIA NVENC **solo la codificación de video**
(las categorías 2 y 3), preservando byte-idéntico todo lo demás (filtros, audio, mapeo,
resolución, FPS, atomicidad, tracking, detección facial, Whisper).

## Clasificación

1. Solo análisis (sin encoding).
2. Encoding H.264 compatible con NVENC.
3. Filtros CPU + encoding compatible con NVENC.
4. No compatible / no conveniente en esta fase.
5. Audio únicamente.
6. Fuera de alcance.

## Tabla de operaciones

| Archivo | Función | Comando actual (resumen) | Códec vídeo | Preset | Audio | NVENC posible | Riesgo A/V | Decisión |
|---|---|---|---|---|---|---|---|---|
| `depurador.py` | `_run_edl` | `-filter_complex trim/concat` → encode | libx264 | medium/crf18 | `-c:a aac -b:a 128k` | **Sí (cat 3)** | Medio (crossfade audio intacto) | **Integrado** (auto/nvenc/cpu + fallback + atómico + telemetría) |
| `depurador.py` | `_probe_duration` | `ffprobe -show_format` | — | — | — | No (cat 1) | — | Sin cambios |
| `depurador.py` | `_volume_at` | `ffmpeg volumedetect -vn` | — | — | análisis | No (cat 1/5) | — | Sin cambios |
| `core_ass.py` | `burn_video` | `-vf ass=...` → encode | libx264 | medium/crf18 | `-c:a copy` | **Sí (cat 3)** | Medio (filtro ass + atómico) | **Integrado** (selección + fallback, atómico intacto) |
| `core_ass.py` | `burn_video_with_emojis` | vía `core_overlays.construir_comando` | libx264 | medium/crf18 | `-c:a copy` (solo `0:a`) | **Sí (cat 3)** | Alto (overlays/FX/b-roll) | **Integrado** (inyecta `video_args`; CPU byte-idéntico) |
| `core_ass.py` | `extract_thumb` | `-vframes 1 -vf scale` | mjpeg (PNG) | — | — | No (cat 4) | — | Sin cambios (miniatura, no vídeo) |
| `core_overlays.py` | `construir_comando` | constructor puro FFmpeg | libx264 | medium/crf18 | `-c:a copy` | **Sí (cat 3)** | Alto (orden overlays) | **Integrado** (`video_args=None` → histórico byte-idéntico) |
| `reframe.py` | `renderizar_reframe` (tracking) | pipe rawvideo bgr24 → encode | libx264 | fast/crf18 | `-c:a copy` | **Sí (cat 3)** | Alto (pipe OpenCV, faststart) | **Integrado + ATÓMICO** (selección FAST; cada intento a temporal único en `.render_tmp`, verify + `os.replace`; fallback re-pipe a otro temporal; pix_fmt sin duplicar) |
| `reframe.py` | `renderizar_stack` (stack) | pipe rawvideo bgr24 → encode | libx264 | fast/crf18 | `-c:a copy` | **Sí (cat 3)** | Alto (pipe OpenCV, faststart) | **Integrado + ATÓMICO** (mismo contrato que tracking vía `media_integrity.publicar_si_ok`) |
| `reframe.py` | detección de cortes (`scdet`) | `-vf scdet -f null` | — | — | — | No (cat 1) | — | Sin cambios |
| `clipper.py` | `_cortar` | `depurador.run_edl` (1 segmento) | — hereda — | — | — | **Sí (hereda cat 3)** | Medio | **Cubierto** por `run_edl` (no se duplica); snapshot por job |
| `auto.py` / `auto_v2.py` | `procesar_clip_*` | `core.burn_video_with_emojis` | — hereda — | — | — | **Sí (hereda cat 3)** | Alto | **Cubierto**; snapshot inmutable por job Auto |
| `caption.py` | CLI `burn_*` | `core.burn_video*` | — hereda — | — | — | Sí (hereda) | — | **Cubierto** (usa el default del proceso) |
| `media_integrity.py` | `_ffprobe` / `verificar_video` | `ffprobe -show_streams` | — | — | — | No (cat 1) | — | Sin cambios (validación) |
| `system_preflight.py` | checks de entorno | `ffmpeg -version`, `which` | — | — | — | No (cat 1) | — | Sin cambios |
| `submagic.py` | render nube | API remota (upload) | — | — | — | No (cat 6) | — | Remoto: **el upload no codifica local** |
| `jobs._reframe_para_submagic` | pre-reframe local opcional | `reframe.reframe_clip` (horizontal→9:16) antes del upload | — hereda reframe — | fast/crf18 | `-c:a copy` | **Sí (hereda cat 3)** | Alto | **Cubierto**: con `reframe=true` sobre video horizontal HAY encode local (NVENC/CPU). Guard **condicional** en el endpoint (solo si habrá encode local) + snapshot en `run_submagic_render` |
| `broll_*` / `clip_overlay.py` | inputs de overlay | `-loop`, `stream_loop` (entradas) | — | — | audio nunca mapeado | No (cat 6) | — | Sin cambios (entradas del filtro, no encoder) |

## Puntos de codificación H.264 reales (los 4 sitios integrados)

1. **`depurador._run_edl`** — prioridad principal. Depuración de silencios/muletillas.
2. **`core_ass.burn_video`** — captions simples.
3. **`core_overlays.construir_comando`** (vía `burn_video_with_emojis`) — captions con emojis/popups/FX/b-roll.
4. **`reframe._cmd_ffmpeg_pipe`** — reframe tracking/stack (pipe rawvideo).

`clipper`, `Auto` y **Submagic (pre-reframe local)** **no** reimplementan encode: heredan
`depurador.run_edl`, `core.burn_video_with_emojis` y `reframe.reframe_clip`. Cada worker captura
una **instantánea inmutable** del modo (`@video_encoder.con_snapshot`, incluido
`run_submagic_render`) para que un cambio de preferencia a mitad de un job no lo altere.

### Submagic: remoto con pre-reframe local opcional

Submagic es un motor **remoto** (upload a la nube). Con `reframe=true` sobre un video
**horizontal** ejecuta un **reframe LOCAL** (encode) antes del upload; ya vertical o `reframe=false`
→ sube el original sin codificar. Por eso NO se clasifica toda la ruta como "no codifica local".
El endpoint calcula si habrá encode local (`jobs.submagic_hara_encode_local`, predicado puro
compartido con el worker) y **solo entonces** aplica `_guard_encoder` (nvenc explícito sin NVENC →
503 antes del job, sin iniciar upload). Si no habrá encode local, la ruta remota funciona en
auto/cpu/nvenc aunque no haya NVENC.

### Publicación atómica de reframe

`renderizar_reframe` (tracking) y `renderizar_stack` publican **atómicamente** vía
`media_integrity.publicar_si_ok` (fuente única): FFmpeg nunca escribe al nombre final; cada intento
usa un temporal **único** en `.render_tmp` (mismo volumen), se valida con `verificar_video` y solo
tras el éxito se hace `os.replace`. El intento NVENC y el fallback CPU usan temporales distintos;
un intento fallido borra solo su temporal; el final anterior válido se conserva hasta el `replace`
(y sigue intacto si ambos intentos fallan). No quedan temporales ni se publican archivos de 0 bytes.

## No se tocó (byte-idéntico verificado por tests de contrato)

- Tiempos de corte, EDL, `SILENCE_GAP`, `SILENCE_COMPRESS`, `MULETILLA_PAUSE`, `XFADE_S`,
  `_build_filter`, `recalcular_words`, `_eval_joins`.
- Códec/bitrate de audio (`-c:a aac -b:a 128k` en depurador; `-c:a copy` en el resto), mapeo de
  streams, `-movflags +faststart`, resolución (1080x1920), FPS, `-pix_fmt yuv420p`.
- Filtros ass, orden de overlays, FX, tracking, EMA, escenas, stack, detección facial, OpenCV,
  crops, LANCZOS4, Whisper (CUDA de transcripción es independiente de NVENC).
