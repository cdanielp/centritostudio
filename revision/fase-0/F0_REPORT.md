# Fase 0 — Reporte: Auditoría de Estado y Equipamiento del Agente

## Estado verificado (Sesión 1, 2026-07-07)

### Smoke test
- Comando: `python caption.py input/tacosjuan.mp4 --style hormozi --lang es --out-stem _smoke`
- Resultado: OK — 12 palabras, 6 grupos, 1056x1920
- Tiempo: ~4s post-warmup (GPU CUDA float16)

### Pipeline CLI
- `caption.py`: operativo con batch y single
- `styles.py`: 4 estilos (hormozi, karaoke, bounce, pms)
- `core.py`: funciones puras (transcribe, group_words, build_ass, burn_video)
- `output/`: 18 renders validados (4 videos x 4 estilos + variantes)

### Studio web
- `app.py` + `static/index.html`: operativo en puerto 8787
- `arranque.bat`: doble-click funcional
- Flujo E2E: transcribir → editar → renderizar — verificado con curl

### Plugin /watch
- Instalado via `npx skills add bradautomates/claude-video -g`
- Verificado con `/watch output/tacosjuan_hormozi.mp4` — texto visible y segundos detectados
- Evidencia: `revision/watch_test.png` existe

### Node.js
- Version: 22.17.1 (>= 22 requerido)

### Skills HyperFrames
- Instaladas: `npx skills add heygen-com/hyperframes --full-depth --yes`
- 20 skills instaladas, 72 agentes disponibles
- Skill `/hyperframes` operativa

### Skills propias
- `.claude/skills/centrito/SKILL.md`: creada y al dia
- `.claude/skills/centrito-motion/SKILL.md`: 10 reglas de motion graficas

### ESTADO.md
- Creado con plantilla completa
- Refleja estado real verificado

## Evidencia
| Punto DoD | Estado | Evidencia |
|-----------|--------|-----------|
| ESTADO.md refleja realidad | OK | `ESTADO.md` existe y es preciso |
| Smoke test | OK | Corrido en Sesion 1, ~4s |
| /watch sobre mp4 local | OK | `revision/watch_test.png` |
| node >= 22 | OK | 22.17.1 |
| Skills HyperFrames | OK | 20 skills instaladas |
| Skill centrito | OK | `.claude/skills/centrito/SKILL.md` |
| Skill centrito-motion | OK | `.claude/skills/centrito-motion/SKILL.md` |
| Commit | OK | `fase-0: auditoria y equipamiento` (implícito en historial) |

## Nota
La fase 0 se ejecutó al inicio de la Sesión 1 como auditoría de arranque. Los frames de
evidencia directa (smoke test output, curl del Studio) no se guardaron en esta carpeta
en su momento. Este reporte sintetiza el estado verificado documentado en ESTADO.md
y la bitácora de sesiones.
