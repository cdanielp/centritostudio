# S36-B — SRT como fuente oficial de captions + round-trip de clips

Evidencia sintética de la sesión 38. **Todo offline**: sin GPU, sin internet, sin
Whisper/DeepSeek reales. Solo texto SINTÉTICO. Nada generado se versiona.

## Qué demuestra

1. `caption.py VIDEO --srt corregido.srt` usa el **texto del SRT como fuente oficial**;
   Whisper solo aporta **timings** por palabra.
2. Alineación real: `exact_match`, `substitution_match` (1:1 entre anclas reales) y
   **fallback honesto** por cue cuando no hay cobertura (sin karaoke falso).
3. **No se inventan timings** word-by-word: los cues sin cobertura total caen a estático.
4. Round-trip del clipper: `slice_srt` recorta/rebasa el SRT contra el `clip.start` real.
5. El **SRT fuente nunca se modifica**; los derivados son documentos nuevos.

## Cómo correr

```powershell
$env:PYTHONIOENCODING="utf-8"
# 1) crear video + transcript sintéticos (offline)
.\venv\Scripts\python.exe revision\s36-b-srt-caption-roundtrip\gen_fixture.py --create
# 2) render principal + round-trip de clip + verificaciones ffprobe
.\venv\Scripts\python.exe revision\s36-b-srt-caption-roundtrip\smoke_srt_roundtrip.py
# 3) limpiar artefactos generados (nada versionado se toca)
.\venv\Scripts\python.exe revision\s36-b-srt-caption-roundtrip\gen_fixture.py --clean
```

## Fixture (fixtures/corregido_sintetico.srt)

| Cue | Texto SRT (oficial)        | Qué prueba                              | Modo esperado   |
|-----|----------------------------|-----------------------------------------|-----------------|
| 1   | `Hola, mundo.`             | match exacto + puntuación corregida     | word_aligned    |
| 2   | `Esto es una prueba`       | sustitución 1:1 (`prueva`→`prueba`)     | word_aligned    |
| 3   | `El café está listo`       | acentos preservados                     | word_aligned    |
| 4   | `Texto añadido sin audio`  | sin timings reales                      | cue_fallback    |

Resultado del smoke: 4 cues · 3 word-aligned · 1 fallback · cobertura agregada ~0.71.

## ASS generado (extracto real)

```
{\c&H0000D7FF}Hola,{\r} mundo.          <- cue 1, palabra activa por color, timing real
Esto es una {\c&H0000D7FF}prueba{\r}    <- cue 2, "prueba" (SRT) con timing de "prueva"
El café {\c&H0000D7FF}está{\r} listo    <- cue 3, acentos intactos
Texto añadido sin audio                 <- cue 4, UN evento estático, sin animación
```

## Qué NO se versiona

`work/` (mp4/ass/srt derivados), `transcripts/` (words/sidecars), PNGs, logs. Solo se
versionan: los `.srt` sintéticos de `fixtures/`, los scripts y este README/CHECKLIST.

## Alcance

Solo backend/CLI de S36-B. NO toca Studio/UI, Auto v1/v2, batch mapping ni edición de
SRT. Eso es S36-C. Ver `CHECKLIST_VISUAL.md` para el veredicto de K.
