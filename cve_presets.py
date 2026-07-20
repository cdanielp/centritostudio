"""cve_presets.py — carga segura de cve_presets.json (F6 esencial; DISENO_CVE §6).

Overrides / presets nuevos del CVE con el MISMO patron fail-safe por-campo de styles.json.
Contrato (DISENO_CVE §6):
- Archivo ausente / JSON roto / no-dict -> {} (built-ins intactos).
- Allowlist explicito de campos con validadores de tipo/rango; nada fuera de la lista se
  copia (sin ejecucion arbitraria, sin rutas). Campo invalido/desconocido -> se ignora.
- Preset nuevo sin `base` valido hereda de clean_podcast (el mas sobrio: fallar hacia abajo).
- El `style` del CVE referencia estilos por NOMBRE (styles.json los gobierna); ademas admite
  un dict de overrides de StyleConfig validados campo por campo por styles.

`construir_presets` es puro (built-ins + user -> registro efectivo); no lee disco.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import styles

_INTENSIDADES = frozenset({"minimal", "clean", "viral"})
_POSICIONES = frozenset({"bottom", "center", "top"})
_KEYWORDS = frozenset({"off", "brain", "auto+brain", "manual"})
_DENSIDADES = frozenset({"baja", "media", "alta"})
_BASE_DEFECTO = "clean_podcast"

# Allowlist de campos SIMPLES de un preset -> validador de tipo/rango. Se mapea la clave
# JSON (izq) a la clave interna que consume _plan_desde_dict (der) via _CLAVE_INTERNA.
_VALIDADORES = {
    "intensidad": lambda v: v in _INTENSIDADES,
    "posicion": lambda v: v in _POSICIONES,
    "keywords": lambda v: v in _KEYWORDS,
    "densidad": lambda v: v in _DENSIDADES,
    "glow": lambda v: isinstance(v, bool),
    "avoid_faces": lambda v: isinstance(v, bool),
}
_CLAVE_INTERNA = {"posicion": "position"}  # el resto conserva su nombre


def cargar(path: Path) -> dict:
    """Lee cve_presets.json. Cualquier fallo -> {} (fail-safe). Admite {"presets": {...}}."""
    if not path or not Path(path).exists():
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        print(f"[cve] {Path(path).name} ilegible, se ignora (built-ins intactos)")
        return {}
    if not isinstance(data, dict):
        return {}
    section = data.get("presets", data)
    return section if isinstance(section, dict) else {}


def _base_para(key: str, spec: dict, registro: dict) -> dict:
    """Preset base del que hereda: `base` valido, o el propio built-in, o clean_podcast."""
    base_name = spec.get("base")
    if isinstance(base_name, str) and base_name in registro:
        return dict(registro[base_name])
    if key in registro:
        return dict(registro[key])
    return dict(registro[_BASE_DEFECTO])


def _aplicar_style(nuevo: dict, valor, styles_disponibles: set[str]) -> None:
    """`style` string valido -> nombre; dict -> overrides validados; invalido -> base."""
    if isinstance(valor, str) and valor.lower().strip() in styles_disponibles:
        nuevo["style"] = valor.lower().strip()
        nuevo.pop("style_overrides", None)
    elif isinstance(valor, dict):
        validos = styles.filtrar_overrides_validos(valor)
        if validos:
            nuevo["style_overrides"] = validos


def _aplicar_overrides(nuevo: dict, spec: dict, styles_disponibles: set[str]) -> None:
    """Aplica solo los campos del allowlist que validen; mapea overlays bool y style."""
    for clave, validador in _VALIDADORES.items():
        if clave in spec and validador(spec[clave]):
            nuevo[_CLAVE_INTERNA.get(clave, clave)] = spec[clave]
    if isinstance(spec.get("overlays"), bool):
        nuevo["overlays"] = "brain" if spec["overlays"] else "off"
    elif isinstance(spec.get("overlays"), str) and spec["overlays"] in ("off", "brain"):
        nuevo["overlays"] = spec["overlays"]
    if "style" in spec:
        _aplicar_style(nuevo, spec["style"], styles_disponibles)


def construir_presets(builtins: dict, user: dict, styles_disponibles: set[str]) -> dict:
    """Registro efectivo = built-ins + presets de usuario validados (puro, fail-safe por campo)."""
    registro = copy.deepcopy(builtins)
    if not isinstance(user, dict):
        return registro
    for nombre, spec in user.items():
        if not isinstance(spec, dict):
            continue
        key = str(nombre).lower().strip()
        if not key:
            continue
        nuevo = _base_para(key, spec, registro)
        _aplicar_overrides(nuevo, spec, styles_disponibles)
        registro[key] = nuevo
    return registro
