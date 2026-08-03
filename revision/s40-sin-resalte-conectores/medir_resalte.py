"""medir_resalte.py — % de resaltes que caen en conector, medido SOBRE EL .ass emitido (S40).

No mide grupos ni intenciones: abre el `.ass` que se quemó y cuenta, evento por evento, cuál
es la palabra ACTIVA (la que lleva el tag inline de resalte) y si es un conector. Es la misma
medición que hizo K a mano, automatizada, para poder repetirla antes y después.

Se reporta contra DOS listas para que la métrica no sea autocomplaciente:

  * `SIN_RESALTE` — la lista que gobierna la supresión. Es la que debe quedar cerca de 0.
  * `STOPWORDS_ES` — la lista ampliada del gate, más grande. Lo que quede aquí y no en la
    primera es el residuo: palabras vacías que SIGUEN recibiendo resalte a propósito.

Uso:
    venv\\Scripts\\python revision\\s40-sin-resalte-conectores\\medir_resalte.py <a.ass> [b.ass ...]
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

import stopwords_es  # noqa: E402

# Un evento de caption resalta UNA palabra: la que va dentro de un bloque con tag inline
# terminado en {\r}. Se captura el tag y el texto visible de ese bloque.
_BLOQUE = re.compile(r"\{([^}]*)\}([^{]+)\{\\r\}")

# Prioridad de atribucion. Un evento puede traer VARIOS bloques con `{\r}`: la palabra activa,
# una keyword persistente (color + escala, sin animacion) y las ya dichas del karaoke. Sin
# prioridad, el primer bloque con `\c&H` gana y en los cues con keyword se atribuye el resalte
# a la palabra equivocada. La activa es, en este orden: la que anima (`\t(`), la que rellena
# (`\kf` con duracion REAL — `\kf0` es el relleno nulo del conector, no un resalte), y solo si
# no hay ninguna, la primera coloreada que no sea una keyword persistente.
_PRIORIDAD = (r"\\t\(", r"\\kf[1-9]", r"\\c&H")

# Keyword persistente: color + escala fija, sin animacion ni relleno. NO es el resalte de la
# palabra activa. Con pop desactivado la keyword ACTIVA tiene esta misma forma y es
# indistinguible: en ese caso el medidor la deja fuera, o sea subcuenta. Los estilos medidos
# aqui (hormozi) llevan pop, asi que la ambigüedad no se da.
_PERSISTENTE = re.compile(r"\\fscx")


def _palabra_activa(linea: str) -> str | None:
    """Texto de la palabra resaltada de un evento Dialogue, o None si no resalta ninguna."""
    if not linea.startswith("Dialogue:"):
        return None
    bloques = _BLOQUE.findall(linea.split(",", 9)[-1])
    for patron in _PRIORIDAD:
        for tag, visible in bloques:
            if not re.search(patron, tag):
                continue
            if patron == r"\\c&H" and _PERSISTENTE.search(tag):
                continue  # keyword persistente, no la palabra activa
            return visible.strip()
    return None


def medir(ass_path: Path) -> dict:
    """Tres lecturas del mismo dato, de la mas estricta con la regla a la mas laxa.

      `pct_conectores`  aplica el MISMO predicado que el render (`es_conector`), que respeta
                        la tilde diacritica: "que" es conector, "qué" no. Es el que debe ir a 0.
      `pct_sin_tilde`   ignora el acento: cuenta "qué" como "que". Es la lectura mas dura y la
                        que probablemente uso la medicion a mano.
      `pct_ampliada`    ignora el acento y usa la lista ampliada completa: incluye los adverbios
                        y muletillas que se dejaron fuera a proposito. Es el residuo.
    """
    activas = [
        p
        for p in (_palabra_activa(ln) for ln in ass_path.read_text(encoding="utf-8").splitlines())
        if p
    ]
    total = len(activas) or 1
    conectores = [p for p in activas if stopwords_es.es_conector(p)]
    sin_tilde = [p for p in activas if stopwords_es.normalizar(p) in stopwords_es.SIN_RESALTE]
    ampliada = [p for p in activas if stopwords_es.normalizar(p) in stopwords_es.STOPWORDS_ES]
    return {
        "archivo": ass_path.name,
        "resaltes": len(activas),
        "conectores": len(conectores),
        "pct_conectores": len(conectores) / total * 100,
        "pct_sin_tilde": len(sin_tilde) / total * 100,
        "pct_ampliada": len(ampliada) / total * 100,
        "top": Counter(stopwords_es.normalizar(p) for p in conectores).most_common(8),
        # Que palabras siguen contando como vacias al ignorar el acento: si son todas formas
        # acentuadas ("QUÉ", "MÁS"), el residuo es correcto y no una fuga de la regla.
        "residuo_sin_tilde": Counter(p for p in sin_tilde if p not in conectores).most_common(8),
    }


def main(argv: list[str]) -> int:
    if not argv:
        print("uso: medir_resalte.py <archivo.ass> [otro.ass ...]")
        return 2
    print(
        f"{'archivo':<40} {'resaltes':>8} {'%regla':>8} {'%sin tilde':>11} {'%ampliada':>10}"
    )
    for arg in argv:
        p = Path(arg)
        if not p.is_file():
            print(f"[X] no existe: {arg}")
            continue
        r = medir(p)
        print(
            f"{r['archivo']:<40} {r['resaltes']:>8} {r['pct_conectores']:>7.1f}% "
            f"{r['pct_sin_tilde']:>10.1f}% {r['pct_ampliada']:>9.1f}%"
        )
        if r["top"]:
            print("    conectores resaltados: " + ", ".join(f"{w}({n})" for w, n in r["top"]))
        if r["residuo_sin_tilde"]:
            print(
                "    solo vacias si se ignora el acento: "
                + ", ".join(f"{w}({n})" for w, n in r["residuo_sin_tilde"])
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
