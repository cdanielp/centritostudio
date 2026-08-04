"""Catalogo de plantillas del Motor B (HF-1).

HF-1 define QUE debe declarar una plantilla para ser valida; el contenido del catalogo lo
escribe HF-2. Una plantilla declara cuatro cosas y nada mas:

  nombre       identificador estable (el contrato de pieza lo referencia)
  version      cambiarla invalida la cache de todas las piezas que la usan
  slots_texto  los slots que su HTML sabe pintar; el validador exige que el contrato
               traiga exactamente esos, ni uno menos ni uno de mas
  proyecto     ruta del proyecto HyperFrames que se renderiza

Sin `slots_texto` declarados no hay forma de detectar un typo en un paquete: `titluo` se
renderizaria como un titulo vacio en silencio.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .errores import PlantillaDesconocida

CAMPOS_PLANTILLA = ("nombre", "version", "slots_texto", "proyecto")


@dataclass(frozen=True)
class Plantilla:
    """Una plantilla declarada por HF-2 y consumible por el invocador."""

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
    def desde_archivo(cls, ruta: Path) -> Catalogo:
        """Carga un catalogo desde un JSON con una lista de plantillas (formato de HF-2)."""
        ruta = Path(ruta)
        if not ruta.is_file():
            return cls([])
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        return cls([cls._plantilla_desde(d, ruta) for d in datos])

    @staticmethod
    def _plantilla_desde(dato: object, ruta: Path) -> Plantilla:
        if not isinstance(dato, dict) or set(dato) != set(CAMPOS_PLANTILLA):
            raise PlantillaDesconocida(
                f"{ruta.name}: cada plantilla declara exactamente "
                f"{', '.join(CAMPOS_PLANTILLA)}; se recibio {dato!r}"
            )
        return Plantilla(
            nombre=str(dato["nombre"]),
            version=str(dato["version"]),
            slots_texto=tuple(dato["slots_texto"]),
            proyecto=str(dato["proyecto"]),
        )


__all__ = ["CAMPOS_PLANTILLA", "Catalogo", "Plantilla"]
