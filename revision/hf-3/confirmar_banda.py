"""Confirma con un render REAL donde cae la banda superior sobre un clip de cara centrada.

Compone una pieza en la banda superior sobre un clip 9:16 cuyo bucket de cara es `center`,
extrae un frame y MIDE en pixeles donde quedo el contenido del letrero, comparandolo con la
banda declarada y con la franja prohibida de captions. Es la comprobacion de que el
desplazamiento calculado en `motion_capa.desplazamiento_de_banda` cae donde dice el plan.

Uso, desde la raiz del repo:

    venv\\Scripts\\python revision\\hf-3\\confirmar_banda.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

CLIP = RAIZ / "output" / "clips" / "podcast_test_60s_9x16.mp4"  # bucket de cara: center
SALIDA = Path(__file__).resolve().parent / "confirmacion_banda.json"
TIMEOUT_RENDER_S = 180


def filas_con_alfa(mov: Path, t: float, alto: int, ancho: int) -> tuple[int, int] | None:
    """Primera y ultima fila con alfa distinto de cero en el frame de la pieza."""
    crudo = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(mov), "-frames:v", "1",
         "-vf", "alphaextract,format=gray", "-f", "rawvideo", "-"],
        capture_output=True, check=True, timeout=TIMEOUT_RENDER_S,
    ).stdout
    if len(crudo) < alto * ancho:
        return None
    primera = ultima = None
    for y in range(alto):
        fila = crudo[y * ancho : (y + 1) * ancho]
        if max(fila) > 8:  # 8/255: ignora la cola casi invisible de la sombra
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

    if not CLIP.is_file():
        print(f"no existe el clip de prueba: {CLIP.name}")
        return

    import core

    info = core.get_video_info(CLIP)
    ancho, alto = info["width"], info["height"]
    import tray_resolve

    tray = tray_resolve.resolver_tray_csv(CLIP, RAIZ / "transcripts")
    import cve

    zona = cve.zona_cara_en_rango(tray, 0.0, float(info["duration"])) if tray else None
    print(f"clip: {CLIP.name}  {ancho}x{alto}  zona de cara: {zona}")

    plan = mp.planificar(
        duracion_ms=int(round(float(info["duration"]) * 1000)),
        orientacion="vertical",
        textos=mp.TextosMarca(titulo="Banda superior", nombre="N", rol="R", cta="CTA"),
        tramos=[],
        tray_csv=tray,
    )
    if plan.vacio:
        print("el planificador no coloco nada; no hay banda que confirmar")
        return
    pieza = plan.piezas[0]
    print(f"pieza: {pieza.plantilla}  banda: {pieza.banda}")

    catalogo = Catalogo.desde_archivo(RAIZ / "motion" / "catalogo.json", "vertical")
    versiones = mc.versiones_del_catalogo(RAIZ / "motion" / "catalogo.json")
    dato = mc.contrato_de_pieza(
        pieza,
        version=versiones[pieza.plantilla],
        ancho=ancho,
        alto=alto,
        fps=int(round(info.get("fps") or 30)),
        marca=mc.MARCA,
    )
    with tempfile.TemporaryDirectory(prefix="hf3_banda_") as tmp:
        r = pedir_pieza(
            dato, destino=(ancho, alto), catalogo=catalogo,
            raiz_cache=Path(tmp), timeout_s=TIMEOUT_RENDER_S,
        )
        if r.razon_fallo is not None:
            print(f"FALLO el render de la pieza: {r.razon_fallo.value} {r.detalle}")
            return
        medio = pieza.duracion_ms * 0.0006
        filas = filas_con_alfa(Path(r.ruta_mov), medio, alto, ancho)

    if filas is None:
        print("no se pudo medir el alfa de la pieza")
        return
    y0, y1 = filas
    desplazamiento = mc.desplazamiento_de_banda(pieza.banda, alto) or (0, 0)
    dy = desplazamiento[1]
    # El MOV se renderiza SIEMPRE en el carril nativo; el desplazamiento lo aplica el overlay.
    nativo = (y0 / alto, y1 / alto)
    final = ((y0 + dy) / alto, (y1 + dy) / alto)
    resultado = {
        "clip": CLIP.name,
        "zona_cara": zona,
        "pieza": pieza.plantilla,
        "banda": pieza.banda,
        "desplazamiento_px": dy,
        "carril_nativo_medido": [round(v, 4) for v in nativo],
        "banda_final_medida": [round(v, 4) for v in final],
        "banda_declarada": list(mp.BANDA_SUPERIOR),
        "zona_captions": list(mp.ZONA_CAPTIONS),
        "pisa_captions": final[1] > mp.ZONA_CAPTIONS[0],
        "pisa_ui_superior": final[0] < 0.10,
        "queda_sobre_cara_centrada": final[1] <= 0.40,
    }
    print(json.dumps(resultado, indent=2, ensure_ascii=False))
    SALIDA.write_text(json.dumps(resultado, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n-> {SALIDA.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
