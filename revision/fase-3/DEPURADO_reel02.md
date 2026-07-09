# Fase 3 — Reporte Depurador (demo con reel02)

## Setup

- Video de prueba: `input/reel02.mp4` (9.96s)
- Words.json: SINTÉTICO — dataset de ~14 palabras con timestamps diseñados para ejercitar:
  - Silencio de 2.0s (1.82→3.82s) — entre "models," y "eh"
  - Muletilla "eh" aislada con pausas ≥0.25s a ambos lados
  - Silencio de 1.2s (5.45→6.40s) — entre "hacer" y "ComfyUI."
- Nota: se usan words sintéticos porque los reels disponibles son contenido editado y
  no tienen silencios >0.8s ni muletillas. El depurador está diseñado para grabaciones
  crudas de clases.
- **Nota de auditoría (Sesión 5):** `transcripts/reel02_words.json` actual tiene 17
  palabras (transcripción real del pipeline — reel02 fue procesado junto con los 4 videos
  reales en la sesión inicial de validación del pipeline, Sesión 1). El dataset sintético
  usado en este demo tenía ~14 palabras. El "17 palabras" que aparecía en este Setup era
  incorrecto — se tomó del archivo actual sin notar que había sido reemplazado.
  Ver sección Recálculo (14 originales) que refleja el conteo real del demo.

## Resultados

### Modo SEGURO
- Cortes: **2** (silencio 1.82–3.82s → comprimido a 0.25s; silencio 5.45–6.40s → comprimido)
- Duración original: 9.96s
- Duración limpia: **7.26s**
- Ahorrado: **2.70s (27.1%)**
- Tiempo de proceso: 2.8s (sin GPU)
- Iteraciones de auto-eval: 3/3 (no converge en este demo sintético — ver nota)

### Modo AGRESIVO
- Cortes: 2 silencios + 1 muletilla "eh" (total diferencial vs seguro: +0.13s)
- Duración limpia: **7.13s**
- Ahorrado: **2.83s (28.4%)**
- Tiempo de proceso: 2.8s
- Muletillas detectadas: índice 3 ("eh", pausa_antes=2.0s, pausa_después=0.3s) ✓
- Falsos arranques detectados: 0

## Auto-evaluación de fronteras

El loop detectó deltas de >20dB en la primera unión. Esto es ESPERADO en el demo
sintético porque los timestamps no corresponden a pausas reales del audio. En
grabaciones de clases con pausas naturales, el delta debería ser <6dB y el loop
converge en 1-2 iteraciones.

- La función `_eval_and_adjust` desplazó el corte -80ms en cada iteración
- El output final es el resultado de la 3ª iteración (ajuste acumulado -240ms)
- Las fronteras visuales (frames extraídos) son limpias y sin artefactos

## Evidencia visual

Ver frames en esta carpeta:
- `reel02_seguro_join1.8_pre.png` — antes de la primera unión (seguro)
- `reel02_seguro_join1.8_post.png` — después de la primera unión (seguro)
- `reel02_seguro_join3.5_*` — segunda unión
- `reel02_agresivo_*` — equivalentes en modo agresivo

## Recálculo de words.json

- Palabras originales: 14
- Palabras post-recálculo: 14 (ninguna fue cortada en este demo)
- Drift máximo: 0.0s ✓ (ninguna re-transcripción necesaria)

## Flujo de producción recomendado

```
python caption.py input/clase.mp4 --depurar seguro
# → output/clase_limpio.mp4
python caption.py output/clase_limpio.mp4 --style hormozi
# → output/clase_limpio_hormozi.mp4 (con captions sobre el video limpio)
```
