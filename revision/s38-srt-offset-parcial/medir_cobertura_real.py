"""medir_cobertura_real.py — Re-medicion de cobertura del SRT corregido real (S38, tarea 3.4).

PRIVACIDAD: las rutas del SRT y del transcript se pasan por CLI y NO se escriben aqui — el
nombre de un archivo privado tampoco se versiona. El script nunca copia, imprime ni versiona
el texto del SRT. Los sidecars que deja en `output/` se sanean quitando el campo `text` de
cada cue (el esquema v2 lo incluye para auditoria local en `transcripts/`, que no esta
montado; `output/` si lo esta, aunque sea solo para `.mp4`). Solo conteos y porcentajes.

Uso:
    venv\\Scripts\\python revision\\s38-srt-offset-parcial\\medir_cobertura_real.py ^
        --srt input\\<tu_srt_corregido>.srt --words transcripts\\<tu_video>_words.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import srt_caption  # noqa: E402
import srt_offset  # noqa: E402
from srt_import import load_srt  # noqa: E402

OUT = ROOT / "output" / "auditoria_cobertura_srt"
MIN_COVERAGE_PARCIAL = 0.5


def _sanear(payload: dict) -> dict:
    """Quita el texto de los cues: el SRT fuente es privado y no sale de input/."""
    limpio = json.loads(json.dumps(payload))
    for c in limpio.get("cues", []):
        c.pop("text", None)
    limpio["_nota_auditoria"] = "campo text removido (SRT fuente privado)"
    return limpio


def _fila(nombre: str, payload: dict) -> tuple:
    s = payload["summary"]
    return (
        nombre,
        s["coverage"] * 100,
        s["word_aligned"],
        s.get("word_partial", 0),
        s["cue_fallback"],
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--srt", required=True, help="SRT corregido (no se versiona ni se imprime)")
    ap.add_argument("--words", required=True, help="{stem}_words.json del transcript")
    a = ap.parse_args()
    srt_path, words_path = Path(a.srt), Path(a.words)
    if not srt_path.is_file() or not words_path.is_file():
        print("[X] Falta material: revisa --srt y --words")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    words = json.loads(words_path.read_text(encoding="utf-8"))["words"]

    propuesta = srt_offset.estimar_offset(load_srt(srt_path), words)
    print("== Propuesta del estimador (NO se auto-aplica) ==")
    for k, v in srt_offset.offset_a_dict(propuesta).items():
        print(f"  {k:14s} {v}")
    off = propuesta.offset_ms if propuesta.aplicable else 0
    if not propuesta.aplicable:
        print("  [!] propuesta NO aplicable: se mide con offset 0")

    escenarios = [
        ("HOY", {}),
        ("OFFSET", {"offset_ms": off}),
        (
            "OFFSET+PARCIAL",
            {"offset_ms": off, "modo_parcial": True, "min_coverage": MIN_COVERAGE_PARCIAL},
        ),
    ]
    filas = []
    for nombre, kwargs in escenarios:
        _g, _r, payload = srt_caption.preparar_desde_srt(
            srt_path, words, words_file=words_path.name, **kwargs
        )
        dest = OUT / f"medicion__{nombre.lower().replace('+', '_')}_srt_alignment.json"
        srt_caption.escribir_sidecar(_sanear(payload), dest)
        filas.append(_fila(nombre, payload))
        print(f"  sidecar -> {dest.relative_to(ROOT)}")

    print()
    print(f"{'':22s}{'HOY':>12s}{'OFFSET':>12s}{'OFFSET+PARCIAL':>16s}")
    etiquetas = ["coverage", "cues animados", "cues parciales", "cues estaticos"]
    for i, et in enumerate(etiquetas, start=1):
        celdas = []
        for f in filas:
            v = f[i]
            celdas.append(f"{v:.2f}%" if i == 1 else str(v))
        print(f"{et:22s}{celdas[0]:>12s}{celdas[1]:>12s}{celdas[2]:>16s}")

    print()
    return _auditar_material_completo(srt_path, words, words_path.name, off)


def _auditar_material_completo(srt_path, words, words_file, off) -> int:
    """Invariantes D1-D3 sobre el ASS de los 1072 cues, no solo sobre un tramo."""
    import core  # noqa: PLC0415
    import styles  # noqa: PLC0415

    import auditar_ass  # noqa: PLC0415

    groups, result, _p = srt_caption.preparar_desde_srt(
        srt_path,
        words,
        words_file=words_file,
        offset_ms=off,
        modo_parcial=True,
        min_coverage=MIN_COVERAGE_PARCIAL,
    )
    # D1 EXACTO sobre el modelo (sin la rejilla de 10 ms del formato ASS).
    desvio_ini = sum(
        1 for g in groups if g["words"] and abs(g["words"][0]["start"] - g["start"]) > 1e-9
    )
    desvio_fin = sum(
        1 for g in groups if g["words"] and abs(g["words"][-1]["end"] - g["end"]) > 1e-9
    )
    print("== D1 sobre el MODELO (exacto, los 1072 cues) ==")
    print(f"  cues cuyo primer evento NO arranca en cue.start: {desvio_ini}  (debe ser 0)")
    print(f"  cues cuyo ultimo evento NO cierra en cue.end   : {desvio_fin}  (debe ser 0)")

    ass = OUT / "material_completo.ass"
    core.build_ass(groups, 1920, 1080, styles.get_style("hormozi"), ass)
    print()
    ok = auditar_ass.imprimir(auditar_ass.auditar(groups, ass), "(material completo)")
    print(f"  sidecar/ass -> {ass.relative_to(ROOT)}")
    return 0 if (ok and not desvio_ini and not desvio_fin) else 1


if __name__ == "__main__":
    raise SystemExit(main())
