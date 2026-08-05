"""Demo Formato dual: UNA corrida "ambos" sobre un clip real, con letreros y b-roll
encendidos, que entrega los DOS MP4 (9:16 y 16:9) compartiendo LLM y Pexels.

Llama al MISMO orquestador que usa el Modo Automatico v2 (`auto_v2.procesar_clip_v2`), igual
que `demo_vertical.py`, pero con `AutoConfig(formato="ambos")`. Instrumenta con contadores las
funciones que antes de HF-4 Formato dual se habrian llamado dos veces (una por formato): el
brain, el texto-LLM de los letreros, y los fetchers de Pexels. Reporta los conteos al final.

Uso, desde la raiz del repo (necesita PEXELS_API_KEY, DEEPSEEK_API_KEY y npx/Chrome headless):

    venv\\Scripts\\python revision\\hf-4\\demo_formato_dual.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

CLIP_ARCHIVO = "mariosoto_clip2_corto.mp4"  # 1920x1080, 20.5s, transcript ya existe
PAQUETE_DIR = RAIZ / "output" / "paquetes" / "mariosoto_clip2_corto_ambos_hf4"


def _instrumentar(modulo, nombre, contador: dict, clave: str):
    """Envuelve una funcion con un contador SIN cambiar su comportamiento real."""
    original = getattr(modulo, nombre)

    def envoltura(*a, **kw):
        contador[clave] = contador.get(clave, 0) + 1
        return original(*a, **kw)

    setattr(modulo, nombre, envoltura)


def main() -> None:
    import os

    from dotenv import load_dotenv

    load_dotenv()
    faltan = [k for k in ("PEXELS_API_KEY", "DEEPSEEK_API_KEY") if not os.environ.get(k)]
    if faltan:
        print(f"faltan variables de entorno: {', '.join(faltan)}")
        return

    import auto_v2
    import brain
    import motion_textos_llm
    from auto_config import AutoConfig
    from auto_report import STYLE_AUTO

    clip_path = RAIZ / "output" / "clips" / CLIP_ARCHIVO
    if not clip_path.is_file():
        print(f"no existe el clip de prueba: {clip_path}")
        return
    groups_path = RAIZ / "transcripts" / f"{clip_path.stem}_groups.json"
    if not groups_path.is_file():
        print(f"no hay transcript para {clip_path.stem}")
        return

    # PASO 7: borra la cache de piezas ANTES de renderizar evidencia. El paquete es nuevo en
    # esta corrida, pero si una corrida previa dejo un directorio con el mismo nombre (piezas
    # cacheadas de una version anterior de este demo), se limpia para no maquillar el conteo.
    import shutil

    if PAQUETE_DIR.exists():
        print(f"borrando paquete previo: {PAQUETE_DIR}")
        shutil.rmtree(PAQUETE_DIR)
    PAQUETE_DIR.mkdir(parents=True, exist_ok=True)
    piezas_dir = PAQUETE_DIR / "piezas"
    print(f"cache de piezas antes de la corrida: {'existe' if piezas_dir.exists() else 'no existe (limpia)'}")

    contador: dict[str, int] = {}
    _instrumentar(brain, "analizar_grupos", contador, "llm_brain")
    _instrumentar(motion_textos_llm, "pedir_textos", contador, "llm_motion_texto_pasada1")
    _instrumentar(motion_textos_llm, "pedir_textos_para", contador, "llm_motion_texto_pasada2")

    import auto_broll

    _instrumentar(auto_broll, "_resolve_image", contador, "pexels_imagen")
    _instrumentar(auto_broll, "_search_videos", contador, "pexels_video_busqueda")

    clip = {
        "archivo": CLIP_ARCHIVO,
        "titulo": "Como se arma un flujo de reencuadre y letreros de punta a punta",
        "razon": "demo HF-4 (Formato dual, entregable Ambos)",
        "score": 90,
        "dur_s": 20.5,
    }

    config = AutoConfig(
        mode="v2",
        formato="ambos",
        broll_enabled=True,
        motion_enabled=True,
        motion_nombre="Carlos Daniel Penagos",
        motion_rol="Prompt Models Studio",
        motion_cta="Sigue para más",
        motion_textos_llm=False,  # deterministico: los textos salen de las reglas, no del LLM
        motion_estilo="pms",
        verify_av=True,
    )

    infos = auto_v2.procesar_clip_v2(
        clip,
        PAQUETE_DIR,
        config,
        transcripts=RAIZ / "transcripts",
        clips_dir=RAIZ / "output" / "clips",
        root=RAIZ,
    )

    resumen = {
        "paquete_dir": str(PAQUETE_DIR.relative_to(RAIZ)),
        "salidas": [],
        "llamadas": contador,
    }
    clips_dir = RAIZ / "output" / "clips"
    for info in infos:
        final = PAQUETE_DIR / info["archivo"]
        # El sello vive junto al CLIP DE IDENTIDAD en output/clips/ (auto_v2.clip_identidad),
        # NO junto al MP4 final con estilo en el paquete: son dos archivos distintos a proposito.
        stem_fmt = Path(info["archivo"]).stem.removesuffix(f"_{STYLE_AUTO}")
        sello = clips_dir / f"{stem_fmt}_motion_render.json"
        resumen["salidas"].append(
            {
                "archivo": info["archivo"],
                "existe": final.is_file(),
                "tamano_bytes": final.stat().st_size if final.is_file() else 0,
                "sello_motion_render": str(sello.relative_to(RAIZ)),
                "sello_existe": sello.is_file(),
                "avisos": info.get("avisos"),
                "broll": info.get("broll"),
                "motion": (info.get("motion") or {}).get("piezas_ok"),
            }
        )
    (PAQUETE_DIR / "resumen_formato_dual.json").write_text(
        json.dumps(resumen, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(resumen, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
