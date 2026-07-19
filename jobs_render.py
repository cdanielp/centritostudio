"""jobs_render.py - Worker de render del Studio (split de jobs.py, s34 B2).

Mismo contrato que siempre: jobs.py re-exporta run_render y los consumidores
(app.py, tests) no cambian. La novedad s34 es el Caption QA opcional (D25):
modo "alertas" solo reporta; "auto_seguro" aplica confianza alta reagrupando
desde los words corregidos. Fail-open total: sin QA el render es identico.
"""

from __future__ import annotations

import json
from pathlib import Path

import core
from jobs_registry import update_job
from styles import get_style

ROOT = Path(__file__).parent
TRANSCRIPTS = ROOT / "transcripts"
OUTPUT_DIR = ROOT / "output"
# Almacenamiento privado del contrato SRT (S36-C1); solo lo usa la ruta caption_source=srt.
STUDIO_SRT_DIR = TRANSCRIPTS / "studio_srt"


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


def _rutas_render(
    name: str,
    plan,
    style: str,
    pop: str | None,
    intensidad: str | None,
    use_emphasis: bool,
    use_emojis: bool,
) -> tuple[Path, Path]:
    """(ass, mp4) de salida; preset/pop/enfasis/emojis entran al sufijo (no pisar variantes)."""
    if plan:
        import cve  # noqa: PLC0415

        # Sin densidad: el Studio aun no la expone; al exponerla, pasarla aqui
        # (cve.tag_variante ya la acepta) para que variantes no se pisen.
        base_tag = cve.tag_variante(plan.preset, intensidad)
    else:
        base_tag = f"_{style}" + (f"_{pop}" if pop else "")
    suffix = base_tag
    if use_emphasis and not plan:
        suffix += "_enfasis"
    if use_emojis:
        suffix += "_emojis"
    return OUTPUT_DIR / f"{name}{base_tag}.ass", OUTPUT_DIR / f"{name}{suffix}.mp4"


def _aplicar_qa(
    jid: str,
    name: str,
    qa_mode: str,
    qa_guion: str | None,
    groups: list[dict],
    words_per_group: int | None,
) -> tuple[list[dict], str | None]:
    """Caption QA fail-open para el Studio. Devuelve (groups, mensaje_o_None)."""
    try:
        import caption_qa  # noqa: PLC0415

        groups, info = caption_qa.qa_para_studio(name, qa_mode, qa_guion, groups, words_per_group)
        if info is None:
            return groups, None
        destino = (
            f" - detalle en transcripts/{info['alerts_file']}" if info.get("alerts_file") else ""
        )
        msg = (
            f"Caption QA: {info['n_alertas']} alerta(s), {info['aplicadas']} aplicadas, "
            f"{info['pendientes']} pendientes{destino}"
        )
        update_job(jid, progress=16, message=msg)
        return groups, msg
    except Exception as exc:
        print(f"[render] caption-qa fail-open: {type(exc).__name__}")
        return groups, None


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
    qa_mode: str | None = None,
    qa_guion: str | None = None,
    *,
    srt_selection=None,
) -> None:
    """Contrato publico del worker de render. Sin `srt_selection` = ruta transcript historica
    EXACTA (byte-identica); con `srt_selection` (S36-C2A1) = ruta SRT como texto oficial.

    La ruta transcript no importa ni consulta el runtime SRT. La ruta SRT nunca cae al
    transcript: un fallo de seleccion/integridad publica un job en estado error saneado.
    """
    if srt_selection is not None:
        _run_render_srt(jid, mp4, name, style, use_emojis, pop, preset, intensidad, srt_selection)
        return
    _run_render_transcript(
        jid,
        mp4,
        grp_path,
        name,
        style,
        words_per_group,
        use_emphasis,
        use_emojis,
        pop,
        preset,
        intensidad,
        qa_mode,
        qa_guion,
    )


def _run_render_transcript(
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
    qa_mode: str | None = None,
    qa_guion: str | None = None,
) -> None:
    """Worker: genera ASS y quema el video. Con `preset` (CVE) manda el plan del
    engine: style/pop/use_emphasis se ignoran (mismo contrato que la CLI).
    Con `qa_mode` corre el Caption QA antes de agrupar/quemar (fail-open)."""
    try:
        update_job(jid, status="running", progress=10, message="Cargando grupos...")
        groups = json.loads(grp_path.read_text(encoding="utf-8"))
        enfasis_msg = ""

        if words_per_group is not None:
            raw_path = TRANSCRIPTS / f"{name}_words.json"
            if raw_path.exists():
                raw = json.loads(raw_path.read_text(encoding="utf-8"))
                groups = core.group_words(raw["words"], max_words=words_per_group)

        qa_msg = None
        if qa_mode:
            groups, qa_msg = _aplicar_qa(jid, name, qa_mode, qa_guion, groups, words_per_group)

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
        ass_path, out_path = _rutas_render(
            name, plan, style, pop, intensidad, use_emphasis, use_emojis
        )

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

        if plan:
            # cve importado al resolver el plan; sidecar obligatorio con keywords auto (D21)
            cve.escribir_sidecar_seleccion(groups, plan, out_path)

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
                "qa_msg": qa_msg,
            },
        )
    except Exception as exc:
        update_job(jid, status="error", message=str(exc), error=str(exc))


def _run_render_srt(
    jid: str,
    mp4: Path,
    name: str,
    style: str,
    use_emojis: bool,
    pop: str | None,
    preset: str | None,
    intensidad: str | None,
    srt_selection,
) -> None:
    """Worker de render con el SRT seleccionado como texto oficial (S36-C2A1).

    El texto viene del SRT administrado; las words solo aportan timings. El preset CVE anima
    SOLO los cues alineados; los `cue_fallback` quedan estaticos. La salida usa el naming `_srt`
    (no pisa historicos). Ante integridad rota o cualquier fallo: job en error saneado, sin
    ruta/traceback y SIN caer al transcript.
    """
    import srt_render  # noqa: PLC0415
    import studio_srt_runtime as rt  # noqa: PLC0415  (lazy: la ruta transcript no lo importa)
    from srt_import import SrtError  # noqa: PLC0415

    try:
        update_job(jid, status="running", progress=8, message="Cargando seleccion SRT...")
        rt.verify_runtime_integrity(srt_selection)  # revalida integridad al iniciar el worker
        # El worker exige el video EXACTO de la seleccion (nombre+stem+ext). No re-resuelve por
        # stem; un mp4 pasado por error o un cambio .mov<->.mp4 aborta ANTES de tocar FFmpeg.
        rt.verify_selected_video_match(srt_selection, mp4)

        update_job(jid, progress=15, message="Leyendo video info...")
        info = core.get_video_info(mp4)
        w, h = info["width"], info["height"]
        video_ms = int(round(info["duration"] * 1000)) or None

        update_job(jid, progress=25, message="Preparando SRT (texto oficial)...")
        prepared = rt.prepare_selected_srt_groups(
            srt_selection,
            words_path=TRANSCRIPTS / f"{name}_words.json",
            video_duration_ms=video_ms,
            alignment_sidecar_path=TRANSCRIPTS / f"{name}_srt_alignment.json",
        )
        groups = prepared.groups

        plan, preset_msg = None, None
        if preset:
            import cve  # noqa: PLC0415

            plan, preset_msg = cve.resolver_preset_seguro(preset, intensidad)
        if plan:
            update_job(
                jid, progress=32, message=f"Aplicando preset {plan.preset} (solo cues alineados)..."
            )
            groups, plan, aviso = srt_render.apply_preset_to_srt_groups(
                groups,
                plan,
                brain_path=TRANSCRIPTS / f"{name}.brain.json",
                width=w,
                height=h,
                manual_keywords_path=TRANSCRIPTS / f"{name}_keywords.json",
            )
            preset_msg = preset_msg or aviso

        style_cfg = plan.style_cfg if plan else get_style(style, pop)
        variante = srt_render.variante_tag(plan, style, pop, None, intensidad, None)
        ass_path = OUTPUT_DIR / f"{name}{variante}_srt.ass"
        base = srt_render.nombre_base_srt(name, variante, use_emojis, False, None)
        out_path = OUTPUT_DIR / f"{base}.mp4"

        update_job(jid, progress=40, message="Generando subtitulos ASS...")
        core.build_ass(groups, w, h, style_cfg, ass_path)

        if use_emojis:
            import assets_comfy as ac  # noqa: PLC0415

            groups_path = TRANSCRIPTS / f"{name}_groups.json"
            brain_path = TRANSCRIPTS / f"{name}.brain.json"
            overlays = ac.resolver_overlays(groups_path, brain_path)
            update_job(
                jid, progress=55, message=f"Quemando con FFmpeg + {len(overlays)} overlay(s)..."
            )
            elapsed = core.burn_video_with_emojis(mp4, ass_path, out_path, overlays, style_cfg)
        else:
            update_job(jid, progress=55, message="Quemando con FFmpeg...")
            elapsed = core.burn_video(mp4, ass_path, out_path)

        if plan:
            import cve  # noqa: PLC0415

            cve.escribir_sidecar_seleccion(groups, plan, out_path)

        update_job(
            jid,
            status="done",
            progress=100,
            message=f"Listo en {elapsed:.1f}s",
            result={
                "output": out_path.name,
                "elapsed": elapsed,
                "preset_msg": preset_msg,
                "srt": prepared.summary,
            },
        )
    except rt.StudioSrtError as exc:
        # Errores de seleccion/integridad/timings: mensaje ya saneado (sin ruta ni contenido).
        update_job(jid, status="error", message=str(exc), error="srt")
    except SrtError:
        update_job(
            jid, status="error", message="El SRT seleccionado no se pudo alinear.", error="srt"
        )
    except Exception:
        update_job(
            jid, status="error", message="No se pudo renderizar el SRT seleccionado.", error="srt"
        )
