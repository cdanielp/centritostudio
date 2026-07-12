# S36-FX-B — A/B visual de intensidades FX

A/B para fijar la intensidad de la capa FX. **NO se cambiaron defaults ni `fx.py`**: las 3
variantes salen del **MISMO plan base** (mismos timings: 7 punch, 8 flash, 4 scanner, outro)
variando SOLO intensidad. Script de evidencia: `revision/s36-fx-ab/render_ab.py`.

## Fuente y tramo (idénticos en las 3)

- Clip: `output/clips/mariosoto_clip1_corto_9x16.mp4` (1080x1920, 30 fps, 38.65s, clip completo).
- Captions: hormozi (mismo `.ass` para las 3).
- Plan base: `premium` desde `mariosoto_clip1_corto_9x16.brain.json` (7 punch / 8 flash / 4 scanner / outro).

## MP4 para votar (el voto es sobre el video en movimiento)

| Variante | Archivo | Punch zoom | Flash alpha | Scanner (grosor/pasos) |
|---|---|---|---|---|
| 1 · soft | `revision/s36-fx-ab/ab_1_soft.mp4` | 1.07 | 0.50 | delgado 12px / 12 pasos (suave) |
| 2 · current | `revision/s36-fx-ab/ab_2_current.mp4` | 1.10 | 0.70 | 20px / 8 pasos (actual) |
| 3 · strong | `revision/s36-fx-ab/ab_3_strong.mp4` | 1.12 | 0.83 | grueso 34px / 6 pasos (marcado) |

## Métricas objetivas (apoyo, medidas sobre frames)

| Variante | Flash: brillo medio del frame | Scanner: grosor real de la barra |
|---|---|---|
| soft | 159 / 255 | 12 px |
| current | 195 / 255 | 20 px |
| strong | 218 / 255 | 34 px |

Gradiente monótono confirmado (flash y scanner escalan de soft→strong). El punch (1.07/1.10/1.12)
es sutil por diseño y se juzga mejor en movimiento.

## Tabla de valoración (lectura del revisor sobre frames; el VOTO final es de K sobre los MP4)

| Criterio | 1 · soft | 2 · current | 3 · strong |
|---|---|---|---|
| ¿Punch perceptible? | apenas (sutil) | sí | sí, claro |
| ¿Flash molesta? | no (velo suave) | no (límite cómodo) | puede molestar (casi blanco) |
| ¿Scanner aporta? | sí, discreto | sí | sí, dominante |
| ¿Captions intactas? | **sí** | **sí** | **sí** |
| Sensación general | tirando a **débil** | **limpio** / equilibrado | tirando a **saturado** |

## Frames de apoyo (mismo instante en las 3 variantes)

- Flash (t=2.5): `1_soft_flash_t2p5.png` · `2_current_flash_t2p5.png` · `3_strong_flash_t2p5.png`
- Punch pico (t=5.95): `1_soft_punch_t5p95.png` · `2_current_punch_t5p95.png` · `3_strong_punch_t5p95.png`
- Scanner (t=15.05): `1_soft_scanner_t15p05.png` · `2_current_scanner_t15p05.png` · `3_strong_scanner_t15p05.png`

Verificado con ojos: soft = sutil pero visible; strong = audaz sin romper; captions nítidas y
en su posición en las 3. El barrido del scanner y el rebote del punch SOLO se aprecian en el MP4.

## Pendiente

Voto de K sobre los 3 MP4 → se fijan los defaults (o un intermedio). **Ningún default cambiado
ni commiteado hasta el voto** (instrucción de K).
