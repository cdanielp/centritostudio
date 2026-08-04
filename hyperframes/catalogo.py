"""Catalogo de plantillas del Motor B (HF-1).

HF-1 define QUE debe declarar una plantilla para ser valida; el contenido del catalogo lo
escribe HF-2. Una plantilla declara cuatro cosas y nada mas:

  nombre       identificador estable (el contrato de pieza lo referencia)
  version      cambiarla invalida la cache de todas las piezas que la usan
  slots_texto  los slots que su HTML sabe pintar; el validador exige que el contrato
               traiga exactamente esos, ni uno menos ni uno de mas
  proyecto     mapa de orientacion a ruta del proyecto HyperFrames que se renderiza

Sin `slots_texto` declarados no hay forma de detectar un typo en un paquete: `titluo` se
renderizaria como un titulo vacio en silencio.

`proyecto` es un MAPA por orientacion y no una ruta unica (decision de K al cerrar HF-2). Un
solo proyecto no puede servir los dos lienzos: HyperFrames fija el tamano con los `data-width`
y `data-height` ESTATICOS del HTML, y un script que los reescriba se ignora sin error, con lo
que la pieza sale a 1080x1920 y codigo 0 aunque se haya pedido 16:9. La convencion de ruta
`proyecto + "/horizontal"` que uso HF-2 era un puente para no tocar este modulo; aqui muere.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .errores import PlantillaDesconocida

CAMPOS_PLANTILLA = ("nombre", "version", "slots_texto", "proyecto")
ORIENTACIONES = ("vertical", "horizontal")


@dataclass(frozen=True)
class Plantilla:
    """Una plantilla declarada por HF-2 y consumible por el invocador.

    `proyecto` es la ruta del proyecto de la orientacion con la que se cargo el catalogo. Es un
    string y no un mapa a proposito: el invocador construye UN comando para UNA pieza y no tiene
    por que saber que existen dos lienzos. Quien elige es `Catalogo.desde_archivo`.
    """

    nombre: str
    version: str
    slots_texto: tuple[str, ...]
    proyecto: str

    @property
    def clave(self) -> tuple[str, str]:
        return (self.nombre, self.version)


class Catalogo:
    """Coleccion de plantillas indexada por (nombre, version)."""

    def __init__(self, plantillas: list[Plantilla] | None = None) -> None:
        self._por_clave = {p.clave: p for p in (plantillas or [])}

    def __len__(self) -> int:
        return len(self._por_clave)

    def buscar(self, nombre: str, version: str) -> Plantilla | None:
        """Plantilla exacta, o None si el catalogo no la declara en esa version."""
        return self._por_clave.get((nombre, version))

    def exigir(self, nombre: str, version: str) -> Plantilla:
        """Como `buscar`, pero lanza PlantillaDesconocida nombrando lo que si hay."""
        encontrada = self.buscar(nombre, version)
        if encontrada is not None:
            return encontrada
        disponibles = ", ".join(f"{n}@{v}" for n, v in sorted(self._por_clave)) or "ninguna"
        raise PlantillaDesconocida(
            f"el catalogo no declara la plantilla '{nombre}' version '{version}'. "
            f"Declaradas: {disponibles}."
        )

    @classmethod
    def desde_archivo(cls, ruta: Path, orientacion: str = "vertical") -> Catalogo:
        """Carga el catalogo para UNA orientacion (formato de HF-2 con `proyecto` como mapa)."""
        if orientacion not in ORIENTACIONES:
            raise PlantillaDesconocida(
                f"orientacion invalida: {orientacion!r} (usa {', '.join(ORIENTACIONES)})"
            )
        ruta = Path(ruta)
        if not ruta.is_file():
            return cls([])
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        return cls([cls._plantilla_desde(d, ruta, orientacion) for d in datos])

    @staticmethod
    def _plantilla_desde(dato: object, ruta: Path, orientacion: str) -> Plantilla:
        if not isinstance(dato, dict) or set(dato) != set(CAMPOS_PLANTILLA):
            raise PlantillaDesconocida(
                f"{ruta.name}: cada plantilla declara exactamente "
                f"{', '.join(CAMPOS_PLANTILLA)}; se recibio {dato!r}"
            )
        proyectos = dato["proyecto"]
        if not isinstance(proyectos, dict) or set(proyectos) != set(ORIENTACIONES):
            raise PlantillaDesconocida(
                f"{ruta.name}: plantilla '{dato.get('nombre')}': proyecto debe declarar "
                f"exactamente {', '.join(ORIENTACIONES)}; se recibio {proyectos!r}"
            )
        proyecto = proyectos[orientacion]
        if not isinstance(proyecto, str) or not proyecto.strip():
            raise PlantillaDesconocida(
                f"{ruta.name}: plantilla '{dato.get('nombre')}': proyecto.{orientacion} debe ser "
                f"una ruta no vacia; se recibio {proyecto!r}"
            )
        return Plantilla(
            nombre=str(dato["nombre"]),
            version=str(dato["version"]),
            slots_texto=tuple(dato["slots_texto"]),
            proyecto=proyecto,
        )


__all__ = ["CAMPOS_PLANTILLA", "ORIENTACIONES", "Catalogo", "Plantilla"]
