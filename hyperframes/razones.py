"""Vocabulario CERRADO de razones de fallo del Motor B (HF-1).

Un cliente (Auto v2 en HF-3) rutea por estas razones sin leer mensajes libres: la lista es
un contrato, no una sugerencia. Anadir una razon nueva es un cambio de contrato y rompe el
test que compara el conjunto exacto, que es justo lo que se quiere.
"""

from __future__ import annotations

from enum import StrEnum


class Razon(StrEnum):
    """Por que no hay MOV. StrEnum para serializar directo a JSON."""

    BINARIO_AUSENTE = "binario_ausente"
    CONTRATO_INVALIDO = "contrato_invalido"
    CAPACIDAD_NO_SOPORTADA = "capacidad_no_soportada"
    PLANTILLA_DESCONOCIDA = "plantilla_desconocida"
    TIMEOUT_RENDER = "timeout_render"
    RENDER_FALLIDO = "render_fallido"
    SALIDA_INVALIDA = "salida_invalida"
    CACHE_CORRUPTA = "cache_corrupta"
    LOCK_OCUPADO = "lock_ocupado"


RAZONES = frozenset(Razon)

__all__ = ["RAZONES", "Razon"]
