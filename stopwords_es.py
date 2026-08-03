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

_AMPLIACION = frozenset(
    # Pronombres personales y posesivos que faltaban
    "yo el ella ello nosotros nosotras vosotros ustedes ellos ellas usted "
    "conmigo contigo consigo nuestro nuestra nuestros nuestras tus mis "
    # Preposiciones y locuciones
    "sin sobre bajo entre hasta desde hacia durante tras segun ante contra "
    "mediante salvo excepto incluso ademas tambien tampoco "
    # Verbos auxiliares y copulativos (formas frecuentes)
    "soy eres somos sois eran fueron fuiste fuimos sea sean seria serian "
    "estoy estas estamos estan estaba estaban estuvo estuve estado "
    "haber habia habian hubo haya hayan hemos has habre habria "
    "tener tiene tienen tengo tienes tenemos tenia tenian tuvo tuve "
    "hacer hace hacen hago haces hacemos hicieron hizo hecho "
    "poder puede pueden puedo puedes podemos podia podian pudo pude "
    "decir dice dicen digo dices dijo dijeron dicho "
    "ir ira iba iban fui vamos vaya "
    # Demostrativos, indefinidos y cuantificadores
    "aquel aquella aquellos aquellas estos estas esos esas "
    "algo alguien alguno alguna algunos algunas cualquier cualquiera "
    "otro otra otros otras mismo misma mismos mismas cada cual cuales "
    "quien quienes cuanto cuanta cuantos cuantas tanto tanta tantos tantas "
    "poco poca pocos pocas mucho mucha muchos muchas demasiado bastante "
    # Adverbios de lugar, tiempo y modo sin carga semantica
    "aqui ahi alli alla aca arriba abajo adelante atras cerca lejos "
    "luego despues antes siempre casi apenas solo solamente asi aun todavia "
    "mientras quiza quizas acaso tal "
    # Conectores y muletillas de habla espontanea (transcripciones reales)
    "pues bueno osea digamos verdad claro obvio "
    "cosa cosas gente forma manera vez veces parte lado tipo".split()
)

STOPWORDS_ES = STOPWORDS_BASE | _AMPLIACION


def es_stopword(palabra: str, *, ampliada: bool = False) -> bool:
    """True si la palabra es vacia. `ampliada=False` = lista historica (ruta clasica)."""
    return normalizar(palabra) in (STOPWORDS_ES if ampliada else STOPWORDS_BASE)


__all__ = ["STOPWORDS_BASE", "STOPWORDS_ES", "es_stopword", "normalizar"]
