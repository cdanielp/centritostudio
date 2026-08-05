"""Diagnostico (no modifica nada): mide donde cae CADA plantilla horizontal, con texto corto
y con texto largo de tres lineas, antes y despues de aplicar el desplazamiento de banda
superior. Mide el ALFA del MOV ya renderizado (no el CSS declarado).

Uso: venv\\Scripts\\python revision\\hf-4b\\medir_recorte.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

ANCHO, ALTO, FPS = 1920, 1080, 30
TIMEOUT_S = 180

LARGO_3_LINEAS = (
    "Este titulo es deliberadamente larguisimo para forzar tres lineas completas de texto "
    "envuelto dentro de la placa y así medir si algo se corta de verdad"
)

CASOS = {
    "hook": {"kicker": "DATO", "titulo": "Un titulo corto"},
    "hook_largo": {"kicker": "DATO", "titulo": LARGO_3_LINEAS, "_plantilla": "hook"},
    "cierre": {"titulo": "Un cierre corto", "cta": "Sigue para más"},
    "cierre_largo": {"titulo": LARGO_3_LINEAS, "cta": "Sigue para más", "_plantilla": "cierre"},
    "titulo_seccion": {"titulo": "Una seccion corta"},
    "titulo_seccion_largo": {"titulo": LARGO_3_LINEAS, "_plantilla": "titulo_seccion"},
    "dato_destacado": {"cifra": "42%", "etiqueta": "de crecimiento"},
    "dato_destacado_largo": {
        "cifra": "42%",
        "etiqueta": LARGO_3_LINEAS,
        "_plantilla": "dato_destacado",
    },
    "lower_third": {"nombre": "Carlos Daniel Penagos", "rol": "Prompt Models Studio"},
    "lower_third_largo": {
        "nombre": "Carlos Daniel Penagos",
        "rol": LARGO_3_LINEAS,
        "_plantilla": "lower_third",
    },
}


def filas_con_alfa(mov: Path, t: float, alto: int, ancho: int) -> tuple[int, int] | None:
    crudo = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(mov), "-frames:v", "1",
         "-vf", "alphaextract,format=gray", "-f", "rawvideo", "-"],
        capture_output=True, check=True, timeout=TIMEOUT_S,
    ).stdout
    if len(crudo) < alto * ancho:
        return None
    primera = ultima = None
    for y in range(alto):
        fila = crudo[y * ancho : (y + 1) * ancho]
        if max(fila) > 8:
            primera = y if primera is None else primera
            ultima = y
    if primera is None:
        return None
    return primera, ultima


def main() -> None:
    import motion_capa as mc
    import motion_plan as mp
    from hyperframes import pedir_pieza
    from hyperframes.catalogo import Catalogo

    resultados = {}
    with tempfile.TemporaryDirectory(prefix="hf4b_medir_") as tmp:
        tmp_path = Path(tmp)
        for nombre_caso, texto in CASOS.items():
            plantilla = texto.pop("_plantilla", nombre_caso.split("_largo")[0])
            dur = mp.DURACION_MS[plantilla]
            pieza = mp.Pieza(plantilla, 0, dur, dict(texto), banda=mp.BANDA_CENTRO)
            versiones = mc.versiones_del_catalogo(RAIZ / "motion" / "catalogo.json")
            dato = mc.contrato_de_pieza(
                pieza, version=versiones[plantilla], ancho=ANCHO, alto=ALTO, fps=FPS,
                marca=mc.marca_de(plantilla, mc.MARCA),
            )
            catalogo = Catalogo.desde_archivo(RAIZ / "motion" / "catalogo.json", "horizontal")
            r = pedir_pieza(
                dato, destino=(ANCHO, ALTO), catalogo=catalogo,
                raiz_cache=tmp_path / nombre_caso, timeout_s=TIMEOUT_S,
            )
            if r.razon_fallo is not None:
                resultados[nombre_caso] = {"error": f"{r.razon_fallo.value} {r.detalle}"}
                continue
            medio = dur * 0.0006
            filas = filas_con_alfa(Path(r.ruta_mov), medio, ALTO, ANCHO)
            if filas is None:
                resultados[nombre_caso] = {"error": "sin alfa medible"}
                continue
            y0, y1 = filas
            dy = (mc.desplazamiento_de_banda(mp.BANDA_ARRIBA, ALTO) or (0, 0))[1]
            resultados[nombre_caso] = {
                "plantilla": plantilla,
                "nativo_sin_shift": [round(y0 / ALTO, 4), round(y1 / ALTO, 4)],
                "con_banda_superior": [round((y0 + dy) / ALTO, 4), round((y1 + dy) / ALTO, 4)],
                "se_sale_arriba_con_shift": (y0 + dy) < 0,
                "se_sale_abajo_con_shift": (y1 + dy) > ALTO,
                "invade_captions_con_shift": (y1 + dy) / ALTO > mp.ZONA_CAPTIONS[0],
            }
            print(nombre_caso, json.dumps(resultados[nombre_caso], ensure_ascii=False))

    salida = Path(__file__).resolve().parent / "medicion_antes.json"
    salida.write_text(json.dumps(resultados, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n-> {salida.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
