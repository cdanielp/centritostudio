"""TAREA 4: costo real con `textos_llm` ENCENDIDO (no deterministico), en dos corridas
separadas -- una con `formato="9:16"` y otra con `formato="ambos"` -- para comprobar si Ambos
paga doble por letreros/brain/Pexels o no.

Mismo orquestador real que el Modo Automatico v2 (`auto_v2.procesar_clip_v2`), como
`demo_formato_dual.py`, pero con `motion_textos_llm=True` y paquetes NUEVOS por corrida (nunca
reusa cache de una corrida a otra, para no maquillar el conteo).

Uso, desde la raiz del repo (necesita PEXELS_API_KEY y DEEPSEEK_API_KEY):

    venv\\Scripts\\python revision\\hf-4\\medir_costo_formato.py
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

CLIP_ARCHIVO = "mariosoto_clip2_corto.mp4"


def _instrumentar(modulo, nombre, contador: dict, clave: str):
    original = getattr(modulo, nombre)

    def envoltura(*a, **kw):
        contador[clave] = contador.get(clave, 0) + 1
        return original(*a, **kw)

    setattr(modulo, nombre, envoltura)


def _limpiar_cache_del_clip() -> None:
    """Borra TODO derivado de `mariosoto_clip2_corto` para las dos variantes de formato, en
    `output/clips/` y `transcripts/`, ANTES de cada corrida. Sin esto, la segunda corrida
    encuentra en disco el plan/brain/reframe que dejo la primera (misma `huella_de_entrada`,
    mismo `clips_dir` compartido) y el conteo de llamadas mentiria por debajo -- que es
    exactamente lo que paso en la primera version de este script (la corrida "ambos" reuso
    el plan de letreros de la corrida "9:16" y salio con 0 llamadas al LLM de letreros).
    """
    stem = CLIP_ARCHIVO.replace(".mp4", "")
    patrones_clips = (f"{stem}_9x16*", f"{stem}_16x9*", f"trayectoria_{stem}_9x16*")
    for carpeta, patrones in (
        (RAIZ / "output" / "clips", patrones_clips),
        (RAIZ / "transcripts", (f"{stem}_9x16*", f"{stem}_16x9*")),
    ):
        for patron in patrones:
            for f in carpeta.glob(patron):
                f.unlink()


def _correr(formato: str, paquete_dir: Path) -> dict:
    import auto_broll
    import auto_v2
    import brain
    import motion_textos_llm
    from auto_config import AutoConfig

    _limpiar_cache_del_clip()
    if paquete_dir.exists():
        shutil.rmtree(paquete_dir)
    paquete_dir.mkdir(parents=True, exist_ok=True)

    contador: dict[str, int] = {}
    _instrumentar(brain, "analizar_grupos", contador, "llm_brain")
    _instrumentar(motion_textos_llm, "pedir_textos", contador, "llm_motion_texto_pasada1")
    _instrumentar(motion_textos_llm, "pedir_textos_para", contador, "llm_motion_texto_pasada2")
    _instrumentar(auto_broll, "_resolve_image", contador, "pexels_imagen")
    _instrumentar(auto_broll, "_search_videos", contador, "pexels_video_busqueda")

    clip = {
        "archivo": CLIP_ARCHIVO,
        "titulo": "Como se arma un flujo de reencuadre y letreros de punta a punta",
        "razon": "TAREA 4 (medicion de costo, textos_llm ON)",
        "score": 90,
        "dur_s": 20.5,
    }
    config = AutoConfig(
        mode="v2",
        formato=formato,
        broll_enabled=True,
        motion_enabled=True,
        motion_nombre="Carlos Daniel Penagos",
        motion_rol="Prompt Models Studio",
        motion_cta="Sigue para más",
        motion_textos_llm=True,  # NO deterministico: el LLM escribe los letreros
        motion_estilo="pms",
        verify_av=True,
    )

    t0 = time.monotonic()
    infos = auto_v2.procesar_clip_v2(
        clip,
        paquete_dir,
        config,
        transcripts=RAIZ / "transcripts",
        clips_dir=RAIZ / "output" / "clips",
        root=RAIZ,
    )
    segundos = time.monotonic() - t0

    return {
        "formato": formato,
        "segundos": round(segundos, 1),
        "salidas": len(infos),
        "llamadas": contador,
    }


def main() -> None:
    import os

    from dotenv import load_dotenv

    load_dotenv()
    faltan = [k for k in ("PEXELS_API_KEY", "DEEPSEEK_API_KEY") if not os.environ.get(k)]
    if faltan:
        print(f"faltan variables de entorno: {', '.join(faltan)}")
        return

    clip_path = RAIZ / "output" / "clips" / CLIP_ARCHIVO
    if not clip_path.is_file():
        print(f"no existe el clip de prueba: {clip_path}")
        return

    resultados = [
        _correr("9:16", RAIZ / "output" / "paquetes" / "mariosoto_00hf4_costo_9x16"),
        _correr("ambos", RAIZ / "output" / "paquetes" / "mariosoto_00hf4_costo_ambos"),
    ]

    print("\n" + json.dumps(resultados, indent=2, ensure_ascii=False))

    salida = Path(__file__).resolve().parent / "COSTO_FORMATO.json"
    salida.write_text(json.dumps(resultados, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n-> {salida.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
