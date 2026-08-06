"""motion_plan_spatial.py — Colocacion espacial de letreros (HF-4, Paso 1).

`motion_plan.planificar()` decide QUE piezas lleva un clip, EN QUE MILISEGUNDO entra cada una y
QUE TEXTO llevan: eso no depende del formato de salida. Este modulo decide, por separado, DONDE
va cada pieza ya temporizada — en que banda, y si esa banda invade la franja de captions DE ESE
FORMATO. Es el paso ESPACIAL: se corre una vez POR FORMATO pedido, nunca vuelve a preguntarle
nada al LLM ni a Pexels, y nunca reabre la busqueda de instantes libres.

PURO: mismo contrato que `motion_plan` (sin IA, sin red, sin reloj). La unica lectura de disco
es el CSV de trayectoria del reframe, vía `cve.zona_cara_en_rango` (fail-open, ya existia).

CERO dependencia de `motion_plan.py` (evita import circular: `motion_plan.Pieza` usa
`BANDA_CENTRO` como valor por defecto de campo, asi que este modulo tiene que terminar de
importarse antes de que esa clase se defina).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from motion_plan import Pieza

# ── Vocabulario de bandas ─────────────────────────────────────────────────────
BANDA_CENTRO = "centro"
BANDA_ARRIBA = "superior"
BANDA_INFERIOR = "inferior"
BANDAS_VALIDAS = (BANDA_CENTRO, BANDA_ARRIBA, BANDA_INFERIOR)

# Etiqueta en espanol de cada banda, para el selector del editor y para los motivos de rechazo.
ETIQUETA_BANDA = {BANDA_ARRIBA: "Arriba", BANDA_CENTRO: "Centro", BANDA_INFERIOR: "Abajo"}

# ── Restricciones espaciales (medidas en HF-2, D51; no se vuelven a medir) ───
# Franja de captions REAL por orientacion (DECISIONES.md D51 Ronda 3, ESTADO.md:184). Antes de
# HF-4 Paso 1 las dos orientaciones comparaban contra el mismo (0.70, 0.92) porque el horizontal
# no tenia consumidor en produccion (el Modo Automatico siempre reencuadraba a 9:16). Con
# Formato dual cada orientacion valida contra su propia franja medida.
ZONA_CAPTIONS_POR_ORIENTACION = {
    "vertical": (0.802, 0.899),
    "horizontal": (0.725, 0.899),
}

CARRIL_VERTICAL = (0.54, 0.68)  # donde el HTML de las piezas dibuja su contenido en 9:16

# Segunda banda, POR ENCIMA de la cara. Con la cara en `center` (0.40-0.60) o en `bottom`
# (>0.60) el carril de 54-68% queda invadido y antes se omitia la pieza entera; medido sobre
# los clips reales del proyecto, eso dejaba en cero al 61.9% de los verticales.
#
# CONFIRMADO CON RENDER REAL (revision/hf-3/confirmar_banda.py, sobre un clip 1080x1920 con la
# cara en `center`): el hook, que es la pieza mas alta, ocupa nativamente 60.9-68.6% del alto y
# tras el desplazamiento de -653 px cae en 26.9-34.6%. Queda por debajo del 10% de zona segura
# de UI de TikTok/Reels, por encima del borde superior de una cara centrada (una cabeza centrada
# en 0.50 arranca alrededor de 0.35) y muy lejos de la franja de captions.
BANDA_SUPERIOR = (0.20, 0.35)

# Cuanto hay que subir la pieza, en fraccion del alto, para llevar su contenido del carril
# nativo a la banda superior. Es negativo: la pieza se compone desplazada hacia arriba.
DESPLAZAMIENTO_SUPERIOR = BANDA_SUPERIOR[0] - CARRIL_VERTICAL[0]

# Tercera banda del control de posicion del editor (HF-4, paso 2): "Abajo". Se define pegada
# JUSTO DEBAJO del carril nativo, con su mismo alto (14 puntos de fraccion), en vez de inventar
# una medida nueva. No hay margen real ahi: el carril nativo termina en 0.68 y la franja de
# captions vertical empieza en 0.802, asi que esta banda cae de lleno en zona de captions en
# vertical (y tambien en horizontal, que empieza en 0.725). Es la opcion que el editor ofrece
# pero rechaza al guardar (ver motion_edicion.validar_plan): se deja en el selector, con su
# motivo, en vez de esconderla.
_ALTO_CARRIL = CARRIL_VERTICAL[1] - CARRIL_VERTICAL[0]
RANGO_INFERIOR = (CARRIL_VERTICAL[1], CARRIL_VERTICAL[1] + _ALTO_CARRIL)

# Cuanto hay que bajar la pieza para llevarla del carril nativo a la banda inferior. Positivo:
# la pieza se compone desplazada hacia abajo.
DESPLAZAMIENTO_INFERIOR = RANGO_INFERIOR[0] - CARRIL_VERTICAL[0]

# Rango ocupado (fraccion de alto) de cada banda. Mismos numeros para las dos orientaciones: ni
# el carril nativo ni la banda superior tienen CSS distinto por orientacion (D51). Lo que SI
# cambia por orientacion es contra que franja de captions se comparan, ver banda_invade_captions.
RANGO_POR_BANDA = {
    BANDA_CENTRO: CARRIL_VERTICAL,
    BANDA_ARRIBA: BANDA_SUPERIOR,
    BANDA_INFERIOR: RANGO_INFERIOR,
}


def banda_invade_captions(banda: str, orientacion: str) -> bool:
    """True si el rango de esa banda pisa la franja de captions DE ESA orientacion."""
    rango = RANGO_POR_BANDA.get(banda)
    zona = ZONA_CAPTIONS_POR_ORIENTACION.get(orientacion)
    return rango is not None and zona is not None and rango[1] > zona[0]


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


def zona_cara(tray_csv: Path | None, t0_ms: int, t1_ms: int) -> str | None:
    """Bucket de la cara en esa ventana, o None si no hay dato. Fail-open, ya existia en cve."""
    if not tray_csv:
        return None
    import cve  # noqa: PLC0415 (import perezoso: el planificador no arrastra el motor de captions)

    return cve.zona_cara_en_rango(tray_csv, t0_ms / 1000.0, t1_ms / 1000.0)


def banda_libre(orientacion: str, t0_ms: int, t1_ms: int, tray_csv: Path | None) -> str:
    """Banda donde va la pieza en esa ventana. SIEMPRE devuelve una: nunca omite.

    Solo se consulta la cara en 9:16: ahi las cinco piezas comparten un carril estrecho y una
    cara centrada o baja se lo come, asi que la pieza sube a la banda superior. Sin dato de cara
    se usa el carril nativo, que es el aprobado en el gate visual de HF-2.

    En 16:9 la cara NUNCA se consulta (ni se toca el reframe): un horizontal no pasa por el
    reencuadre y por tanto jamas trae trayectoria. El carril nativo (54-68% de alto) es el mismo
    HTML que en vertical, sin CSS por orientacion, y ahi caia el letrero antes de esto: la banda
    superior, que ya existia para la cara centrada/baja en 9:16, es tambien el destino sin dato
    de cara en 16:9.
    """
    if orientacion != "vertical":
        return BANDA_ARRIBA
    return BANDA_POR_ZONA_CARA.get(zona_cara(tray_csv, t0_ms, t1_ms), BANDA_SIN_DATO)


def colocar_bandas(
    piezas: tuple[Pieza, ...], *, orientacion: str, tray_csv: Path | None
) -> tuple[Pieza, ...]:
    """PASO ESPACIAL: reasigna SOLO `banda` sobre piezas ya temporizadas por
    `motion_plan.planificar()`. `t0_ms`/`t1_ms`/`plantilla`/`texto`/`tramo_t0` quedan intactos.

    Se corre una vez POR FORMATO pedido sobre la MISMA lista de piezas (el resultado de una
    unica llamada a `planificar()`): nunca vuelve a preguntarle nada al LLM ni a Pexels, y nunca
    reabre la busqueda de instantes libres que ya hizo `planificar()`.
    """
    return tuple(
        dataclasses.replace(p, banda=banda_libre(orientacion, p.t0_ms, p.t1_ms, tray_csv))
        for p in piezas
    )
