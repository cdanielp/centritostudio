# Evidencia S33 — Caption QA (corrector de transcripción + guion opcional)

**Fecha:** 2026-07-11 · **Sesión:** 33 · **Commits:** f1d37a7 (B2), a71b732 (B3-B6), ce0d827 (B7-B8)

## Caso de validación

Video real (`input/qa_demo_s33.mp4`, copia de tacosjuan 1056x1920) + **transcript
ARTIFICIAL declarado** (`transcripts/qa_demo_s33_words.json`) que simula los 3 dolores
reales reportados por K — se fabrica porque `vocabulario.txt` ya corrige estos casos
al transcribir de verdad, pero el error sigue ocurriendo con términos nuevos:

| Transcrito (mal) | Esperado | Ruta de detección | Confianza | ¿Se aplica en auto_seguro? |
|---|---|---|---|---|
| "confeti UI" | ComfyUI | variante conocida del glosario | alta | SÍ (span de 2 palabras fusionado) |
| "checpoint" | checkpoint | variante del glosario (fuzzy 0.947 también la caza) | alta | SÍ |
| "aflicjo" | archivo | guion: "el guion dice 'archivo' tras '... abrir el'" | media | NO (pendiente de revisión) |

Guion auto-descubierto por convención: `transcripts/qa_demo_s33_guion.txt` (sin `--guion`).

## Renders (3, transcript reutilizado, ~3.1s c/u)

1. `output/qa_demo_s33_sinqa.mp4` — sin flags: comportamiento actual intacto ("CONFETI UI").
2. `output/qa_demo_s33_alertas.mp4` — `--caption-qa` (modo alertas): captions IDÉNTICOS
   al baseline (frame_alertas_confeti_intacto.png) + sidecar de alertas generado.
3. `output/qa_demo_s33_autoseguro.mp4` — `--caption-qa --caption-qa-mode auto_seguro`:
   "COMFYUI" y "CHECKPOINT" quemados; "AFLICJO" sigue (media no se auto-aplica).

## Frames verificados con ojos (regla de oro #7)

- `frame_sinqa_confeti.png` — "Y USAMOS **CONFETI** UI PARA EL RENDER" (baseline).
- `frame_autoseguro_comfyui.png` — "Y USAMOS **COMFYUI** PARA EL RENDER" (corregido,
  la palabra fusionada conserva el highlight de palabra activa y el timing del span).
- `frame_sinqa_checpoint.png` / `frame_autoseguro_checkpoint.png` — "CHECPOINT" → "CHECKPOINT".
- `frame_autoseguro_aflicjo_pendiente.png` — "AFLICJO" visible: la sugerencia media del
  guion NO se aplicó sola (queda en el sidecar como pendiente para revisión humana).
- `frame_alertas_confeti_intacto.png` — modo alertas no modifica el render.

## Sidecar generado (`qa_demo_s33_caption_alerts.json`, copiado aquí)

3 alertas · 2 aplicadas · 1 pendiente. Campos por alerta: timestamp, texto_detectado,
sugerencia, confianza (baja/media/alta), motivo, fuente (glosario/guion/heuristica/
deepseek), aplicar_auto, aplicada, n_palabras.

## Garantías verificadas

- `transcripts/qa_demo_s33_words.json` en disco: **hash md5 idéntico** antes/después de
  los 3 renders (el QA corrige EN MEMORIA; manual futuro gana siempre).
- Timestamps: el span corregido ocupa [s del primer token, e del último]; 20 eventos ASS
  → 19 (fusión), el resto de eventos con el mismo timing.
- Fail-open: 316 tests verdes incluyen QA roto → render con original, DeepSeek caído →
  alertas deterministas intactas, glosario roto → builtins.
- Captions actuales NO rotos: render 1 sin flags idéntico al flujo previo + smoke test.
