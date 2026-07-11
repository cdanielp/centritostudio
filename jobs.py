"""jobs.py - Workers de background para Centrito Studio (registro en jobs_registry)."""

from __future__ import annotations

import json
from pathlib import Path

import core

# Re-export: los consumidores (app.py, tests) siguen usando jobs.new_job/get_job.
from jobs_registry import get_job, new_job, update_job  # noqa: F401
from styles import get_style

ROOT = Path(__file__).parent
TRANSCRIPTS = ROOT / "transcripts"
OUTPUT_DIR = ROOT / "output"


# ---Worker: transcripcion ---──────────────────────────────────────────────────


def run_transcribe(jid: str, mp4: Path, lang: str, model_arg: str, name: str) -> None:
    """Worker: transcribe el video y guarda words.json y groups.json."""
    try:
        update_job(jid, status="running", progress=5, message="Cargando modelo Whisper...")
        device, compute = core.detect_device()
        model_path, label = core.resolve_model(model_arg)
        update_job(jid, progress=15, message=f"Transcribiendo con {label}...")

        result = core.transcribe_video(mp4, lang, device, compute, model_path)
        update_job(jid, progress=60, message="Agrupando palabras...")

        groups = core.group_words(result["words"])
        update_job(jid, progress=85, message="Guardando transcript...")

        raw_path = TRANSCRIPTS / f"{name}_words.json"
        grp_path = TRANSCRIPTS / f"{name}_groups.json"
        raw_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        grp_path.write_text(json.dumps(groups, ensure_ascii=False, indent=2), encoding="utf-8")

        update_job(
            jid,
            status="done",
            progress=100,
            message=f"OK - {len(result['words'])} palabras, {len(groups)} grupos",
            result={"words": len(result["words"]), "groups": len(groups)},
        )
    except Exception as exc:
        update_job(jid, status="error", message=str(exc), error=str(exc))


# ---Worker: analisis IA ---────────────────────────────────────────────────────


def run_analyze(jid: str, grp_path: Path, name: str) -> None:
    """Worker: analiza grupos con LLM y guarda brain.json."""
    try:
        import brain  # noqa: PLC0415

        update_job(jid, status="running", progress=10, message="Cargando grupos...")
        groups = json.loads(grp_path.read_text(encoding="utf-8"))
        update_job(jid, progress=30, message="Enviando al LLM...")
        data = brain.analizar_grupos(groups, contexto=name, video_name=name)
        n_kw = sum(1 for g in data.get("groups", []) if g.get("kw") is not None)
        n_em = sum(1 for g in data.get("groups", []) if g.get("emoji"))
        update_job(
            jid,
            status="done",
            progress=100,
            message=f"OK - {n_kw} keywords, {n_em} emojis",
            result={"keywords": n_kw, "emojis": n_em},
        )
    except Exception as exc:
        update_job(jid, status="error", message=str(exc), error=str(exc))


# ---Worker: depuracion ---────────────────────────────────────────────────────


def run_depurar(jid: str, mp4: Path, words_path: Path, name: str, mode: str) -> None:
    """Worker: depura el video eliminando silencios y opcionalmente muletillas."""
    try:
        import depurador as dep  # noqa: PLC0415

        update_job(jid, status="running", progress=10, message="Cargando words.json...")
        raw = json.loads(words_path.read_text(encoding="utf-8"))
        words = raw.get("words", [])
        out_mp4 = OUTPUT_DIR / f"{name}_limpio.mp4"
        update_job(jid, progress=20, message=f"Depurando en modo {mode}...")
        result = dep.depurar(mp4, words, mode, out_mp4)

        new_words, drift = dep.recalcular_words(words, result["edl"])
        raw_clean = {**raw, "words": new_words}
        (TRANSCRIPTS / f"{name}_limpio_words.json").write_text(
            json.dumps(raw_clean, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        drift_note = " (re-transcribir recomendado)" if drift > dep.DRIFT_THRESHOLD else ""
        update_job(
            jid,
            status="done",
            progress=100,
            message=f"Listo - {result['cuts']} cortes, -{result['saved_s']}s{drift_note}",
            result={**result, "output": out_mp4.name, "drift_s": drift},
        )
    except Exception as exc:
        update_job(jid, status="error", message=str(exc), error=str(exc))


# ---Worker: clipper ---───────────────────────────────────────────────────────


def run_clips(jid: str, mp4: Path, words_path: Path, name: str, tipos: str) -> None:
    """Worker: genera clips virales con IA y los guarda en output/clips/."""
    try:
        import clipper  # noqa: PLC0415

        update_job(jid, status="running", progress=5, message="Cargando words.json...")
        raw = json.loads(words_path.read_text(encoding="utf-8"))
        words = raw.get("words", [])
        update_job(jid, progress=10, message=f"Construyendo frases ({len(words)} palabras)...")

        def _progress(msg: str, pct: int) -> None:
            update_job(jid, progress=pct, message=msg)

        # Monkey-patch print para capturar mensajes de progreso al job
        import builtins  # noqa: PLC0415

        orig_print = builtins.print

        def _patched_print(*args, **kwargs) -> None:
            orig_print(*args, **kwargs)
            txt = " ".join(str(a) for a in args)
            if "[clipper]" in txt or "[clipper_brain]" in txt:
                clean = txt.replace("[clipper] ", "").replace("[clipper_brain] ", "")
                update_job(jid, message=clean)

        builtins.print = _patched_print
        try:
            result = clipper.generar_clips(mp4, words, tipos)
        finally:
            builtins.print = orig_print

        n_clips = len(result.get("clips", []))
        err = result.get("error")
        casi = result.get("casi", [])

        if err:
            update_job(jid, status="error", progress=100, message=err, error=err, result=result)
            return

        resumen = result.get("telemetria_resumen", {})
        msg = f"Listo - {n_clips} clip(s) generados" + (
            f" | ${resumen.get('costo_usd', 0):.4f}" if resumen else ""
        )
        if n_clips == 0 and casi:
            mejor = max(casi, key=lambda c: c.get("score", 0))
            msg = (
                f"Ningun segmento supero {clipper.SCORE_MIN}/100. "
                f"El mejor llego a {mejor.get('score', 0)}: "
                f'"{mejor.get("titulo", "")}" -- {mejor.get("razon", "")}'
            )
        elif n_clips == 0:
            msg = f"Ningun clip supero el umbral {clipper.SCORE_MIN}/100"

        update_job(
            jid,
            status="done",
            progress=100,
            message=msg,
            result={
                "clips": result.get("clips", []),
                "casi": casi,
                "telemetria_resumen": resumen,
                "n_clips": n_clips,
            },
        )
    except Exception as exc:
        update_job(jid, status="error", message=str(exc), error=str(exc))


# --- Worker: reframe ----------------------------------------------------------


def run_reframe(
    jid: str,
    clip_path: Path,
    output_path: Path,
    turnos: dict | None,
    punch_in: bool,
    layout: str = "tracking",
    detector_type: str = "yunet",
    tracker: str = "escenas",
) -> None:
    """Worker: reencuadra un clip de 16:9 a 9:16 (tracking o stack)."""
    try:
        import reframe  # noqa: PLC0415

        update_job(jid, status="running", progress=10, message="Detectando caras...")
        if layout == "stack":
            result = reframe.reframe_stack_clip(clip_path, output_path, detector_type=detector_type)
            update_job(
                jid,
                status="done",
                progress=100,
                message=f"Stack listo ({result['n_caras']} bandas) en {result['dur_s']:.1f}s",
                result=result,
            )
        else:
            result = reframe.reframe_clip(
                clip_path,
                output_path,
                turnos=turnos,
                punch_in=punch_in,
                detector_type=detector_type,
                tracker=tracker,
            )
            update_job(
                jid,
                status="done",
                progress=100,
                message=f"Listo ({result['n_caras']} cara(s)) en {result['dur_s']:.1f}s",
                result=result,
            )
    except ValueError as exc:
        update_job(jid, status="error", progress=0, message=str(exc), error=str(exc))
    except Exception as exc:
        update_job(jid, status="error", message=str(exc), error=str(exc))


# --- Worker: modo automatico ---------------------------------------------------


def run_auto(jid: str, mp4: Path, name: str, objetivo: str = "clips") -> None:
    """Worker: Modo Automatico v1 — capa delgada sobre auto.ejecutar_auto (regla #19)."""
    try:
        import auto  # noqa: PLC0415

        update_job(jid, status="running", progress=2, message="Iniciando Modo Automatico...")

        def _progress(pct: int, msg: str) -> None:
            update_job(jid, progress=pct, message=msg)

        result = auto.ejecutar_auto(mp4, name, progress=_progress, objetivo=objetivo)
        n = len(result.get("clips", []))
        msg = result.get("resumen", f"{n} clip(s) en el paquete")
        if n == 0 and result.get("casi"):
            mejor = max(result["casi"], key=lambda c: c.get("score", 0))
            msg = (
                "Ningun segmento supero el umbral del clipper. "
                f'El mejor llego a {mejor.get("score", 0)}: "{mejor.get("titulo", "")}"'
            )
        update_job(jid, status="done", progress=100, message=msg, result=result)
    except Exception as exc:
        update_job(jid, status="error", message=str(exc), error=str(exc))


# --- Worker: render -----------------------------------------------------------


def _apply_emphasis(groups: list[dict], name: str) -> tuple[list[dict], str]:
    """Aplica brain.json al grupo si existe. Devuelve (grupos_enriquecidos, mensaje)."""
    brain_path = TRANSCRIPTS / f"{name}.brain.json"
    if not brain_path.exists():
        msg = "Enfasis NO aplicado: sin brain.json (analiza primero)"
        print(f"[render] {msg}")
        return groups, msg
    brain_data = json.loads(brain_path.read_text(encoding="utf-8"))
    enriched = core.apply_brain(groups, brain_data)
    n_kw = sum(1 for g in brain_data.get("groups", []) if g.get("kw") is not None)
    provider = brain_data.get("provider", "?")
    latency = brain_data.get("latency_s", "?")
    tokens = brain_data.get("tokens", {}).get("total", "?")
    print(f"[render] Enfasis IA | {provider} kw={n_kw} tok={tokens} lat={latency}s")
    return enriched, f"Enfasis aplicado: {n_kw} keywords"


def run_render(
    jid: str,
    mp4: Path,
    grp_path: Path,
    name: str,
    style: str,
    words_per_group: int | None,
    use_emphasis: bool = False,
    use_emojis: bool = False,
    pop: str | None = None,
    preset: str | None = None,
    intensidad: str | None = None,
) -> None:
    """Worker: genera ASS y quema el video. Con `preset` (CVE) manda el plan del
    engine: style/pop/use_emphasis se ignoran (mismo contrato que la CLI)."""
    try:
        update_job(jid, status="running", progress=10, message="Cargando grupos...")
        groups = json.loads(grp_path.read_text(encoding="utf-8"))
        enfasis_msg = ""

        if words_per_group is not None:
            raw_path = TRANSCRIPTS / f"{name}_words.json"
            if raw_path.exists():
                raw = json.loads(raw_path.read_text(encoding="utf-8"))
                groups = core.group_words(raw["words"], max_words=words_per_group)

        plan, preset_msg = None, None
        if preset:
            try:
                import cve  # noqa: PLC0415

                plan, preset_msg = cve.resolver_preset_seguro(preset, intensidad)
            except Exception as exc:  # import cve roto: captions clasicos
                preset_msg = f"Preset no resuelto ({exc}) - render con estilo clasico"

        if use_emphasis and not plan:
            groups, enfasis_msg = _apply_emphasis(groups, name)
            update_job(jid, progress=18, message=enfasis_msg)

        update_job(jid, progress=20, message="Leyendo video info...")
        info = core.get_video_info(mp4)
        w, h = info["width"], info["height"]

        if plan:
            # cve ya quedo importado al resolver el plan (plan no-None lo implica)
            update_job(jid, progress=25, message=f"Aplicando preset {plan.preset}...")
            brain = TRANSCRIPTS / f"{name}.brain.json"
            groups, plan, aviso_brain = cve.aplicar_preset(groups, plan, brain, w, h)
            preset_msg = preset_msg or aviso_brain

        style_cfg = plan.style_cfg if plan else get_style(style, pop)
        # Preset/pop/intensidad entran en el nombre para no pisar variantes distintas.
        if plan:
            base_tag = cve.tag_variante(plan.preset, intensidad)
        else:
            base_tag = f"_{style}" + (f"_{pop}" if pop else "")
        suffix = base_tag
        if use_emphasis and not plan:
            suffix += "_enfasis"
        if use_emojis:
            suffix += "_emojis"
        ass_path = OUTPUT_DIR / f"{name}{base_tag}.ass"
        out_path = OUTPUT_DIR / f"{name}{suffix}.mp4"

        update_job(jid, progress=35, message="Generando subtitulos ASS...")
        core.build_ass(groups, w, h, style_cfg, ass_path)

        if use_emojis:
            import assets_comfy as ac  # noqa: PLC0415

            update_job(jid, progress=48, message="Generando assets IA (ComfyUI)...")
            groups_path = TRANSCRIPTS / f"{name}_groups.json"
            brain_path = TRANSCRIPTS / f"{name}.brain.json"
            overlays = ac.resolver_overlays(groups_path, brain_path)
            n_ov = len(overlays)
            update_job(jid, progress=52, message=f"Quemando con FFmpeg + {n_ov} overlay(s)...")
            elapsed = core.burn_video_with_emojis(mp4, ass_path, out_path, overlays, style_cfg)
            emojis_result = (
                f"{n_ov} overlays aplicados"
                if n_ov
                else "Sin overlays (ComfyUI apagado o sin keywords)"
            )
        else:
            update_job(jid, progress=50, message="Quemando con FFmpeg...")
            elapsed = core.burn_video(mp4, ass_path, out_path)
            emojis_result = None

        emphasis_result = enfasis_msg if (use_emphasis and not plan) else None
        update_job(
            jid,
            status="done",
            progress=100,
            message=f"Listo en {elapsed:.1f}s",
            result={
                "output": out_path.name,
                "elapsed": elapsed,
                "emphasis_msg": emphasis_result,
                "emojis_msg": emojis_result,
                "preset_msg": preset_msg,
            },
        )
    except Exception as exc:
        update_job(jid, status="error", message=str(exc), error=str(exc))
