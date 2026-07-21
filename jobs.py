"""jobs.py - Workers de background para Centrito Studio (registro en jobs_registry)."""

from __future__ import annotations

import json
from pathlib import Path

import core
import video_encoder

# Re-export: los consumidores (app.py, tests) siguen usando jobs.new_job/get_job
# y jobs.run_render (worker movido a jobs_render.py en el split s34 B2).
from jobs_registry import get_job, new_job, update_job  # noqa: F401
from jobs_render import run_render  # noqa: F401

ROOT = Path(__file__).parent
TRANSCRIPTS = ROOT / "transcripts"
OUTPUT_DIR = ROOT / "output"


# ---Worker: transcripcion ---──────────────────────────────────────────────────


def _write_json_pair(p1: Path, blob1: str, p2: Path, blob2: str) -> None:
    """Escribe dos JSON ya serializados de forma atomica y durable (H2, P2-ATOM-STATE).

    Cada destino usa el contrato unico de `atomic_io` (temporal UNICO + fsync + os.replace), asi
    dos writers concurrentes al mismo destino nunca colisionan el `.tmp`.
    """
    from atomic_io import atomic_write_text  # noqa: PLC0415

    atomic_write_text(Path(p1), blob1)
    atomic_write_text(Path(p2), blob2)


def run_transcribe(
    jid: str,
    mp4: Path,
    lang: str,
    model_arg: str,
    name: str,
    *,
    srt_artifact_key: str | None = None,
    selected_video_binding=None,
) -> None:
    """Worker: transcribe el video y guarda words/groups.

    Sin `srt_artifact_key` = ruta transcript HISTORICA EXACTA (`transcripts/{name}_words.json`
    + `_groups.json`). Con `srt_artifact_key` (S36-C2A1) = namespace privado por filename
    (`transcripts/studio_srt_timings/{name}/{key}/words.json` + `groups.json`), que NUNCA pisa
    los artefactos historicos. La ruta SRT revalida el binding del video (TOCTOU) antes de Whisper.
    """
    try:
        import transcript_provenance as tp  # noqa: PLC0415

        if srt_artifact_key is not None:  # ruta SRT: namespace privado + binding TOCTOU
            import studio_srt_runtime as rt  # noqa: PLC0415

            if selected_video_binding is None:
                raise ValueError("falta el binding del video seleccionado")
            rt.verify_selected_video_binding(selected_video_binding, mp4)  # antes de Whisper
            arts = tp.resolve_srt_timing_artifacts(
                transcripts_dir=TRANSCRIPTS, video_stem=name, video_filename=Path(mp4).name
            )
            if arts.key != srt_artifact_key:
                raise ValueError("clave de artefacto SRT inconsistente")
            words_dst, groups_dst = arts.words_path, arts.groups_path
        else:  # ruta transcript historica (stem-root)
            words_dst = TRANSCRIPTS / f"{name}_words.json"
            groups_dst = TRANSCRIPTS / f"{name}_groups.json"

        update_job(jid, status="running", progress=5, message="Cargando modelo Whisper...")
        device, compute = core.detect_device()
        model_path, label = core.resolve_model(model_arg)
        update_job(jid, progress=15, message=f"Transcribiendo con {label}...")

        result = core.transcribe_video(mp4, lang, device, compute, model_path)
        # Liga los timings al video EXACTO recibido (procedencia): filename + size + mtime.
        # No modifica words/language/timings; solo agrega metadata segura `source_video`.
        result = tp.attach_video_provenance(result, mp4)
        update_job(jid, progress=60, message="Agrupando palabras...")

        groups = core.group_words(result["words"])
        update_job(jid, progress=85, message="Guardando transcript...")

        words_blob = json.dumps(result, ensure_ascii=False, indent=2)
        groups_blob = json.dumps(groups, ensure_ascii=False, indent=2)
        _write_json_pair(words_dst, words_blob, groups_dst, groups_blob)

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


@video_encoder.con_snapshot  # instantania inmutable del encoder para todo el job
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
        from atomic_io import atomic_write_json  # noqa: PLC0415

        atomic_write_json(TRANSCRIPTS / f"{name}_limpio_words.json", raw_clean)
        drift_note = " (re-transcribir recomendado)" if drift > dep.DRIFT_THRESHOLD else ""
        update_job(
            jid,
            status="done",
            progress=100,
            message=f"Listo - {result['cuts']} cortes, -{result['saved_s']}s{drift_note}",
            result={**result, "output": out_mp4.name, "drift_s": drift},
        )
    except Exception as exc:
        mensaje = _error_publico_depurar(exc)
        update_job(jid, status="error", message=mensaje, error=mensaje)


def _error_publico_depurar(exc: Exception) -> str:
    """Mensaje accionable y saneado del worker de depurar (sin stderr, rutas ni payloads)."""
    nombre = type(exc).__name__
    if nombre in ("FFmpegUnavailable", "FFprobeUnavailable", "MediaDependencyUnavailable"):
        return str(exc)  # el texto tipado ya es accionable y no lleva rutas
    if nombre == "NVENCUnavailable":
        return str(exc)  # mensaje accionable saneado (revisa el driver / usa modo auto o cpu)
    if nombre == "MediaProbeError":
        return "No se pudo analizar el video para depurarlo."
    return "La depuracion no pudo completarse."


# ---Worker: clipper ---───────────────────────────────────────────────────────


@video_encoder.con_snapshot  # instantania inmutable del encoder (clipper hereda run_edl)
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


@video_encoder.con_snapshot  # instantania inmutable del encoder para todo el job
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
                # F6 avoid_faces (BLOQUEO 1): el CSV de trayectoria queda JUNTO al MP4
                # reframado (trayectoria_<stem>.csv) para que el render lo resuelva solo.
                tray_dir=output_path.parent,
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


# --- Worker: Submagic (motor nube opt-in) -------------------------------------


def _reframe_para_submagic(jid: str, mp4: Path, reframe_9x16: bool) -> tuple[Path, dict]:
    """Decide si reencuadrar a 9:16 antes de subir. Devuelve (ruta_a_subir, evidencia).

    Submagic NO reencuadra: si el clip no es vertical hay que darselo ya en 9:16.
    Reusa reframe.reframe_clip (mismo face tracking del motor local), sin tocar
    caption.py ni core_ass.py. Si ya es vertical o el toggle esta apagado, se sube
    el original."""
    info = core.get_video_info(mp4)
    w, h = info["width"], info["height"]
    ev = {"origen": f"{w}x{h}", "aplicado": False, "subido": f"{w}x{h}"}
    import submagic  # noqa: PLC0415

    if not reframe_9x16:
        ev["motivo"] = "toggle apagado"
        return mp4, ev
    if not submagic.necesita_reframe(w, h):
        ev["motivo"] = "ya era vertical"
        update_job(jid, message=f"Ya era vertical ({w}x{h}) - sin reencuadre")
        return mp4, ev

    import reframe  # noqa: PLC0415

    stage_dir = OUTPUT_DIR / "submagic_stage"
    staged = stage_dir / f"{mp4.stem}_9x16_for_submagic.mp4"
    update_job(jid, status="running", progress=5, message=f"Reencuadrando {w}x{h} a 9:16...")
    reframe.reframe_clip(mp4, staged)
    vinfo = core.get_video_info(staged)
    vw, vh = vinfo["width"], vinfo["height"]
    if not submagic.es_9x16(vw, vh):
        raise RuntimeError(f"Reframe no produjo 9:16 (quedo {vw}x{vh})")
    ev.update({"aplicado": True, "subido": f"{vw}x{vh}", "motivo": "horizontal reencuadrado"})
    update_job(jid, message=f"Reencuadrado {w}x{h} -> {vw}x{vh}")
    return staged, ev


def run_submagic_render(
    jid: str,
    mp4: Path,
    name: str,
    reframe_9x16: bool = True,
    template_name: str | None = None,
) -> None:
    """Worker: edita un video con Submagic (nube). NO pasa por caption.py.

    Flujo async: reframe a 9:16 si aplica -> upload multipart -> poll estado ->
    export fallback si no hay downloadUrl -> poll downloadUrl -> descarga MP4 a
    output/. Fail seguro: errores HTTP muestran status + mensaje sin secretos
    (regla #9)."""
    try:
        import time  # noqa: PLC0415

        import submagic  # noqa: PLC0415

        if not submagic.tiene_key():
            msg = "Falta SUBMAGIC_API_KEY en .env (ver .env.example)"
            update_job(jid, status="error", message=msg, error=msg)
            return

        def _prog(texto: str, pct: int) -> None:
            if pct < 0:
                update_job(jid, message=texto)
            else:
                update_job(jid, progress=pct, message=texto)

        upload_path, reframe_ev = _reframe_para_submagic(jid, mp4, reframe_9x16)
        params = {"templateName": template_name} if template_name else None

        t_up = time.monotonic()
        update_job(jid, status="running", progress=10, message="Subiendo a Submagic...")
        pid, rate_up = submagic.enviar_video(upload_path, title=name, params=params)
        up_s = round(time.monotonic() - t_up, 1)
        update_job(jid, progress=25, message=f"Subido en {up_s}s - procesando en la nube...")

        t_poll = time.monotonic()
        try:
            url = submagic.esperar_download_url(pid, progress=_prog)
        except TimeoutError:
            # Fallback: autoRender no disparo -> export manual y re-poll.
            update_job(jid, progress=60, message="Sin downloadUrl - lanzando export...")
            submagic.exportar(pid)
            url = submagic.esperar_download_url(pid, progress=_prog)
        poll_s = round(time.monotonic() - t_poll, 1)

        t_dl = time.monotonic()
        update_job(jid, progress=90, message="Descargando MP4 final...")
        dest = OUTPUT_DIR / f"{name}_submagic.mp4"
        nbytes = submagic.descargar(url, dest)
        dl_s = round(time.monotonic() - t_dl, 1)

        update_job(
            jid,
            status="done",
            progress=100,
            message=f"Listo - {dest.name} ({nbytes // 1024} KB)",
            result={
                "output": dest.name,
                "project_id_parcial": pid[:6] + "..." if len(pid) > 6 else pid,
                "bytes": nbytes,
                "tiempos_s": {"upload": up_s, "poll": poll_s, "download": dl_s},
                "rate_limit": rate_up,
                "engine": "submagic",
                "sin_caption_local": True,
                "reframe": reframe_ev,
                "template": template_name or submagic.DEFAULT_PARAMS["templateName"],
            },
        )
    except Exception as exc:
        update_job(jid, status="error", message=str(exc), error=str(exc))


# --- Worker: modo automatico ---------------------------------------------------


def _error_publico_auto(exc: Exception) -> str:
    """Traduce fallos del worker sin publicar paths, keys ni payloads internos."""
    # H3: dependencia multimedia ausente -> mensaje accionable (el texto tipado no lleva rutas).
    if type(exc).__name__ in (
        "FFmpegUnavailable",
        "FFprobeUnavailable",
        "MediaDependencyUnavailable",
    ):
        return str(exc)
    if type(exc).__name__ == "AudioIntegrityError":
        return "La verificacion de integridad de audio no fue aprobada."
    if type(exc).__name__ == "AVSyncError":
        return "La verificacion de sincronizacion A/V no fue aprobada."
    return "El procesamiento automatico no pudo completarse."


@video_encoder.con_snapshot  # instantania inmutable del encoder para todo el pipeline Auto
def run_auto(jid: str, mp4: Path, name: str, objetivo: str = "clips", *, config=None) -> None:
    """Worker: Modo Automatico v1 — capa delgada sobre auto.ejecutar_auto (regla #19)."""
    try:
        import auto  # noqa: PLC0415

        inicial = (
            "Iniciando Automatico v2..."
            if config is not None and getattr(config, "mode", None) == "v2"
            else "Iniciando Modo Automatico clasico..."
        )
        update_job(jid, status="running", progress=2, message=inicial)

        def _progress(pct: int, msg: str) -> None:
            update_job(jid, progress=pct, message=msg)

        result = auto.ejecutar_auto(mp4, name, progress=_progress, objetivo=objetivo, config=config)
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
        mensaje = _error_publico_auto(exc)
        update_job(jid, status="error", message=mensaje, error=mensaje)
