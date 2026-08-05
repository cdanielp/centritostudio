"""Demo VERTICAL 1080x1920 de punta a punta: reencuadre + captions + b-roll de Pexels + letreros.

Los "gemelos verticales" (el reencuadre de un clip horizontal ya existente) nunca se habian
ejercitado de punta a punta con la capa de letreros encendida (HF-4). Este script llama al
MISMO orquestador que usa el Modo Automatico v2 (`auto_v2.procesar_clip_v2`) sobre un clip
horizontal real que ya tiene transcript, sin repetir transcripcion ni el analisis IA del
clipper (ya existen en disco). El carril vertical no cambio en este HF-4 (solo el horizontal se
tocó, ver Paso 1), asi que este demo tambien sirve de evidencia para la invariante del Paso 6b.

Uso, desde la raiz del repo (necesita PEXELS_API_KEY y npx/Chrome headless):

    venv\\Scripts\\python revision\\hf-4\\demo_vertical.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

CLIP_ARCHIVO = "mariosoto_clip2_corto.mp4"  # 1920x1080, 20.5s, transcript ya existe
PAQUETE_DIR = Path(__file__).resolve().parent / "evidencia_vertical"


def main() -> None:
    import os

    from dotenv import load_dotenv

    load_dotenv()

    if not os.environ.get("PEXELS_API_KEY"):
        print("falta PEXELS_API_KEY en el entorno; el b-roll no se podria resolver")
        return

    from auto_config import AutoConfig
    from auto_v2 import procesar_clip_v2

    clip = {
        "archivo": CLIP_ARCHIVO,
        "titulo": "Como se arma un flujo de reencuadre y letreros de punta a punta",
        "razon": "demo HF-4 (paso 5a)",
        "score": 90,
        "dur_s": 20.5,
    }

    PAQUETE_DIR.mkdir(parents=True, exist_ok=True)
    config = AutoConfig(
        mode="v2",
        broll_enabled=True,
        motion_enabled=True,
        motion_nombre="Carlos Daniel Penagos",
        motion_rol="Prompt Models Studio",
        motion_cta="Sigue para más",
        motion_textos_llm=False,  # deterministico: los textos salen de las reglas, no del LLM
        motion_estilo="pms",
        verify_av=True,
    )

    info = procesar_clip_v2(
        clip,
        PAQUETE_DIR,
        config,
        transcripts=RAIZ / "transcripts",
        clips_dir=RAIZ / "output" / "clips",
        root=RAIZ,
    )
    print(json.dumps(info, indent=2, ensure_ascii=False, default=str))

    final = PAQUETE_DIR / info["archivo"]
    print(f"\n-> {final.relative_to(RAIZ)}" if final.is_file() else "\nNO se genero el MP4 final")


if __name__ == "__main__":
    main()
