"""Dobles y datos compartidos de los tests HF-1.

Ningun test de HF-1 necesita HyperFrames instalado ni renderiza nada: el CLI se sustituye
por `ProcesoFalso` y ffprobe por `sondeo_falso`. El unico test que renderiza de verdad
va marcado `@pytest.mark.hf_real` y esta excluido por default (ver pytest.ini).
"""

from __future__ import annotations

from pathlib import Path

from hyperframes.invocador import Adaptador, Ejecucion

PIEZA_OK = {
    "contrato": 1,
    "pieza_id": "hook_principal",
    "plantilla": {"nombre": "hook", "version": "1.0.0"},
    "estilo": "pms",
    "duracion_ms": 6000,
    "fps": 30,
    "tamano": {"ancho": 1920, "alto": 1080},
    "texto": {"titulo": "Configuracion basica", "subtitulo": "ano 2026"},
    "marca": {"primario": "#FF5A2B", "secundario": "#111111", "texto": "#FFFFFF"},
    "posicion": {"modo": "cuadro_completo"},
    "fit": "nativo",
    "audio": False,
    "semilla": 0,
}

ENTORNO = {
    "hyperframes": "0.7.90",
    "node": "v24.18.0",
    "chromium": "152.0.7928.2",
    "ffmpeg": "8.0-essentials_build-www.gyan.dev",
}

DESTINO = (1920, 1080)

SONDEO_OK = {
    "pix_fmt": "yuva444p12le",
    "duracion_ms": 6000,
    "fps": 30,
    "ancho": 1920,
    "alto": 1080,
}


def pieza(**cambios) -> dict:
    """Copia de PIEZA_OK con los campos indicados sustituidos."""
    d = {k: (v.copy() if isinstance(v, dict) else v) for k, v in PIEZA_OK.items()}
    d.update(cambios)
    return d


def salida_de(cmd: list[str]) -> Path | None:
    """Ruta que el comando pide escribir (`--output`). None si el comando no la lleva."""
    if "--output" not in cmd:
        return None
    return Path(cmd[cmd.index("--output") + 1])


class ProcesoFalso:
    """Doble del CLI de HyperFrames: cuenta llamadas y escribe un archivo en `--output`."""

    def __init__(
        self,
        *,
        codigo: int = 0,
        expiro: bool = False,
        escribe: bool = True,
        error: str = "",
        antes=None,
    ) -> None:
        self.codigo = codigo
        self.expiro = expiro
        self.escribe = escribe
        self.error = error
        self.antes = antes  # callable(cmd) ejecutado antes de responder (para concurrencia)
        self.llamadas: list[list[str]] = []

    def __call__(self, cmd: list[str], timeout: float) -> Ejecucion:
        self.llamadas.append(list(cmd))
        if self.antes is not None:
            self.antes(cmd)
        if self.expiro:
            return Ejecucion(codigo=-1, expiro=True)
        destino = salida_de(cmd)
        if self.escribe and destino is not None and self.codigo == 0:
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(b"MOV-FALSO-" + destino.name.encode("ascii", "ignore"))
        return Ejecucion(codigo=self.codigo, error=self.error)

    @property
    def veces(self) -> int:
        return len(self.llamadas)


def sondeo_falso(**cambios):
    """Doble de ffprobe: devuelve SONDEO_OK con los campos indicados sustituidos."""
    datos = dict(SONDEO_OK, **cambios)
    return lambda _ruta: dict(datos)


def adaptador(
    proceso: ProcesoFalso | None = None,
    *,
    sondeo=None,
    entorno: dict | None = None,
    binario: str | None = "C:\\fake\\npx.cmd",
) -> Adaptador:
    """Adaptador completo con dobles. `binario=None` simula HyperFrames no instalado."""
    return Adaptador(
        ejecutar=proceso or ProcesoFalso(),
        sondear=sondeo or sondeo_falso(),
        leer_entorno=lambda: dict(entorno if entorno is not None else ENTORNO),
        localizar=lambda _nombre: binario,
    )
