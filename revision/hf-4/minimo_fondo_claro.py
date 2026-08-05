"""Render REAL del estilo "minimo" sobre un fondo CLARO, con la colocacion REAL del pipeline.

El intento anterior compuso el MOV de la pieza 1:1 sobre el frame (sin pasar por
`motion_capa.desplazamiento_de_banda`) y el letrero cayo a 77-89% de altura, dentro de
ZONA_CAPTIONS (70-92%). Este script sigue el MISMO camino que un render real (D50/HF-4):

    resolver_estilo -> contrato_de_pieza -> pedir_pieza -> desplazamiento_de_banda -> overlay

igual que `motion_capa._clips_de_motion`, y mide en pixeles donde cae el letrero para
confirmar que esta vez SI queda fuera de la franja de captions.

El fondo claro es sintetico (gradiente ffmpeg, no un clip real) a proposito: aisla la pregunta
("se lee el estilo minimo sobre claro?") de si un clip concreto es "bastante claro". El estilo
minimo no lleva placa solida detras del texto (ver motion/lower_third_minimo/index.html): el
texto es casi blanco (#F5F5F7) y depende solo de la sombra para contraste, que es justo lo que
un fondo claro pone a prueba.

Uso, desde la raiz del repo:

    venv\\Scripts\\python revision\\hf-4\\minimo_fondo_claro.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

ANCHO, ALTO, FPS, DUR_S = 1080, 1920, 30, 6.0
SALIDA_PNG = Path(__file__).resolve().parent / "minimo_fondo_claro.png"
SALIDA_JSON = Path(__file__).resolve().parent / "minimo_fondo_claro.json"
TIMEOUT_S = 180


def filas_con_alfa(mov: Path, t: float, alto: int, ancho: int) -> tuple[int, int] | None:
    """Primera y ultima fila con alfa distinto de cero en el frame de la pieza. Igual medida
    que `revision/hf-3/confirmar_banda.py`, para que los dos resultados sean comparables."""
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

    pieza = mp.Pieza(
        "lower_third", 0, mp.DURACION_MS["lower_third"],
        {"nombre": "Carlos Daniel Penagos", "rol": "Prompt Models Studio"},
        banda=mp.BANDA_CENTRO,  # carril nativo: lo que pone el planificador sin dato de cara
    )

    ruta_catalogo = RAIZ / "motion" / "catalogo.json"
    versiones = mc.versiones_del_catalogo(ruta_catalogo)
    nombre_resuelto, version_resuelta, cayo_a_pms = mc.resolver_estilo(
        "lower_third", "minimo", versiones
    )
    if cayo_a_pms:
        print("el estilo 'minimo' no existe para lower_third; no hay nada que confirmar")
        return
    print(f"plantilla resuelta: {nombre_resuelto} v{version_resuelta}")

    dato = mc.contrato_de_pieza(
        pieza,
        version=version_resuelta,
        nombre_plantilla=nombre_resuelto,
        estilo="minimo",
        ancho=ANCHO,
        alto=ALTO,
        fps=FPS,
        marca=mc.marca_de(nombre_resuelto, mc.MARCA),
    )
    catalogo = Catalogo.desde_archivo(ruta_catalogo, "vertical")

    with tempfile.TemporaryDirectory(prefix="hf4_minimo_claro_") as tmp:
        tmp_path = Path(tmp)
        r = pedir_pieza(
            dato, destino=(ANCHO, ALTO), catalogo=catalogo,
            raiz_cache=tmp_path / "cache", timeout_s=TIMEOUT_S,
        )
        if r.razon_fallo is not None:
            print(f"FALLO el render de la pieza: {r.razon_fallo.value} {r.detalle}")
            return

        medio = pieza.duracion_ms * 0.0006
        filas = filas_con_alfa(Path(r.ruta_mov), medio, ALTO, ANCHO)

        fondo = tmp_path / "fondo_claro.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
             "-i", f"gradients=s={ANCHO}x{ALTO}:c0=0xF4F4F7:c1=0xD9D9E0:d={DUR_S}:rate={FPS}",
             "-pix_fmt", "yuv420p", str(fondo)],
            check=True, timeout=TIMEOUT_S,
        )

        # Dos pasos, como `studio_motion._componer_previsualizacion`: primero se saca UN
        # fotograma RGBA de la pieza en su instante "medio" (la animacion de entrada todavia
        # no termino en t=0, componer ahi habria dejado el letrero a medio aparecer o invisible)
        # y despues se compone ESE PNG sobre el fondo. Meter los dos videos en el mismo
        # filter_complex con -ss solo en el fondo deja la pieza en su propio t=0.
        capa = tmp_path / "capa.png"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", f"{medio:.3f}", "-i", str(r.ruta_mov),
             "-frames:v", "1", "-vf", "format=rgba", "-pix_fmt", "rgba", str(capa)],
            check=True, timeout=TIMEOUT_S,
        )

        desplazamiento = mc.desplazamiento_de_banda(pieza.banda, ALTO) or (0, 0)
        medio_video = min(medio, DUR_S - 0.1)
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", f"{max(medio_video, 0):.3f}", "-i", str(fondo),
             "-i", str(capa), "-filter_complex",
             f"[0:v][1:v]overlay={desplazamiento[0]}:{desplazamiento[1]}",
             "-frames:v", "1", str(SALIDA_PNG)],
            check=True, timeout=TIMEOUT_S,
        )

    if filas is None:
        print("no se pudo medir el alfa de la pieza")
        return
    y0, y1 = filas
    dy = desplazamiento[1]
    nativo = (y0 / ALTO, y1 / ALTO)
    final = ((y0 + dy) / ALTO, (y1 + dy) / ALTO)
    resultado = {
        "estilo": "minimo",
        "plantilla_resuelta": nombre_resuelto,
        "banda": pieza.banda,
        "desplazamiento_px": dy,
        "carril_nativo_medido": [round(v, 4) for v in nativo],
        "posicion_final_medida": [round(v, 4) for v in final],
        "zona_captions": list(mp.ZONA_CAPTIONS),
        "pisa_captions": final[1] > mp.ZONA_CAPTIONS[0],
        "png": str(SALIDA_PNG.relative_to(RAIZ)),
    }
    print(json.dumps(resultado, indent=2, ensure_ascii=False))
    SALIDA_JSON.write_text(json.dumps(resultado, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n-> {SALIDA_PNG.relative_to(RAIZ)}")
    print(f"-> {SALIDA_JSON.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
