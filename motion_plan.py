"""motion_plan.py — Planificador de letreros del Motor B (HF-3, bloque 3).

Decide QUE piezas del catalogo de `motion/` lleva un clip y EN QUE MILISEGUNDO entra cada una.
Es lo que convierte la capa de letreros en algo usable: sin esto habria que escribir a mano un
contrato de pieza por letrero.

DETERMINISTA Y SIN EFECTOS: no hay IA, ni red, ni reloj, ni aleatoriedad. La unica lectura de
disco es el CSV de trayectoria del reframe, y va a traves de `cve.zona_cara_en_rango`, que es
fail-open y ya existia. Dos llamadas con las mismas entradas devuelven exactamente el mismo
plan, y el plan se puede probar entero sin renderizar un solo frame.

El planificador NO pide piezas ni compone video: devuelve datos. Quien los convierte en MOV y
en overlays es `motion_capa`.

Reglas de colocacion (fijadas por K, no se interpretan):

  clip < 6700 ms          solo `hook`, en t=0 (por debajo de eso el cierre no cabe)
  clip de 6700 a 12000    `hook` en t=0 y `cierre` terminando 200 ms antes del final
  clip > 12000 ms         ademas `lower_third` empezando en t=3000
  `dato_destacado`        solo si el clip pasa de 12000 ms y algun tramo trae una cifra
  `titulo_seccion`        rellena los huecos de mas de 20 s en clips de mas de 30 s

Los textos de `hook` y `lower_third` salen de la configuracion y del clipper. Los de `cierre`
y `titulo_seccion` salen de LO QUE SE DICE en el clip: el cierre dejo de repetir el titulo del
hook (manda la llamada a la accion) y el titulo de seccion titula el tramo donde el hablante
cambia de tema. Sigue sin haber IA: los cambios de tema se detectan por PAUSA entre tramos.

Una pieza que no cabe se OMITE con su motivo. Nunca se encima con otra y nunca se le recorta
la duracion: un letrero a medias es peor que ningun letrero.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

# ── Duraciones nativas del catalogo de HF-2 ──────────────────────────────────
# No se leen de `motion/ejemplos/` para que el planificador siga siendo puro; un test fija
# que esta tabla coincide con los ejemplos del catalogo, que son la fuente de verdad.
DURACION_MS = {
    "hook": 2500,
    "lower_third": 4500,
    "titulo_seccion": 2000,
    "dato_destacado": 3000,
    "cierre": 3500,
}

# ── Umbrales temporales ──────────────────────────────────────────────────────
# Umbral del `cierre`. NO es 6000: con 6000 el cierre nunca cabia y se omitia siempre, que es
# justo lo que este numero pretendia evitar. La aritmetica manda:
#   el hook ocupa            [0, 2500]
#   el cierre arranca en     dur - MARGEN_FINAL_MS - DURACION_MS["cierre"] = dur - 3700
#   y necesita               dur - 3700 >= 2500 + SEPARACION_MIN_MS = 3000
#   luego                    dur >= 6700
# Por debajo de 6700 las dos reglas se contradicen y cae el cierre, que tiene menos prioridad.
UMBRAL_CORTO_MS = 6700  # por debajo: solo hook
UMBRAL_LARGO_MS = 12000  # por encima: entran lower_third y dato_destacado
LOWER_THIRD_T0_MS = 3000
MARGEN_FINAL_MS = 200  # el cierre termina esto antes del final del clip
SEPARACION_MIN_MS = 500  # aire minimo entre el fin de una pieza y el inicio de la siguiente

# Relleno de huecos (punto 4.4). En un clip largo, el espectador no puede pasar mas de
# HUECO_MAX_MS sin un solo letrero: hoy el hook y el cierre se comen los extremos y el medio
# queda desnudo. El relleno usa `titulo_seccion`, cuya frase sale de LO QUE SE DICE en ese
# hueco, nunca del titulo del clip.
UMBRAL_RELLENO_MS = 30000  # solo en clips de mas de 30 s
HUECO_MAX_MS = 20000  # sin ninguna pieza durante mas de esto, entra un titulo_seccion
# Pausa entre tramos a partir de la cual se considera que el tema cambia. Es la misma escala
# que usa `core.group_words` para cortar grupos (0.4 s); aqui se pide casi el doble para no
# confundir una respiracion con un cambio de tema.
PAUSA_CAMBIO_TEMA_MS = 700
TITULO_SECCION_MAX_CHARS = 46  # la plantilla pinta una linea; mas texto se sale de la placa
# La pastilla del cierre es un elemento de acento, no un parrafo: si el secundario no cabe en
# una etiqueta corta, deja de parecer una etiqueta.
CIERRE_SECUNDARIO_MAX_CHARS = 28
# Un tramo de subtitulo puede ser tan corto como "Por que?" o "futuro,". Eso es una esquirla de
# la frase, no un titulo: como letrero no dice nada y encima queda raro. Se exige un minimo de
# sustancia y, si el tramo elegido no lo alcanza, se busca otro.
TEXTO_MINIMO_CHARS = 12
# La etiqueta del dato acompana a una cifra grande; con mas texto compite con ella.
DATO_ETIQUETA_MAX_CHARS = 38

# Donde SI se puede cortar una frase sin que suene partida.
PUNTUACION_CLAUSULA = ".,;:!?"
# Conjunciones que abren clausula: cortar JUSTO ANTES de una deja la anterior entera.
CONJUNCIONES = frozenset(
    {"y", "e", "o", "u", "pero", "porque", "aunque", "que", "cuando", "si", "mientras", "pues"}
)
# Ademas de las conjunciones, un fragmento tampoco puede arrancar por preposicion: "de un
# Garcia con una vision" empieza colgando de la frase anterior.
PREPOSICIONES = frozenset(
    {
        "a",
        "ante",
        "bajo",
        "con",
        "contra",
        "de",
        "desde",
        "en",
        "entre",
        "hacia",
        "hasta",
        "para",
        "por",
        "segun",
        "sin",
        "sobre",
        "tras",
        "del",
        "al",
    }
)
ARRANQUE_PROHIBIDO = CONJUNCIONES | PREPOSICIONES

# ── Muletillas (ESPECIFICO DE ESPANOL) ───────────────────────────────────────
# El habla espontanea las mete cada pocas palabras y hoy acaban en pantalla ("yo pues este
# tengo 26 anos"). Se limpian ANTES de medir longitud, para que el hueco que dejan lo ocupe
# texto con contenido en vez de perderse contra el tope de caracteres.
#
# Lista en TOKENS ya normalizados (sin tildes, en minusculas). Las de varias palabras van
# primero en la limpieza, porque "o sea" tiene que morir entero antes de que "sea" se salve.
MULETILLAS_COMPUESTAS = (
    ("ya", "sabes"),
    ("la", "verdad"),
    ("como", "que"),
    ("o", "sea"),
)
MULETILLAS_SIMPLES = frozenset(
    {"pues", "este", "osea", "digamos", "entonces", "bueno", "mira", "eh", "mmm"}
)
# `no` va aparte porque NO se puede quitar del arranque: "no sabemos que paso" sin el `no` dice
# exactamente lo contrario. Solo cuenta como muletilla la coletilla `¿no?`, que va aislada entre
# signos ("...los traslados, no, son carisimos").
MULETILLAS_SOLO_AISLADAS = frozenset({"no"})
# `entonces` es la unica que abre oracion de verdad: con un verbo detras se conserva
# ("entonces bajo la desercion"), y si no, es relleno.
MULETILLAS_CON_EXCEPCION_DE_VERBO = frozenset({"entonces"})
# Los articulos SI pueden abrir un letrero ("La desercion escolar subio") pero NO cerrarlo:
# "las que de la" deja la frase colgando igual que una preposicion.
ARTICULOS = frozenset({"el", "la", "los", "las", "un", "una", "unos", "unas", "lo"})
FINAL_PROHIBIDO = ARRANQUE_PROHIBIDO | ARTICULOS

# Mayor a menor. Cuando dos piezas no pueden convivir, cae la de MENOR prioridad.
PRIORIDAD = ("hook", "cierre", "lower_third", "dato_destacado")

# ── Techo de densidad ────────────────────────────────────────────────────────
# Piezas por minuto que puede llevar un clip. El relleno de huecos itera hasta que ninguno
# pasa de HUECO_MAX_MS y eso, en un clip largo con habla continua, produce una pieza cada 20 s
# ademas de las fijas: se llega a 11 letreros en 77 s, que satura. UN SOLO NUMERO para poder
# subirlo o bajarlo sin tocar nada mas.
MAX_PIEZAS_POR_MINUTO = 5
# `hook`, `lower_third` y `cierre` son la estructura del clip (gancho, quien habla, que hacer):
# nunca se recortan aunque el techo quede por debajo. El techo se cobra de las opcionales.
PIEZAS_PROTEGIDAS = frozenset({"hook", "lower_third", "cierre"})
PIEZAS_OPCIONALES = frozenset({"titulo_seccion", "dato_destacado"})

# ── Restricciones espaciales (medidas en HF-2, D51; no se vuelven a medir) ───
ZONA_CAPTIONS = (0.70, 0.92)  # franja prohibida de diseno, en fraccion del alto
CARRIL_VERTICAL = (0.54, 0.68)  # donde el HTML de las piezas dibuja su contenido en 9:16

# Segunda banda, POR ENCIMA de la cara. Con la cara en `center` (0.40-0.60) o en `bottom`
# (>0.60) el carril de 54-68% queda invadido y antes se omitia la pieza entera; medido sobre
# los clips reales del proyecto, eso dejaba en cero al 61.9% de los verticales.
#
# CONFIRMADO CON RENDER REAL (revision/hf-3/confirmar_banda.py, sobre un clip 1080x1920 con la
# cara en `center`): el hook, que es la pieza mas alta, ocupa nativamente 60.9-68.6% del alto y
# tras el desplazamiento de -653 px cae en 26.9-34.6%. Queda por debajo del 10% de zona segura
# de UI de TikTok/Reels, por encima del borde superior de una cara centrada (una cabeza centrada
# en 0.50 arranca alrededor de 0.35) y muy lejos de la franja de captions (70-92%).
BANDA_SUPERIOR = (0.20, 0.35)
BANDA_CENTRO = "centro"
BANDA_ARRIBA = "superior"

# Cuanto hay que subir la pieza, en fraccion del alto, para llevar su contenido del carril
# nativo a la banda superior. Es negativo: la pieza se compone desplazada hacia arriba.
DESPLAZAMIENTO_SUPERIOR = BANDA_SUPERIOR[0] - CARRIL_VERTICAL[0]

# Buckets de `cve.zona_cara_en_rango` y la banda que dejan libre en 9:16.
BANDA_POR_ZONA_CARA = {
    "top": BANDA_CENTRO,  # cara arriba: el carril nativo esta despejado
    "center": BANDA_ARRIBA,
    "bottom": BANDA_ARRIBA,
}

# SIN dato de cara (CSV ausente, legacy o sin deteccion viva) la pieza va al carril nativo, que
# es el que K aprobo en el gate visual de HF-2 justamente por no pisar caras. Antes se omitia,
# y eso contradecia el fail-open de toda la capa: un dato que falta apagaba la funcion entera en
# vez de degradarla. Ademas dejaba 8 clips derivados en cero PARA SIEMPRE, porque no tienen
# fuente 16:9 y nunca van a tener trayectoria. La falta del dato se registra como INCIDENCIA
# del plan, no como fallo de la pieza.
BANDA_SIN_DATO = BANDA_CENTRO
INCIDENCIA_SIN_DATO_DE_CARA = "sin_dato_de_cara"

ORIENTACIONES = ("vertical", "horizontal")

# ── Deteccion de cifras (ESPECIFICO DE ESPANOL) ──────────────────────────────
# Un numero suelto NO es un dato destacable. "del 2023 al 2024" ponia un 2023 gigante en
# pantalla y "2, grabado." ponia un 2: los dos son numeros de verdad y ninguno es una cifra que
# merezca un letrero. Se exige UNIDAD, porque la unidad es lo que convierte un numero en dato.
_NUMERO = re.compile(r"(?P<moneda>[$€])?\s?(?P<valor>\d+(?:[.,]\d+)*)\s?(?P<pct>%)?")
# Unidades que van DETRAS del numero y lo cualifican. En tokens normalizados.
UNIDADES_POSTERIORES = frozenset(
    {
        "mil", "millon", "millones", "mill", "millardo", "millardos",
        "veces", "vez",
        "hora", "horas", "minuto", "minutos", "segundo", "segundos",
        "dia", "dias", "semana", "semanas", "mes", "meses", "ano", "anos",
        "pesos", "dolares", "euros",
        "km", "kilometros", "metros", "kilos", "gramos",
        "puntos", "grados",
    }
)
# Un ano no es un dato: es una fecha. Se descartan los enteros de cuatro digitos de este rango
# cuando NO llevan unidad pegada, que es justo como aparecen las fechas al hablar.
ANO_MIN, ANO_MAX = 1900, 2100
# Unidades de varias palabras. Se prueban ANTES que las simples: con "20 por ciento", quedarse
# en "por" produce "20 por", que no es ni una cifra ni castellano.
UNIDADES_COMPUESTAS = (("por", "ciento"),)

MOTIVO_FUERA_DE_CLIP = "no_cabe_en_el_clip"
MOTIVO_SIN_AIRE = "sin_separacion_minima"
MOTIVO_SIN_CIFRA = "ningun_tramo_trae_cifra"
MOTIVO_ETIQUETA_SUCIA = "la_cifra_esta_en_un_tramo_que_no_da_etiqueta_limpia"
MOTIVO_TECHO_DENSIDAD = "supera_el_techo_de_piezas_por_minuto"
MOTIVO_CLIP_CORTO = "clip_demasiado_corto"
MOTIVO_SIN_NOMBRE = "sin_nombre_configurado"
MOTIVO_SIN_TITULO = "sin_titulo_del_clipper"
MOTIVO_SIN_HUECO = "sin_hueco_que_rellenar"
MOTIVO_SIN_TRAMO = "sin_tramo_con_texto_en_el_hueco"


@dataclass(frozen=True)
class Tramo:
    """Un tramo de texto del SRT, en milisegundos relativos al inicio del clip."""

    t0_ms: int
    t1_ms: int
    texto: str


@dataclass(frozen=True)
class Pieza:
    """Una pieza colocada: que plantilla, en que ventana, con que textos y en que banda."""

    plantilla: str
    t0_ms: int
    t1_ms: int
    texto: dict[str, str]
    banda: str = BANDA_CENTRO
    # De que tramo del SRT salio su texto, o None si el texto viene de la configuracion. Es lo
    # que permite la regla global de no repetir tramo entre piezas.
    tramo_t0: int | None = None

    @property
    def duracion_ms(self) -> int:
        return self.t1_ms - self.t0_ms


@dataclass(frozen=True)
class Omision:
    """Una pieza que se penso y no se coloco, con el motivo exacto."""

    plantilla: str
    motivo: str
    detalle: str = ""


@dataclass(frozen=True)
class PlanMotion:
    """Resultado del planificador: lo colocado y lo descartado, ambos auditables."""

    orientacion: str
    piezas: tuple[Pieza, ...] = ()
    omisiones: tuple[Omision, ...] = ()
    # Cosas que degradaron el plan sin impedirlo. Una incidencia NO es una omision: la pieza se
    # coloco igual, pero conviene saber con que informacion se decidio donde.
    incidencias: tuple[str, ...] = ()

    @property
    def vacio(self) -> bool:
        return not self.piezas

    def a_dict(self) -> dict:
        return {
            "orientacion": self.orientacion,
            "piezas": [
                {
                    "plantilla": p.plantilla,
                    "t0_ms": p.t0_ms,
                    "t1_ms": p.t1_ms,
                    "texto": dict(p.texto),
                    "banda": p.banda,
                    "tramo_t0": p.tramo_t0,
                }
                for p in self.piezas
            ],
            "omisiones": [
                {"plantilla": o.plantilla, "motivo": o.motivo, "detalle": o.detalle}
                for o in self.omisiones
            ],
            "incidencias": list(self.incidencias),
        }


@dataclass(frozen=True)
class TextosMarca:
    """Textos configurables. Neutros por default: aqui no se inventa copy de marca."""

    titulo: str = ""  # el que ya genera el clipper viral
    kicker: str = ""
    nombre: str = ""
    rol: str = ""
    cta: str = ""


@dataclass
class _Candidata:
    """Pieza en estudio antes de pasar por los filtros.

    `ventanas` son los rangos [desde, hasta] donde la pieza PUEDE arrancar, en orden de
    preferencia. Una ventana y no un instante suelto porque anclar la pieza al milisegundo
    exacto en que empieza un tramo la mataba en cuanto ese instante chocaba con otra pieza,
    aunque el resto del tramo estuviera libre.
    """

    plantilla: str
    ventanas: tuple[tuple[int, int], ...]
    texto: dict[str, str]
    tramo_t0: int | None = None


def _norma(palabra: str) -> str:
    """Token normalizado (minusculas, sin tildes ni puntuacion) para comparar contra los sets.

    `stopwords_es.normalizar` no toca la enye, asi que "anos" se anade aqui: sin esto, "26
    anos" no reconocia su unidad y la cifra se descartaba.
    """
    import stopwords_es as sw  # noqa: PLC0415 (modulo hoja, solo stdlib)

    return sw.normalizar(palabra).replace("ñ", "n")


def _es_verbo_probable(palabra: str) -> bool:
    """Heuristica de verbo conjugado en espanol: sin diccionario y sin dependencias.

    Solo se usa para decidir si un `entonces` inicial abre una oracion de verdad. Se conforma
    con las terminaciones mas frecuentes de presente, pasado e imperfecto porque el coste de
    equivocarse es minusculo: como mucho se conserva una muletilla o se quita una palabra que
    tampoco aportaba.
    """
    t = _norma(palabra)
    if len(t) < 4 or t in ("entonces",):
        return False
    return t.endswith(
        (
            "ar",
            "er",
            "ir",
            "o",
            "as",
            "es",
            "a",
            "e",
            "an",
            "en",
            "amos",
            "emos",
            "imos",
            "aba",
            "ia",
            "io",
            "ue",
            "ara",
            "era",
        )
    )


def limpiar_muletillas(texto: str) -> str:
    """Quita las muletillas del habla espontanea. ESPECIFICO DE ESPANOL. PURO.

    Se quitan en dos sitios y solo en esos dos:

    1. Al PRINCIPIO del fragmento, en cadena ("pues este bueno, tengo 26" -> "tengo 26").
    2. En RACHA de dos o mas seguidas en cualquier posicion ("yo pues este tengo 26" -> "yo
       tengo 26"). Una suelta puede cargar sentido; dos seguidas no.
    3. Como interjeccion AISLADA en medio, o sea rodeada de comas ("subio, pues, un 42%").

    Las que tambien significan algo se respetan cuando hacen su trabajo: un `entonces` inicial
    seguido de verbo abre oracion y se conserva ("entonces bajo la desercion"), y `no` jamas se
    quita del arranque, porque "no sabemos que paso" sin el dice lo contrario.
    """
    palabras = _palabras(texto)
    if not palabras:
        return ""
    palabras = _quitar_muletillas_compuestas(palabras)
    palabras = _quitar_muletillas_iniciales(palabras)
    palabras = _quitar_rachas_de_muletillas(palabras)
    palabras = _quitar_muletillas_aisladas(palabras)
    return " ".join(palabras).strip()


def _quitar_muletillas_compuestas(palabras: list[str]) -> list[str]:
    """Las de varias palabras van primero: "o sea" muere entero antes de que "sea" se salve."""
    salida = list(palabras)
    for compuesta in MULETILLAS_COMPUESTAS:
        i = 0
        while i + len(compuesta) <= len(salida):
            ventana = tuple(_norma(w) for w in salida[i : i + len(compuesta)])
            if ventana == compuesta:
                del salida[i : i + len(compuesta)]
            else:
                i += 1
    return salida


def _quitar_muletillas_iniciales(palabras: list[str]) -> list[str]:
    """Quita muletillas del arranque, en cadena, mientras quede algo detras."""
    salida = list(palabras)
    while len(salida) > 1:
        cabeza = _norma(salida[0])
        if cabeza not in MULETILLAS_SIMPLES:
            break
        # `entonces` inicial con verbo detras abre oracion de verdad: se conserva.
        if cabeza in MULETILLAS_CON_EXCEPCION_DE_VERBO and _es_verbo_probable(salida[1]):
            break
        salida.pop(0)
    return salida


def _quitar_muletillas_aisladas(palabras: list[str]) -> list[str]:
    """Quita la muletilla que va entre comas en medio de la frase, nunca la que carga sentido."""
    rellenables = MULETILLAS_SIMPLES | MULETILLAS_SOLO_AISLADAS
    salida: list[str] = []
    for i, palabra in enumerate(palabras):
        aislada = (
            0 < i < len(palabras) - 1
            and _norma(palabra) in rellenables
            and palabras[i - 1].endswith(tuple(PUNTUACION_CLAUSULA))
            and palabra.endswith(tuple(PUNTUACION_CLAUSULA))
        )
        if not aislada:
            salida.append(palabra)
    return salida


def _quitar_rachas_de_muletillas(palabras: list[str]) -> list[str]:
    """Quita DOS o mas muletillas seguidas en cualquier posicion.

    Una muletilla suelta en medio puede estar cargando sentido, pero dos seguidas no: "yo pues
    este tengo 26 anos" es el caso literal que aparecio en la demo 08. Se exige racha de dos
    para no tocar los usos legitimos, que siempre van solos.
    """
    salida: list[str] = []
    i = 0
    while i < len(palabras):
        fin = i
        while fin < len(palabras) and _norma(palabras[fin]) in MULETILLAS_SIMPLES:
            fin += 1
        if fin - i >= 2:
            i = fin
            continue
        salida.append(palabras[i])
        i += 1
    return salida


def puntos_informativos(texto: str) -> float:
    """Cuanta informacion carga un texto, en puntos absolutos. PURO y sin dependencias.

    Heuristica, no modelo: una palabra vacia del espanol (articulo, preposicion, conjuncion,
    pronombre, auxiliar) no suma nada; una palabra con contenido suma 1; si pasa de 5 letras
    suma medio punto mas, porque los sustantivos y verbos largos son los que llevan el
    significado; y una cifra suma otro medio, porque un numero en pantalla es justo lo que hace
    que un letrero valga la pena.

    La lista de palabras vacias se LEE de `stopwords_es`, que ya existe y esta testeada, en vez
    de escribir una nueva aqui: dos listas de stopwords en el mismo repo se desincronizan.
    """
    import stopwords_es as sw  # noqa: PLC0415 (modulo hoja, solo stdlib)

    puntos = 0.0
    for palabra in _palabras(texto):
        limpio = sw.normalizar(palabra)
        if not limpio:
            continue
        if any(c.isdigit() for c in limpio):
            puntos += 1.5
            continue
        if limpio in sw.STOPWORDS_ES:
            continue
        puntos += 1.5 if len(limpio) > 5 else 1.0
    return puntos


def densidad_informativa(texto: str) -> float:
    """Puntos de informacion POR CARACTER. Es lo que decide entre dos fragmentos que caben."""
    limpio = " ".join((texto or "").split())
    if not limpio:
        return 0.0
    return puntos_informativos(limpio) / len(limpio)


def techo_de_piezas(duracion_ms: int) -> int:
    """Cuantas piezas admite un clip de esa duracion. Prorrateado, minimo 1.

    El redondeo es al alza desde la mitad (`floor(x + 0.5)`) y NO `round`, que en Python
    redondea 2.5 a 2 por el criterio del banquero: un clip de 30 s daria 2 piezas en vez de 3
    y nadie entenderia por que.
    """
    minutos = max(duracion_ms, 1) / 60000.0
    return max(1, math.floor(MAX_PIEZAS_POR_MINUTO * minutos + 0.5))


def _aplicar_techo(colocadas: list[Pieza], omisiones: list[Omision], duracion_ms: int) -> None:
    """Recorta las piezas OPCIONALES hasta respetar el techo. Muta `colocadas` en sitio.

    Las protegidas no se tocan aunque ellas solas ya pasen del techo: sin gancho, sin quien
    habla y sin llamada a la accion el clip pierde su estructura, y ese es un precio peor que
    ir un poco por encima de la densidad objetivo. De las opcionales cae primero la de MENOR
    sustancia; a igualdad de sustancia, la mas tardia, para que el clip conserve el ritmo de
    entrada. Cada recorte deja su omision con motivo, nunca desaparece en silencio.
    """
    techo = techo_de_piezas(duracion_ms)
    protegidas = [p for p in colocadas if p.plantilla in PIEZAS_PROTEGIDAS]
    opcionales = [p for p in colocadas if p.plantilla not in PIEZAS_PROTEGIDAS]
    permitidas = max(techo - len(protegidas), 0)
    if len(opcionales) <= permitidas:
        return
    # Peor primero: menos sustancia, y entre iguales la que llega mas tarde.
    orden = sorted(
        opcionales,
        key=lambda p: (puntos_informativos(" ".join(p.texto.values())), -p.t0_ms),
    )
    sobran = orden[: len(opcionales) - permitidas]
    for pieza in sobran:
        colocadas.remove(pieza)
        omisiones.append(Omision(pieza.plantilla, MOTIVO_TECHO_DENSIDAD, f"t0={pieza.t0_ms}ms"))


def buscar_cifra(texto: str) -> str | None:
    """Primera cifra DESTACABLE del texto, con su unidad pegada, o None. PURO.

    Destacable no es lo mismo que numerica. Se descarta:

      * el ano suelto ("del 2023 al 2024"), que es una fecha y no un dato;
      * el entero de un digito sin unidad ("2, grabado."), que casi siempre es ruido de
        transcripcion o una enumeracion.

    Y se EXIGE unidad, porque la unidad es lo que convierte un numero en dato: `%`, moneda, o
    una palabra detras que lo cualifique ("26 anos", "5 millones", "3 horas"). La unidad viaja
    CON la cifra al slot, que es lo que se pinta: "10.5%", nunca "10.5".
    """
    limpio = " ".join((texto or "").split())
    for m in _NUMERO.finditer(limpio):
        cifra = _cifra_con_unidad(limpio, m)
        if cifra:
            return cifra
    return None


def _cifra_con_unidad(limpio: str, m: re.Match) -> str | None:
    """La cifra formateada si es destacable, o None. `m` es una coincidencia de `_NUMERO`."""
    valor, moneda, pct = m.group("valor"), m.group("moneda"), m.group("pct")
    if moneda:
        return f"{moneda}{valor}"
    if pct:
        return f"{valor}%"

    detras = _palabras(limpio[m.end() :])
    compuesta = _unidad_compuesta(detras)
    if compuesta:
        return f"{valor} {compuesta}"
    if detras and _norma(detras[0]) in UNIDADES_POSTERIORES:
        return f"{valor} {detras[0].strip(PUNTUACION_CLAUSULA)}"

    # Sin unidad: solo sobreviven los numeros que ya dicen algo por si solos, y ni el ano ni el
    # digito suelto lo hacen.
    entero = valor.replace(".", "").replace(",", "")
    if not entero.isdigit():
        return None
    if len(entero) == 4 and ANO_MIN <= int(entero) <= ANO_MAX:
        return None
    if len(entero) <= 1:
        return None
    return None


def _unidad_compuesta(detras: list[str]) -> str | None:
    """Unidad de varias palabras que sigue al numero, ya limpia, o None."""
    for compuesta in UNIDADES_COMPUESTAS:
        if len(detras) < len(compuesta):
            continue
        if tuple(_norma(w) for w in detras[: len(compuesta)]) == compuesta:
            return " ".join(w.strip(PUNTUACION_CLAUSULA) for w in detras[: len(compuesta)])
    return None


def _candidatas(dur_ms: int, tramos: list[Tramo], t: TextosMarca) -> tuple[list[_Candidata], list]:
    """Piezas que la regla de duracion propone, en orden de prioridad, y lo ya descartado.

    Los tramos del SRT se REPARTEN: ninguna pieza puede usar el mismo que otra, porque dos
    letreros que dicen lo mismo se leen como un error. El reparto va de la pieza MAS atada a un
    tramo concreto a la menos atada: `dato_destacado` solo puede usar el tramo donde se dice la
    cifra, mientras que el `cierre` sirve con cualquier tramo anterior a el. Si el cierre eligiera
    primero se quedaria con el tramo de la cifra y mataria al dato sin necesidad.
    """
    fuera: list[Omision] = []
    props: list[_Candidata] = []
    # Reserva PROVISIONAL durante la construccion. La definitiva se recalcula tras colocar, a
    # partir de las piezas que de verdad entraron.
    reservados: set[int] = set()

    if t.titulo.strip():
        props.append(_Candidata("hook", ((0, 0),), {"kicker": t.kicker, "titulo": t.titulo}))
    else:
        fuera.append(Omision("hook", MOTIVO_SIN_TITULO))

    if dur_ms > UMBRAL_LARGO_MS:
        if t.nombre.strip():
            props.append(
                _Candidata(
                    "lower_third",
                    ((LOWER_THIRD_T0_MS, LOWER_THIRD_T0_MS),),
                    {"nombre": t.nombre, "rol": t.rol},
                )
            )
        else:
            fuera.append(Omision("lower_third", MOTIVO_SIN_NOMBRE))
        dato = _candidata_dato(tramos, reservados)
        if dato is None:
            fuera.append(Omision("dato_destacado", MOTIVO_SIN_CIFRA))
        elif isinstance(dato, str):
            fuera.append(Omision("dato_destacado", dato))
        else:
            if dato.tramo_t0 is not None:
                reservados.add(dato.tramo_t0)
            props.append(dato)
    else:
        for nombre in ("lower_third", "dato_destacado"):
            fuera.append(Omision(nombre, MOTIVO_CLIP_CORTO))

    if dur_ms >= UMBRAL_CORTO_MS:
        t0_cierre = dur_ms - MARGEN_FINAL_MS - DURACION_MS["cierre"]
        # El cierre YA NO repite el titulo del hook. Manda la llamada a la accion, y el texto
        # secundario sale de lo ultimo que se dice en el clip: asi el letrero final comenta el
        # video en vez de volver a anunciarlo. Sin tramo libre, el secundario va vacio y la
        # plantilla esconde esa linea.
        # Reparto ORIGINAL de la plantilla: el titulo va grande y la CTA corta en la pastilla.
        # La pastilla es un acento de dos palabras; meter ahi el fragmento hablado lo dejaba
        # ilegible. Lo unico que se conserva del intento anterior es que el titulo del cierre no
        # puede repetir el del hook: para eso sale de lo ultimo que se habla.
        titulo_cierre, cola_t0 = _cola_hablada(
            tramos, t0_cierre, reservados, TITULO_SECCION_MAX_CHARS
        )
        if cola_t0 is not None:
            reservados.add(cola_t0)
        props.append(
            _Candidata(
                "cierre",
                ((t0_cierre, t0_cierre),),
                {"titulo": titulo_cierre, "cta": t.cta},
                cola_t0,
            )
        )
    else:
        fuera.append(Omision("cierre", MOTIVO_CLIP_CORTO))

    props.sort(key=lambda c: PRIORIDAD.index(c.plantilla))
    return props, fuera


def _sin_tilde(palabra: str) -> str:
    """Minusculas y sin diacriticos, para comparar `aunque` con `Aunque` y `si` con `si`."""
    bajo = palabra.lower()
    for con, sin in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ü", "u")):
        bajo = bajo.replace(con, sin)
    return bajo


def _palabras(texto: str) -> list[str]:
    return [w for w in re.split(r"\s+", " ".join((texto or "").split())) if w]


def condensar_clausula(texto: str, maximo: int, minimo: int = TEXTO_MINIMO_CHARS) -> str:
    """Fragmento de texto que se lee como una frase entera, o "" si no lo hay.

    Cortar por palabras a N caracteres producia letreros como "con secundarias que tenga
    todas": media oracion, que se lee peor que no poner nada. Aqui el corte solo cae en un
    LIMITE DE CLAUSULA (puntuacion o antes de una conjuncion), el fragmento no puede EMPEZAR
    por conjuncion ni preposicion, y si nada de eso da un fragmento de tamano razonable se
    devuelve vacio para que la pieza se omita. Calidad por encima de cobertura.
    """
    limpio = limpiar_muletillas(" ".join((texto or "").split()))
    if not limpio:
        return ""
    validos = []
    for candidato in _candidatos_de_clausula(limpio, maximo):
        recortado = _quitar_arranque_debil(candidato).rstrip(" " + PUNTUACION_CLAUSULA)
        if not minimo <= len(recortado) <= maximo:
            continue
        if _termina_colgando(recortado):
            continue
        validos.append(recortado)
    if not validos:
        return ""
    # Gana el de mayor DENSIDAD informativa, no el mas largo. El mas largo suele ser el mismo
    # fragmento con dos subordinadas pegadas detras que no anaden nada; el denso dice lo mismo
    # en menos espacio y se lee de un golpe. A igualdad de densidad gana el mas corto, que es
    # lo que menos tapa del video.
    return max(validos, key=lambda t: (densidad_informativa(t), -len(t)))


def _termina_colgando(fragmento: str) -> bool:
    """True si la ultima palabra deja la frase en el aire ("...y con preparatorias que").

    Es el espejo de `_quitar_arranque_debil`: un letrero que ACABA en conjuncion o preposicion
    se lee tan partido como uno que empieza por ella. Aqui no se recorta, se descarta el
    candidato entero y se prueba uno mas corto.
    """
    palabras = _palabras(fragmento)
    if not palabras:
        return True
    return _sin_tilde(palabras[-1].strip(PUNTUACION_CLAUSULA)) in FINAL_PROHIBIDO


def _candidatos_de_clausula(limpio: str, maximo: int) -> list[str]:
    """Prefijos que terminan en limite de clausula. Sin ordenar: los ordena quien elige."""
    palabras = _palabras(limpio)
    cortes: list[str] = []
    if len(limpio) <= maximo:
        cortes.append(limpio)
    acumulado: list[str] = []
    for i, palabra in enumerate(palabras):
        siguiente = palabras[i + 1] if i + 1 < len(palabras) else None
        acumulado.append(palabra)
        parcial = " ".join(acumulado)
        if len(parcial) > maximo:
            break
        termina_en_puntuacion = palabra[-1] in PUNTUACION_CLAUSULA
        empieza_clausula = (
            siguiente is not None
            and _sin_tilde(siguiente.strip(PUNTUACION_CLAUSULA)) in CONJUNCIONES
        )
        if termina_en_puntuacion or empieza_clausula:
            cortes.append(parcial)
    return cortes


def _quitar_arranque_debil(fragmento: str) -> str:
    """Quita conjunciones y preposiciones del principio: un letrero no arranca por 'y' ni 'de'."""
    palabras = _palabras(fragmento)
    while palabras and _sin_tilde(palabras[0].strip(PUNTUACION_CLAUSULA)) in ARRANQUE_PROHIBIDO:
        palabras.pop(0)
    return " ".join(palabras)


def _condensar(texto: str, maximo: int = TITULO_SECCION_MAX_CHARS) -> str:
    """Compatibilidad: mismo contrato que `condensar_clausula` con el minimo por defecto."""
    return condensar_clausula(texto, maximo)


def _cola_hablada(
    tramos: list[Tramo],
    desde_ms: int,
    usados: set[int] | None = None,
    maximo: int = TITULO_SECCION_MAX_CHARS,
) -> tuple[str, int | None]:
    """Ultimo tramo con texto que empieza antes de `desde_ms`, condensado a etiqueta corta.

    Vacio si no hay ninguno, y entonces la plantilla esconde la pastilla en vez de pintarla en
    blanco. Aqui no se inventa texto: si el clip no dice nada antes del cierre, no hay etiqueta.
    """
    ocupados = usados or set()
    previos = [
        t
        for t in sorted(tramos, key=lambda x: x.t0_ms)
        if t.t0_ms <= desde_ms and (t.texto or "").strip() and t.t0_ms not in ocupados
    ]
    # Del mas cercano al cierre hacia atras: el primero que de una clausula limpia gana. Sin
    # ninguno, cadena vacia y la plantilla esconde la pastilla en vez de pintar media frase.
    for tramo in reversed(previos):
        etiqueta = condensar_clausula(tramo.texto, maximo)
        if etiqueta:
            return etiqueta, tramo.t0_ms
    return "", None


def _candidata_dato(tramos: list[Tramo], usados: set[int]) -> _Candidata | str | None:
    """`dato_destacado` dentro del tramo donde se dice la cifra, lo antes posible.

    K fijo "se coloca al inicio de ese tramo, y si no cabe se omite". El primer intento sigue
    siendo el inicio exacto, pero la ventana llega hasta el final del tramo: clavarla al
    milisegundo la mataba en cuanto ese instante chocaba con otra pieza aunque el resto del
    tramo estuviera libre. Se midio en un clip real de 56.8 s con dos cifras habladas: las dos
    caian dentro del lower_third y el dato se omitia entero, teniendo hueco de sobra 500 ms
    despues. Los tramos posteriores con cifra quedan de reserva, en orden temporal.
    """
    con_cifra = [
        (tr, buscar_cifra(tr.texto))
        for tr in sorted(tramos, key=lambda x: x.t0_ms)
        if buscar_cifra(tr.texto) and tr.t0_ms not in usados
    ]
    if not con_cifra:
        return None
    # La etiqueta acompana a la cifra y se lee igual que cualquier otro letrero, asi que pasa
    # por la misma guarda de clausula. Un tramo con cifra pero sin etiqueta limpia no sirve:
    # se prueba el siguiente, y si ninguno da, no hay dato.
    titulables = [
        (tr, cifra, etiqueta)
        for tr, cifra in con_cifra
        if (etiqueta := condensar_clausula(tr.texto, DATO_ETIQUETA_MAX_CHARS))
    ]
    if not titulables:
        return MOTIVO_ETIQUETA_SUCIA  # hay cifra, pero ningun tramo se puede etiquetar limpio
    tramo, cifra, etiqueta = titulables[0]
    return _Candidata(
        "dato_destacado",
        tuple((int(tr.t0_ms), int(tr.t1_ms)) for tr, _, _ in titulables),
        {"cifra": cifra, "etiqueta": etiqueta},
        int(tramo.t0_ms),
    )


def _hay_aire(t0: int, t1: int, colocadas: list[Pieza]) -> bool:
    """True si [t0, t1] respeta la separacion minima con TODAS las piezas ya colocadas."""
    return all(
        t0 - p.t1_ms >= SEPARACION_MIN_MS or p.t0_ms - t1 >= SEPARACION_MIN_MS for p in colocadas
    )


def zona_cara(tray_csv: Path | None, t0_ms: int, t1_ms: int) -> str | None:
    """Bucket de la cara en esa ventana, o None si no hay dato. Fail-open, ya existia en cve."""
    if not tray_csv:
        return None
    import cve  # noqa: PLC0415 (import perezoso: el planificador no arrastra el motor de captions)

    return cve.zona_cara_en_rango(tray_csv, t0_ms / 1000.0, t1_ms / 1000.0)


def _banda_libre(orientacion: str, t0_ms: int, t1_ms: int, tray_csv: Path | None) -> str:
    """Banda donde va la pieza en esa ventana. SIEMPRE devuelve una: nunca omite.

    Solo se consulta la cara en 9:16: ahi las cinco piezas comparten un carril estrecho y una
    cara centrada o baja se lo come, asi que la pieza sube a la banda superior. Sin dato de cara
    se usa el carril nativo, que es el aprobado en el gate visual de HF-2. En 16:9 las bandas del
    catalogo son disjuntas (lower_third abajo a la izquierda, el resto centradas arriba) y no
    compiten con la cara, asi que la pieza se queda donde la dibuja su HTML.
    """
    if orientacion != "vertical":
        return BANDA_CENTRO
    return BANDA_POR_ZONA_CARA.get(zona_cara(tray_csv, t0_ms, t1_ms), BANDA_SIN_DATO)


def _colocar(
    cand: _Candidata,
    duracion_ms: int,
    orientacion: str,
    tray_csv: Path | None,
    colocadas: list[Pieza],
) -> tuple[Pieza | None, str]:
    """Primer instante VALIDO de las ventanas de la candidata, o (None, motivo)."""
    dur = DURACION_MS[cand.plantilla]
    motivo = MOTIVO_FUERA_DE_CLIP
    for desde, hasta in cand.ventanas:
        for t0 in _instantes(desde, hasta, dur, duracion_ms, colocadas):
            t1 = t0 + dur
            if not _hay_aire(t0, t1, colocadas):
                motivo = MOTIVO_SIN_AIRE
                continue
            banda = _banda_libre(orientacion, t0, t1, tray_csv)
            return Pieza(cand.plantilla, t0, t1, dict(cand.texto), banda, cand.tramo_t0), ""
        if hasta + dur > duracion_ms and motivo == MOTIVO_FUERA_DE_CLIP:
            motivo = MOTIVO_FUERA_DE_CLIP
    return None, motivo


def _instantes(
    desde: int, hasta: int, dur: int, duracion_ms: int, colocadas: list[Pieza]
) -> list[int]:
    """Instantes de arranque a probar dentro de [desde, hasta], en orden de preferencia.

    Primero el inicio pedido, que es lo que manda la regla. Si no vale, los finales de las
    piezas ya colocadas mas la separacion minima: son los unicos puntos donde puede abrirse un
    hueco, asi que probar otra cosa seria adivinar. Todos acotados a la ventana y al clip.
    """
    candidatos = [desde]
    for p in colocadas:
        candidatos.append(p.t1_ms + SEPARACION_MIN_MS)
    vistos: list[int] = []
    for t0 in candidatos:
        if desde <= t0 <= hasta and 0 <= t0 and t0 + dur <= duracion_ms and t0 not in vistos:
            vistos.append(t0)
    return sorted(vistos)


def _huecos(colocadas: list[Pieza], duracion_ms: int) -> list[tuple[int, int]]:
    """Tramos de tiempo del clip sin ninguna pieza, incluidos los extremos."""
    if not colocadas:
        return [(0, duracion_ms)]
    orden = sorted(colocadas, key=lambda p: p.t0_ms)
    huecos = [(0, orden[0].t0_ms)]
    for previa, siguiente in zip(orden, orden[1:], strict=False):
        huecos.append((previa.t1_ms, siguiente.t0_ms))
    huecos.append((orden[-1].t1_ms, duracion_ms))
    return [(a, b) for a, b in huecos if b > a]


def _tramo_titulable(
    tramos: list[Tramo], desde: int, hasta: int, usados: set[int] | None = None
) -> tuple[Tramo, str] | None:
    """(tramo, titulo) del primer tramo del hueco que da una clausula limpia, o None.

    `_tramo_relevante` elige el tramo por criterio de contenido; aqui se comprueba ademas que
    ese tramo se pueda TITULAR sin partir la frase. Si el preferido no da nada limpio se prueban
    los siguientes del hueco, y si ninguno vale se devuelve None y la pieza no se coloca:
    calidad por encima de cobertura.
    """
    ocupados = usados or set()
    preferido = _tramo_relevante(tramos, desde, hasta, ocupados)
    if preferido is None:
        return None
    resto = [
        t
        for t in sorted(tramos, key=lambda x: x.t0_ms)
        if desde <= t.t0_ms < hasta and t is not preferido and t.t0_ms not in ocupados
    ]
    for tramo in (preferido, *resto):
        titulo = condensar_clausula(tramo.texto, TITULO_SECCION_MAX_CHARS)
        if titulo:
            return tramo, titulo
    return None


def _tramo_relevante(
    tramos: list[Tramo], desde: int, hasta: int, usados: set[int] | None = None
) -> Tramo | None:
    """Tramo con el que titular ese hueco. Determinista y sin IA.

    Se prefiere el primer tramo que arranca tras una PAUSA larga dentro del hueco, porque una
    pausa es donde el hablante cambia de tema. Si no hay ninguna, el tramo con mas texto del
    hueco, que es el que mas contenido tiene que resumir. Los empates los rompe el tiempo.
    """
    dentro = [
        t
        for t in sorted(tramos, key=lambda x: x.t0_ms)
        if desde <= t.t0_ms < hasta and len(" ".join((t.texto or "").split())) >= TEXTO_MINIMO_CHARS
    ]
    if not dentro:
        return None
    # Las pausas se miden sobre TODOS los tramos, no sobre los disponibles: quitar de la lista
    # los ya usados inventaba pausas donde solo habia un tramo apartado, y el relleno se creia
    # que ahi cambiaba el tema.
    orden_total = sorted(tramos, key=lambda x: x.t0_ms)
    fin_previo = {t.t0_ms: None for t in orden_total}
    for previa, siguiente in zip(orden_total, orden_total[1:], strict=False):
        fin_previo[siguiente.t0_ms] = previa.t1_ms
    tras_pausa = [
        t
        for t in dentro
        if fin_previo.get(t.t0_ms) is not None
        and t.t0_ms - fin_previo[t.t0_ms] >= PAUSA_CAMBIO_TEMA_MS
    ]
    # Dentro del hueco se prefiere lo mas CENTRADO, no lo mas largo: un letrero pegado a un
    # extremo parte el hueco en 5 s y 40 s, y el de 40 s sigue estando vacio. Centrado, cada
    # mitad baja a la vez. Entre los que empatan gana el que llega antes.
    medio = (desde + hasta) // 2
    candidatos = tras_pausa or dentro
    return min(candidatos, key=lambda t: (abs(t.t0_ms - medio), t.t0_ms))


def _rellenar_huecos(
    colocadas: list[Pieza],
    omisiones: list[Omision],
    duracion_ms: int,
    orientacion: str,
    tray_csv: Path | None,
    tramos: list[Tramo],
    presupuesto: int,
    usados: set[int],
) -> None:
    """Mete `titulo_seccion` donde el clip pasa demasiado tiempo sin un solo letrero.

    Es la unica pieza cuyo texto sale de LO QUE SE DICE y no de la configuracion ni del titulo
    del clip. Solo entra en clips largos y solo en huecos de mas de HUECO_MAX_MS; el bucle
    repite mientras siga abriendo huecos nuevos, porque un hueco de 50 s necesita mas de un
    letrero para bajar de 20 s.

    `presupuesto` es lo que deja el techo de densidad. Los huecos se atacan de MAYOR a menor:
    si no alcanza para todos, el que se queda sin letrero es el mas corto, que es el que menos
    se nota.
    """
    if duracion_ms <= UMBRAL_RELLENO_MS:
        return
    if presupuesto <= 0:
        omisiones.append(Omision("titulo_seccion", MOTIVO_TECHO_DENSIDAD))
        return
    if not tramos:
        omisiones.append(Omision("titulo_seccion", MOTIVO_SIN_TRAMO))
        return
    dur = DURACION_MS["titulo_seccion"]
    motivo_final = MOTIVO_SIN_HUECO
    colocada_alguna = False
    while presupuesto > 0:
        candidatos = [(a, b) for a, b in _huecos(colocadas, duracion_ms) if b - a > HUECO_MAX_MS]
        if not candidatos:
            break
        # UNA pieza por vuelta, y los huecos se recalculan en cada una. Colocar en varios
        # huecos con la lista de una sola foto amontonaba los letreros: el segundo se decidia
        # contra un hueco que el primero ya habia partido.
        candidatos.sort(key=lambda h: h[1] - h[0], reverse=True)  # el hueco mas grande primero
        progreso = False
        for desde, hasta in candidatos:
            elegido = _tramo_titulable(tramos, desde, hasta, usados)
            if elegido is None:
                motivo_final = MOTIVO_SIN_TRAMO
                continue
            tramo, titulo = elegido
            cand = _Candidata(
                "titulo_seccion",
                ((max(tramo.t0_ms, desde), max(hasta - dur, desde)),),
                {"titulo": titulo},
                int(tramo.t0_ms),
            )
            pieza, motivo = _colocar(cand, duracion_ms, orientacion, tray_csv, colocadas)
            if pieza is None:
                motivo_final = motivo
                continue
            colocadas.append(pieza)
            usados.add(int(tramo.t0_ms))
            presupuesto -= 1
            colocada_alguna = True
            progreso = True
            break  # a recalcular huecos con la pieza nueva ya dentro
        if not progreso:
            break
    if not colocada_alguna:
        omisiones.append(Omision("titulo_seccion", motivo_final))


def planificar(
    *,
    duracion_ms: int,
    orientacion: str,
    textos: TextosMarca,
    tramos: list[Tramo] | None = None,
    tray_csv: Path | None = None,
) -> PlanMotion:
    """Plan de letreros de UN clip. Puro salvo la lectura fail-open del CSV de trayectoria.

    `duracion_ms` es la duracion del clip ya reencuadrado. `tramos` son los textos del SRT en
    ms relativos al clip. `tray_csv` es la trayectoria que escribio el reframe; None o legacy
    hace que el carril vertical se considere OCUPADO, que es la lectura conservadora: sin dato
    de la cara no se puede afirmar que el letrero no la tape.
    """
    if orientacion not in ORIENTACIONES:
        raise ValueError(f"orientacion invalida: {orientacion!r} (usa {', '.join(ORIENTACIONES)})")
    if not isinstance(duracion_ms, int) or isinstance(duracion_ms, bool) or duracion_ms <= 0:
        raise ValueError(f"duracion_ms debe ser un entero positivo, se recibio {duracion_ms!r}")

    lista_tramos = list(tramos or [])
    props, omisiones = _candidatas(duracion_ms, lista_tramos, textos)
    colocadas: list[Pieza] = []
    incidencias: list[str] = []
    # Se consulta UNA vez sobre el clip entero: si no hay dato de cara en ningun momento, no lo
    # va a haber por ventana, y repetir la lectura del CSV por pieza solo costaria tiempo.
    if orientacion == "vertical" and zona_cara(tray_csv, 0, duracion_ms) is None:
        incidencias.append(INCIDENCIA_SIN_DATO_DE_CARA)

    for cand in props:
        pieza, motivo = _colocar(cand, duracion_ms, orientacion, tray_csv, colocadas)
        if pieza is None:
            omisiones.append(Omision(cand.plantilla, motivo))
        else:
            colocadas.append(pieza)

    # El techo se cobra ANTES de rellenar y el relleno recibe lo que sobra. Rellenar primero y
    # recortar despues quitaba justo las piezas que se habian puesto para cerrar un hueco, y
    # dejaba huecos peores que si no se hubiera rellenado.
    _aplicar_techo(colocadas, omisiones, duracion_ms)
    presupuesto = max(techo_de_piezas(duracion_ms) - len(colocadas), 0)
    # Reserva DEFINITIVA: se recalcula de las piezas que de verdad entraron, para que un tramo
    # apartado por una candidata que luego se descarto no quede bloqueado sin motivo.
    usados = {p.tramo_t0 for p in colocadas if p.tramo_t0 is not None}
    _rellenar_huecos(
        colocadas,
        omisiones,
        duracion_ms,
        orientacion,
        tray_csv,
        lista_tramos,
        presupuesto,
        usados,
    )
    colocadas.sort(key=lambda p: p.t0_ms)
    omisiones.sort(key=lambda o: (o.plantilla, o.motivo))
    return PlanMotion(orientacion, tuple(colocadas), tuple(omisiones), tuple(incidencias))


__all__ = [
    "ANO_MAX",
    "ANO_MIN",
    "ARRANQUE_PROHIBIDO",
    "UNIDADES_POSTERIORES",
    "MULETILLAS_SOLO_AISLADAS",
    "MULETILLAS_COMPUESTAS",
    "MULETILLAS_SIMPLES",
    "limpiar_muletillas",
    "MAX_PIEZAS_POR_MINUTO",
    "MOTIVO_TECHO_DENSIDAD",
    "PIEZAS_OPCIONALES",
    "PIEZAS_PROTEGIDAS",
    "densidad_informativa",
    "puntos_informativos",
    "techo_de_piezas",
    "MOTIVO_ETIQUETA_SUCIA",
    "FINAL_PROHIBIDO",
    "BANDA_ARRIBA",
    "CIERRE_SECUNDARIO_MAX_CHARS",
    "DATO_ETIQUETA_MAX_CHARS",
    "TEXTO_MINIMO_CHARS",
    "TITULO_SECCION_MAX_CHARS",
    "condensar_clausula",
    "BANDA_SIN_DATO",
    "INCIDENCIA_SIN_DATO_DE_CARA",
    "BANDA_CENTRO",
    "BANDA_SUPERIOR",
    "CARRIL_VERTICAL",
    "DESPLAZAMIENTO_SUPERIOR",
    "DURACION_MS",
    "MARGEN_FINAL_MS",
    "PRIORIDAD",
    "SEPARACION_MIN_MS",
    "UMBRAL_CORTO_MS",
    "UMBRAL_LARGO_MS",
    "ZONA_CAPTIONS",
    "Omision",
    "Pieza",
    "PlanMotion",
    "TextosMarca",
    "Tramo",
    "buscar_cifra",
    "planificar",
]
