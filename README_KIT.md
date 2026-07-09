# CENTRITO KIT — Guardrails para que Sonnet trabaje solo sin hacer spaghetti

Este kit convierte las reglas del proyecto en mecanismos AUTOMÁTICOS. La lógica: lo que está
en CLAUDE.md y skills es una sugerencia que el modelo puede ignorar; lo que está en hooks y
tests es una garantía que no puede esquivar.

## Qué contiene y qué previene cada pieza

| Pieza | Qué previene |
|---|---|
| `.claude/settings.json` (hooks + permisos) | Que termine el turno con lint/tests rotos (hook Stop bloquea), código sin formatear (PostToolUse), lectura del .env y comandos destructivos (deny list) |
| `hooks/gate.bat` | La compuerta: exit 2 devuelve el error al agente y lo obliga a corregir antes de "terminar" |
| `hooks/autoformat.bat` | Formato inconsistente: ruff fix + format tras CADA edición, silencioso |
| `check.bat` | El "¿está sano el proyecto?" en un comando. `check.bat full` agrega smoke render con GPU |
| `ruff.toml` | Spaghetti medible: complejidad máxima 12 por función, imports ordenados, bugs comunes (bugbear) |
| `tests/test_estilos.py` | Regresiones en estilos: corre desde HOY contra styles.py |
| `tests/test_contrato_core.py` | Que la Fase 1 refactorice mal: es el Definition of Done EJECUTABLE de core.py (agrupación por pausas, sin huérfanas, UTF-8, consistencia entre resoluciones). Se salta solo hasta que core.py exista |
| `.claude/agents/revisor.md` | Que quien escribe se califique solo: subagente revisor con checklist de 12 puntos y veredicto APROBADO/CAMBIOS |
| `.claude/commands/revisar.md` | Revisión con un comando: `/revisar objetivo del cambio` |
| `.claude/commands/cerrar-fase.md` | Fases cerradas sin evidencia: `/cerrar-fase 2` exige DoD punto por punto con ruta de archivo |
| `.claude/skills/centrito-dev/SKILL.md` | Decisiones de código inconsistentes: contrato de core.py, límites duros, y los gotchas donde Sonnet YA falló (cp1252, symlinks, escape de rutas ass, BOM, pytest 5) |
| `.claude/skills/centrito-qa/SKILL.md` | El "ya funciona" sin pruebas: protocolo de evidencia + loop de 3 vueltas máximo |

## Instalación (6 pasos, 5 minutos)

1. Descomprime este zip EN LA RAÍZ de `C:\CLAUDECODE\ediciondevideo\` (se fusiona con `.claude/` existente; conserva tus skills previas).
2. Si ya tenías un `.claude/settings.json` propio: fusiona a mano las llaves `hooks` y `permissions` (no lo pises a ciegas).
3. Instala las herramientas en el venv: `venv\Scripts\pip install ruff pytest`
4. Primera corrida: `check.bat` — es normal que ruff marque cosas en el código existente la primera vez; deja que Claude Code las corrija con `venv\Scripts\python -m ruff check --fix .` y `ruff format .`, revisa el diff y commitea como `chore: baseline ruff`.
5. Reinicia Claude Code (los skills/commands/hooks se cargan al iniciar sesión).
6. Prueba: escribe `/revisar baseline del kit` y verifica que lanza el subagente revisor.

## Cambio en el prompt de sesión

Agrega esta línea al mini-prompt de arranque que ya usas con MAESTRO.md:

> Antes de cerrar cualquier fase usa /cerrar-fase N; antes de cualquier commit usa /revisar. El hook Stop es intencional: si te bloquea, corrige lo que reporta.

## Si el gate estorba alguna vez

El hook Stop bloquea el cierre del turno cuando ruff o pytest fallan (y se auto-libera tras 8
bloqueos consecutivos, es el comportamiento de Claude Code). Si algún día necesitas trabajar
con el proyecto roto a propósito, comenta temporalmente el bloque "Stop" de
`.claude/settings.json` — y vuélvelo a poner al terminar. No borres tests para pasar la
compuerta: esa es la única falta grave.
