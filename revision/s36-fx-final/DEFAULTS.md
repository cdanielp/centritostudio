# S36-FX — Defaults visuales aprobados (voto final de K, S36-FX-B)

Tras el A/B de intensidades (`revision/s36-fx-ab/`), K fijó estos defaults.

## Valores aprobados

| Efecto | Parámetro | Valor final | ¿Cambió? |
|---|---|---|---|
| Punch-in | `PUNCH_ZOOM` | **1.10** | no (ya era 1.10) |
| Flash | `FLASH_ALPHA` | **0.50** (soft) | **sí** (era 0.70) |
| Scanner | `SCANNER_ALPHA` | **0.70** (current) | no |
| Scanner | `SCANNER_STEPS` | **8** (current) | no |
| Scanner | grosor barra | **20px** (`video_h//90`, current) | no |

**Único cambio de código:** `FLASH_ALPHA` 0.70 → 0.50 en `fx.py`. El resto ya coincidía con
el voto. Corrección de K aplicada: el scanner queda en **current** (20px/8/0.70), NO en soft.

## Smoke final (defaults aplicados)

```powershell
.\venv\Scripts\python caption.py output/clips/mariosoto_clip1_corto_9x16.mp4 `
    --style hormozi --lang es --fx premium
```

- Plan: `premium` desde brain → 7 punch / 8 flash / 4 scanner / outro (~10.6s).
- **Flash brillo medio: 159/255** (= soft, confirmado). **Scanner grosor: 20px** (= current).
- **Audio intacto:** `aac, 38.650000, 1666` frames (`-c:a copy`).
- Captions nítidas y en posición en todos los frames.

## Frames

- `01_flash_soft_t2p5.png` — flash soft (velo suave, no satura)
- `02_punch_t5p95.png` — punch 1.10 (encuadre cerrado)
- `03_scanner_t15p05.png` — scanner current (barra 20px)
- `04_outro_logo_t37p5.png` — logo/outro (PNG real)
- `05_captions_ok_t8.png` — captions intactas

## Nota

- `FLASH_ALPHA=0.50` queda por debajo del rango-guía inicial (0.55-0.85); es la elección
  explícita de K (flash soft) y prevalece sobre la guía advisory.
- No se tocaron frecuencias, UI, Submagic ni motores. Solo el default de `FLASH_ALPHA`.
