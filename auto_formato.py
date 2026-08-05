"""auto_formato.py — Formato de salida del Modo Automatico (HF-4, Paso 2 y 3).

`AutoConfig.formato` ("9:16" | "16:9" | "ambos") entra aqui y sale la lista de salidas a
producir para un clip: una por MP4 final. Es el UNICO lugar que decide si `reframe.reframe_clip`
corre, y con que sufijo se nombra cada salida. Ningun otro modulo toma esa decision.

Regla que protege la invariante de byte-identidad (Paso 6b de HF-4): la salida "9:16", cuando
esta pedida, es SIEMPRE la PRIMERA de la lista. `auto._procesar_clip`/`_procesar_clip_srt` y
`auto_v2.procesar_clip_v2` dependen de este orden para correr esa pierna por el codigo exacto
de siempre, sin ninguna condicion nueva de por medio.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Sufijo de nombre por formato. "9x16" es historico (auto._final_path); "16x9" es nuevo.
SUFIJO_POR_FORMATO = {"9:16": "9x16", "16:9": "16x9"}

# Un "16:9" pedido sobre una fuente que YA es vertical no tiene ruta de reencuadre en este
# repo: `reframe.py` solo sabe encuadrar HACIA 9:16 (reencuadre.py:OUTPUT_W/H fijos), nunca al
# reves. No es un bug de esta sesion ni se abre reframe.py para resolverlo (fuera de alcance,
# PROHIBIDO): los clips fuente del clipper son 16:9 por diseno (D11, F4.1), asi que este caso
# es el borde, no el camino comun. Se omite con motivo explicito, nunca en silencio.
MOTIVO_SIN_REFRAME_HORIZONTAL = "fuente_vertical_sin_ruta_de_reframe_horizontal"


@dataclass(frozen=True)
class SalidaFormato:
    """Una salida (un MP4) a producir para un clip."""

    formato: str  # "9:16" | "16:9"
    sufijo: str  # "9x16" | "16x9"
    necesita_reframe: bool


@dataclass(frozen=True)
class FormatosPedidos:
    """Lo que hay que producir, mas lo que se omitio y por que (nunca en silencio)."""

    salidas: tuple[SalidaFormato, ...]
    omitidos: tuple[dict, ...] = ()


def _orientacion_de(ancho: int, alto: int) -> str:
    return "vertical" if alto > ancho else "horizontal"


def formatos_pedidos(formato: str, *, src_ancho: int, src_alto: int) -> FormatosPedidos:
    """`formato` + dimensiones de la fuente -> que salidas producir, en orden.

    "9:16" pedido va SIEMPRE primero en la lista cuando esta presente. "16:9" pedido sobre una
    fuente horizontal nunca reencuadra (usa la fuente tal cual); sobre una fuente vertical se
    omite con `MOTIVO_SIN_REFRAME_HORIZONTAL`.
    """
    src_orientacion = _orientacion_de(src_ancho, src_alto)
    salidas: list[SalidaFormato] = []
    omitidos: list[dict] = []

    if formato in ("9:16", "ambos"):
        salidas.append(SalidaFormato("9:16", SUFIJO_POR_FORMATO["9:16"], necesita_reframe=True))

    if formato in ("16:9", "ambos"):
        if src_orientacion == "horizontal":
            salidas.append(
                SalidaFormato("16:9", SUFIJO_POR_FORMATO["16:9"], necesita_reframe=False)
            )
        else:
            omitidos.append({"formato": "16:9", "motivo": MOTIVO_SIN_REFRAME_HORIZONTAL})

    return FormatosPedidos(tuple(salidas), tuple(omitidos))


def ruta_final(clip: dict, paquete_dir: Path, sufijo: str, *, estilo: str) -> tuple[str, Path]:
    """Nombre canonico de una salida dentro del paquete. Generaliza `auto._final_path` (que
    sigue existiendo intacta, para sufijo="9x16") a cualquier sufijo de formato."""
    stem_fmt = f"{clip['archivo'].replace('.mp4', '')}_{sufijo}"
    return stem_fmt, paquete_dir / f"{stem_fmt}_{estilo}.mp4"


__all__ = [
    "MOTIVO_SIN_REFRAME_HORIZONTAL",
    "SUFIJO_POR_FORMATO",
    "FormatosPedidos",
    "SalidaFormato",
    "formatos_pedidos",
    "ruta_final",
]
