"""motion_gate_visibilidad.py — Gate: piezas SELLADAS vs piezas VISIBLES (HF-4 hotfix).

`motion_capa.pieza_cabe_en_el_lienzo` (Paso 2 de HF-4b) es un backstop de TIEMPO DE RENDER: mide
el alfa de la pieza SUELTA, antes de componerla. Dos piezas de `mariosoto_clip2_corto` (hook y
cierre, 9:16) pasaron ese backstop con returncode 0 -- porque en esa version fallaba abierto
sobre "sin alfa medible" -- y el `_motion_render.json` sellado declaro 3 piezas mientras el MP4
final solo mostraba 1.

Este modulo es la SEGUNDA compuerta, sobre el ARTEFACTO FINAL: dado un sello (lo que dice el
plan) y el MP4 ya compuesto (lo que el usuario recibe), mide con FFmpeg si el acento de marca de
cada pieza aparece de verdad dentro de su ventana temporal. Es deliberadamente redundante con el
backstop de render: uno cazaria un bug de la plantilla, este cazaria ademas un bug del propio
paso de composicion/overlay que el backstop no toca.

PURO en el sentido del proyecto: sin red, sin estado de modulo. Llama a `ffmpeg` por subprocess
(igual que `motion_capa.bbox_alfa`) y a Pillow para contar pixeles, ambos ya dependencias del
proyecto.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

# Bajo este conteo de pixeles coincidentes, la pieza se considera NO visible. Calibrado contra
# renders reales: una pieza visible mide cientos a decenas de miles de pixeles de acento; una
# pieza ausente mide 0. 20 deja margen de sobra a compresion/antialiasing sin colar un falso OK.
UMBRAL_PIXELES_VISIBLE = 20
TOLERANCIA_COLOR = 30


@dataclass(frozen=True)
class ProblemaVisibilidad:
    plantilla: str
    t0_ms: int
    t1_ms: int
    pixeles_hallados: int
    color: str


def _hex_a_rgb(color_hex: str) -> tuple[int, int, int]:
    h = color_hex.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _extraer_frame(mp4: Path, t_s: float, salida_png: Path, timeout_s: int = 60) -> bool:
    """Extrae UN frame a `salida_png`. True si ffmpeg lo escribio."""
    resultado = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-ss",
            f"{t_s:.3f}",
            "-i",
            str(mp4),
            "-frames:v",
            "1",
            str(salida_png),
        ],
        capture_output=True,
        timeout=timeout_s,
    )
    return resultado.returncode == 0 and salida_png.is_file()


def contar_pixeles_acento(png: Path, color_hex: str, *, muestreo: int = 2) -> int:
    """Pixeles de `png` que coinciden con `color_hex` (tolerancia fija), extrapolado por el
    paso de muestreo (2 = revisa 1 de cada 4 pixeles y multiplica x4: mismo criterio que la
    verificacion manual de esta sesion)."""
    from PIL import Image  # noqa: PLC0415 (dependencia pesada, solo donde se usa)

    objetivo = _hex_a_rgb(color_hex)
    im = Image.open(png).convert("RGB")
    ancho, alto = im.size
    px = im.load()
    hallados = 0
    for y in range(0, alto, muestreo):
        for x in range(0, ancho, muestreo):
            r, g, b = px[x, y]
            if (
                abs(r - objetivo[0]) < TOLERANCIA_COLOR
                and abs(g - objetivo[1]) < TOLERANCIA_COLOR
                and abs(b - objetivo[2]) < TOLERANCIA_COLOR
            ):
                hallados += 1
    return hallados * (muestreo * muestreo)


def piezas_declaradas_pero_invisibles(
    mp4: Path, sello: dict, acento_por_plantilla: dict[str, str], *, tmp_dir: Path
) -> tuple[ProblemaVisibilidad, ...]:
    """(problemas,) -- vacio si TODAS las piezas del sello aparecen de verdad en `mp4`.

    Mide en el instante medio de cada ventana declarada (mismo criterio que
    `motion_capa._FRACCION_INSTANTE_MEDIO`, aplicado sobre tiempo absoluto del clip en vez de
    duracion de la pieza). Una plantilla sin acento mapeado se salta (no es de este catalogo).
    """
    tmp_dir = Path(tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    problemas: list[ProblemaVisibilidad] = []
    for i, pieza in enumerate(sello.get("piezas", [])):
        plantilla = pieza["plantilla"]
        color = acento_por_plantilla.get(plantilla)
        if color is None:
            continue
        t0_ms, t1_ms = pieza["t0_ms"], pieza["t1_ms"]
        t_medio = (t0_ms + (t1_ms - t0_ms) * 0.6) / 1000.0
        png = tmp_dir / f"gate_{i:02d}_{plantilla}.png"
        if not _extraer_frame(mp4, t_medio, png):
            problemas.append(ProblemaVisibilidad(plantilla, t0_ms, t1_ms, 0, color))
            continue
        n = contar_pixeles_acento(png, color)
        if n < UMBRAL_PIXELES_VISIBLE:
            problemas.append(ProblemaVisibilidad(plantilla, t0_ms, t1_ms, n, color))
    return tuple(problemas)


__all__ = [
    "TOLERANCIA_COLOR",
    "UMBRAL_PIXELES_VISIBLE",
    "ProblemaVisibilidad",
    "contar_pixeles_acento",
    "piezas_declaradas_pero_invisibles",
]
