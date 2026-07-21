# NVENC — Evidencia (fase GPU pre-HyperFrames)

Base: `b59989f11a8a77cc8925ca066e7aaf1e8908a855` (merge PR #27, cierre H3).
Rama: `perf/gpu-nvenc`. Máquina: RTX 5070 Ti, driver 610.62, FFmpeg 8.0 (gyan.dev), Python 3.12.

> Los `.mp4`/reportes JSON de ejecución NO se versionan (se generan bajo
> `output/revision-pre-hyperframes/nvenc/` y en `TemporaryDirectory`). Este `.md` es el resumen.

## 1. Entorno NVENC detectado

```
ffmpeg -hide_banner -encoders | grep nvenc
  V....D h264_nvenc  NVIDIA NVENC H.264 encoder
GPU: NVIDIA GeForce RTX 5070 Ti, driver 610.62
Micro-probe 256x256/1s h264_nvenc p5: rc 0 (funcional)
Nota: NVENC rechaza dimensiones < ~128 px (min-dimension del driver) -> el probe usa 256x256.
```

`video_encoder.detect_nvenc()` → `available=True, reason="ok"`, cacheado por proceso.

## 2. Smoke (`smoke_nvenc.py`)

```
--self-test  : VERDE (7/7)  — detección (encoder ausente / runtime falla / funcional),
               selección (auto→nvenc, auto→cpu) y fallback (una vez, no reintenta input).
--real       : checks=14 blockers=0 fails=0 na=0  — VEREDICTO: PASS
```

Checks reales (RTX de destino):

| # | Check | Resultado |
|---|---|---|
| 1-3 | Detección (sin nvenc / runtime falla / funcional) | PASS |
| 4-5 | auto→NVENC / auto→CPU | PASS |
| 6 | nvenc explícito rechaza antes del job (NVENCUnavailable) | PASS |
| 7 | cpu no usa NVENC | PASS |
| 8 | **depurador NVENC** (h264, aac intacto, integridad) | PASS |
| 9 | **captions NVENC** | PASS |
| 10 | **overlays/emoji NVENC** | PASS |
| 11 | **reframe NVENC** (pipe rawvideo) | PASS |
| 12 | **fallback atómico real** (64×64 → init NVENC falla → CPU, sin residuos) | PASS |
| 13 | A/V dentro de tolerancia (≤50 ms) | PASS |
| 14 | salida sin rutas ni stderr privados | PASS |

## 3. Benchmark (`benchmark_nvenc.py`, fixture mandelbrot 1080p 20s)

| Pipeline | CPU libx264 | NVENC | Speedup | SSIM | ΔA/V | dims/fps | integridad |
|---|---|---|---|---|---|---|---|
| Encode puro | 7.95s | 1.86s | **4.27x** | 0.967 | ≤50 ms | iguales | PASS |
| **Depuración** | 5.06s | 2.01s | **2.52x** | 0.965 | ≤50 ms | iguales | PASS |
| Captions | 7.88s | 1.94s | **4.06x** | 0.967 | ≤50 ms | iguales | PASS |
| Captions + overlay | 6.92s | 2.09s | **3.32x** | 0.994 | ≤50 ms | iguales | PASS |
| Reframe (pipe) | 10.21s | 7.19s | **1.42x** | 0.992 | ≤50 ms | iguales | PASS |

- **speedup ≥ 1.25x** en todos los pipelines (objetivo mínimo cumplido; depuración 2.52x).
- **SSIM ≥ 0.95** en todos (paridad de calidad CPU↔NVENC; no identidad de bytes).
- Δduración ≤ 1 frame / 50 ms; Δinicio A/V ≤ 50 ms; H.264; audio presente; 0 archivos de 0 bytes;
  sin temporales residuales.

### Cuello de botella (reframe 1.42x)

El encode NVENC de reframe es rápido, pero el wall time lo domina la **lectura + resize LANCZOS4
en OpenCV (CPU)** que alimenta el pipe rawvideo — fuera de alcance de esta fase. Aun así supera
1.25x. En un fixture trivial (baja entropía) el speedup de pipeline baja porque libx264 codifica
casi instantáneo; por eso el benchmark usa `mandelbrot` (alta entropía **estructurada**), que
representa mejor el contenido real y a la vez mantiene SSIM alto.

## 4. Correctivo pre-merge (atomicidad reframe + pre-reframe Submagic)

**Reframe atómico** — `renderizar_reframe` (tracking) y `renderizar_stack` publican vía
`media_integrity.publicar_si_ok` (fuente única): FFmpeg escribe a un temporal único en
`.render_tmp`, se valida con `verificar_video` y solo tras el éxito se hace `os.replace`. El
intento NVENC y el fallback CPU usan temporales distintos; un intento fallido borra solo su
temporal; el final anterior válido sobrevive a fallo NVENC y a fallo NVENC+CPU. Sin residuos, sin
0-byte. 13 tests (`test_nvenc_reframe_atomic.py`), sin FFmpeg real. Verificado también en real:
tracking/stack publican y no dejan `.render_tmp`.

**Submagic** — es remoto pero con `reframe=true` sobre horizontal hace reframe LOCAL antes del
upload. Predicado puro compartido `jobs._submagic_reframe_local` (endpoint == worker); guard
**condicional** (`jobs.submagic_hara_encode_local`) y snapshot en `run_submagic_render`. 9 tests
(`test_nvenc_submagic.py`): horizontal+nvenc-no-disp→503 sin upload; horizontal+auto→CPU;
horizontal+nvenc→NVENC; vertical y `reframe=false`→permitido; snapshot inmutable.

## 5. Suite y calidad

- Tests NVENC: `test_nvenc_encoder.py` + `test_nvenc_pipelines.py` + `test_nvenc_reframe_atomic.py`
  (13) + `test_nvenc_submagic.py` (9). Byte-identidad CPU verificada por los tests de contrato.
- Cifras finales de la suite completa, ruff/format/check.bat y smokes H1/H2/H3: ver el body del PR.

## 6. Confirmaciones

- **No** se modificaron algoritmos audiovisuales: EDL, silencios, muletillas, crossfades,
  captions, overlays, tracking, crops, audio, sincronización, resolución, FPS, Whisper, detectores.
- **No** se usaron datos privados (`input/video.srt` intacto; todo lavfi/TemporaryDirectory).
- **H4, H5 y HyperFrames/F7 no iniciados.**
