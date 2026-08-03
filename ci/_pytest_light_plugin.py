"""Plugin de pytest para el gate remoto ligero (H5): cero skips es invariante duro.

El subconjunto CI se selecciono para correr COMPLETO, sin red/FFmpeg/GPU/modelos/Node.
Si un test manifestado empieza a saltarse (p. ej. porque una dependencia dejo de estar
o aparecio un `skipif` nuevo), el gate debe ponerse ROJO en lugar de pasar en verde con
la cobertura erosionada silenciosamente. Un skip/xfail/xpass fuerza exit code != 0.
"""

from __future__ import annotations

_OFENSORES = ("skipped", "xfailed", "xpassed")


def pytest_sessionfinish(session, exitstatus):
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is None:
        return
    saltados = sum(len(reporter.stats.get(clave, [])) for clave in _OFENSORES)
    if saltados and session.exitstatus == 0:
        session.exitstatus = 1
