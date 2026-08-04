"""Motor B: contrato de datos entre Centrito y HyperFrames (HF-1).

Paquete HUERFANO por diseno: ningun modulo del pipeline lo importa todavia. Existe para que
HF-3 pueda pedir una pieza de motion graphics sin saber que debajo hay un navegador, un CLI
de node y un formato de video con canal alfa.

Uso previsto (HF-3):

    from hyperframes import pedir_pieza
    from hyperframes.catalogo import Catalogo

    r = pedir_pieza(
        contrato_de_pieza,
        destino=(1920, 1080),
        catalogo=Catalogo.desde_archivo(Path("motion/catalogo.json")),
        raiz_cache=Path("output/.piezas"),
    )
    if r.razon_fallo is None:
        # r.ruta_mov es un MOV ProRes 4444 con alfa listo para la ruta de clips.
        # r.consumo_sugerido trae los ajustes de invocacion medidos en HF-0.
        ...

`pedir_pieza` nunca lanza. `validar_contrato` SI lanza: HF-2 necesita ver el error al
construir el catalogo, no un resultado silencioso.
"""

from __future__ import annotations

from .capacidad import PERFIL_RUTA_CLIPS, verificar_capacidad
from .catalogo import Catalogo, Plantilla
from .contrato import calcular_hash, canonicalizar, validar_contrato
from .razones import RAZONES, Razon
from .servicio import CONSUMO_SUGERIDO, Resultado, pedir_pieza

__all__ = [
    "CONSUMO_SUGERIDO",
    "PERFIL_RUTA_CLIPS",
    "RAZONES",
    "Catalogo",
    "Plantilla",
    "Razon",
    "Resultado",
    "calcular_hash",
    "canonicalizar",
    "pedir_pieza",
    "validar_contrato",
    "verificar_capacidad",
]
