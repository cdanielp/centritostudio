# B-roll Pexels — CLIP de VIDEO como cutaway (PR B)

Integra un **clip de video** de Pexels como overlay/cutaway temporal dentro del mismo render
FFmpeg, con captions ASS encima, **audio original conservado** y clip **silenciado** (regla #19).
Un solo pase FFmpeg. V1: `fit="cover"`, un único clip por render.

## Arquitectura (aditiva, no rompe nada)

| Archivo | Rol |
|---|---|
| `clip_overlay.py` | Tipo `ClipOverlay` + validación + filtros FFmpeg puros del clip (trim/loop/cover/fade) |
| `broll_video_cutaway.py` | Puente `resolver_cutaway_video_pexels(...)` → `ClipOverlay` (reutiliza el fetcher del PR A) |
| `cve_clips.py` | Adaptador del sidecar `{stem}_popups.json` (`source="pexels_video"`) → clips |
| `core_overlays.py` | `construir_comando(..., clips=None, fps=30.0)` — teje los clips (byte-idéntico sin clips) |
| `core_ass.py` / `caption.py` | `burn_video_with_emojis(clips=...)` + wiring del pipeline |

No se fuerza el video dentro de `Popup` (que es de imagen); `Popup` queda intacto.

## Entrada manual (`{stem}_popups.json`)

Ver `ejemplo_popups.json`:

```json
{ "source": "pexels_video", "query": "snowy mountains vertical video",
  "t": 1.0, "dur": 3.0, "source_start": 0.0, "loop": true, "cutaway": true,
  "fit": "cover", "size_pct": 1.0, "behind_text": true, "mute": true }
```

Compatibilidad: `source="pexels"` sigue siendo imagen; ausente/`local`/`biblioteca` siguen siendo
PNG; renders sin Pexels no requieren API key ni tocan la red.

## Contrato de errores POR CAPAS (D31)

- Puente `resolver_cutaway_video_pexels`: **honesto**, el `ValueError` de contrato (query vacía,
  `t1<=t0`, `source_start<0`, `fit!=cover`, `size_pct`/`loop`/`mute` inválidos) se **propaga**.
- Adaptador `cve_clips`: **captura** ese `ValueError` y omite SOLO esa entrada con log ASCII; el
  resto del archivo (PNG e imagen) se sigue procesando; el render no se derriba.
- Errores operativos de Pexels (cero resultados, timeout, rate limit): omiten solo ese b-roll.
- `RuntimeError/TypeError/AssertionError`: **se propagan**.

## Política de un solo clip (V1)

Máximo UNA entrada `source="pexels_video"` activa por render: se procesa la PRIMERA del JSON; las
demás se omiten con log. Multi-clip queda diferido a un PR posterior.

## FFmpeg (un solo pase)

Clip como input `-i` propio (`-stream_loop -1` si `loop=true`). Cadena del clip:
`trim=start=source_start:duration=ventana` → `setpts` (rebase) → `fps` de la base → `cover`
(`scale=...:force_original_aspect_ratio=increase` + `crop`, sin deformar) → `setsar=1` →
`format=yuva420p` → `fade` alpha → `setpts` (a t0). Overlay centrado con
`eof_action=pass:repeatlast=0:enable='between(t,t0,t1)'`: fuera de la ventana y cuando un clip
`loop=false` corto termina, **vuelve al video original** (no congela). El audio del clip **nunca**
se mapea: la salida mapea solo `[video_final]` + `0:a`. Sin `amix`/`amerge`.

## Tests

`tests/test_contrato_broll_video_cutaway.py`: **39 tests**, todos sin red salvo **un** render real
con clips sintéticos `lavfi` (sin Internet). Total del repo: **577**. Byte-identidad de la ruta sin
clips fijada por el golden de `test_contrato_popups.py`.

## Evidencia real (esta sesión, con API key)

Script: `gen_evidencia.py` (se niega sin key; NUNCA imprime la key). Render de 6s sobre
`input/reel01.mp4` (persona real 672x1248): 0-1s persona, 1-5s clip Pexels cover full-frame con
captions "B-ROLL DE VIDEO PEXELS" / "EL AUDIO ORIGINAL SE CONSERVA" encima, 5-6s persona.

```
fetch          : DESCARGA NUEVA (no cache, no mock)
video_id       : 19906163
file_id        : 8764129
autor          : Lucas Leonel Suárez
duration clip  : 16s
seleccion      : 720x1280 (video 1080x1920)  -> menor variante que cubre el destino 672x1248
render         : pexels_video_cutaway_demo.mp4 (6.0s) en 0.83s
ffprobe salida : 672x1248 | duration=6.000000 | streams: video + audio
```

**Verificación DURA de audio (regla #19):**
```
comando mapea 0:a: True | sin amix/amerge/N:a: True
original (base 6s): codec_name=aac duration=6.000000 nb_read_packets=283
salida            : codec_name=aac duration=6.000000 nb_read_packets=283
IDENTICO (codec/dur/paquetes): True
```

Frames extraídos (los 4 "durante" con **hashes distintos** = movimiento real): `frame_antes.png`
(0.5s), `frame_durante_1..4.png` (1.5/2.5/3.0/4.5s), `frame_despues.png` (5.5s).

**MP4 de 6s en disco (NO commiteado):**
`revision/broll-pexels-video-cutaway/pexels_video_cutaway_demo.mp4`

### Nota honesta sobre la costura del loop (regla #20)

El clip elegido dura **16s**, mayor que la ventana de 4s (1-5s), así que con `source_start=0` el
`trim` toma los primeros 4s y **el clip NO da la vuelta** en este render: la ruta de loop
(`-stream_loop -1`) está activa pero no hay costura visible porque no se agota el clip. Para ver una
costura de loop habría que usar un clip más corto que la ventana o `source_start` cerca del final.
El test sintético `test_render_real_ffmpeg_clip_sintetico` sí ejercita un clip (2s) más corto que la
ventana (1.5s) con `loop=true`.

## Lo que K debe revisar VIENDO EL MP4 COMPLETO (no los frames)

- El clip realmente se mueve y no se congela.
- Que NO deforme la imagen (cover full-frame).
- Los captions quedan encima y legibles sobre el clip.
- El audio sigue siendo el de la persona (verificado arriba, pero confírmalo de oído).
- El clip empieza en 1s y termina en 5s (persona antes y después).
- El clip corresponde a la query ("snowy mountains").
- (Costura del loop: no aplica con este clip de 16s; ver nota arriba.)

Nada de esto se commitea: MP4, clip, `_base.mp4`, `_caption.ass` y frames están en `.gitignore` /
`.git/info/exclude`. Solo `README.md`, `gen_evidencia.py` y `ejemplo_popups.json` van al repo.
