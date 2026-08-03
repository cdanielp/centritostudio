"""stopwords_es.py — Palabras vacias del espanol. Modulo hoja: solo stdlib, sin IO.

DOS listas, y la diferencia entre ellas es un contrato, no un detalle:

  * `STOPWORDS_BASE` es la lista HISTORICA del motor de keywords, extraida aqui palabra por
    palabra. `cve_keywords.STOPWORDS` es este mismo objeto. Cambiar un solo termino cambia
    que palabras destaca la ruta clasica de captions, asi que NO se toca: hay un test que
    la compara contra el literal historico.

  * `STOPWORDS_ES` es BASE + ampliacion (pronombres, preposiciones, auxiliares y conectores
    que faltaban). La consume UNICAMENTE el gate de cues parciales (`cve_parciales`). La
    ruta clasica jamas la ve: la byte-identidad de los renders sin `--srt` depende de eso.

La ampliacion NO puede pisar las senales fuertes del motor (numeros, dinero, fechas,
negaciones): esas palabras significan algo aunque sean gramaticalmente vacias. La
invariante se verifica en tests (`test_stopwords_es.py`), no de palabra.
"""

from __future__ import annotations

# Traduccion de acentos usada para comparar contra los sets (no altera texto visible).
_SIN_ACENTOS = str.maketrans("áéíóúü", "aeiouu")


def normalizar(texto: str) -> str:
    """Palabra en minusculas sin puntuacion ni acentos (para comparar contra sets).

    Fuente unica: `cve_keywords._normalizar` es un alias de esta funcion. La logica es la
    historica, movida sin cambiarla.
    """
    return texto.lower().strip(".,!?;:¿¡\"'()").translate(_SIN_ACENTOS)


# ─────────────────────────────────────────────────────────────────────────────
# BASE — historica. Congelada por contrato (ver docstring del modulo).
# ─────────────────────────────────────────────────────────────────────────────

STOPWORDS_BASE = frozenset(
    "el la los las un una unas unos de en que y o a con por para se me te le les "
    "es son fue era ser estar esta este esto esa ese eso al del lo mi tu su sus "
    "como mas muy ya si no nos hay han ha he va van voy vas todo toda todos todas "
    "pero aunque embargo entonces cuando donde porque".split()
)

# ─────────────────────────────────────────────────────────────────────────────
# AMPLIACION — solo para el gate de cues parciales.
# ─────────────────────────────────────────────────────────────────────────────
#
# Criterio de entrada: la palabra no aporta significado por si sola en un caption. Criterio
# de EXCLUSION (por eso no estan aqui): numerales, meses/dias, terminos de dinero y
# negaciones — el motor los trata como senal fuerte y destacarlos es correcto.
# "ahora"/"hoy" son FECHAS; "nunca"/"nadie"/"ninguno" son NEGACIONES: fuera.

# La ampliacion vive en bloques CON NOMBRE porque no todos sirven para lo mismo: el gate de
# cues parciales los usa todos, y el resalte visual (S40) solo los gramaticales. Editar un
# bloque es editar datos: no hay logica escondida en ninguno.

_PRONOMBRES = (
    "yo el ella ello nosotros nosotras vosotros ustedes ellos ellas usted "
    "conmigo contigo consigo nuestro nuestra nuestros nuestras tus mis"
)

_PREPOSICIONES = (
    "sin sobre bajo entre hasta desde hacia durante tras segun ante contra "
    "mediante salvo excepto incluso ademas tambien tampoco"
)

_AUXILIARES = (
    "soy eres somos sois eran fueron fuiste fuimos sea sean seria serian "
    "estoy estas estamos estan estaba estaban estuvo estuve estado "
    "haber habia habian hubo haya hayan hemos has habre habria "
    "tener tiene tienen tengo tienes tenemos tenia tenian tuvo tuve "
    "hacer hace hacen hago haces hacemos hicieron hizo hecho "
    "poder puede pueden puedo puedes podemos podia podian pudo pude "
    "decir dice dicen digo dices dijo dijeron dicho "
    "ir ira iba iban fui vamos vaya"
)

_DEMOSTRATIVOS = (
    "aquel aquella aquellos aquellas estos estas esos esas "
    "algo alguien alguno alguna algunos algunas cualquier cualquiera "
    "otro otra otros otras mismo misma mismos mismas cada cual cuales "
    "quien quienes cuanto cuanta cuantos cuantas tanto tanta tantos tantas "
    "poco poca pocos pocas mucho mucha muchos muchas demasiado bastante"
)

# Adverbios de lugar, tiempo y modo sin carga semantica.
_ADVERBIOS = (
    "aqui ahi alli alla aca arriba abajo adelante atras cerca lejos "
    "luego despues antes siempre casi apenas solo solamente asi aun todavia "
    "mientras quiza quizas acaso tal"
)

# Conectores y muletillas de habla espontanea (transcripciones reales).
_MULETILLAS = "pues bueno osea digamos verdad claro obvio cosa cosas gente forma manera vez veces parte lado tipo"  # noqa: E501

_AMPLIACION = frozenset(
    " ".join(
        (_PRONOMBRES, _PREPOSICIONES, _AUXILIARES, _DEMOSTRATIVOS, _ADVERBIOS, _MULETILLAS)
    ).split()
)

STOPWORDS_ES = STOPWORDS_BASE | _AMPLIACION

# ─────────────────────────────────────────────────────────────────────────────
# SIN_RESALTE (S40) — conectores que NO reciben resalte visual en el caption
# ─────────────────────────────────────────────────────────────────────────────
#
# Esta es la lista que gobierna el render: una palabra activa que caiga aquí se pinta con el
# estilo base (sin color de resalte, sin \kf, sin pop). Es DATO editable: agregar o quitar un
# término aquí cambia el render y nada más.
#
# Solo entra lo GRAMATICAL — artículos, preposiciones, pronombres, auxiliares, demostrativos.
# Quedan deliberadamente FUERA:
#   * `_ADVERBIOS`: "solo", "siempre", "casi" cargan énfasis real en un caption viral
#     ("SOLO hoy"); apagarlos mata ritmo a cambio de poco.
#   * `_MULETILLAS`: "cosa", "gente", "forma" son sustantivos; suprimirlos es una decisión de
#     estilo, no de gramática, y se toma con el render delante.
# El medidor reporta ambos porcentajes (esta lista y la ampliada completa) para que el residuo
# de esos dos bloques sea visible y se decida con números.
SIN_RESALTE = STOPWORDS_BASE | frozenset(
    " ".join((_PRONOMBRES, _PREPOSICIONES, _AUXILIARES, _DEMOSTRATIVOS)).split()
)


def es_stopword(palabra: str, *, ampliada: bool = False) -> bool:
    """True si la palabra es vacia. `ampliada=False` = lista historica (ruta clasica)."""
    return normalizar(palabra) in (STOPWORDS_ES if ampliada else STOPWORDS_BASE)


# Tilde diacritica: el acento es lo UNICO que separa al conector atono de la palabra con
# carga. "que" conecta, "qué" pregunta; "si" condiciona, "sí" afirma; "mas" es un "pero"
# arcaico, "más" es cantidad. `normalizar` borra acentos para comparar contra los sets, asi
# que sin esta lista el resalte se apagaria justo en la version que SI importa.
CON_TILDE_DIACRITICA = frozenset(
    "qué cómo cuál cuáles cuándo cuánto cuánta cuántos cuántas dónde quién quiénes "
    "sí más tú él mí sé té dé aún".split()
)

_PUNTUACION = ".,!?;:¿¡\"'()"


def _sin_puntuacion(texto: str) -> str:
    """Minusculas sin puntuacion pero CONSERVANDO los acentos (para la tilde diacritica)."""
    return texto.lower().strip(_PUNTUACION)


def es_conector(palabra: str) -> bool:
    """True si la palabra NO debe recibir resalte visual (S40). Puro: solo consulta datos.

    La forma ACENTUADA gana: "qué" o "sí" nunca son conectores aunque "que" y "si" lo sean.
    """
    if _sin_puntuacion(palabra) in CON_TILDE_DIACRITICA:
        return False
    return normalizar(palabra) in SIN_RESALTE


__all__ = [
    "CON_TILDE_DIACRITICA",
    "SIN_RESALTE",
    "STOPWORDS_BASE",
    "STOPWORDS_ES",
    "es_conector",
    "es_stopword",
    "normalizar",
]
