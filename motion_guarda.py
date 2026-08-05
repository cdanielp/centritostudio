"""motion_guarda.py — Contraste entre lo que el modelo escribe y lo que de verdad se dijo.

La primera version de este modulo trataba todos los campos igual y se equivoco en los dos
sentidos a la vez. El caso que la motivo resulto ser al reves de lo que parecia: el audio dice
DESERCION, Whisper transcribio DECEPCION, el modelo escribio lo correcto y la guarda lo tumbo.
Y "Saludos", "Presentacion" o "Forzar" tampoco eran alucinaciones: eran un titular abstrayendo,
que es exactamente lo que se le pide.

De ahi el reparto por TIPO de campo, que es lo unico que hace util a la guarda:

- CIFRA de `dato_destacado`: ESTRICTO. Un numero en pantalla que nadie dijo es un dato falso, y
  no hay redaccion que lo justifique. Si no esta en la transcripcion, ese campo cae a reglas.
- NOMBRES PROPIOS: TOLERANTE. Si la palabra se parece a alguna de la transcripcion (distancia
  de edicion corta, sin acentos ni mayusculas), se acepta: es una correccion de Whisper, no un
  invento. Solo se marca lo que no se parece a nada.
- CUALQUIER OTRO CAMPO: solo se REGISTRA. Un titular tiene derecho a usar una palabra que
  resume lo dicho sin repetirlo, y el editor existe: K es la ultima guarda, no este modulo.

Tambien vive aqui el contraste entre piezas del MISMO clip, que es el otro modo de fallar del
modelo: dos letreros diciendo lo mismo con otras palabras.

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
# Cuantas ediciones puede haber entre un nombre propio escrito y uno transcrito para seguir
# siendo el mismo. Con 2 caben "Garcia"/"Garzia" y "desercion"/"decepcion", que es justo el
# error tipico de un transcriptor; con mas empezarian a colarse palabras distintas.
DISTANCIA_MAXIMA = 2
# Cuantas palabras significativas seguidas tienen que compartir dos letreros para considerarlos
# el mismo. Con dos saltarian coincidencias normales del castellano; con tres ya es la misma
# frase dicha dos veces.
SECUENCIA_MINIMA = 3

_PALABRA = re.compile(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+")
_NUMERO = re.compile(r"\d+(?:[.,]\d+)?")
_DECIMAL_PARTIDO = re.compile(r"(\d)\s+([.,])\s*(\d)")


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


def _distancia(a: str, b: str, tope: int = DISTANCIA_MAXIMA) -> int:
    """Distancia de edicion entre dos palabras ya normalizadas, cortada en `tope`.

    Cortar no es una optimizacion cosmetica: aqui se compara cada palabra sospechosa contra
    TODO el vocabulario del clip, y sin el corte una transcripcion larga se nota.
    """
    if abs(len(a) - len(b)) > tope:
        return tope + 1
    previa = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        actual = [i]
        for j, cb in enumerate(b, start=1):
            actual.append(min(previa[j] + 1, actual[j - 1] + 1, previa[j - 1] + (ca != cb)))
        if min(actual) > tope:
            return tope + 1
        previa = actual
    return previa[-1]


def _se_parece(palabra: str, vocabulario: set[str]) -> bool:
    """True si alguna palabra de lo dicho esta a distancia de edicion corta. TOLERANTE."""
    base = normalizar(palabra)
    return any(_distancia(base, v) <= DISTANCIA_MAXIMA for v in vocabulario)


def _es_nombre_propio(palabra: str, posicion: int) -> bool:
    """Mayuscula inicial y no es la primera palabra del letrero.

    No hay etiquetador de partes de la oracion y no hace falta uno: en un titular, una palabra
    capitalizada a mitad de frase es un nombre propio o es un error, y las dos cosas se tratan
    igual de bien con la tolerancia de edicion.
    """
    return posicion > 0 and palabra[:1].isupper()


def cifra_dicha(cifra: str, hablado: str, *, clip: str = "") -> bool:
    """ESTRICTO. El numero tiene que haberse pronunciado. PURO.

    Es el unico campo donde la transcripcion manda sin discusion: un titular puede abstraer,
    pero un numero en pantalla que nadie pronuncio es un dato inventado.

    Se acepta por dos vias, y cada una mira donde tiene sentido:

    - Los DIGITOS aparecen tal cual en el clip ("10.5" en "en un 10.5 por ciento"). Se busca en
      todo el clip a proposito: un numero dicho en el segundo tres y mostrado en el cuarenta
      sigue siendo un numero que se dijo, y donde va la pieza lo decide `motion_plan`, no esto.
      La coma y el punto se unifican porque el transcriptor no es coherente con el decimal.
    - `hablado` trae la cantidad EN PALABRAS ("diez y medio por ciento"). Aqui si se exige el
      tramo, porque un numeral suelto en cualquier parte del clip no avala nada. Sin esta via
      se perderia lo que motivo pedirle los textos al modelo: la regla exige unidad literal
      detras del numero y por eso `dato_destacado` solo salia en 4 de 34 clips.

    Los numerales salen de `cve_keywords.NUMERALES`, que ya existe. Ninguna lista nueva.
    """
    if not (cifra or "").strip():
        return True  # sin cifra no hay nada que contrastar

    def _numeros(fuente: str) -> set[str]:
        # El transcriptor parte el decimal: escribe "10 .5 %" donde se dijo "diez punto cinco
        # por ciento". Sin recomponerlo, la cifra correcta del clip que motivo todo esto caia al
        # respaldo por un espacio. Es ruido del transcriptor, no una regla de espanol.
        junto = _DECIMAL_PARTIDO.sub(r"\1\2\3", fuente or "")
        return {n.replace(",", ".") for n in _NUMERO.findall(junto)}

    numeros = _numeros(cifra)
    if not numeros:
        return revisar(cifra, clip or hablado).ok  # sin digitos ("la mitad") es texto normal
    if numeros <= _numeros(clip or hablado):
        return True
    import cve_keywords  # noqa: PLC0415

    return any(normalizar(p) in cve_keywords.NUMERALES for p in _PALABRA.findall(hablado or ""))


def _hay_que_revisar(palabra: str, *, es_propio: bool = False) -> bool:
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
    if es_propio:
        # Una palabra capitalizada a mitad de titular no es un verbo, diga lo que diga el
        # detector: sin esta salida, "Villahermosa" se descartaba por terminar en vocal y un
        # nombre propio inventado no llegaba nunca a registrarse.
        return True
    return not motion_plan._es_verbo_probable(palabra)


def revisar(texto: str, transcripcion: str) -> Veredicto:
    """Sustantivos del texto generado que NO se dijeron en el clip. PURO.

    `transcripcion` tiene que ser la del CLIP ENTERO, no el fragmento donde va el letrero: un
    letrero puede y debe usar una palabra que se dijo treinta segundos antes. Contrastar contra
    el fragmento convertia la guarda en ruido, marcando como inventada media frase legitima.

    Un NOMBRE PROPIO parecido a algo dicho se acepta sin marcarlo: quien se equivoco casi
    siempre es el transcriptor, y tumbar el texto correcto por eso es el peor de los dos fallos.
    """
    if not (texto or "").strip():
        return Veredicto()
    vocabulario = _vocabulario(transcripcion)
    if not vocabulario:
        return Veredicto()  # sin transcripcion no hay contra que contrastar: fail-open
    sospechosas = []
    for posicion, palabra in enumerate(_PALABRA.findall(texto)):
        propio = _es_nombre_propio(palabra, posicion)
        if not _hay_que_revisar(palabra, es_propio=propio):
            continue
        if _se_dijo(palabra, vocabulario):
            continue
        if propio and _se_parece(palabra, vocabulario):
            continue
        sospechosas.append(palabra)
    # Se conserva el orden de aparicion y se quitan repetidas, para que el log no cante la misma
    # palabra cinco veces.
    vistas: list[str] = []
    for palabra in sospechosas:
        if palabra not in vistas:
            vistas.append(palabra)
    return Veredicto(tuple(vistas))


def _significativas(texto: str) -> list[str]:
    """Palabras con contenido del letrero, normalizadas y en orden. PURO.

    Se quitan las vacias con `stopwords_es`, que ya existe. Sin eso, "de futuro y" contaria como
    secuencia compartida y cualquier par de letreros pareceria el mismo.
    """
    import stopwords_es as sw  # noqa: PLC0415

    palabras = [normalizar(p) for p in _PALABRA.findall(texto or "")]
    return [p for p in palabras if p and p not in sw.STOPWORDS_ES]


def secuencia_compartida(texto_a: str, texto_b: str, minimo: int = SECUENCIA_MINIMA) -> tuple:
    """La secuencia de palabras significativas mas larga que comparten dos letreros. PURO.

    Vacia si no llegan al minimo. Es el detector de la otra forma de fallar del modelo: dos
    piezas del mismo clip diciendo lo mismo, que en pantalla se lee como un error de montaje.
    """
    a, b = _significativas(texto_a), _significativas(texto_b)
    if len(a) < minimo or len(b) < minimo:
        return ()
    mejor: tuple = ()
    for largo in range(minimo, len(a) + 1):
        comunes = _ventanas(a, largo) & _ventanas(b, largo)
        if not comunes:
            break
        mejor = sorted(comunes)[0]
    return mejor


def _ventanas(palabras: list[str], largo: int) -> set[tuple]:
    if largo > len(palabras):
        return set()
    return {tuple(palabras[i : i + largo]) for i in range(len(palabras) - largo + 1)}


__all__ = [
    "DISTANCIA_MAXIMA",
    "LARGO_MINIMO",
    "RAIZ_MINIMA",
    "SECUENCIA_MINIMA",
    "Veredicto",
    "cifra_dicha",
    "normalizar",
    "revisar",
    "secuencia_compartida",
]
