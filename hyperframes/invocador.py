"""Invocador del CLI de HyperFrames (HF-1).

El comando se CONSTRUYE y se devuelve como lista, igual que hace el repo con FFmpeg: asi es
dato inspeccionable y fijable en un test, no una cadena que se arma dentro de un subprocess.

La salida se fuerza a MOV ProRes 4444 (`yuva444p12le`). WebM VP9 no se ofrece: HF-0 midio
que su `pix_fmt` declara `yuv420p` y que, sin `-c:v libvpx-vp9` explicito, FFmpeg pierde el
canal alfa en silencio, sin error ni aviso.

Todo lo que toca el mundo exterior (proceso, ffprobe, versiones, PATH) entra por `Adaptador`,
de modo que la suite corre entera sin HyperFrames instalado y sin renderizar nada.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import contrato as ct
from .catalogo import Plantilla
from .razones import Razon

BINARIO_DEFAULT = "npx"
FORMATO = "mov"
CALIDAD = "high"
PIX_FMT_ESPERADO = "yuva444p12le"
TIMEOUT_DEFAULT_S = 180  # HF-0: un overlay de 6 s tardo 14.9 s en esta maquina
TOLERANCIA_MS = 120  # un MOV real no cae al milisegundo exacto
CAMPOS_VARIABLES = ("duracion_ms", "fps", "marca", "semilla", "tamano", "texto")


@dataclass(frozen=True)
class Ejecucion:
    """Resultado crudo de correr el CLI."""

    codigo: int
    salida: str = ""
    error: str = ""
    expiro: bool = False


@dataclass(frozen=True)
class Render:
    """Resultado de renderizar una pieza a un archivo temporal."""

    razon: Razon | None
    sondeo: dict = field(default_factory=dict)
    segundos: float = 0.0
    detalle: str = ""


@dataclass(frozen=True)
class Adaptador:
    """Frontera con el exterior. Los tests pasan dobles; produccion usa `adaptador_real`."""

    ejecutar: Callable[[list[str], float], Ejecucion]
    sondear: Callable[[Path], dict]
    leer_entorno: Callable[[], dict]
    localizar: Callable[[str], str | None]


def variables_json(dato: dict) -> str:
    """JSON canonico con lo que la plantilla necesita para pintarse (`--variables`)."""
    return ct.canonicalizar({campo: dato[campo] for campo in CAMPOS_VARIABLES if campo in dato})


def construir_comando(
    dato: dict, plantilla: Plantilla, salida: Path | str, *, binario: str = BINARIO_DEFAULT
) -> list[str]:
    """Comando completo del CLI para renderizar la pieza a `salida`.

    `--fps` sale del contrato, no de un default: HF-0 midio que la cadena de clips fuerza el
    fps del video base, asi que una pieza a 30 sobre un destino a 24 pierde 1 de cada 5
    frames de animacion. La pieza se renderiza directamente al fps del destino.
    """
    return [
        binario,
        "hyperframes",
        "render",
        plantilla.proyecto,
        "--format",
        FORMATO,
        "--quality",
        CALIDAD,
        "--fps",
        str(dato["fps"]),
        "--output",
        str(salida),
        "--variables",
        variables_json(dato),
        "--no-best-effort",
    ]


def _verificar_salida(dato: dict, sondeo: dict) -> str:
    """Devuelve el primer desvio encontrado, o cadena vacia si la salida es la esperada."""
    if sondeo.get("pix_fmt") != PIX_FMT_ESPERADO:
        return f"pix_fmt {sondeo.get('pix_fmt')!r} en vez de {PIX_FMT_ESPERADO!r}"
    if sondeo.get("fps") != dato["fps"]:
        return f"fps {sondeo.get('fps')!r} en vez de {dato['fps']!r}"
    ancho, alto = sondeo.get("ancho"), sondeo.get("alto")
    if (ancho, alto) != (dato["tamano"]["ancho"], dato["tamano"]["alto"]):
        return f"tamano {ancho}x{alto} en vez de {dato['tamano']['ancho']}x{dato['tamano']['alto']}"
    desvio = abs(int(sondeo.get("duracion_ms") or 0) - dato["duracion_ms"])
    if desvio > TOLERANCIA_MS:
        return f"duracion {sondeo.get('duracion_ms')} ms se aleja {desvio} ms de la pedida"
    return ""


def _descartar(ruta: Path) -> None:
    try:
        Path(ruta).unlink()
    except OSError:
        pass


def renderizar(
    dato: dict,
    plantilla: Plantilla,
    salida: Path,
    adaptador: Adaptador,
    *,
    timeout_s: float = TIMEOUT_DEFAULT_S,
    binario: str = BINARIO_DEFAULT,
) -> Render:
    """Renderiza la pieza a `salida` y verifica el archivo producido.

    Cualquier desvio descarta el archivo: mas vale no tener pieza que tener una sin alfa,
    que se compondria como un rectangulo opaco tapando el video.
    """
    salida = Path(salida)
    comando = construir_comando(dato, plantilla, salida, binario=binario)
    arranque = time.perf_counter()
    ejecucion = adaptador.ejecutar(comando, timeout_s)
    segundos = time.perf_counter() - arranque

    if ejecucion.expiro:
        _descartar(salida)
        return Render(Razon.TIMEOUT_RENDER, segundos=segundos, detalle=f"supero {timeout_s}s")
    if ejecucion.codigo != 0:
        _descartar(salida)
        return Render(
            Razon.RENDER_FALLIDO,
            segundos=segundos,
            detalle=f"codigo {ejecucion.codigo}: {(ejecucion.error or '')[-2000:]}",
        )
    if not salida.is_file() or salida.stat().st_size == 0:
        _descartar(salida)
        return Render(Razon.SALIDA_INVALIDA, segundos=segundos, detalle="no se escribio el MOV")
    try:
        sondeo = adaptador.sondear(salida)
    except Exception as exc:  # noqa: BLE001 - cualquier fallo de ffprobe es salida invalida
        _descartar(salida)
        return Render(Razon.SALIDA_INVALIDA, segundos=segundos, detalle=f"ffprobe fallo: {exc}")

    desvio = _verificar_salida(dato, sondeo)
    if desvio:
        _descartar(salida)
        return Render(Razon.SALIDA_INVALIDA, sondeo=sondeo, segundos=segundos, detalle=desvio)
    return Render(None, sondeo=sondeo, segundos=segundos)


# ───────────────────────────── adaptador real ────────────────────────────


def _ejecutar_real(comando: list[str], timeout: float) -> Ejecucion:
    """Corre el CLI de verdad. Un timeout no es una excepcion: es un resultado tipado."""
    try:
        proceso = subprocess.run(
            comando,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return Ejecucion(codigo=-1, expiro=True)
    except OSError as exc:
        return Ejecucion(codigo=-1, error=str(exc))
    return Ejecucion(
        codigo=proceso.returncode, salida=proceso.stdout or "", error=proceso.stderr or ""
    )


def _sondear_real(ruta: Path) -> dict:
    """ffprobe del MOV producido: pix_fmt, tamano, fps y duracion en ms."""
    salida = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=pix_fmt,width,height,r_frame_rate:format=duration",
            "-of",
            "json",
            str(ruta),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    datos = json.loads(salida)
    flujo = (datos.get("streams") or [{}])[0]
    numerador, _, denominador = (flujo.get("r_frame_rate") or "0/1").partition("/")
    fps = int(round(int(numerador) / int(denominador or 1)))
    duracion = float((datos.get("format") or {}).get("duration") or 0.0)
    return {
        "pix_fmt": flujo.get("pix_fmt"),
        "ancho": flujo.get("width"),
        "alto": flujo.get("height"),
        "fps": fps,
        "duracion_ms": int(round(duracion * 1000)),
    }


def adaptador_real(binario: str = BINARIO_DEFAULT) -> Adaptador:
    """Adaptador de produccion: subprocess, ffprobe, doctor y `shutil.which`.

    El binario se resuelve UNA vez a su ruta completa. En Windows `npx` es `npx.CMD` y
    `CreateProcess` no aplica PATHEXT: pasar el literal "npx" a subprocess falla con
    WinError 2 aunque `which` lo encuentre. Medido en HF-1 sobre esta maquina.
    """
    import shutil  # noqa: PLC0415

    from .entorno import leer_entorno  # noqa: PLC0415

    resuelto = shutil.which(binario) or binario
    return Adaptador(
        ejecutar=_ejecutar_real,
        sondear=_sondear_real,
        leer_entorno=lambda: leer_entorno(resuelto),
        localizar=shutil.which,
    )


__all__ = [
    "BINARIO_DEFAULT",
    "PIX_FMT_ESPERADO",
    "TIMEOUT_DEFAULT_S",
    "TOLERANCIA_MS",
    "Adaptador",
    "Ejecucion",
    "Render",
    "adaptador_real",
    "construir_comando",
    "renderizar",
    "variables_json",
]
