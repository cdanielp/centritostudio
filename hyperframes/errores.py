"""Excepciones del Motor B (HF-1).

Estas excepciones SI se lanzan en la validacion explicita, para que HF-2 vea el error al
construir el catalogo. La funcion de alto nivel `pedir_pieza` las captura todas y las
traduce a `razon_fallo`: un motion graphic que no sale jamas tumba un paquete de clips.
"""

from __future__ import annotations

from .razones import Razon


class HyperFramesError(Exception):
    """Base de los errores del Motor B. Cada subclase declara su razon del vocabulario."""

    razon: Razon = Razon.RENDER_FALLIDO


class ContratoInvalido(HyperFramesError):
    """El JSON de la pieza no cumple el esquema (campo faltante, desconocido o mal tipado)."""

    razon = Razon.CONTRATO_INVALIDO


class CapacidadNoSoportada(HyperFramesError):
    """La pieza es valida pero la ruta de clips de Centrito no puede consumirla hoy."""

    razon = Razon.CAPACIDAD_NO_SOPORTADA


class PlantillaDesconocida(HyperFramesError):
    """El catalogo no declara esa plantilla en esa version."""

    razon = Razon.PLANTILLA_DESCONOCIDA


class EntornoIlegible(HyperFramesError):
    """No se pudieron leer las versiones del entorno. Nunca se inventa un valor por defecto:
    un default falso haria que la cache sirviera un MOV renderizado con otro Chrome."""

    razon = Razon.BINARIO_AUSENTE


__all__ = [
    "CapacidadNoSoportada",
    "ContratoInvalido",
    "EntornoIlegible",
    "HyperFramesError",
    "PlantillaDesconocida",
]
