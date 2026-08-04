"""Medicion del planificador de letreros sobre TODOS los clips reales que hay en el proyecto.

No renderiza nada: recorre los clips que ya existen en `output/clips/`, resuelve para cada uno
su duracion, su transcript y su CSV de trayectoria, y llama a `motion_plan.planificar`. Sirve
para saber cuantos clips se quedan sin una sola pieza y por que, que es la unica forma de
decidir si las reglas de colocacion sirven en el material real de K y no en un caso de prueba.

Uso, desde la raiz del repo:

    venv\\Scripts\\python revision\\hf-3\\medir_carril.py

Escribe la tabla por stdout y el detalle por clip en `revision/hf-3/medicion_carril.json`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

CLIPS_DIR = RAIZ / "output" / "clips"
TRANSCRIPTS = RAIZ / "transcripts"
SALIDA = Path(__file__).resolve().parent / "medicion_carril.json"

# Textos representativos de un run real: hay titulo del clipper, hay nombre y hay CTA, para que
# ninguna pieza se caiga por configuracion vacia y lo que se mida sean las REGLAS.
TITULO = "Titulo del clipper viral"
NOMBRE, ROL, CTA = "Carlos Daniel Penagos", "Prompt Models Studio", "Sigue para mas"


def duracion_y_tamano(mp4: Path) -> tuple[float, int, int] | None:
    """(duracion_s, ancho, alto) por ffprobe, o None si el archivo no es legible."""
    try:
        salida = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=width,height:format=duration", "-of", "json", str(mp4)],
            capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    datos = json.loads(salida)
    flujo = (datos.get("streams") or [{}])[0]
    dur = float((datos.get("format") or {}).get("duration") or 0.0)
    ancho, alto = flujo.get("width"), flujo.get("height")
    if not dur or not ancho or not alto:
        return None
    return dur, int(ancho), int(alto)


def tramos_de(stem: str):
    """Tramos del transcript del clip, si existe. Sin transcript, lista vacia."""
    import motion_capa

    ruta = TRANSCRIPTS / f"{stem}_groups.json"
    if not ruta.is_file():
        return []
    try:
        return motion_capa.tramos_de_groups(json.loads(ruta.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return []


def zona_cara(tray_csv: Path | None, dur_s: float) -> str | None:
    """Bucket dominante de la cara en todo el clip. Solo para el desglose del informe."""
    if tray_csv is None:
        return None
    import cve

    return cve.zona_cara_en_rango(tray_csv, 0.0, dur_s)


def clips_reales() -> list[Path]:
    """Todos los MP4 de `output/clips/` menos los fixtures internos (prefijo `_`)."""
    return sorted(p for p in CLIPS_DIR.glob("*.mp4") if not p.name.startswith("_"))


def medir() -> list[dict]:
    import motion_capa
    import motion_plan as mp
    import tray_resolve

    filas: list[dict] = []
    for mp4 in clips_reales():
        info = duracion_y_tamano(mp4)
        if info is None:
            continue
        dur_s, ancho, alto = info
        orientacion = motion_capa.orientacion_de(ancho, alto)
        tray = tray_resolve.resolver_tray_csv(mp4, TRANSCRIPTS)
        plan = mp.planificar(
            duracion_ms=int(round(dur_s * 1000)),
            orientacion=orientacion,
            textos=mp.TextosMarca(titulo=TITULO, nombre=NOMBRE, rol=ROL, cta=CTA),
            tramos=tramos_de(mp4.stem),
            tray_csv=tray,
        )
        filas.append({
            "clip": mp4.name,
            "dur_s": round(dur_s, 2),
            "orientacion": orientacion,
            "tray_csv": bool(tray),
            "zona_cara": zona_cara(tray, dur_s),
            "n_piezas": len(plan.piezas),
            "piezas": [p.plantilla for p in plan.piezas],
            "bandas": sorted({p.banda for p in plan.piezas}),
            "omisiones": {o.plantilla: o.motivo for o in plan.omisiones},
            "incidencias": list(plan.incidencias),
        })
    return filas


MOTIVO_ETIQUETA = {
    "no_cabe_en_el_clip": "no cabe por tiempo",
    "sin_separacion_minima": "no cabe por tiempo",
    "clip_demasiado_corto": "no cabe por tiempo",
    "ningun_tramo_trae_cifra": "sin cifra en el habla",
    "sin_nombre_configurado": "sin texto configurado",
    "sin_titulo_del_clipper": "sin texto configurado",
}


def _motivo_de_cero(fila: dict) -> str:
    """Por que ese clip se quedo sin NINGUNA pieza, en una sola etiqueta."""
    motivos = set(fila["omisiones"].values())
    for clave in ("no_cabe_en_el_clip", "sin_separacion_minima", "clip_demasiado_corto"):
        if clave in motivos:
            return "no cabe por tiempo"
    if "sin_titulo_del_clipper" in motivos or "sin_nombre_configurado" in motivos:
        return "sin texto configurado"
    return "otro"


def informe(filas: list[dict]) -> str:
    lineas: list[str] = []
    reparto = Counter(min(f["n_piezas"], 3) for f in filas)
    total = len(filas)
    lineas.append(f"CLIPS MEDIDOS: {total}")
    lineas.append("")
    lineas.append("| piezas colocadas | clips | % |")
    lineas.append("|---|---|---|")
    for n, etiqueta in ((0, "0"), (1, "1"), (2, "2"), (3, "3 o mas")):
        c = reparto.get(n, 0)
        lineas.append(f"| {etiqueta} | {c} | {100 * c / total:.1f}% |")

    ceros = [f for f in filas if f["n_piezas"] == 0]
    lineas.append("")
    lineas.append(f"CLIPS EN CERO: {len(ceros)} de {total} ({100 * len(ceros) / total:.1f}%)")
    lineas.append("")
    lineas.append("| motivo del cero | clips |")
    lineas.append("|---|---|")
    for motivo, c in sorted(Counter(_motivo_de_cero(f) for f in ceros).items()):
        lineas.append(f"| {motivo} | {c} |")

    verticales = [f for f in filas if f["orientacion"] == "vertical"]
    v_cero = [f for f in verticales if f["n_piezas"] == 0]
    pct = 100 * len(v_cero) / len(verticales) if verticales else 0.0
    lineas.append("")
    lineas.append(
        f"VERTICALES EN CERO: {len(v_cero)} de {len(verticales)} ({pct:.1f}%)"
    )
    horizontales = [f for f in filas if f["orientacion"] == "horizontal"]
    h_cero = [f for f in horizontales if f["n_piezas"] == 0]
    pct_h = 100 * len(h_cero) / len(horizontales) if horizontales else 0.0
    lineas.append(
        f"HORIZONTALES EN CERO: {len(h_cero)} de {len(horizontales)} ({pct_h:.1f}%)"
    )

    sin_dato = [f for f in verticales if "sin_dato_de_cara" in (f.get("incidencias") or [])]
    lineas.append("")
    lineas.append(
        f"VERTICALES SIN DATO DE CARA: {len(sin_dato)} de {len(verticales)}. Colocan en el "
        f"carril nativo (54-68%), el aprobado en el gate visual de HF-2 por no pisar caras."
    )
    reparto_banda = Counter(b for f in filas for b in (f.get("bandas") or []))
    lineas.append(
        f"CLIPS POR BANDA USADA: centro={reparto_banda.get('centro', 0)} "
        f"superior={reparto_banda.get('superior', 0)}"
    )
    piezas = Counter(p for f in filas for p in (f.get("piezas") or []))
    lineas.append("")
    lineas.append("| pieza | veces colocada |")
    lineas.append("|---|---|")
    for nombre, c in sorted(piezas.items()):
        lineas.append(f"| {nombre} | {c} |")
    return "\n".join(lineas)


def main() -> None:
    filas = medir()
    if not filas:
        print("no se encontro ningun clip legible en output/clips/")
        return
    texto = informe(filas)
    print(texto)
    SALIDA.write_text(
        json.dumps({"resumen": texto.splitlines(), "clips": filas}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\ndetalle por clip -> {SALIDA.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
