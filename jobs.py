"""jobs.py - Workers de background para Centrito Studio (registro en jobs_registry)."""

from __future__ import annotations

import json
from pathlib import Path

import core

# Re-export: los consumidores (app.py, tests) siguen usando jobs.new_job/get_job
# y jobs.run_render (worker movido a jobs_render.py en el split s34 B2).
from jobs_registry import get_job, new_job, update_job  # noqa: F401
from jobs_render import run_render  # noqa: F401

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
