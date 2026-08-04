"""Contrato de pieza (HF-1): esquema estricto, canonicalizacion y clave de cache.

Estricto quiere decir que un campo desconocido es ERROR, no algo que se ignora en silencio:
un typo en un paquete de HF-2 tiene que doler al construirlo, no producir una pieza sin ese
dato. El esquema es dato declarativo (`ESQUEMA`), no una cascada de ifs.
"""

from __future__ import annotations

import hashlib
import json
import re

from path_safety import is_safe_basename

from .errores import ContratoInvalido

VERSION_SOPORTADA = 1
FIT_VALIDOS = ("nativo", "cover", "contain")
MODOS_POSICION = ("cuadro_completo", "caja")
ANCLAJES = (
    "arriba_izquierda",
    "arriba_derecha",
    "abajo_izquierda",
    "abajo_derecha",
    "centro",
)
CAMPOS_MARCA = ("primario", "secundario", "texto")
CAMPOS_CAJA = ("x", "y", "ancho", "alto", "anclaje")
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")

# Campos de primer nivel. El valor es el nombre del verificador; el orden no importa
# porque la validacion recorre el esquema, nunca la entrada.
ESQUEMA = {
    "contrato": "version",
    "pieza_id": "identificador",
    "plantilla": "plantilla",
    "duracion_ms": "entero_positivo",
    "fps": "entero_positivo",
    "tamano": "tamano",
    "texto": "texto",
    "marca": "marca",
    "posicion": "posicion",
    "fit": "fit",
    "audio": "booleano",
    "semilla": "entero_no_negativo",
}


def _falla(mensaje: str) -> None:
    raise ContratoInvalido(mensaje)


def _es_entero(valor: object) -> bool:
    """True solo para enteros de verdad. `bool` es subclase de int y aqui NO cuenta."""
    return isinstance(valor, int) and not isinstance(valor, bool)


def _ver_version(valor: object) -> None:
    if valor != VERSION_SOPORTADA:
        _falla(
            f"version de contrato no soportada: se recibio {valor!r} y esta version de "
            f"Centrito soporta {VERSION_SOPORTADA}"
        )


def _ver_identificador(valor: object) -> None:
    if not is_safe_basename(valor):
        _falla(f"pieza_id no es un nombre seguro: {valor!r}")


def _ver_plantilla(valor: object) -> None:
    if not isinstance(valor, dict) or set(valor) != {"nombre", "version"}:
        _falla(f"plantilla debe traer exactamente nombre y version, se recibio {valor!r}")
    for clave in ("nombre", "version"):
        if not isinstance(valor[clave], str) or not valor[clave].strip():
            _falla(f"plantilla.{clave} debe ser texto no vacio, se recibio {valor[clave]!r}")


def _ver_entero_positivo(valor: object) -> None:
    if not _es_entero(valor) or valor <= 0:
        _falla(f"debe ser un entero mayor que cero, se recibio {valor!r}")


def _ver_entero_no_negativo(valor: object) -> None:
    if not _es_entero(valor) or valor < 0:
        _falla(f"debe ser un entero mayor o igual a cero, se recibio {valor!r}")


def _ver_tamano(valor: object) -> None:
    if not isinstance(valor, dict) or set(valor) != {"ancho", "alto"}:
        _falla(f"tamano debe traer exactamente ancho y alto, se recibio {valor!r}")
    for clave in ("ancho", "alto"):
        if not _es_entero(valor[clave]) or valor[clave] <= 0:
            _falla(f"tamano.{clave} debe ser un entero mayor que cero, se recibio {valor[clave]!r}")


def _ver_texto(valor: object) -> None:
    if not isinstance(valor, dict):
        _falla(f"texto debe ser un diccionario de slots, se recibio {valor!r}")
    for clave, contenido in valor.items():
        if not isinstance(clave, str) or not isinstance(contenido, str):
            _falla(f"texto.{clave!r} debe ser texto, se recibio {contenido!r}")


def _ver_marca(valor: object) -> None:
    if not isinstance(valor, dict) or set(valor) != set(CAMPOS_MARCA):
        _falla(f"marca debe traer exactamente {', '.join(CAMPOS_MARCA)}, se recibio {valor!r}")
    for clave in CAMPOS_MARCA:
        color = valor[clave]
        if not isinstance(color, str) or not _HEX.match(color):
            _falla(f"marca.{clave} debe ser un hex #RRGGBB, se recibio {color!r}")


def _ver_posicion(valor: object) -> None:
    if not isinstance(valor, dict) or "modo" not in valor:
        _falla(f"posicion debe traer modo, se recibio {valor!r}")
    modo = valor["modo"]
    if modo not in MODOS_POSICION:
        _falla(f"posicion.modo debe ser uno de {', '.join(MODOS_POSICION)}, se recibio {modo!r}")
    if modo == "cuadro_completo":
        if set(valor) != {"modo"}:
            _falla(f"posicion cuadro_completo no admite mas campos, se recibio {sorted(valor)}")
        return
    esperados = {"modo", *CAMPOS_CAJA}
    if set(valor) != esperados:
        faltan = sorted(esperados - set(valor))
        sobran = sorted(set(valor) - esperados)
        _falla(f"posicion caja: faltan {faltan}, sobran {sobran}")
    _ver_caja(valor)


def _ver_caja(valor: dict) -> None:
    for clave in ("x", "y"):
        if not _es_entero(valor[clave]):
            _falla(f"posicion.{clave} debe ser un entero, se recibio {valor[clave]!r}")
    for clave in ("ancho", "alto"):
        if not _es_entero(valor[clave]) or valor[clave] <= 0:
            _falla(f"posicion.{clave} debe ser un entero mayor que cero")
    if valor["anclaje"] not in ANCLAJES:
        _falla(f"posicion.anclaje debe ser uno de {', '.join(ANCLAJES)}")


def _ver_fit(valor: object) -> None:
    if valor not in FIT_VALIDOS:
        _falla(f"fit debe ser uno de {', '.join(FIT_VALIDOS)}, se recibio {valor!r}")


def _ver_booleano(valor: object) -> None:
    if not isinstance(valor, bool):
        _falla(f"debe ser true o false, se recibio {valor!r}")


_VERIFICADORES = {
    "version": _ver_version,
    "identificador": _ver_identificador,
    "plantilla": _ver_plantilla,
    "entero_positivo": _ver_entero_positivo,
    "entero_no_negativo": _ver_entero_no_negativo,
    "tamano": _ver_tamano,
    "texto": _ver_texto,
    "marca": _ver_marca,
    "posicion": _ver_posicion,
    "fit": _ver_fit,
    "booleano": _ver_booleano,
}


def validar_contrato(dato: object) -> dict:
    """Valida el contrato de pieza contra el esquema estricto. Lanza ContratoInvalido.

    PURO: no muta la entrada. Devuelve el mismo dict para encadenar.
    """
    if not isinstance(dato, dict):
        _falla(f"el contrato de pieza debe ser un objeto JSON, se recibio {type(dato).__name__}")
    sobran = sorted(set(dato) - set(ESQUEMA))
    if sobran:
        _falla(f"campos desconocidos en el contrato de pieza: {', '.join(sobran)}")
    faltan = sorted(set(ESQUEMA) - set(dato))
    if faltan:
        _falla(f"faltan campos obligatorios en el contrato de pieza: {', '.join(faltan)}")
    for campo, verificador in ESQUEMA.items():
        try:
            _VERIFICADORES[verificador](dato[campo])
        except ContratoInvalido as exc:
            raise ContratoInvalido(f"{campo}: {exc}") from None
    return dato


def validar_slots(dato: dict, slots_declarados: tuple[str, ...]) -> None:
    """Comprueba que `texto` traiga exactamente los slots que declara la plantilla.

    Tambien rechaza un slot que colisione con una clave reservada: los slots suben al nivel
    raiz de las variables y ahi gana la clave del sistema, asi que un slot llamado `fps`
    jamas llegaria a la plantilla y esta pintaria `30` donde esperaba una frase.
    """
    from .invocador import claves_reservadas  # noqa: PLC0415

    reservadas = claves_reservadas()
    recibidos = set(dato.get("texto") or {})
    esperados = set(slots_declarados)
    faltan = sorted(esperados - recibidos)
    sobran = sorted(recibidos - esperados)
    if faltan or sobran:
        _falla(f"los slots de texto no cuadran con la plantilla: faltan {faltan}, sobran {sobran}")
    chocan = sorted(recibidos & set(reservadas))
    if chocan:
        _falla(
            f"estos slots de texto chocan con claves reservadas de la pieza: {', '.join(chocan)}. "
            f"Reservadas: {', '.join(reservadas)}."
        )


def canonicalizar(dato: object) -> str:
    """JSON canonico: claves ordenadas (tambien anidadas), compacto, UTF-8, sin salto final."""
    return json.dumps(dato, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def calcular_hash(dato: dict, entorno: dict) -> str:
    """Clave de cache: sha256 del contrato canonico + plantilla + las 4 versiones del entorno.

    Las partes van dentro de un objeto JSON en vez de concatenarse a pelo: una concatenacion
    plana dejaria que mover un caracter entre dos versiones produjera la misma clave.
    """
    plantilla = dato.get("plantilla") or {}
    partes = {
        "pieza": canonicalizar(dato),
        "plantilla": {
            "nombre": plantilla.get("nombre"),
            "version": plantilla.get("version"),
        },
        "entorno": {clave: entorno.get(clave) for clave in sorted(entorno)},
    }
    return hashlib.sha256(canonicalizar(partes).encode("utf-8")).hexdigest()


__all__ = [
    "ESQUEMA",
    "VERSION_SOPORTADA",
    "calcular_hash",
    "canonicalizar",
    "validar_contrato",
    "validar_slots",
]
