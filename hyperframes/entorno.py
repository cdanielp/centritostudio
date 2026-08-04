"""Versiones del entorno del Motor B, leidas en TIEMPO DE EJECUCION (HF-1).

Las cuatro versiones (hyperframes, node, chromium, ffmpeg) entran a la clave de cache: si
cualquiera cambia, el MOV cacheado deja de ser valido. Por eso NUNCA se inventa un default:
un default falso serviria una pieza renderizada con otro Chrome como si fuera la buena.

Una sola llamada (`hyperframes doctor --json`) trae las cuatro.

Hallazgo HF-1: el payload trae `ok: false` cuando faltan Docker o whisper-cpp, que no hacen
falta para renderizar. Gatear en ese `ok` global seria un falso negativo permanente, asi que
se gatea en los cuatro checks concretos.
"""

from __future__ import annotations

import json
import re
import subprocess

from .errores import EntornoIlegible

# check del doctor -> clave del entorno
CHECKS = {
    "Version": "hyperframes",
    "Node.js": "node",
    "Chrome": "chromium",
    "FFmpeg": "ffmpeg",
}
CLAVES = tuple(CHECKS.values())
TIMEOUT_DOCTOR_S = 60
_VERSION_CHROME = re.compile(r"(\d+\.\d+\.\d+\.\d+)")


def _primer_objeto_json(texto: str) -> dict:
    """Primer objeto JSON del texto. La CLI imprime avisos antes del payload."""
    decodificador = json.JSONDecoder()
    for inicio in range(len(texto)):
        if texto[inicio] != "{":
            continue
        try:
            objeto, _fin = decodificador.raw_decode(texto, inicio)
        except ValueError:
            continue
        if isinstance(objeto, dict):
            return objeto
    raise EntornoIlegible("la salida de 'hyperframes doctor --json' no traia un objeto JSON")


def _detalle(payload: dict, nombre: str) -> str:
    """Detalle del check `nombre`, exigiendo que exista y este en ok."""
    for check in payload.get("checks") or []:
        if not isinstance(check, dict) or check.get("name") != nombre:
            continue
        if not check.get("ok"):
            raise EntornoIlegible(f"el entorno reporta el check '{nombre}' en fallo")
        detalle = str(check.get("detail") or "").strip()
        if not detalle:
            raise EntornoIlegible(f"el check '{nombre}' no trae detalle con la version")
        return detalle
    raise EntornoIlegible(f"falta el check '{nombre}' en la salida del doctor")


def _version_simple(detalle: str, nombre: str, indice: int) -> str:
    """Version por posicion dentro del detalle (0 para Version/Node.js, 1 para FFmpeg)."""
    partes = detalle.split()
    if len(partes) <= indice:
        raise EntornoIlegible(f"no se pudo leer la version de '{nombre}' en: {detalle}")
    return partes[indice]


def parsear_doctor(salida: str) -> dict:
    """Extrae las cuatro versiones del payload de `hyperframes doctor --json`."""
    payload = _primer_objeto_json(salida)
    versiones = {
        "hyperframes": _version_simple(_detalle(payload, "Version"), "Version", 0),
        "node": _version_simple(_detalle(payload, "Node.js"), "Node.js", 0),
        "ffmpeg": _version_simple(_detalle(payload, "FFmpeg"), "FFmpeg", 1),
    }
    detalle_chrome = _detalle(payload, "Chrome")
    encontrado = _VERSION_CHROME.search(detalle_chrome)
    if not encontrado:
        raise EntornoIlegible(f"no se pudo leer la version de Chrome/Chromium en: {detalle_chrome}")
    versiones["chromium"] = encontrado.group(1)
    for clave, valor in versiones.items():
        if not valor.strip():
            raise EntornoIlegible(f"la version de '{clave}' llego vacia")
    return versiones


def leer_entorno(binario: str) -> dict:
    """Corre `doctor --json` con `binario` y devuelve las cuatro versiones."""
    try:
        proceso = subprocess.run(
            [binario, "hyperframes", "doctor", "--json"],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_DOCTOR_S,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        raise EntornoIlegible(f"no se pudo ejecutar '{binario}': {exc}") from None
    except subprocess.TimeoutExpired:
        raise EntornoIlegible(f"'hyperframes doctor' no respondio en {TIMEOUT_DOCTOR_S}s") from None
    return parsear_doctor(proceso.stdout or "")


__all__ = ["CHECKS", "CLAVES", "leer_entorno", "parsear_doctor"]
