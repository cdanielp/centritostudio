# SMOKE FX — S36-FX (capa local de efectos FFmpeg)

Capa FX local **opcional** sobre FFmpeg que aplica efectos visuales ANTES del quemado
ASS (para no deformar los captions). Apagada por default: con `fx_preset=None` el render
histórico sigue byte-idéntico (fijado por test de contrato).

## Comando usado

```powershell
$env:PYTHONIOENCODING="utf-8"
.\venv\Scripts\python caption.py output/clips/mariosoto_clip1_corto_9x16.mp4 `
    --style hormozi --lang es --fx premium
```

- **Clip fuente:** `output/clips/mariosoto_clip1_corto_9x16.mp4` (1080x1920, 30 fps, 38.65s, voz humana en podcast).
- **Preset:** `premium` (= pro + outro) → punch-in + flash + scanner + logo/outro.
- **Datos:** plan derivado de `transcripts/mariosoto_clip1_corto_9x16.brain.json` (rama `brain`, no fallback).
- **Salida:** `output/mariosoto_clip1_corto_9x16_hormozi_fx-premium.mp4` (privado, NO commiteado).
- **Tiempo de render:** ~11.6s (transcript reutilizado).

## Efectos generados (log del pipeline)

```
[fx] premium (brain): 7 punch, 8 flash, 4 scanner
```

- **7 punch-in** desde `kw_ts` del brain (zoom 1.10, ~0.9s, easing `sin()` no lineal, vía `zoompan`).
- **8 flash** blancos en fronteras de segmento (0.14s, alpha 0.70, `drawbox` blanco a pantalla completa).
- **4 scanner** rojos en énfasis (0.6s, barrido vertical escalonado de 8 barras `drawbox` rojas).
- **1 logo/outro** centrado en los últimos 2.5s (PNG real vía capa de overlays `core_overlays`).

## Nota técnica (decisiones de implementación forzadas por FFmpeg 8.0)

- **Punch-in = `zoompan`** (no `crop:eval=frame`: el `crop` de FFmpeg 8.0 no acepta `eval`;
  `w/h` no animan por frame). `zoompan` con `fps` = fps REAL de la fuente + `d=1` mantiene
  el audio en sync (verificado: 1666 frames de audio idénticos fuente vs render).
- **Scanner = barrido escalonado** de N barras estáticas: `drawbox` NO evalúa `y` por frame
  (no tiene `eval=frame` en FFmpeg 8.0), así que el barrido se compone con `SCANNER_STEPS`
  barras estáticas, cada una en su sub-ventana temporal. Verificado en fondo sintético
  (barra en filas 0 → 814 → 1628 conforme avanza el tiempo).

## Logo placeholder

`assets/marca/logo.png` es un **PLACEHOLDER** (rectángulo morado #7C3AED generado con Pillow,
texto "PMS placeholder"). El logo real (M2) lo aporta K; la capa lo toma automáticamente
del primer `.png` de `assets/marca/`. Nunca se genera el logo con IA (guardrail S36-FX).

## Frames revisados (verificación visual, MAESTRO regla #7)

| Frame | t (s) | Qué prueba | Resultado |
|---|---|---|---|
| `00_fuente_sin_fx_t8.png` | 8.0 | baseline: fuente sin FX | referencia |
| `01_antes_punch_t4p5.png` | 4.5 | fuera de ventana: sin efecto | encuadre normal |
| `02_flash_t2p5.png` | 2.5 | flash blanco | overlay blanco a pantalla completa OK |
| `03_punch_t5p95.png` | 5.95 | punch-in (pico del zoom) | encuadre CERRADO vs baseline OK |
| `04_scanner_t15p05.png` | 15.05 | scanner rojo (medio) | barra roja horizontal nítida OK |
| `04b_scanner_t15p3.png` | 15.3 | scanner rojo (abajo) | barra más abajo → barre OK |
| `05_outro_logo_t37p5.png` | 37.5 | logo/outro | PNG morado real centrado OK |
| `06_captions_ok_t8.png` | 8.0 | captions no deformadas | captions nítidas, posición normal |

**Captions intactas:** en TODOS los frames los captions hormozi (keyword amarilla, uppercase)
se ven nítidos y en su posición; el FX se quema ANTES del `ass`, no lo deforma.

**Audio intacto:** `ffprobe` fuente vs render FX → `aac, 38.650000, 1666` idéntico (`-c:a copy`).

## Hallazgos del revisor (regla #14)

**Veredicto: APROBADO — 0 bloqueantes.** Verificó pureza de `fx.py` (solo json/dataclasses/
pathlib/core_overlays, cero whisper/LLM/subprocess), ruta sin FX byte-idéntica, captions no
deformadas (ass sobre `[vfx]`), audio `-map 0:a -c:a copy` intacto, fail-open en
`_resolver_plan_fx`/`cargar_brain_fx`, escape correcto de comas FFmpeg dentro de comillas
simples, prints ASCII-safe, y contrato de `core` no roto.

**Riesgos NO bloqueantes anotados:**
- (a) `zoompan` con `d=1` + `fps` de la fuente re-temporiza el video; con material VFR o
  `r_frame_rate` promediado (p.ej. 29.97 real) podría haber micro-desfase A/V en clips largos.
  Deuda: smoke A/V con material 29.97 antes de exponer a testers. (Este smoke fue 30/1 exacto.)
- (b) El revisor no re-generó el render FFmpeg de punta a punta; confió en las capturas de
  `revision/s36-fx/` (que sí verifiqué con ojos).
- (c) Re-correr el mismo preset sobrescribe el output sin aviso (consistente con el resto del
  pipeline, no regresión).
- (d) FX es CLI-only por ahora (`jobs.py`/Studio no lo exponen) — consistente con precedentes
  `--popups` (s31) y marcado manual (s32); deuda para la sesión de Studio.

## Veredicto

FX opcional funcionando de punta a punta sobre clip real: 4 efectos verificados con ojos,
captions no deformadas, audio bit-a-bit intacto, ruta histórica byte-idéntica con
`fx_preset=None`. **370 tests verdes**, `check.bat` verde. Listo para el ojo de K sobre el
MP4 en movimiento (el barrido del scanner y el rebote del punch-in solo se juzgan en video).
