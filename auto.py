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

# Contrato del Modo Automatico (S37-B): puro, sin red ni disco; default mode="classic"
# garantiza que ejecutar_auto(...) sin config = comportamiento historico exacto.
from auto_config import AutoConfig

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
    S37-B: los paquetes v2 ({name}_v2_*) se EXCLUYEN — classic jamas reanuda un
    paquete v2 (ni al reves; ver _paquete_dir_v2).
    """
    PAQUETES_DIR.mkdir(parents=True, exist_ok=True)
    incompletos = sorted(
        d
        for d in PAQUETES_DIR.glob(f"{name}_*")
        if d.is_dir() and not (d / "paquete.json").exists() and not d.name.startswith(f"{name}_v2_")
    )
    if incompletos:
        return incompletos[-1], True
    fecha = time.strftime("%Y%m%d-%H%M")
    nuevo = PAQUETES_DIR / f"{name}_{fecha}"
    nuevo.mkdir(parents=True, exist_ok=True)
    return nuevo, False


def _paquete_dir_v2(name: str, fingerprint: str) -> tuple[Path, bool]:
    """Paquete v2 distinguible ({name}_v2_{fecha}) con marker de fingerprint.

    Solo se reanuda un paquete v2 incompleto cuyo `auto_v2.json` tenga el MISMO
    config_fingerprint (mismo pipeline). Fingerprint distinto -> paquete nuevo (el
    anterior no se destruye). Un paquete clasico jamas se reutiliza como v2.
    """
    PAQUETES_DIR.mkdir(parents=True, exist_ok=True)
    for d in sorted(PAQUETES_DIR.glob(f"{name}_v2_*"), reverse=True):
        if not d.is_dir() or (d / "paquete.json").exists():
            continue
        marker = d / "auto_v2.json"
        try:
            datos = json.loads(marker.read_text(encoding="utf-8")) if marker.exists() else {}
        except (ValueError, OSError):
            continue
        if datos.get("config_fingerprint") == fingerprint:
            return d, True
    fecha = time.strftime("%Y%m%d-%H%M")
    nuevo = PAQUETES_DIR / f"{name}_v2_{fecha}"
    n = 2
    while nuevo.exists():  # config distinta en el mismo minuto: paquete NUEVO, no se pisa
        nuevo = PAQUETES_DIR / f"{name}_v2_{fecha}-{n}"
        n += 1
    nuevo.mkdir(parents=True, exist_ok=True)
    (nuevo / "auto_v2.json").write_text(
        json.dumps({"config_fingerprint": fingerprint, "pipeline_mode": "v2"}, indent=2),
        encoding="utf-8",
    )
    return nuevo, False


def _final_path(clip: dict, paquete_dir: Path) -> tuple[str, Path]:
    """Nombre canonico del clip final dentro del paquete. Puro. Fuente unica del
    nombre para el render y para la deteccion de checkpoint en la reanudacion."""
    stem_9x16 = f"{clip['archivo'].replace('.mp4', '')}_9x16"
    return stem_9x16, paquete_dir / f"{stem_9x16}_{STYLE_AUTO}.mp4"


def _sidecar_path(final_path: Path) -> Path:
    """Checkpoint de metadata junto al clip final. Puro."""
    return final_path.with_name(final_path.stem + ".info.json")


def _cargar_checkpoint(sidecar: Path) -> dict | None:
    """Lee el checkpoint del clip o None si falta/está corrupto (se re-renderiza)."""
    if not sidecar.exists():
        return None
    try:
        return json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None  # checkpoint corrupto -> se trata como inexistente


def _emitir_manifiesto_srt(paquete_dir: Path, srt_ctx, clips_info: list[dict]) -> None:
    """Escribe el manifiesto FINAL saneado del run SRT (cierre S36-C2C). Solo runs con contexto."""
    if srt_ctx is None:
        return
    import auto_srt_manifest  # noqa: PLC0415

    manifest = auto_srt_manifest.build_run_manifest(
        run_id=paquete_dir.name,
        source_filename=srt_ctx.source_filename,
        srt_selected=True,
        clips=clips_info,
    )
    auto_srt_manifest.write_run_manifest(paquete_dir, manifest)


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


def _clip_id(clip: dict) -> str:
    """clip_id estable y seguro derivado del basename del MP4 del clip (validado aguas abajo)."""
    return Path(clip["archivo"]).stem


def _marcar_pipeline_en_meta(meta: dict, *, es_v2: bool, es_srt: bool, fingerprint, config) -> None:
    """Sella la procedencia del pipeline en meta. classic-transcript queda byte-identico
    (no toca meta); v2 y SRT-classic añaden su fingerprint para distinguir el paquete."""
    if es_v2:
        meta["pipeline_mode"] = "v2"
        meta["config_fingerprint"] = fingerprint
        meta["config"] = config.to_dict()
    elif es_srt:  # SRT-classic: procedencia para no confundirlo con classic-transcript
        meta["caption_source"] = "srt"
        meta["config_fingerprint"] = fingerprint


def _procesar_clip_srt(clip: dict, paquete_dir: Path, ctx) -> dict:
    """Un clip con caption_source=srt: deriva SRT/words/groups del PADRE por rango y renderiza.

    El texto oficial viene del clip.srt (rebasado a t=0); las words del clip solo aportan timings
    (semántica S36-C2A1: word_aligned/substitution/cue_fallback). Emojis desde los groups del clip.
    NO usa los `{stem}_words/groups` históricos. Reutiliza auto_srt_artifacts + srt_caption + core.
    """
    import auto_srt_artifacts  # noqa: PLC0415
    import core  # noqa: PLC0415
    import reframe  # noqa: PLC0415
    import srt_caption  # noqa: PLC0415
    from styles import get_style  # noqa: PLC0415

    stem_9x16, final_path = _final_path(clip, paquete_dir)
    clip_path = CLIPS_DIR / clip["archivo"]
    start_ms = int(round(float(clip["start"]) * 1000))
    end_ms = int(round(float(clip["end"]) * 1000))

    # Artefactos privados del clip en el namespace del run (SRT/words/groups/manifest).
    arts = auto_srt_artifacts.resolve_clip_artifacts(ctx.run_dir, _clip_id(clip))
    art_summary = auto_srt_artifacts.derive_clip_artifacts(
        arts,
        srt_document=ctx.srt_document,
        parent_words=ctx.parent_words,
        parent_video=ctx.binding.path,
        output_clip=clip_path,
        source_start_ms=start_ms,
        source_end_ms=end_ms,
    )

    rf = reframe.reframe_clip(clip_path, CLIPS_DIR / f"{stem_9x16}.mp4", tracker="escenas")
    clip_9x16 = CLIPS_DIR / f"{stem_9x16}.mp4"
    info = core.get_video_info(clip_9x16)
    dur_ms = int(round(float(info["duration"]) * 1000)) if info.get("duration") else None

    # Groups SRT-alineados del clip (texto oficial del clip.srt + timings de las words del clip).
    clip_words = json.loads(arts.words_path.read_text(encoding="utf-8"))["words"]
    groups, _result, alignment_payload = srt_caption.preparar_desde_srt(
        arts.srt_path, clip_words, video_duration_ms=dur_ms, words_file=arts.words_path.name
    )
    auto_srt_artifacts.persist_alignment(arts, alignment_payload)
    # fracción de cues caídos a cue_fallback (sin karaoke real); 0.0 si no hay cues.
    fallback_ratio = round(_result.cue_fallback / _result.n_cues, 4) if _result.n_cues else 0.0

    import assets_comfy as ac  # noqa: PLC0415

    overlays = ac.resolver_overlays(arts.groups_path, TRANSCRIPTS / f"{stem_9x16}.brain.json")
    style_cfg = get_style(STYLE_AUTO)
    ass_path = ROOT / "output" / f"{stem_9x16}_{STYLE_AUTO}.ass"
    core.build_ass(groups, info["width"], info["height"], style_cfg, ass_path)
    core.burn_video_with_emojis(clip_9x16, ass_path, final_path, overlays, style_cfg)

    return {
        "archivo": final_path.name,
        "titulo": clip.get("titulo", ""),
        "razon": clip.get("razon", ""),
        "score": clip.get("score"),
        "dur_s": clip.get("dur_s", 0),
        "avisos": avisos_de_segmentos(rf.get("segmentos", [])),
        "caption_source": "srt",
        "clip_id": arts.clip_id,
        "caption_coverage": art_summary["caption_coverage"],
        "n_cues": art_summary["n_cues"],
        "fallback_ratio": fallback_ratio,
        "emojis_msg": (
            f"{len(overlays)} overlay(s)"
            if overlays
            else "sin overlays (ComfyUI apagado o sin keywords)"
        ),
    }


def _renderizar_clip(
    clip: dict,
    paquete_dir: Path,
    final_path: Path,
    *,
    es_srt: bool,
    es_v2: bool,
    srt_ctx,
    config,
    etiqueta: str,
    pct: int,
    progress,
) -> dict:
    """Renderiza (o reutiliza) un clip según la ruta. SRT aísla el fallo por clip (saneado)."""
    if es_srt:
        progress(pct, f"Etapa 3-4/4: reencuadre + captions SRT (clip {etiqueta})...")
        try:  # fallo aislado por clip: un clip que revienta no detiene los demas
            return _procesar_clip_srt(clip, paquete_dir, srt_ctx)
        except Exception as exc:  # noqa: BLE001 (se sanea; el run continua en 'partial')
            progress(pct, f"Clip {etiqueta}: error, continua con los demas")
            return {
                "archivo": final_path.name,
                "titulo": clip.get("titulo", ""),
                "clip_id": _clip_id(clip),
                "caption_source": "srt",
                "status": "error",
                "error_code": type(exc).__name__,
            }
    if es_v2:
        import auto_v2  # noqa: PLC0415

        progress(pct, f"Etapa 3-4/4: reencuadre + captions + b-roll (clip {etiqueta})...")
        return auto_v2.procesar_clip_v2(
            clip, paquete_dir, config, transcripts=TRANSCRIPTS, clips_dir=CLIPS_DIR, root=ROOT
        )
    if final_path.exists():
        progress(pct, f"Clip {etiqueta}: reutilizando render previo")
        return _info_orfano(clip, final_path)
    progress(pct, f"Etapa 3-4/4: reencuadre + captions (clip {etiqueta})...")
    return _procesar_clip(clip, paquete_dir)


def ejecutar_auto(
    video_path: Path,
    name: str,
    progress=None,
    objetivo: str = "clips",
    *,
    config: AutoConfig | None = None,
) -> dict:
    """Orquestador del Modo Automatico. Objetivo unico: clips virales.

    Pipeline classic (identico a s26 RUTA A): transcripcion -> clipper (analisis IA +
    corte, hasta MAX_CLIPS) -> reframe escenas -> captions hormozi + emojis
    fail-open. Devuelve {paquete, resumen, clips, meta}.

    S37-B: `config` (keyword-only) activa el Modo Automatico v2 con
    AutoConfig(mode="v2"): mismo camino hasta el clipper, y por clip agrega b-roll
    automatico (planner S37-A + fetchers Pexels), FX express y verificacion A/V dura.
    config=None o mode="classic" -> ruta historica EXACTA (sin planner, sin Pexels,
    sin FX, sin sidecars nuevos).

    Reanudable: si una corrida previa quedo a medias (cierre de ventana, corte de
    luz), reusa transcript, analisis del clipper y clips ya renderizados; solo
    completa lo que falta. Cada clip final es un checkpoint (regla MAESTRO #20).
    Los paquetes classic y v2 nunca se mezclan (naming + fingerprint).
    """
    if objetivo not in OBJETIVOS:
        raise ValueError(f"Objetivo '{objetivo}' no soportado. Opciones: {OBJETIVOS}")
    es_v2 = config is not None and config.mode == "v2"
    es_srt = config is not None and config.caption_source == "srt"
    # Un run SRT es un pipeline distinto: paquete fingerprinteado (aislado del transcript/classic).
    usa_fp = es_v2 or es_srt
    fingerprint = config.fingerprint() if usa_fp else None
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

    if es_v2:
        import auto_v2  # noqa: PLC0415 (lazy: la ruta clasica jamas importa la capa v2)
    if usa_fp:
        paquete_dir, reanudado = _paquete_dir_v2(name, fingerprint)
        fecha = paquete_dir.name[len(name) + 4 :]  # {name}_v2_{fecha}
    else:
        paquete_dir, reanudado = _paquete_dir(name)
        fecha = paquete_dir.name[len(name) + 1 :]
    srt_ctx = None
    if es_srt:  # resuelve y verifica la fuente SRT del run (selección/video/timings) una vez
        import auto_srt_run  # noqa: PLC0415

        srt_ctx = auto_srt_run.resolve_auto_srt_context(
            name, paquete_dir.name, input_dir=video_path.parent, transcripts_dir=TRANSCRIPTS
        )
    if reanudado:
        progress(28, f"Reanudando paquete {paquete_dir.name} (clips ya listos se conservan)...")

    clips_info: list[dict] = []
    t1 = time.time()
    for i, clip in enumerate(clips, 1):
        pct = 30 + int(60 * (i - 1) / max(len(clips), 1))
        _stem, final_path = _final_path(clip, paquete_dir)
        sidecar = _sidecar_path(final_path)
        info_prev = _cargar_checkpoint(sidecar)
        if info_prev is not None:
            if es_srt:
                valido = final_path.exists()  # done invalido (output faltante) -> re-render
            else:
                valido = not es_v2 or auto_v2.checkpoint_v2_valido(
                    info_prev, fingerprint, final_path, TRANSCRIPTS
                )
            if valido:
                progress(pct, f"Clip {i}/{len(clips)}: ya listo (reanudacion, sin re-render)")
                clips_info.append(info_prev)
                continue
            progress(pct, f"Clip {i}/{len(clips)}: checkpoint incompatible, se re-renderiza")
        info = _renderizar_clip(
            clip,
            paquete_dir,
            final_path,
            es_srt=es_srt,
            es_v2=es_v2,
            srt_ctx=srt_ctx,
            config=config,
            etiqueta=f"{i}/{len(clips)}",
            pct=pct,
            progress=progress,
        )
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
    _marcar_pipeline_en_meta(
        meta, es_v2=es_v2, es_srt=es_srt, fingerprint=fingerprint, config=config
    )
    (paquete_dir / "REPORTE.md").write_text(
        generar_reporte_md(name, clips_info, meta), encoding="utf-8"
    )
    (paquete_dir / "paquete.json").write_text(
        json.dumps({"clips": clips_info, "meta": meta}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if es_srt:  # manifiesto FINAL saneado del run SRT (cierre S36-C2C)
        _emitir_manifiesto_srt(paquete_dir, srt_ctx, clips_info)
    resumen = resumen_paquete(clips_info)
    progress(100, resumen)
    return {
        "paquete": paquete_dir.relative_to(ROOT).as_posix(),
        "resumen": resumen,
        "clips": clips_info,
        "meta": meta,
        "casi": resultado.get("casi", []),
    }
