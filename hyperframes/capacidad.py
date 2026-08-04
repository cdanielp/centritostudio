"""Perfil de capacidad: que puede consumir HOY la ruta de clips de Centrito (HF-1).

Validar el esquema no basta. Una pieza puede ser un contrato perfectamente valido y aun asi
imposible de componer, porque `clip_overlay.py` tiene limites propios que HF-1 no toca.
El perfil vive en UNA constante inspeccionable, y cada rechazo NOMBRA la linea que impone el
limite para que HF-3 sepa exactamente que desbloquear en vez de ir a buscarlo.

Medido en HF-0 sobre el filter_complex real de un overlay de 1920x1080 con alfa.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errores import CapacidadNoSoportada


@dataclass(frozen=True)
class Limite:
    """Un limite de la ruta de clips: que campo, que se admite y quien lo impone."""

    campo: str
    admitido: str
    referencia: str
    motivo: str


PERFIL_RUTA_CLIPS: dict[str, Limite] = {
    "posicion_modo": Limite(
        campo="posicion.modo",
        admitido="cuadro_completo",
        referencia="clip_overlay.py:144",
        motivo=(
            "el overlay se compone con x=(W-w)/2:y=(H-h)/2 fijo al centro, "
            "asi que no hay forma de colocar un grafico sub-cuadro"
        ),
    ),
    "fit": Limite(
        campo="fit",
        admitido="nativo",
        referencia="clip_overlay.py:20",
        motivo=(
            "FIT_VALIDOS solo admite 'cover', que siempre escala y recorta a la caja; "
            "una pieza a tamano nativo solo sobrevive si ya mide igual que el destino"
        ),
    ),
    "audio": Limite(
        campo="audio",
        admitido="false",
        referencia="clip_overlay.py:73",
        motivo=(
            "validar_clip_overlay exige mute=True y el render mapea solo 0:a, "
            "asi que el audio de la pieza jamas entraria a la mezcla"
        ),
    ),
    "tamano": Limite(
        campo="tamano",
        admitido="igual al tamano del video destino",
        referencia="clip_overlay.py:124",
        motivo=(
            "el encaje cover escala a la caja y recorta el excedente; "
            "si la pieza no mide igual que el destino se deforma el encuadre"
        ),
    ),
}


def _rechazar(limite: Limite, recibido: str) -> None:
    raise CapacidadNoSoportada(
        f"{limite.campo}={recibido} no es consumible por la ruta de clips de Centrito. "
        f"Se admite {limite.admitido}. Lo impone {limite.referencia}: {limite.motivo}."
    )


def verificar_capacidad(dato: dict, destino: tuple[int, int]) -> None:
    """Comprueba la pieza contra PERFIL_RUTA_CLIPS. Lanza CapacidadNoSoportada.

    `destino` es (ancho, alto) del video sobre el que se va a componer.
    """
    modo = (dato.get("posicion") or {}).get("modo")
    if modo != PERFIL_RUTA_CLIPS["posicion_modo"].admitido:
        _rechazar(PERFIL_RUTA_CLIPS["posicion_modo"], str(modo))

    fit = dato.get("fit")
    if fit != PERFIL_RUTA_CLIPS["fit"].admitido:
        _rechazar(PERFIL_RUTA_CLIPS["fit"], str(fit))

    if dato.get("audio") is not False:
        _rechazar(PERFIL_RUTA_CLIPS["audio"], str(dato.get("audio")).lower())

    tamano = dato.get("tamano") or {}
    pieza = (tamano.get("ancho"), tamano.get("alto"))
    if pieza != tuple(destino):
        _rechazar(
            PERFIL_RUTA_CLIPS["tamano"],
            f"{pieza[0]}x{pieza[1]} sobre un destino de {destino[0]}x{destino[1]}",
        )


__all__ = ["PERFIL_RUTA_CLIPS", "Limite", "verificar_capacidad"]
