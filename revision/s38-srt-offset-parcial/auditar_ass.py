"""auditar_ass.py — Invariantes D1-D3 sobre el .ass REALMENTE generado (S38-v2).

No mide el modelo intermedio: parsea el .ass de salida, que es lo que ve el reproductor.
K rechazo la v1 por defectos que solo se ven ahi.

Comprueba:
  D1  desviacion del arranque de cada cue: primer evento del grupo vs `group["start"]`
  D2  eventos por debajo del minimo (default 150 ms)
  D3  solapes entre eventos consecutivos y eventos duplicados
  +   % del tramo con caption en pantalla

Importable (`auditar(groups, ass_path)`) y ejecutable. Sin red, sin GPU.
"""

from __future__ import annotations

import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pysubs2  # noqa: E402


def _eventos(ass_path: Path) -> list[tuple[int, int, str]]:
    """(start_ms, end_ms, texto_plano) de cada Dialogue, en orden temporal."""
    subs = pysubs2.load(str(ass_path), encoding="utf-8-sig")
    evs = [(e.start, e.end, e.plaintext.strip()) for e in subs.events if not e.is_comment]
    evs.sort(key=lambda x: (x[0], x[1]))
    return evs


# El formato ASS guarda los tiempos en CENTISEGUNDOS: la rejilla es de 10 ms y un valor del
# modelo se redondea hasta 5 ms. Es un suelo del formato, no un defecto del reparto, asi que
# el desvio de arranque se mide contra esta tolerancia. El desvio EXACTO (que debe ser 0) se
# mide sobre el modelo en `medir_cobertura_real.py`.
TOLERANCIA_ASS_MS = 5


def auditar(groups: list[dict], ass_path: Path, min_evento_ms: int = 150) -> dict:
    """Informe de invariantes. `groups` es lo que se paso a `core.build_ass`."""
    evs = _eventos(ass_path)
    cortos = [e for e in evs if e[1] - e[0] < min_evento_ms]
    solapes = [(a, b) for a, b in zip(evs, evs[1:], strict=False) if b[0] < a[1]]
    dupes = [k for k, n in collections.Counter((s, e, t) for s, e, t in evs).items() if n > 1]

    # D1: por cada grupo, el primer evento que arranca dentro de su ventana.
    desvios = []
    for g in groups:
        gi_ms = int(round(g["start"] * 1000))
        gf_ms = int(round(g["end"] * 1000))
        dentro = [e for e in evs if gi_ms - 20 <= e[0] < gf_ms]
        if dentro:
            desvios.append(min(e[0] for e in dentro) - gi_ms)

    # Cobertura de pantalla: union de intervalos (los eventos pueden solaparse).
    union, fin = 0, None
    ini = None
    for s, e, _t in evs:
        if ini is None:
            ini, fin = s, e
        elif s <= fin:
            fin = max(fin, e)
        else:
            union += fin - ini
            ini, fin = s, e
    if ini is not None:
        union += fin - ini
    span = (evs[-1][1] - evs[0][0]) if evs else 0

    return {
        "n_eventos": len(evs),
        "eventos_bajo_minimo": len(cortos),
        "min_dur_ms": min((e[1] - e[0] for e in evs), default=0),
        "solapes": len(solapes),
        "duplicados": len(dupes),
        "desvio_arranque_max_ms": max((abs(d) for d in desvios), default=0),
        "desvio_arranque_no_cero": sum(1 for d in desvios if abs(d) > TOLERANCIA_ASS_MS),
        "cues_medidos": len(desvios),
        "pantalla_pct": round(100 * union / span, 1) if span else 0.0,
    }


def imprimir(informe: dict, etiqueta: str = "") -> bool:
    """Imprime el informe. Devuelve True si TODAS las invariantes se cumplen."""
    ok = (
        informe["eventos_bajo_minimo"] == 0
        and informe["solapes"] == 0
        and informe["duplicados"] == 0
        and informe["desvio_arranque_no_cero"] == 0
    )
    print(f"== Invariantes del ASS {etiqueta} ==")
    print(f"  eventos                    {informe['n_eventos']}")
    print(f"  bajo el minimo (150 ms)    {informe['eventos_bajo_minimo']}  (debe ser 0)")
    print(f"  duracion minima real       {informe['min_dur_ms']} ms")
    print(f"  solapes                    {informe['solapes']}  (debe ser 0)")
    print(f"  duplicados                 {informe['duplicados']}  (debe ser 0)")
    print(
        f"  desvio de arranque         {informe['desvio_arranque_no_cero']}"
        f"/{informe['cues_medidos']} cues fuera de +-{TOLERANCIA_ASS_MS} ms"
        f" (rejilla ASS), max {informe['desvio_arranque_max_ms']} ms  (debe ser 0)"
    )
    print(f"  pantalla con caption       {informe['pantalla_pct']}%")
    print(f"  VEREDICTO: {'INVARIANTES OK' if ok else 'INVARIANTES ROTAS'}")
    return ok


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("uso: auditar_ass.py <archivo.ass>")
        raise SystemExit(2)
    inf = auditar([], Path(sys.argv[1]))
    raise SystemExit(0 if imprimir(inf, Path(sys.argv[1]).name) else 1)
