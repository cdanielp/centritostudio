"""auto.py - Modo Automatico v1: capa delgada que orquesta el motor existente.

Regla MAESTRO #19 (DOS MODOS, UN MOTOR): este modulo NO implementa pipeline.
Solo llama funciones publicas de core, clipper, reframe, brain y assets_comfy
(el mismo camino probado en s26 RUTA A), arma el paquete en output/paquetes/
y traduce las metricas por segmento que el modo escenas YA calcula a un
reporte de calidad por tramos en lenguaje humano. Cero mediciones nuevas.

El paquete SIEMPRE termina en revision humana antes de publicar (regla #19).
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

# Reporte de calidad: funciones puras en auto_report.py (split s34 B1).
# Se re-exportan aqui para compatibilidad (tests y jobs consumen auto.*).
from auto_report import (  # noqa: F401
    C1V2_AVISO,
    STYLE_AUTO,
    _fmt_t,
    avisos_de_segmentos,
    estado_clip,
    generar_reporte_md,
    recomendacion_final,
    resumen_paquete,
)

ROOT = Path(__file__).parent
TRANSCRIPTS = ROOT / "transcripts"
CLIPS_DIR = ROOT / "output" / "clips"
PAQUETES_DIR = ROOT / "output" / "paquetes"

OBJETIVOS = ("clips",)  # v1: solo "Clips virales"; roadmap en PREGUNTAS #29


def _progress_nulo(pct: int, msg: str) -> None:
    print(f"[auto] {pct:3d}% {msg}")


def _asegurar_transcript(video_path: Path, name: str, lang: str = "es") -> tuple[list, bool]:
    """Devuelve (words, reutilizado). Transcribe SOLO si falta words.json (voto #10)."""
    import core  # noqa: PLC0415

    words_path = TRANSCRIPTS / f"{name}_words.json"
    if words_path.exists() and words_path.stat().st_mtime >= video_path.stat().st_mtime:
        raw = json.loads(words_path.read_text(encoding="utf-8"))
        return raw.get("words", []), True
    device, compute = core.detect_device()
    model_path, _label = core.resolve_model("auto")
    result = core.transcribe_video(video_path, lang, device, compute, model_path)
    groups = core.group_words(result["words"])
    TRANSCRIPTS.mkdir(exist_ok=True)
    words_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (TRANSCRIPTS / f"{name}_groups.json").write_text(
        json.dumps(groups, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result["words"], False


def _asegurar_clips(video_path: Path, words: list, name: str) -> tuple[dict, bool]:
    """Devuelve (resultado_clipper, reutilizado). Reusa {name}_clips.json si es
    posterior al video: evita re-gastar LLM al reanudar (voto #10 extendido al
    analisis del clipper). El clipper ya persiste el resultado completo a disco.
    """
    import clipper  # noqa: PLC0415

    clips_json = CLIPS_DIR / f"{name}_clips.json"
    if clips_json.exists() and clips_json.stat().st_mtime >= video_path.stat().st_mtime:
        return json.loads(clips_json.read_text(encoding="utf-8")), True
    return clipper.generar_clips(video_path, words, "ambos"), False


def _paquete_dir(name: str) -> tuple[Path, bool]:
    """(paquete_dir, reanudado). Reanuda el paquete incompleto mas reciente del
    video (sin paquete.json = corrida interrumpida); si no hay, crea uno nuevo.
    Un autopiloto debe sobrevivir a un cierre de ventana / corte de luz (incidente
    s27): cada clip ya renderizado es un checkpoint que no se vuelve a pagar.
    """
    PAQUETES_DIR.mkdir(parents=True, exist_ok=True)
    incompletos = sorted(
        d
        for d in PAQUETES_DIR.glob(f"{name}_*")
        if d.is_dir() and not (d / "paquete.json").exists()
    )
    if incompletos:
        return incompletos[-1], True
    fecha = time.strftime("%Y%m%d-%H%M")
    nuevo = PAQUETES_DIR / f"{name}_{fecha}"
    nuevo.mkdir(parents=True, exist_ok=True)
    return nuevo, False


def _final_path(clip: dict, paquete_dir: Path) -> tuple[str, Path]:
    """Nombre canonico del clip final dentro del paquete. Puro. Fuente unica del
    nombre para el render y para la deteccion de checkpoint en la reanudacion."""
    stem_9x16 = f"{clip['archivo'].replace('.mp4', '')}_9x16"
    return stem_9x16, paquete_dir / f"{stem_9x16}_{STYLE_AUTO}.mp4"


def _sidecar_path(final_path: Path) -> Path:
    """Checkpoint de metadata junto al clip final. Puro."""
    return final_path.with_name(final_path.stem + ".info.json")


def _info_orfano(clip: dict, final_path: Path) -> dict:
    """Reconstruye el info de un clip final ya renderizado que no tiene sidecar
    (paquete de una corrida previa a la reanudacion). Reusa el MP4 tal cual: los
    avisos por tramos no se pueden recuperar sin re-renderizar el reframe (motor
    intacto esta sesion), asi que se marcan como no disponibles en vez de repetir
    el render. Cero desperdicio.
    """
    return {
        "archivo": final_path.name,
        "titulo": clip.get("titulo", ""),
        "razon": clip.get("razon", ""),
        "score": clip.get("score"),
        "dur_s": clip.get("dur_s", 0),
        "avisos": [],
        "tramos_disponibles": False,
        "emojis_msg": "reutilizado de corrida previa",
    }


def _brain_fail_open(groups: list[dict], stem: str) -> dict | None:
    """Analisis IA del clip. Fail-open: sin brain el paquete sigue (regla #8)."""
    try:
        import brain  # noqa: PLC0415

        data = brain.analizar_grupos(groups, video_name=stem)
        return data if data.get("groups") else None
    except Exception as exc:
        print(f"[auto] brain fail-open: {type(exc).__name__}")
        return None


def _procesar_clip(clip: dict, paquete_dir: Path) -> dict:
    """Un clip del clipper -> reframe escenas + captions + emojis en el paquete.

    Orquestacion pura de funciones existentes (regla #19): reframe.reframe_clip,
    core.apply_brain/build_ass/burn_video_with_emojis, assets_comfy.resolver_overlays.
    """
    import core  # noqa: PLC0415
    import reframe  # noqa: PLC0415
    from styles import get_style  # noqa: PLC0415

    stem = clip["archivo"].replace(".mp4", "")
    stem_9x16, final_path = _final_path(clip, paquete_dir)
    clip_path = CLIPS_DIR / clip["archivo"]

    rf = reframe.reframe_clip(clip_path, CLIPS_DIR / f"{stem_9x16}.mp4", tracker="escenas")

    # Transcript re-basado del clipper -> stems _9x16 (regla #4: no re-transcribir)
    for suf in ("_words.json", "_groups.json"):
        src = TRANSCRIPTS / f"{stem}{suf}"
        if src.exists():
            shutil.copy(src, TRANSCRIPTS / f"{stem_9x16}{suf}")

    groups_path = TRANSCRIPTS / f"{stem_9x16}_groups.json"
    groups = json.loads(groups_path.read_text(encoding="utf-8")) if groups_path.exists() else []

    brain_data = _brain_fail_open(groups, stem_9x16)
    if brain_data:
        groups = core.apply_brain(groups, brain_data)

    import assets_comfy as ac  # noqa: PLC0415

    overlays = ac.resolver_overlays(groups_path, TRANSCRIPTS / f"{stem_9x16}.brain.json")

    clip_9x16 = CLIPS_DIR / f"{stem_9x16}.mp4"
    info = core.get_video_info(clip_9x16)
    style_cfg = get_style(STYLE_AUTO)
    ass_path = ROOT / "output" / f"{stem_9x16}_{STYLE_AUTO}.ass"
    core.build_ass(groups, info["width"], info["height"], style_cfg, ass_path)

    core.burn_video_with_emojis(clip_9x16, ass_path, final_path, overlays, style_cfg)

    # Caption QA solo-lectura para el REPORTE (regla 15: no altera el render)
    try:
        import caption_qa  # noqa: PLC0415

        info_qa = caption_qa.qa_para_reporte(stem_9x16)  # fail-open interno
    except ImportError:
        info_qa = None

    return {
        "archivo": final_path.name,
        "titulo": clip.get("titulo", ""),
        "razon": clip.get("razon", ""),
        "score": clip.get("score"),
        "dur_s": clip.get("dur_s", 0),
        "avisos": avisos_de_segmentos(rf.get("segmentos", [])),
        "qa": info_qa,
        "emojis_msg": (
            f"{len(overlays)} overlay(s)"
            if overlays
            else "sin overlays (ComfyUI apagado o sin keywords)"
        ),
    }


def ejecutar_auto(video_path: Path, name: str, progress=None, objetivo: str = "clips") -> dict:
    """Orquestador del Modo Automatico v1. Objetivo unico: clips virales.

    Pipeline (identico a s26 RUTA A): transcripcion -> clipper (analisis IA +
    corte, hasta MAX_CLIPS) -> reframe escenas -> captions hormozi + emojis
    fail-open. Devuelve {paquete, resumen, clips, meta}.

    Reanudable: si una corrida previa quedo a medias (cierre de ventana, corte de
    luz), reusa transcript, analisis del clipper y clips ya renderizados; solo
    completa lo que falta. Cada clip final es un checkpoint (regla MAESTRO #20).
    """
    if objetivo not in OBJETIVOS:
        raise ValueError(f"Objetivo '{objetivo}' no soportado. Opciones: {OBJETIVOS}")
    progress = progress or _progress_nulo
    t0 = time.time()

    progress(5, "Etapa 1/4: transcripcion...")
    t1 = time.time()
    words, reutilizado = _asegurar_transcript(video_path, name)
    t_tx = time.time() - t1

    progress(20, "Etapa 2/4: analisis IA + clipper...")
    t1 = time.time()
    resultado, analisis_reutilizado = _asegurar_clips(video_path, words, name)
    t_clip = time.time() - t1
    if resultado.get("error"):
        raise RuntimeError(resultado["error"])
    clips = resultado.get("clips", [])

    paquete_dir, reanudado = _paquete_dir(name)
    fecha = paquete_dir.name[len(name) + 1 :]
    if reanudado:
        progress(28, f"Reanudando paquete {paquete_dir.name} (clips ya listos se conservan)...")

    clips_info: list[dict] = []
    t1 = time.time()
    for i, clip in enumerate(clips, 1):
        pct = 30 + int(60 * (i - 1) / max(len(clips), 1))
        _stem, final_path = _final_path(clip, paquete_dir)
        sidecar = _sidecar_path(final_path)
        if sidecar.exists():
            progress(pct, f"Clip {i}/{len(clips)}: ya listo (reanudacion, sin re-render)")
            clips_info.append(json.loads(sidecar.read_text(encoding="utf-8")))
            continue
        if final_path.exists():
            progress(pct, f"Clip {i}/{len(clips)}: reutilizando render previo")
            info = _info_orfano(clip, final_path)
        else:
            progress(pct, f"Etapa 3-4/4: reencuadre + captions (clip {i}/{len(clips)})...")
            info = _procesar_clip(clip, paquete_dir)
        sidecar.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        clips_info.append(info)
    t_render = time.time() - t1

    progress(95, "Armando paquete...")
    meta = {
        "fecha": fecha,
        "objetivo": objetivo,
        "reanudado": reanudado,
        "transcript_reutilizado": reutilizado,
        "analisis_reutilizado": analisis_reutilizado,
        "t_transcripcion_s": round(t_tx, 1),
        "t_clipper_s": round(t_clip, 1),
        "t_render_s": round(t_render, 1),
        "t_total_s": round(time.time() - t0, 1),
        "costo_usd": resultado.get("telemetria_resumen", {}).get("costo_usd", 0),
    }
    (paquete_dir / "REPORTE.md").write_text(
        generar_reporte_md(name, clips_info, meta), encoding="utf-8"
    )
    (paquete_dir / "paquete.json").write_text(
        json.dumps({"clips": clips_info, "meta": meta}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    resumen = resumen_paquete(clips_info)
    progress(100, resumen)
    return {
        "paquete": paquete_dir.relative_to(ROOT).as_posix(),
        "resumen": resumen,
        "clips": clips_info,
        "meta": meta,
        "casi": resultado.get("casi", []),
    }
