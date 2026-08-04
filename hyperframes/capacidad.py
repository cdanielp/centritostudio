"""Perfil de capacidad: que puede consumir HOY la ruta de clips de Centrito (HF-1, ampliado HF-3).

Validar el esquema no basta. Una pieza puede ser un contrato perfectamente valido y aun asi
imposible de componer, porque `clip_overlay.py` tiene limites propios que HF-1 no toca.
El perfil vive en UNA constante inspeccionable, y cada rechazo NOMBRA la linea que impone el
limite para que quede claro que hay que desbloquear en vez de ir a buscarlo.

Medido en HF-0 sobre el filter_complex real de un overlay de 1920x1080 con alfa. HF-3 levanto
tres de los cuatro limites (`fit=nativo`, `posicion.modo=caja` y el tamano ligado a la caja);
el del audio sigue en pie porque lo impone el mapeo `0:a` del render, no `clip_overlay`.
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
        admitido="cuadro_completo o caja",
        referencia="clip_overlay.py:overlay_clip",
        motivo=(
            "el overlay se compone centrado cuando no se da posicion y en (x, y) literales "
            "cuando si; cualquier otro modo no tiene traduccion a ese filtro"
        ),
    ),
    "fit": Limite(
        campo="fit",
        admitido="nativo o cover",
        referencia="clip_overlay.py:FIT_VALIDOS",
        motivo=(
            "'nativo' compone la pieza con sus propios pixeles y 'cover' escala y recorta a la "
            "caja; 'contain' sigue sin implementarse en la cadena de clips"
        ),
    ),
    "audio": Limite(
        campo="audio",
        admitido="false",
        referencia="core_ass.burn_video_with_emojis (mapeo -map 0:a)",
        motivo=(
            "el render mapea SOLO el audio original, asi que el audio de la pieza se descartaria "
            "en silencio; aceptarlo seria mentirle al llamador"
        ),
    ),
    "tamano": Limite(
        campo="tamano",
        admitido="igual al destino en cuadro_completo, igual a la caja en modo caja",
        referencia="clip_overlay.py:filtro_clip",
        motivo=(
            "con fit nativo no hay escalado: la pieza ocupa exactamente los pixeles que trae, "
            "asi que declarar otro tamano la descuadraria respecto de donde se coloca"
        ),
    ),
}


def _rechazar(limite: Limite, recibido: str) -> None:
    raise CapacidadNoSoportada(
        f"{limite.campo}={recibido} no es consumible por la ruta de clips de Centrito. "
        f"Se admite {limite.admitido}. Lo impone {limite.referencia}: {limite.motivo}."
    )


def _tamano_esperado(posicion: dict, destino: tuple[int, int]) -> tuple[int, int]:
    """Que tamano debe declarar la pieza segun donde se va a colocar."""
    if posicion.get("modo") == "caja":
        return (posicion.get("ancho"), posicion.get("alto"))
    return tuple(destino)


def verificar_capacidad(dato: dict, destino: tuple[int, int]) -> None:
    """Comprueba la pieza contra PERFIL_RUTA_CLIPS. Lanza CapacidadNoSoportada.

    `destino` es (ancho, alto) del video sobre el que se va a componer.
    """
    from clip_overlay import FIT_VALIDOS as FIT_RUTA_CLIPS  # noqa: PLC0415

    posicion = dato.get("posicion") or {}
    modo = posicion.get("modo")
    if modo not in ("cuadro_completo", "caja"):
        _rechazar(PERFIL_RUTA_CLIPS["posicion_modo"], str(modo))

    # 'nativo' del contrato = componer sin escalar, que es exactamente el fit del mismo nombre
    # de la ruta de clips. La lista se lee de `clip_overlay` y no se copia: dos listas separadas
    # se desincronizan y el perfil terminaria mintiendo sobre lo que la ruta admite.
    fit = dato.get("fit")
    if fit not in FIT_RUTA_CLIPS:
        _rechazar(PERFIL_RUTA_CLIPS["fit"], str(fit))

    if dato.get("audio") is not False:
        _rechazar(PERFIL_RUTA_CLIPS["audio"], str(dato.get("audio")).lower())

    tamano = dato.get("tamano") or {}
    pieza = (tamano.get("ancho"), tamano.get("alto"))
    esperado = _tamano_esperado(posicion, destino)
    if pieza != esperado:
        _rechazar(
            PERFIL_RUTA_CLIPS["tamano"],
            f"{pieza[0]}x{pieza[1]} donde se esperaba {esperado[0]}x{esperado[1]}",
        )


__all__ = ["PERFIL_RUTA_CLIPS", "Limite", "verificar_capacidad"]
