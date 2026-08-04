"""motion_guarda.py — El LLM no puede poner en pantalla palabras que nadie dijo.

Las heuristicas nunca inventan: recortan lo que hay. Un modelo si, y el sintoma quedo medido en
la demo 12, donde escribio "La decepcion escolar" sobre un clip que dice DESERCION. Eso no es
un texto flojo, es un texto FALSO, y sale a pantalla completa.

La guarda es un contraste, no un corrector: se sacan las palabras con contenido del texto
generado y se comprueba que cada una se haya dicho de verdad en la transcripcion. Tolera
plural, genero y acentos, porque "traslado" y "traslados" son la misma palabra y exigir la
forma exacta convertiria la guarda en ruido.

PURO: sin red, sin disco, sin reloj. Quien decide que hacer con el veredicto es el llamador.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Sufijos que se prueban al comparar, del mas largo al mas corto. Cubren plural y genero, que
# es lo que cambia entre lo que alguien dice y como lo escribe un letrero.
SUFIJOS = ("es", "s", "as", "os", "a", "o")
# Por debajo de esto no se comprueba: son articulos, preposiciones y conectores, y ademas una
# raiz de tres letras coincide con cualquier cosa.
LARGO_MINIMO = 5
# Cuantos caracteres de raiz tienen que coincidir para dar una palabra por dicha. Con menos, se
# aceptarian parentescos falsos; con mas, se rechazarian derivaciones legitimas.
RAIZ_MINIMA = 5

_PALABRA = re.compile(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+")


@dataclass(frozen=True)
class Veredicto:
    """Resultado del contraste. `sospechosas` vacio es aprobado."""

    sospechosas: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.sospechosas


def normalizar(palabra: str) -> str:
    """Minusculas, sin acentos y sin puntuacion. La enye se conserva como `n`."""
    plano = unicodedata.normalize("NFKD", palabra.lower())
    return "".join(c for c in plano if not unicodedata.combining(c)).replace("ñ", "n")


def _raices(palabra: str) -> set[str]:
    """La palabra normalizada y sus variantes sin sufijo de plural o genero."""
    base = normalizar(palabra)
    formas = {base}
    for sufijo in SUFIJOS:
        if base.endswith(sufijo) and len(base) - len(sufijo) >= RAIZ_MINIMA:
            formas.add(base[: -len(sufijo)])
    return formas


def _vocabulario(fuente: str) -> set[str]:
    """Todas las raices de lo que se dijo. Se calcula una vez por clip."""
    formas: set[str] = set()
    for palabra in _PALABRA.findall(fuente or ""):
        formas |= _raices(palabra)
    return formas


def _se_dijo(palabra: str, vocabulario: set[str]) -> bool:
    """True si alguna raiz de la palabra aparece en lo que se dijo.

    El contraste va en las dos direcciones: la palabra generada puede ser el plural de una
    dicha en singular ("traslados" sobre "traslado") o al reves. Comparar solo en un sentido
    dejaria pasar la mitad de los casos legitimos.
    """
    candidatas = _raices(palabra)
    if candidatas & vocabulario:
        return True
    # Prefijo: "desercion" contra "deserciones", que ningun sufijo de la lista cubre. LAS DOS
    # partes tienen que ser largas: sin exigirselo tambien al vocabulario, un "de" suelto de la
    # transcripcion daba por dicha cualquier palabra que empezara por esas letras, y "decepcion"
    # pasaba la guarda que existe justamente para cazarla.
    largas = [v for v in vocabulario if len(v) >= RAIZ_MINIMA]
    return any(
        len(c) >= RAIZ_MINIMA and any(v.startswith(c) or c.startswith(v) for v in largas)
        for c in candidatas
    )


def _hay_que_revisar(palabra: str) -> bool:
    """True solo para SUSTANTIVOS y NOMBRES PROPIOS, que es donde vive el significado.

    No hay analizador morfologico y no hace falta: basta con descartar lo que seguro no es un
    sustantivo. Los verbos se descartan reusando el detector que ya existe en `motion_plan`, y
    las palabras vacias del espanol reusando `stopwords_es`. Ninguna lista nueva.

    El modelo PUEDE y DEBE reescribir la gramatica: si dice "cuestan" donde el hablante dijo
    "cuesta" no esta inventando nada. Lo que no puede es cambiar "desercion" por "decepcion".
    """
    import motion_plan  # noqa: PLC0415
    import stopwords_es as sw  # noqa: PLC0415

    base = normalizar(palabra)
    if len(base) < LARGO_MINIMO or base.isdigit():
        return False
    if base in sw.STOPWORDS_ES:
        return False
    return not motion_plan._es_verbo_probable(palabra)


def revisar(texto: str, transcripcion: str) -> Veredicto:
    """Sustantivos del texto generado que NO se dijeron en el clip. PURO.

    `transcripcion` tiene que ser la del CLIP ENTERO, no el fragmento donde va el letrero: un
    letrero puede y debe usar una palabra que se dijo treinta segundos antes. Contrastar contra
    el fragmento convertia la guarda en ruido, marcando como inventada media frase legitima.
    """
    if not (texto or "").strip():
        return Veredicto()
    vocabulario = _vocabulario(transcripcion)
    if not vocabulario:
        return Veredicto()  # sin transcripcion no hay contra que contrastar: fail-open
    sospechosas = [
        palabra
        for palabra in _PALABRA.findall(texto)
        if _hay_que_revisar(palabra) and not _se_dijo(palabra, vocabulario)
    ]
    # Se conserva el orden de aparicion y se quitan repetidas, para que el log no cante la misma
    # palabra cinco veces.
    vistas: list[str] = []
    for palabra in sospechosas:
        if palabra not in vistas:
            vistas.append(palabra)
    return Veredicto(tuple(vistas))


__all__ = ["LARGO_MINIMO", "RAIZ_MINIMA", "Veredicto", "normalizar", "revisar"]
