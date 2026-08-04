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
  `titulo_seccion`        no se coloca automaticamente en esta version

Una pieza que no cabe se OMITE con su motivo. Nunca se encima con otra y nunca se le recorta
la duracion: un letrero a medias es peor que ningun letrero.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
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

# Mayor a menor. Cuando dos piezas no pueden convivir, cae la de MENOR prioridad.
PRIORIDAD = ("hook", "cierre", "lower_third", "dato_destacado")

# ── Restricciones espaciales (medidas en HF-2, D51; no se vuelven a medir) ───
ZONA_CAPTIONS = (0.70, 0.92)  # franja prohibida de diseno, en fraccion del alto
CARRIL_VERTICAL = (0.54, 0.68)  # donde viven las piezas en 9:16; el unico carril libre
# Buckets de `cve.zona_cara_en_rango` que dejan el carril vertical despejado. `center` y
# `bottom` lo invaden, y None (CSV legacy o sin deteccion viva) se trata como ocupado.
ZONAS_CARA_LIBRES = ("top",)

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


@dataclass(frozen=True)
class Tramo:
    """Un tramo de texto del SRT, en milisegundos relativos al inicio del clip."""

    t0_ms: int
    t1_ms: int
    texto: str


@dataclass(frozen=True)
class Pieza:
    """Una pieza colocada: que plantilla, en que ventana y con que textos."""

    plantilla: str
    t0_ms: int
    t1_ms: int
    texto: dict[str, str]

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
    """Pieza en estudio antes de pasar por los filtros."""

    plantilla: str
    t0_ms: int
    texto: dict[str, str]
    alternativas_t0: tuple[int, ...] = field(default_factory=tuple)


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
        props.append(_Candidata("hook", 0, {"kicker": t.kicker, "titulo": t.titulo}))
    else:
        fuera.append(Omision("hook", MOTIVO_SIN_TITULO))

    if dur_ms >= UMBRAL_CORTO_MS:
        t0_cierre = dur_ms - MARGEN_FINAL_MS - DURACION_MS["cierre"]
        props.append(_Candidata("cierre", t0_cierre, {"titulo": t.titulo, "cta": t.cta}))
    else:
        fuera.append(Omision("cierre", MOTIVO_CLIP_CORTO))

    if dur_ms > UMBRAL_LARGO_MS:
        if t.nombre.strip():
            props.append(
                _Candidata("lower_third", LOWER_THIRD_T0_MS, {"nombre": t.nombre, "rol": t.rol})
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


def _candidata_dato(tramos: list[Tramo]) -> _Candidata | None:
    """`dato_destacado` al inicio del primer tramo con cifra, con los siguientes de reserva.

    K fijo "se coloca al inicio de ese tramo, y si no cabe se omite". Se guardan los tramos
    posteriores como alternativas porque la regla habla de "algun tramo": quedarse solo con el
    primero dejaria la pieza practicamente muerta, ya que los primeros segundos casi siempre los
    ocupa el hook. El orden temporal la mantiene determinista.
    """
    conteo = [(tr, buscar_cifra(tr.texto)) for tr in sorted(tramos, key=lambda x: x.t0_ms)]
    con_cifra = [(tr, c) for tr, c in conteo if c]
    if not con_cifra:
        return None
    tramo, cifra = con_cifra[0]
    return _Candidata(
        "dato_destacado",
        int(tramo.t0_ms),
        {"cifra": cifra, "etiqueta": " ".join((tramo.texto or "").split())},
        tuple(int(tr.t0_ms) for tr, _ in con_cifra[1:]),
    )


def _hay_aire(t0: int, t1: int, colocadas: list[Pieza]) -> bool:
    """True si [t0, t1] respeta la separacion minima con TODAS las piezas ya colocadas."""
    return all(
        t0 - p.t1_ms >= SEPARACION_MIN_MS or p.t0_ms - t1 >= SEPARACION_MIN_MS for p in colocadas
    )


def _zona_libre(orientacion: str, t0_ms: int, t1_ms: int, tray_csv: Path | None) -> bool:
    """True si el carril de las piezas esta despejado en esa ventana.

    Solo se comprueba en 9:16: ahi las cinco piezas comparten el unico carril libre (54-68% del
    alto) y una cara centrada o baja se lo come. En 16:9 las bandas del catalogo son disjuntas
    (lower_third abajo a la izquierda, el resto centradas arriba) y no compiten con la cara.
    """
    if orientacion != "vertical":
        return True
    import cve  # noqa: PLC0415 (import perezoso: el planificador no arrastra el motor de captions)

    zona = cve.zona_cara_en_rango(tray_csv, t0_ms / 1000.0, t1_ms / 1000.0) if tray_csv else None
    return zona in ZONAS_CARA_LIBRES


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

    props, omisiones = _candidatas(duracion_ms, list(tramos or []), textos)
    colocadas: list[Pieza] = []

    for cand in props:
        dur = DURACION_MS[cand.plantilla]
        motivo = None
        for t0 in (cand.t0_ms, *cand.alternativas_t0):
            t1 = t0 + dur
            if t0 < 0 or t1 > duracion_ms:
                motivo = MOTIVO_FUERA_DE_CLIP
                continue
            if not _hay_aire(t0, t1, colocadas):
                motivo = MOTIVO_SIN_AIRE
                continue
            if not _zona_libre(orientacion, t0, t1, tray_csv):
                motivo = MOTIVO_CARA
                continue
            colocadas.append(Pieza(cand.plantilla, t0, t1, dict(cand.texto)))
            motivo = None
            break
        if motivo is not None:
            omisiones.append(Omision(cand.plantilla, motivo))

    colocadas.sort(key=lambda p: p.t0_ms)
    omisiones.sort(key=lambda o: (o.plantilla, o.motivo))
    return PlanMotion(orientacion, tuple(colocadas), tuple(omisiones))


__all__ = [
    "CARRIL_VERTICAL",
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
