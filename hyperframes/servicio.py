"""`pedir_pieza`: la unica funcion que HF-3 (Auto v2) va a llamar (HF-1).

Contrato: NUNCA lanza por un fallo de render. Devuelve un `Resultado` con `ruta_mov=None` y
una `razon_fallo` del vocabulario cerrado. Es la regla de oro 8 del repo (fail-open del
cerebro) aplicada al Motor B: un motion graphic que no sale no puede tumbar un paquete de
clips que por lo demas esta bien.

El pedido pasa por seis puertas antes de renderizar (binario, entorno, esquema, plantilla,
slots, capacidad) y solo despues mira la cache. Las puertas van primero porque son baratas y
porque una pieza que la ruta de clips no puede consumir no debe ni ocupar espacio en disco.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import almacen
from . import contrato as ct
from .capacidad import verificar_capacidad
from .catalogo import Catalogo, Plantilla
from .errores import HyperFramesError
from .invocador import (
    BINARIO_DEFAULT,
    TIMEOUT_DEFAULT_S,
    Adaptador,
    adaptador_real,
    renderizar,
)
from .razones import Razon

# Ajustes de invocacion medidos en HF-0. Viajan en el resultado para que HF-3 no tenga que
# redescubrirlos: `fade=False` porque la plantilla YA trae su animacion de entrada y salida,
# y el fade de 0.20 s de la ruta de clips se sumaria encima produciendo doble entrada;
# `fit="cover"` y `mute=True` porque son los unicos valores que esa ruta admite hoy.
CONSUMO_SUGERIDO = {"fade": False, "fit": "cover", "mute": True}


@dataclass(frozen=True)
class Resultado:
    """Lo que recibe el cliente. Serializable a JSON con `a_dict()`."""

    hash: str | None = None
    ruta_mov: Path | None = None
    desde_cache: bool = False
    pix_fmt: str | None = None
    duracion_ms_real: int | None = None
    fps_real: int | None = None
    sha256: str | None = None
    entorno: dict = field(default_factory=dict)
    segundos_render: float = 0.0
    razon_fallo: Razon | None = None
    detalle: str = ""
    incidencias: tuple[Razon, ...] = ()
    consumo_sugerido: dict = field(default_factory=lambda: dict(CONSUMO_SUGERIDO))

    def a_dict(self) -> dict:
        """Version serializable (Path a str, Razon a su valor)."""
        return {
            "hash": self.hash,
            "ruta_mov": str(self.ruta_mov) if self.ruta_mov else None,
            "desde_cache": self.desde_cache,
            "pix_fmt": self.pix_fmt,
            "duracion_ms_real": self.duracion_ms_real,
            "fps_real": self.fps_real,
            "sha256": self.sha256,
            "entorno": dict(self.entorno),
            "segundos_render": self.segundos_render,
            "razon_fallo": self.razon_fallo.value if self.razon_fallo else None,
            "detalle": self.detalle,
            "incidencias": [r.value for r in self.incidencias],
            "consumo_sugerido": dict(self.consumo_sugerido),
        }


def _fallo(razon: Razon, detalle: str, incidencias: tuple, hash_: str | None = None) -> Resultado:
    return Resultado(hash=hash_, razon_fallo=razon, detalle=detalle, incidencias=incidencias)


def _desde_hit(hit: almacen.Hit, hash_: str, entorno: dict, incidencias: tuple) -> Resultado:
    side = hit.sidecar
    return Resultado(
        hash=hash_,
        ruta_mov=hit.ruta,
        desde_cache=True,
        pix_fmt=side.get("pix_fmt"),
        duracion_ms_real=side.get("duracion_ms"),
        fps_real=side.get("fps"),
        sha256=side.get("sha256"),
        entorno=entorno,
        segundos_render=0.0,
        incidencias=incidencias,
    )


def _preparar(dato: object, destino: tuple[int, int], catalogo: Catalogo) -> Plantilla:
    """Las cuatro puertas de validacion. Lanza HyperFramesError con su razon."""
    ct.validar_contrato(dato)
    plantilla = catalogo.exigir(dato["plantilla"]["nombre"], dato["plantilla"]["version"])
    ct.validar_slots(dato, plantilla.slots_texto)
    verificar_capacidad(dato, destino)
    return plantilla


def pedir_pieza(
    dato: object,
    *,
    destino: tuple[int, int],
    catalogo: Catalogo,
    raiz_cache: Path,
    adaptador: Adaptador | None = None,
    timeout_s: float = TIMEOUT_DEFAULT_S,
    espera_lock_s: float = 30.0,
    binario: str = BINARIO_DEFAULT,
) -> Resultado:
    """Devuelve la pieza lista para componer, desde cache o renderizandola. Nunca lanza."""
    adaptador = adaptador or adaptador_real(binario)
    incidencias: tuple[Razon, ...] = ()

    ruta_binario = adaptador.localizar(binario)
    if not ruta_binario:
        return _fallo(Razon.BINARIO_AUSENTE, f"no se encontro '{binario}' en el PATH", incidencias)
    try:
        entorno = adaptador.leer_entorno()
    except HyperFramesError as exc:
        return _fallo(exc.razon, str(exc), incidencias)

    try:
        plantilla = _preparar(dato, destino, catalogo)
    except HyperFramesError as exc:
        return _fallo(exc.razon, str(exc), incidencias)

    hash_ = ct.calcular_hash(dato, entorno)
    hit = almacen.buscar(raiz_cache, hash_)
    if hit.razon is not None:
        incidencias += (hit.razon,)
    if hit.encontrado:
        return _desde_hit(hit, hash_, entorno, incidencias)

    return _renderizar_con_lock(
        dato,
        plantilla,
        hash_,
        entorno,
        incidencias,
        raiz_cache=raiz_cache,
        adaptador=adaptador,
        timeout_s=timeout_s,
        espera_lock_s=espera_lock_s,
        binario=ruta_binario,
    )


def _renderizar_con_lock(
    dato: dict,
    plantilla: Plantilla,
    hash_: str,
    entorno: dict,
    incidencias: tuple[Razon, ...],
    *,
    raiz_cache: Path,
    adaptador: Adaptador,
    timeout_s: float,
    espera_lock_s: float,
    binario: str,
) -> Resultado:
    """Toma el lock del hash y renderiza. Si otro proceso gano la carrera, sirve su resultado."""
    # El umbral de rancio sale del MISMO timeout con el que se renderiza: si se desincronizan,
    # una corrida viva puede ver su lock reclamado por otra.
    with almacen.lock(raiz_cache, hash_, espera_s=espera_lock_s, timeout_s=timeout_s) as tomado:
        if not tomado:
            return _fallo(
                Razon.LOCK_OCUPADO,
                f"otra corrida esta renderizando la misma pieza y no se libero en {espera_lock_s}s",
                incidencias,
                hash_,
            )
        # Otro proceso pudo publicarla mientras esperabamos el lock.
        hit = almacen.buscar(raiz_cache, hash_)
        if hit.razon is not None:
            incidencias += (hit.razon,)
        if hit.encontrado:
            return _desde_hit(hit, hash_, entorno, incidencias)

        with almacen.temporal(raiz_cache, hash_) as temp:
            render = renderizar(
                dato, plantilla, temp, adaptador, timeout_s=timeout_s, binario=binario
            )
            if render.razon is not None:
                return _fallo(render.razon, render.detalle, incidencias, hash_)
            mov = almacen.publicar(
                raiz_cache,
                hash_,
                temp,
                contrato=dato,
                entorno=entorno,
                sondeo=render.sondeo,
                segundos_render=render.segundos,
            )

    return Resultado(
        hash=hash_,
        ruta_mov=mov,
        desde_cache=False,
        pix_fmt=render.sondeo.get("pix_fmt"),
        duracion_ms_real=render.sondeo.get("duracion_ms"),
        fps_real=render.sondeo.get("fps"),
        sha256=almacen.sha256_de(mov),
        entorno=entorno,
        segundos_render=round(render.segundos, 3),
        incidencias=incidencias,
    )


__all__ = ["CONSUMO_SUGERIDO", "Resultado", "pedir_pieza"]
