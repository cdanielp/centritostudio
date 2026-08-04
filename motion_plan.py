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

  clip < 6000 ms          solo `hook`, en t=0
  clip de 6000 a 12000    `hook` en t=0 y `cierre` terminando 200 ms antes del final
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
UMBRAL_CORTO_MS = 6000  # por debajo: solo hook
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

# Mayor a menor. Cuando dos piezas no pueden convivir, cae la de MENOR prioridad.
PRIORIDAD = ("hook", "cierre", "lower_third", "dato_destacado")

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

# Buckets de `cve.zona_cara_en_rango` y la banda que dejan libre en 9:16. None (CSV legacy,
# sin deteccion viva) NO aparece aqui a proposito: sin dato de la cara no se puede afirmar que
# ningun letrero la tape, asi que se omite la pieza.
BANDA_POR_ZONA_CARA = {
    "top": BANDA_CENTRO,  # cara arriba: el carril nativo esta despejado
    "center": BANDA_ARRIBA,
    "bottom": BANDA_ARRIBA,
}

ORIENTACIONES = ("vertical", "horizontal")

# Una cifra: digitos, con o sin separadores, y con moneda o porcentaje opcionales.
_CIFRA = re.compile(r"[$€]?\s?\d+(?:[.,]\d+)*\s?%?")

MOTIVO_FUERA_DE_CLIP = "no_cabe_en_el_clip"
MOTIVO_SIN_AIRE = "sin_separacion_minima"
MOTIVO_CARA = "carril_ocupado_por_la_cara"
MOTIVO_SIN_CIFRA = "ningun_tramo_trae_cifra"
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
                }
                for p in self.piezas
            ],
            "omisiones": [
                {"plantilla": o.plantilla, "motivo": o.motivo, "detalle": o.detalle}
                for o in self.omisiones
            ],
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


def buscar_cifra(texto: str) -> str | None:
    """Primera cifra del texto, ya normalizada, o None. Puro."""
    m = _CIFRA.search(texto or "")
    if not m:
        return None
    return " ".join(m.group(0).split())


def _candidatas(dur_ms: int, tramos: list[Tramo], t: TextosMarca) -> tuple[list[_Candidata], list]:
    """Piezas que la regla de duracion propone, en orden de prioridad, y lo ya descartado."""
    fuera: list[Omision] = []
    props: list[_Candidata] = []

    if t.titulo.strip():
        props.append(_Candidata("hook", ((0, 0),), {"kicker": t.kicker, "titulo": t.titulo}))
    else:
        fuera.append(Omision("hook", MOTIVO_SIN_TITULO))

    if dur_ms >= UMBRAL_CORTO_MS:
        t0_cierre = dur_ms - MARGEN_FINAL_MS - DURACION_MS["cierre"]
        # El cierre YA NO repite el titulo del hook. Manda la llamada a la accion, y el texto
        # secundario sale de lo ultimo que se dice en el clip: asi el letrero final comenta el
        # video en vez de volver a anunciarlo. Sin tramos, el secundario va vacio y la plantilla
        # esconde esa linea.
        props.append(
            _Candidata(
                "cierre",
                ((t0_cierre, t0_cierre),),
                {"titulo": t.cta, "cta": _cola_hablada(tramos, t0_cierre)},
            )
        )
    else:
        fuera.append(Omision("cierre", MOTIVO_CLIP_CORTO))

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
        dato = _candidata_dato(tramos)
        if dato is None:
            fuera.append(Omision("dato_destacado", MOTIVO_SIN_CIFRA))
        else:
            props.append(dato)
    else:
        for nombre in ("lower_third", "dato_destacado"):
            fuera.append(Omision(nombre, MOTIVO_CLIP_CORTO))

    props.sort(key=lambda c: PRIORIDAD.index(c.plantilla))
    return props, fuera


def _condensar(texto: str, maximo: int = TITULO_SECCION_MAX_CHARS) -> str:
    """Texto de un tramo listo para una placa de una linea. Puro y sin puntos suspensivos."""
    limpio = " ".join((texto or "").split())
    if len(limpio) <= maximo:
        return limpio
    corte = limpio[:maximo].rsplit(" ", 1)[0]
    return corte or limpio[:maximo]


def _cola_hablada(tramos: list[Tramo], desde_ms: int) -> str:
    """Ultimo tramo con texto que empieza antes de `desde_ms`, condensado a etiqueta corta.

    Vacio si no hay ninguno, y entonces la plantilla esconde la pastilla en vez de pintarla en
    blanco. Aqui no se inventa texto: si el clip no dice nada antes del cierre, no hay etiqueta.
    """
    previos = [
        t for t in sorted(tramos, key=lambda x: x.t0_ms)
        if t.t0_ms <= desde_ms and len(" ".join((t.texto or "").split())) >= TEXTO_MINIMO_CHARS
    ]
    return _condensar(previos[-1].texto, CIERRE_SECUNDARIO_MAX_CHARS) if previos else ""


def _candidata_dato(tramos: list[Tramo]) -> _Candidata | None:
    """`dato_destacado` dentro del tramo donde se dice la cifra, lo antes posible.

    K fijo "se coloca al inicio de ese tramo, y si no cabe se omite". El primer intento sigue
    siendo el inicio exacto, pero la ventana llega hasta el final del tramo: clavarla al
    milisegundo la mataba en cuanto ese instante chocaba con otra pieza aunque el resto del
    tramo estuviera libre. Se midio en un clip real de 56.8 s con dos cifras habladas: las dos
    caian dentro del lower_third y el dato se omitia entero, teniendo hueco de sobra 500 ms
    despues. Los tramos posteriores con cifra quedan de reserva, en orden temporal.
    """
    con_cifra = [
        (tr, buscar_cifra(tr.texto)) for tr in sorted(tramos, key=lambda x: x.t0_ms)
        if buscar_cifra(tr.texto)
    ]
    if not con_cifra:
        return None
    tramo, cifra = con_cifra[0]
    return _Candidata(
        "dato_destacado",
        tuple((int(tr.t0_ms), int(tr.t1_ms)) for tr, _ in con_cifra),
        {"cifra": cifra, "etiqueta": _condensar(tramo.texto)},
    )


def _hay_aire(t0: int, t1: int, colocadas: list[Pieza]) -> bool:
    """True si [t0, t1] respeta la separacion minima con TODAS las piezas ya colocadas."""
    return all(
        t0 - p.t1_ms >= SEPARACION_MIN_MS or p.t0_ms - t1 >= SEPARACION_MIN_MS for p in colocadas
    )


def _banda_libre(orientacion: str, t0_ms: int, t1_ms: int, tray_csv: Path | None) -> str | None:
    """Banda donde cabe la pieza en esa ventana, o None si no cabe en ninguna.

    Solo se consulta la cara en 9:16: ahi las cinco piezas comparten un carril estrecho y una
    cara centrada o baja se lo come. Con la cara en `center` o `bottom` la pieza sube a la banda
    superior en vez de omitirse, que es lo que hacia antes. En 16:9 las bandas del catalogo son
    disjuntas (lower_third abajo a la izquierda, el resto centradas arriba) y no compiten con la
    cara, asi que la pieza se queda donde la dibuja su HTML.
    """
    if orientacion != "vertical":
        return BANDA_CENTRO
    import cve  # noqa: PLC0415 (import perezoso: el planificador no arrastra el motor de captions)

    zona = cve.zona_cara_en_rango(tray_csv, t0_ms / 1000.0, t1_ms / 1000.0) if tray_csv else None
    return BANDA_POR_ZONA_CARA.get(zona)


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
            if banda is None:
                motivo = MOTIVO_CARA
                continue
            return Pieza(cand.plantilla, t0, t1, dict(cand.texto), banda), ""
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


def _tramo_relevante(tramos: list[Tramo], desde: int, hasta: int) -> Tramo | None:
    """Tramo con el que titular ese hueco. Determinista y sin IA.

    Se prefiere el primer tramo que arranca tras una PAUSA larga dentro del hueco, porque una
    pausa es donde el hablante cambia de tema. Si no hay ninguna, el tramo con mas texto del
    hueco, que es el que mas contenido tiene que resumir. Los empates los rompe el tiempo.
    """
    dentro = [
        t for t in sorted(tramos, key=lambda x: x.t0_ms)
        if desde <= t.t0_ms < hasta
        and len(" ".join((t.texto or "").split())) >= TEXTO_MINIMO_CHARS
    ]
    if not dentro:
        return None
    orden_total = sorted(tramos, key=lambda x: x.t0_ms)
    fin_previo = {t.t0_ms: None for t in orden_total}
    for previa, siguiente in zip(orden_total, orden_total[1:], strict=False):
        fin_previo[siguiente.t0_ms] = previa.t1_ms
    tras_pausa = [
        t for t in dentro
        if fin_previo.get(t.t0_ms) is not None
        and t.t0_ms - fin_previo[t.t0_ms] >= PAUSA_CAMBIO_TEMA_MS
    ]
    if tras_pausa:
        return tras_pausa[0]
    return max(dentro, key=lambda t: (len(" ".join((t.texto or "").split())), -t.t0_ms))


def _rellenar_huecos(
    colocadas: list[Pieza],
    omisiones: list[Omision],
    duracion_ms: int,
    orientacion: str,
    tray_csv: Path | None,
    tramos: list[Tramo],
) -> None:
    """Mete `titulo_seccion` donde el clip pasa demasiado tiempo sin un solo letrero.

    Es la unica pieza cuyo texto sale de LO QUE SE DICE y no de la configuracion ni del titulo
    del clip. Solo entra en clips largos y solo en huecos de mas de HUECO_MAX_MS; el bucle
    repite mientras siga abriendo huecos nuevos, porque un hueco de 50 s necesita mas de un
    letrero para bajar de 20 s.
    """
    if duracion_ms <= UMBRAL_RELLENO_MS:
        return
    if not tramos:
        omisiones.append(Omision("titulo_seccion", MOTIVO_SIN_TRAMO))
        return
    dur = DURACION_MS["titulo_seccion"]
    motivo_final = MOTIVO_SIN_HUECO
    colocada_alguna = False
    while True:
        candidatos = [
            (a, b) for a, b in _huecos(colocadas, duracion_ms) if b - a > HUECO_MAX_MS
        ]
        if not candidatos:
            break
        progreso = False
        for desde, hasta in candidatos:
            tramo = _tramo_relevante(tramos, desde, hasta)
            if tramo is None:
                motivo_final = MOTIVO_SIN_TRAMO
                continue
            cand = _Candidata(
                "titulo_seccion",
                ((max(tramo.t0_ms, desde), max(hasta - dur, desde)),),
                {"titulo": _condensar(tramo.texto)},
            )
            pieza, motivo = _colocar(cand, duracion_ms, orientacion, tray_csv, colocadas)
            if pieza is None:
                motivo_final = motivo
                continue
            colocadas.append(pieza)
            colocada_alguna = True
            progreso = True
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

    for cand in props:
        pieza, motivo = _colocar(cand, duracion_ms, orientacion, tray_csv, colocadas)
        if pieza is None:
            omisiones.append(Omision(cand.plantilla, motivo))
        else:
            colocadas.append(pieza)

    _rellenar_huecos(colocadas, omisiones, duracion_ms, orientacion, tray_csv, lista_tramos)
    colocadas.sort(key=lambda p: p.t0_ms)
    omisiones.sort(key=lambda o: (o.plantilla, o.motivo))
    return PlanMotion(orientacion, tuple(colocadas), tuple(omisiones))


__all__ = [
    "BANDA_ARRIBA",
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
