"""Corre el gate de piezas SELLADAS vs VISIBLES (TAREA 3) sobre un paquete ya renderizado.

Uso, desde la raiz del repo:

    venv\\Scripts\\python revision\\hf-4\\verificar_gate_visibilidad.py <paquete_dir>
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))


def main() -> None:
    import motion_capa as mc
    import motion_gate_visibilidad as gv

    paquete_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        RAIZ / "output" / "paquetes" / "mariosoto_00hf4_formato_dual"
    )
    resumen_path = paquete_dir / "resumen_formato_dual.json"
    resumen = json.loads(resumen_path.read_text(encoding="utf-8"))

    total_problemas = 0
    with tempfile.TemporaryDirectory(prefix="gate_vis_") as tmp:
        for salida in resumen["salidas"]:
            mp4 = paquete_dir / salida["archivo"]
            sello_path = RAIZ / salida["sello_motion_render"]
            sello = json.loads(sello_path.read_text(encoding="utf-8"))
            problemas = gv.piezas_declaradas_pero_invisibles(
                mp4, sello, mc.ACENTO_POR_PLANTILLA, tmp_dir=Path(tmp) / salida["archivo"]
            )
            declaradas = len(sello.get("piezas", []))
            print(f"\n{salida['archivo']} ({sello['orientacion']}): "
                  f"{declaradas} piezas declaradas, {declaradas - len(problemas)} visibles")
            for p in problemas:
                print(f"  FALLO: '{p.plantilla}' t=[{p.t0_ms},{p.t1_ms}]ms "
                      f"pixeles={p.pixeles_hallados} (esperaba color {p.color})")
            total_problemas += len(problemas)

    print(f"\n{'GATE OK' if total_problemas == 0 else 'GATE FALLIDO'}: "
          f"{total_problemas} pieza(s) declaradas pero invisibles")
    sys.exit(1 if total_problemas else 0)


if __name__ == "__main__":
    main()
