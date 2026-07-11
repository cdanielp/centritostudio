# DEMO s29+s30 — caption_viral_engine: 4 presets sobre el clip videolargo

**Clip fuente:** `output/clips/videolargo_clip1_largo_9x16.mp4` (grabación de pantalla,
67.8s, 1080x1920). Transcript y brain.json reutilizados (cero re-transcripción, cero LLM).

## Videos (K juzga EN MOVIMIENTO — los MP4 son el entregable)

| Preset | Video | Qué mirar |
|---|---|---|
| clean_podcast | `output/videolargo_clip1_largo_9x16_clean_podcast.mp4` | sobrio, minúsculas, sin pop, palabra activa dorada. Sin keywords (modo off) |
| viral_bounce | `output/videolargo_clip1_largo_9x16_viral_bounce.mp4` | hormozi suave 1.08 + rebote (default final D20); 13 keywords del brain en verde-lima 122% |
| keyword_punch | `output/videolargo_clip1_largo_9x16_keyword_punch.mp4` | 13 keywords (brain + reglas R1-R7) GRANDES al 145% con GLOW verde-lima; el resto igual a hormozi |
| karaoke_highlight (s30) | `output/videolargo_clip1_largo_9x16_karaoke_highlight.mp4` | karaoke moderno: la palabra dicha se LLENA de cian al hablarse, las YA dichas quedan cian, las siguientes en blanco base (fix: SecondaryColour=primario; antes salían rojas) |

## Frames de evidencia (verificados con ojos, regla 7)

- `A_18.9s_{preset}.png` — mismo instante en los 3 presets: grupo "RECUERDAS NUESTRA
  CARPETA DE OUTPUT" con keyword `carpeta` (kw_ts=18.7 del brain).
  - clean_podcast: minúsculas blancas, "carpeta" dorada discreta. OK sobrio.
  - viral_bounce: "CARPETA" verde-lima al 122% estándar. OK.
  - keyword_punch: "CARPETA" al 145% con halo glow — claramente dominante. OK.
- `B_2.0s_keyword_punch.png` — "NUESTRA KIT YA / TIENE LOS CUSTOM": "KIT" grande con
  glow, legible sobre fondo oscuro de la UI. OK.
- `A_18.9s_karaoke_highlight.png` (s30) — "recuerdas nuestra / carpeta de output":
  dichas en cian, activa llenándose. OK.
- `B_6.2s_karaoke_highlight.png` (s30) — "notes que nos / salió en rojo": "notes que nos
  salió" cian (dichas), "en" activa, "rojo" blanco base (futura). Verificado con ojos
  ANTES y DESPUÉS del fix de SecondaryColour: antes las futuras salían ROJAS (default
  pysubs2 con \kf), después salen en base como exige el spec. OK.

## Evidencia Studio (s30)

- `../s30_studio/studio_dropdown_presets.png` — pestaña Render con el dropdown "Preset
  viral (motor CVE)" expandido: 4 presets + "Sin preset", poblados desde /api/presets
  (labels del API, nada hardcodeado). Karaoke Highlight seleccionado.
- `../s30_studio/api_presets.json` — respuesta cruda del endpoint (usa_brain por preset
  para el pre-check de la UI).
- `../s30_studio/_cdp_screenshot.py` — script CDP con el que se capturó (reutilizable
  para futuros smokes del Studio).

## Datos técnicos verificados

- keyword_punch .ass: **250 eventos** (179 de texto + 71 gemelos de glow en capa 0,
  solo en los 13 grupos con keyword). Tags verificados: `\bord7\blur5\3c&H47FF00&\fscx145`.
- viral_bounce y clean_podcast: **179 eventos** (un evento por palabra, capa única) —
  la ruta sin glow no cambia la estructura del ASS.
- Densidad: 13 keywords / 33 grupos = 39.4% (cap 40% del engine respetado).
- Render ~7s por preset (transcript reutilizado).
- El fit de safe zones no degradó ninguna keyword en este clip (todas caben a 145).

## Nota para K

El rebote y el glow se juzgan en movimiento. El punch de la palabra clave re-popea al
activarse (sube al pico y asienta al 145%); si se siente excesivo, `--intensidad clean`
lo baja a 130% sin glow, y `minimal` lo apaga del todo.
