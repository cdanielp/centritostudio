"""path_safety.py — Fuente UNICA de validacion de basenames/stems seguros (H1).

Extraido de `studio_srt_manifest` para que TODO endpoint que reciba un identificador de
usuario (name/filename/stem/clip_id/...) lo valide con la MISMA regla antes de construir
cualquier `Path`. `studio_srt_manifest` reexporta `is_safe_basename`/`_has_control` para
conservar los imports historicos (S36-C1 y anteriores); NO se duplica la implementacion.

Un basename seguro es un componente de ruta PURO: sin separadores, sin drive/UNC, sin
dot-segments y sin puntos/espacios finales (que Windows elimina, cambiando el significado).
Ante la duda RECHAZA; nunca convierte silenciosamente un nombre invalido en valido.

Rechaza:
- cadena vacia; no-str;
- ".", ".." (y cualquier componente que quede vacio tras normalizar);
- slash `/` y backslash `\\`;
- rutas absolutas POSIX (`/x`) y Windows (`C:\\x`); drive letters (`C:x`); UNC (`\\\\srv\\s`);
- NUL y cualquier caracter de control (categoria Unicode Cc: C0/DEL/C1);
- separadores codificados que lleguen ya DECODIFICADOS al endpoint (llegan como `/`/`\\`);
- puntos o espacios FINALES (Windows los recorta -> colision/ambiguedad de nombre);
- cualquier nombre cuyo basename normalizado (POSIX o Windows) no sea exactamente el valor.

Acepta nombres legitimos ya usados por el producto: letras, numeros, espacios internos,
guion, underscore, acentos y Unicode razonable.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path, PureWindowsPath


def _has_control(text: str) -> bool:
    """True si text contiene algun caracter de control Unicode (categoria Cc).

    Cubre C0 (U+0000-U+001F), DEL (U+007F) y C1 (U+0080-U+009F). No rechaza letras
    acentuadas (Ll/Lu), emojis (So) ni espacios normales (Zs).
    """
    return any(unicodedata.category(c) == "Cc" for c in text)


def is_safe_basename(name: object) -> bool:
    """True solo si name es un basename PURO seguro para construir rutas confinadas.

    Endurecido en H1 respecto de la version historica: ademas de separadores y caracteres
    de control, rechaza `..`/`.` y los nombres con punto/espacio final (que Windows recorta).
    """
    if not isinstance(name, str) or name == "":
        return False
    if _has_control(name):
        return False
    # Windows elimina puntos/espacios finales del componente ("foo." -> "foo", "x " -> "x"):
    # aceptarlos permitiria dos nombres distintos que colisionan en el FS. Tambien descarta
    # ".", "..", "..." (todos terminan en punto) como dot-segments.
    if name[-1] in " .":
        return False
    # Basename puro bajo AMBAS convenciones: rechaza `/`, `\\`, drive, UNC, absolutos y los
    # dot-segments que pathlib colapsa a "" en `.name`.
    return Path(name).name == name and PureWindowsPath(name).name == name
