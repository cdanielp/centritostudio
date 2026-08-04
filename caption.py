"""
caption.py — CLI para el pipeline de captions.
Toda la lógica vive en core.py; los flags/ayuda de la CLI en caption_args.py (s34).
Uso: python caption.py input/video.mp4 --style hormozi --lang es
     python caption.py input/ --style karaoke --lang es   (batch)
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import core
from caption_args import build_parser, motion_opts_de_args, qa_opts_de_args
from srt_import import SrtError as _SrtUserError  # error de USUARIO del SRT (no bug); stdlib
from styles import get_style

_TRANSCRIPTS_DIR = Path(__file__).parent / "transcripts"

# Tope del offset explicito (1 hora). Mismo limite que valida la API: mas alla no es un
# desajuste de subtitulos, es un archivo equivocado.
_SRT_OFFSET_MAX_MS = 3_600_000


def _load_or_transcribe(
    video_path: Path, stem: str, lang: str, device: str, compute: str, model_path: str
) -> dict:
    """Reutiliza el transcript existente si es mas reciente que el video (voto #10).

    Un transcript reutilizado se VERIFICA contra el video (P1): el del video depurado y el del
    original tienen timelines distintos y mezclarlos desincroniza el render en silencio.
    """
    import media_provenance  # noqa: PLC0415

    words_path = _TRANSCRIPTS_DIR / f"{stem}_words.json"
    if words_path.exists():
        vid_mtime = video_path.stat().st_mtime
        words_mtime = words_path.stat().st_mtime
        if words_mtime >= vid_mtime:
            print(f"[whisper] reutilizando transcript existente: {words_path.name}")
            raw = json.loads(words_path.read_text(encoding="utf-8"))
            media_provenance.verificar_transcript_contra_video(
                raw,
                video_path,
                video_duration_s=core.get_video_info(video_path)["duration"],
                words_path=words_path,
                root=Path(__file__).parent,
            )
            lang_str = raw.get("language", "?")
            print(f"[whisper] {len(raw.get('words', []))} palabras | idioma: {lang_str}")
            return raw
    transcript = core.transcribe_video(video_path, lang, device, compute, model_path)
    print(f"[whisper] {len(transcript['words'])} palabras | idioma: {transcript['language']}")
    info = core.get_video_info(video_path)
    return media_provenance.attach_media_fingerprint(
        transcript,
        video_path,
        duration_s=info["duration"],
        fps=info.get("fps", 0.0),
        root=Path(__file__).parent,
    )


def _aplicar_caption_qa(transcript: dict, stem: str, qa_opts: dict) -> dict:
    """Capa Caption QA fail-open: si el QA falla, el render sale con la original."""
    try:
        import caption_qa  # noqa: PLC0415

        words, resumen = caption_qa.ejecutar_qa(
            transcript["words"],
            stem,
            modo=qa_opts.get("modo", "alertas"),
            guion_path=qa_opts.get("guion"),
            glosario_path=qa_opts.get("glosario"),
            usar_llm=qa_opts.get("llm", False),
        )
        destino = f" -> {resumen['alerts_file']}" if resumen.get("alerts_file") else ""
        print(
            f"[caption-qa] {resumen['n_alertas']} alerta(s) | {resumen['aplicadas']} "
            f"aplicadas | {resumen['pendientes']} pendientes{destino}"
        )
        return {**transcript, "words": words}
    except Exception as exc:
        print(
            f"[caption-qa] AVISO: QA fallo ({type(exc).__name__}) "
            "- render sale con transcripcion original"
        )
        return transcript


def _resolver_plan_preset(preset: str | None, intensidad: str | None, densidad: str | None):
    """RenderPlan del engine CVE o None. Fallo del engine -> None (captions simples)."""
    if not preset:
        return None
    try:
        import cve  # noqa: PLC0415

        plan, _aviso = cve.resolver_preset_seguro(preset, intensidad, densidad)
        return plan
    except Exception as e:  # cubre hasta un import cve roto
        print(f"[cve] preset no resuelto ({e}) - se usa el estilo clasico")
        return None


_MARCA_DIR = Path(__file__).parent / "assets" / "marca"


def _logo_png() -> Path | None:
    """Logo real de marca para el FX (PNG). None si aun no existe (M2 pendiente de K)."""
    if not _MARCA_DIR.exists():
        return None
    for cand in sorted(_MARCA_DIR.glob("*.png")):
        return cand
    return None


def _resolver_plan_fx(fx_preset: str | None, stem: str, duration: float):
    """FXPlan del preset opcional o None. Fallo de la capa -> None (render sin FX)."""
    if not fx_preset:
        return None
    try:
        import fx  # noqa: PLC0415

        brain_data = fx.cargar_brain_fx(_TRANSCRIPTS_DIR / f"{stem}.brain.json")
        plan = fx.generar_plan_fx(duration, fx_preset, brain_data, _logo_png())
        n = len(plan.punch_ins), len(plan.flashes), len(plan.scanners)
        origen = "brain" if brain_data else "fallback"
        print(f"[fx] {fx_preset} ({origen}): {n[0]} punch, {n[1]} flash, {n[2]} scanner")
        return None if plan.vacio() else plan
    except Exception as e:
        print(f"[fx] preset no aplicado ({e}) - render sin efectos")
        return None


def _clips_de_motion_cli(motion_opts, groups, video_path: Path, width, height, duration) -> list:
    """Letreros del Motor B para la CLI de un video suelto. Sin `--motion` no toca nada.

    La cache de piezas vive en `output/.piezas` (fuera de un paquete de Auto, que es donde vive
    en la ruta de clips). La trayectoria del reframe se busca con el mismo helper que usa el
    resto del render; si no existe, el planificador considera el carril vertical ocupado.
    """
    if motion_opts is None or not getattr(motion_opts, "enabled", False):
        return []
    import motion_capa  # noqa: PLC0415
    import tray_resolve  # noqa: PLC0415

    raiz = Path(__file__).resolve().parent
    return list(
        motion_capa.clips_de_motion(
            opciones=motion_opts,
            ancho=width,
            alto=height,
            fps=core.get_video_info(video_path).get("fps") or 30.0,
            duracion_s=duration,
            raiz_cache=raiz / "output" / ".piezas",
            root=raiz,
            tramos=motion_capa.tramos_de_groups(groups),
            tray_csv=tray_resolve.resolver_tray_csv(video_path, _TRANSCRIPTS_DIR),
            clip_mp4=Path(video_path),
        ).clips
    )


def _resolver_capas_y_quemar(
    video_path: Path,
    ass_path: Path,
    out_path: Path,
    groups: list,
    style_cfg,
    stem: str,
    width: int,
    height: int,
    duration: float,
    use_emojis: bool,
    use_popups: bool,
    fx_preset: str | None,
    motion_opts=None,
) -> None:
    """Resuelve popups/clips/FX/emojis/letreros y quema. Fuente UNICA para el flujo clasico y SRT.

    Reutiliza exactamente los motores existentes (cve_popups/cve_clips/assets_comfy/fx +
    core.burn_video/burn_video_with_emojis); no duplica ni reimplementa internals. Cada
    capa opcional es fail-open dentro de su propio resolver.
    """
    popups: list = []
    clips: list = []
    if use_popups:
        import cve_clips  # noqa: PLC0415
        import cve_popups  # noqa: PLC0415

        popups = cve_popups.resolver_popups(groups, stem, video_w=width, video_h=height)
        clips = cve_clips.resolver_clips(stem, video_w=width, video_h=height)

    clips = [
        *clips,
        *_clips_de_motion_cli(motion_opts, groups, video_path, width, height, duration),
    ]

    fx_plan = _resolver_plan_fx(fx_preset, stem, duration)

    if use_emojis:
        import assets_comfy as ac  # noqa: PLC0415

        groups_path = _TRANSCRIPTS_DIR / f"{stem}_groups.json"
        brain_path = _TRANSCRIPTS_DIR / f"{stem}.brain.json"
        overlays = ac.resolver_overlays(groups_path, brain_path)
        if overlays:
            print(f"[emojis] {len(overlays)} overlay(s) generados - ComfyUI OK")
        else:
            print("[emojis] Sin overlays disponibles (ComfyUI apagado o sin keywords)")
        core.burn_video_with_emojis(
            video_path, ass_path, out_path, overlays, style_cfg, popups, fx_plan, clips=clips
        )
    elif popups or clips or fx_plan is not None:
        core.burn_video_with_emojis(
            video_path, ass_path, out_path, [], style_cfg, popups, fx_plan, clips=clips
        )
    else:
        core.burn_video(video_path, ass_path, out_path)


def _variante_tag(
    plan, style: str, pop: str | None, rebote: bool | None, intensidad, densidad
) -> str:
    """Sufijo de variante para el nombre de salida (delegado a srt_render; fuente unica)."""
    import srt_render  # noqa: PLC0415

    return srt_render.variante_tag(plan, style, pop, rebote, intensidad, densidad)


def _aplicar_preset_srt(
    groups: list, plan, stem: str, width: int, height: int
) -> tuple[list, object]:
    """Aplica el motor CVE SOLO a los grupos word_aligned (delegado a srt_render, D36B-3).

    Conserva intactos los `cue_fallback` y reasigna IDs deterministas. El `aviso` del engine
    se imprime aqui para preservar exactamente la salida de la CLI historica.
    """
    import srt_render  # noqa: PLC0415

    merged, plan, aviso = srt_render.apply_preset_to_srt_groups(
        groups,
        plan,
        brain_path=_TRANSCRIPTS_DIR / f"{stem}.brain.json",
        width=width,
        height=height,
        manual_keywords_path=_TRANSCRIPTS_DIR / f"{stem}_keywords.json",
    )
    if aviso:
        print(f"[cve] {aviso}")
    _reportar_parciales(plan)
    return merged, plan


def _reportar_modo_srt(result, payload: dict) -> None:
    """Dice QUE modo se uso y QUE offset se aplico, y publica el offset PROPUESTO (S41).

    La propuesta se imprime siempre y jamas se aplica sola (D45): un offset mal estimado
    desincroniza el video entero en silencio. Si difiere del aplicado, se sugiere el flag.
    """
    modo = "parcial" if result.modo_parcial else "solo cues completos"
    print(
        f"[srt] modo: {modo} | umbral por cue {result.min_coverage} | "
        f"offset aplicado {result.offset_ms} ms"
    )
    prop = (payload.get("offset", {}) or {}).get("propuesta") or {}
    if not prop:
        return
    sugerido = int(prop.get("offset_ms") or 0)
    detalle = (
        f"{sugerido} ms (anclas {prop.get('n_anclas')}, confianza {prop.get('confianza')}, "
        f"aplicable {prop.get('aplicable')})"
    )
    if sugerido == result.offset_ms:
        # ASCII estricto: la consola de Windows no siempre es cp1252 y un em dash la revienta.
        print(f"[srt] offset propuesto: {detalle} - ya aplicado")
    else:
        print(f"[srt] offset propuesto: {detalle}")
        print(f"[srt] no se aplica solo: para usarlo, repite con --srt-offset {sugerido}")


def _reportar_parciales(plan) -> None:
    """Totales por razon del gate de cues parciales (S39). Silencioso si no hubo parciales."""
    import cve_parciales  # noqa: PLC0415

    linea = cve_parciales.linea_reporte(getattr(plan, "kw_parciales", None))
    if linea:
        print(linea)


def _nombre_srt(stem, variante, use_emojis, use_popups, fx_preset, motion=False) -> str:
    """Sufijo determinista para SRT (delegado a srt_render; fuente unica con el worker)."""
    import srt_render  # noqa: PLC0415

    return srt_render.nombre_base_srt(stem, variante, use_emojis, use_popups, fx_preset, motion)


def _tag_motion(motion_opts) -> str:
    """Token de la capa de letreros para el nombre del MP4. Apagada devuelve cadena vacia."""
    if motion_opts is None or not getattr(motion_opts, "enabled", False):
        return ""
    import cve  # noqa: PLC0415

    return cve.TOKEN_MOTION


def _process_srt(
    video_path: Path,
    style: str,
    lang: str,
    output_dir: Path,
    model_arg: str,
    out_stem: str | None,
    pop: str | None,
    rebote: bool | None,
    preset: str | None,
    intensidad: str | None,
    densidad: str | None,
    use_emojis: bool,
    use_popups: bool,
    fx_preset: str | None,
    qa_opts: dict | None,
    srt_path: Path,
    srt_parcial: bool = False,
    srt_offset_ms: int = 0,
    srt_min_coverage: float | None = None,
    motion_opts=None,
) -> tuple[float, dict]:
    """Render con SRT como texto oficial (S36-B). Whisper solo aporta timings.

    El texto del SRT nunca se sustituye ni se pasa por Caption QA (D36B-1/D36B-5): con
    `--srt`, Caption QA se RECHAZA (SrtError). Reutiliza las mismas capas downstream que la
    ruta historica (preset CVE, popups, clips, emojis, FX, burn). Presets solo animan cues
    word_aligned; los fallback quedan estaticos. Errores de usuario propagan como SrtError
    (nunca sys.exit dentro de la API); `main()` los traduce a exit no cero.
    """
    import srt_caption  # noqa: PLC0415
    from srt_import import SrtError  # noqa: PLC0415

    if qa_opts:
        raise SrtError(
            "--caption-qa no esta disponible junto con --srt en S36-B; el SRT es el texto oficial"
        )

    t0 = time.time()
    output_dir.mkdir(parents=True, exist_ok=True)
    device, compute = core.detect_device()
    model_path, label = core.resolve_model(model_arg)
    print(f"[model] {label} | {device} | {compute}")

    plan = _resolver_plan_preset(preset, intensidad, densidad)
    style_cfg = plan.style_cfg if plan else get_style(style, pop, rebote)
    stem = out_stem or video_path.stem

    vinfo = core.get_video_info(video_path)
    width, height = vinfo["width"], vinfo["height"]
    print(f"[video] {width}x{height}")
    video_ms = int(round(vinfo["duration"] * 1000)) or None

    transcript = _load_or_transcribe(video_path, stem, lang, device, compute, model_path)
    groups, result, payload = srt_caption.preparar_desde_srt(
        srt_path,
        transcript["words"],
        video_duration_ms=video_ms,
        words_file=f"{stem}_words.json",
        offset_ms=srt_offset_ms,
        modo_parcial=srt_parcial,
        min_coverage=srt_min_coverage,
    )
    print(
        f"[srt] {result.n_cues} cues | {result.word_aligned} word-aligned | "
        f"{result.word_partial} parciales | {result.cue_fallback} fallback | "
        f"cobertura {result.coverage:.2f}"
    )
    _reportar_modo_srt(result, payload)

    if plan:  # preset CVE: enriquece SOLO los cues alineados; los fallback siguen estaticos
        groups, plan = _aplicar_preset_srt(groups, plan, stem, width, height)
        style_cfg = plan.style_cfg

    variante = _variante_tag(plan, style, pop, rebote, intensidad, densidad)
    base = _nombre_srt(
        stem, variante, use_emojis, use_popups, fx_preset, bool(_tag_motion(motion_opts))
    )
    ass_path = output_dir / f"{stem}{variante}_srt.ass"
    out_path = output_dir / f"{base}.mp4"
    core.build_ass(groups, width, height, style_cfg, ass_path)
    print(f"[ass] {ass_path.name} generado ({len(groups)} grupos)")

    _resolver_capas_y_quemar(
        video_path,
        ass_path,
        out_path,
        groups,
        style_cfg,
        stem,
        width,
        height,
        vinfo["duration"],
        use_emojis,
        use_popups,
        fx_preset,
        motion_opts,
    )
    if plan:
        import cve  # noqa: PLC0415

        cve.escribir_sidecar_seleccion(groups, plan, out_path)
    srt_caption.escribir_sidecar(payload, _TRANSCRIPTS_DIR / f"{stem}_srt_alignment.json")

    total = time.time() - t0
    print(f"[ok] {video_path.name} -> {out_path.name} en {total:.1f}s\n")
    return total, transcript


def process_video(
    video_path: Path,
    style: str,
    lang: str,
    output_dir: Path,
    model_arg: str = "auto",
    max_words: int | None = None,
    out_stem: str | None = None,
    use_emojis: bool = False,
    use_popups: bool = False,
    pop: str | None = None,
    rebote: bool | None = None,
    preset: str | None = None,
    intensidad: str | None = None,
    densidad: str | None = None,
    qa_opts: dict | None = None,
    fx_preset: str | None = None,
    *,
    srt_path: Path | None = None,
    srt_parcial: bool = False,
    srt_offset_ms: int = 0,
    srt_min_coverage: float | None = None,
    motion_opts=None,
) -> tuple[float, dict]:
    if srt_path is not None:
        return _process_srt(
            video_path,
            style,
            lang,
            output_dir,
            model_arg,
            out_stem,
            pop,
            rebote,
            preset,
            intensidad,
            densidad,
            use_emojis,
            use_popups,
            fx_preset,
            qa_opts,
            srt_path,
            srt_parcial,
            srt_offset_ms,
            srt_min_coverage,
            motion_opts,
        )
    t0 = time.time()
    output_dir.mkdir(parents=True, exist_ok=True)

    device, compute = core.detect_device()
    model_path, label = core.resolve_model(model_arg)
    print(f"[model] {label} | {device} | {compute}")

    plan = _resolver_plan_preset(preset, intensidad, densidad)
    style_cfg = plan.style_cfg if plan else get_style(style, pop, rebote)
    stem = out_stem or video_path.stem
    # pop, rebote, preset e intensidad entran en el nombre para que las variantes no se pisen.
    if plan:
        import cve  # noqa: PLC0415

        # Mismo helper que Studio con las MISMAS dimensiones (plan efectivo): position y
        # avoid_faces del preset. Como la CLI no las overridea, igualan el default -> sin
        # token -> naming historico byte-identico; y si algun dia se exponen, no colisionan.
        variante = cve.tag_variante(
            plan.preset, intensidad, densidad, plan.position, plan.avoid_faces
        )
    else:
        pop_tag = f"_{pop}" if pop else ""
        reb_tag = "" if rebote is None else ("_reb" if rebote else "_plano")
        variante = f"_{style}{pop_tag}{reb_tag}"
    ass_path = output_dir / f"{stem}{variante}.ass"
    fx_tag = f"_fx-{fx_preset}" if fx_preset else ""
    # La capa de letreros nombra el MP4, no el ASS: los captions salen identicos lleve o no
    # lleve letreros, asi que un ASS por variante de motion serian dos archivos iguales.
    suffix = (
        variante
        + ("_emojis" if use_emojis else "")
        + ("_popups" if use_popups else "")
        + fx_tag
        + _tag_motion(motion_opts)
    )
    out_path = output_dir / f"{stem}{suffix}.mp4"

    transcript = _load_or_transcribe(video_path, stem, lang, device, compute, model_path)

    if qa_opts:
        transcript = _aplicar_caption_qa(transcript, stem, qa_opts)

    groups = core.group_words(transcript["words"], max_words=max_words)
    print(f"[grupos] {len(groups)} bloques de subtitulo")

    vinfo = core.get_video_info(video_path)
    width, height = vinfo["width"], vinfo["height"]
    print(f"[video] {width}x{height}")

    if plan:
        import cve  # noqa: PLC0415
        import tray_resolve  # noqa: PLC0415

        brain_path = _TRANSCRIPTS_DIR / f"{stem}.brain.json"
        manual_kw_path = _TRANSCRIPTS_DIR / f"{stem}_keywords.json"
        # avoid_faces: trayectoria del reframe si existe (helper unico, mismo que Studio)
        tray_csv = tray_resolve.resolver_tray_csv(video_path, _TRANSCRIPTS_DIR)
        groups, plan, aviso = cve.aplicar_preset(
            groups, plan, brain_path, width, height, manual_kw_path, tray_csv
        )
        if aviso:
            print(f"[cve] {aviso}")
        style_cfg = plan.style_cfg

    core.build_ass(groups, width, height, style_cfg, ass_path)
    print(f"[ass] {ass_path.name} generado ({sum(len(g['words']) for g in groups)} eventos)")

    _resolver_capas_y_quemar(
        video_path,
        ass_path,
        out_path,
        groups,
        style_cfg,
        stem,
        width,
        height,
        vinfo["duration"],
        use_emojis,
        use_popups,
        fx_preset,
        motion_opts,
    )

    if plan:
        import cve  # noqa: PLC0415

        cve.escribir_sidecar_seleccion(groups, plan, out_path)

    total = time.time() - t0
    print(f"[ok] {video_path.name} -> {out_path.name} en {total:.1f}s\n")
    return total, transcript


def _run_depurar_cli(input_path: Path, mode: str, output_dir: Path) -> None:
    """Depura un video desde la CLI: silencios (seguro) o muletillas (agresivo)."""
    import json  # noqa: PLC0415

    import depurador as dep  # noqa: PLC0415

    if not input_path.is_file():
        print(f"[ERROR] No existe: {input_path}")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{input_path.stem}_limpio.mp4"
    transcripts_dir = Path(__file__).parent / "transcripts"
    words_path = transcripts_dir / f"{input_path.stem}_words.json"

    if not words_path.exists():
        print(f"[ERROR] Falta transcript: {words_path}. Transcribe el video primero.")
        sys.exit(1)

    raw = json.loads(words_path.read_text(encoding="utf-8"))
    words = raw.get("words", [])
    print(f"[depurar] Modo={mode} | {len(words)} palabras | -> {out_path.name}")

    result = dep.depurar(input_path, words, mode, out_path)
    print(f"[depurar] Listo: {result['cuts']} cortes, -{result['saved_s']}s ahorrados")


def _run_clips_cli(input_path: Path, tipos: str, srt_path: Path | None = None) -> None:
    """Genera clips virales desde la CLI. Con --srt genera ademas un SRT rebasado por clip."""
    if not input_path.is_file():
        print(f"[ERROR] No existe: {input_path}")
        sys.exit(1)

    words_path = _TRANSCRIPTS_DIR / f"{input_path.stem}_words.json"
    if not words_path.exists():
        print(f"[ERROR] Falta transcript: {words_path}. Transcribe el video primero.")
        sys.exit(1)

    import clipper  # noqa: PLC0415

    srt_document = None
    if srt_path is not None:
        from srt_import import load_srt  # noqa: PLC0415

        try:
            srt_document = load_srt(srt_path)
        except Exception as exc:
            print(f"[clips] ERROR SRT: {exc}")
            sys.exit(1)
        print(f"[clips] SRT fuente: {srt_path.name} ({len(srt_document.cues)} cues)")

    raw = json.loads(words_path.read_text(encoding="utf-8"))
    words = raw.get("words", [])
    print(f"[clips] {len(words)} palabras | tipos={tipos}")
    result = clipper.generar_clips(input_path, words, tipos, srt_document=srt_document)
    n = len(result.get("clips", []))
    err = result.get("error")
    if err:
        print(f"[clips] ERROR: {err}")
        sys.exit(1)
    print(f"[clips] {n} clip(s) generados en output/clips/")


def _validar_flags_srt(args, srt_path: Path | None) -> None:
    """Guardas de los flags de alineado del SRT (S41). Error de usuario -> exit no cero.

    Modifican como se alinea el SRT, asi que sin `--srt` no significan nada: pedirlos igual es
    un error, no algo que se ignore callado. Mismos limites que valida la API.
    """
    # `is not None` y no truthiness: `--srt-min-coverage 0.0` es un valor pedido, no un vacio.
    pedidos = args.srt_parcial or args.srt_offset or args.srt_min_coverage is not None
    if srt_path is None and pedidos:
        print("[ERROR] --srt-parcial / --srt-offset / --srt-min-coverage exigen --srt")
        sys.exit(1)
    if abs(int(args.srt_offset)) > _SRT_OFFSET_MAX_MS:
        print(f"[ERROR] --srt-offset fuera de rango (maximo +-{_SRT_OFFSET_MAX_MS} ms)")
        sys.exit(1)
    if args.srt_min_coverage is None:
        return
    if not 0.0 <= args.srt_min_coverage <= 1.0:
        print("[ERROR] --srt-min-coverage debe estar entre 0.0 y 1.0")
        sys.exit(1)
    # Sin modo parcial el porton exige anclar TODOS los tokens, asi que el umbral no cambia una
    # sola salida. Aceptarlo callado seria prometer un efecto que no existe.
    if not args.srt_parcial:
        print("[ERROR] --srt-min-coverage solo aplica con --srt-parcial (sin el, no cambia nada)")
        sys.exit(1)


def main() -> None:
    args = build_parser().parse_args()

    output_dir = Path(args.output_dir)
    input_path = Path(args.input)
    rebote = None if args.rebote is None else (args.rebote == "on")
    qa_opts = qa_opts_de_args(args)
    motion_opts = motion_opts_de_args(args)
    srt_path = Path(args.srt) if args.srt else None

    _validar_flags_srt(args, srt_path)

    # Guardas de --srt (S36-B): opt-in, un solo video, y sin Caption QA (el SRT es el texto
    # oficial; Caption QA opera sobre el transcript de Whisper y en S36-B no hay auditor SRT).
    if srt_path is not None:
        if input_path.is_dir() and not args.clips:
            print(
                "[ERROR] --srt requiere un video individual, no una carpeta (S36-B; batch en S36-C)"
            )
            sys.exit(1)
        if qa_opts is not None:
            print(
                "[ERROR] --caption-qa no esta disponible junto con --srt en S36-B; "
                "el SRT es el texto oficial (QA de SRT llegara en S36-C)"
            )
            sys.exit(1)

    if args.depurar:
        _run_depurar_cli(input_path, args.depurar, output_dir)
        return

    if args.clips:
        _run_clips_cli(input_path, args.clips, srt_path)
        return

    if input_path.is_dir():
        videos = sorted(v for v in input_path.glob("*.mp4") if not v.stem.startswith("test_"))
        if not videos:
            print(f"[!] No hay .mp4 en {input_path}")
            sys.exit(1)
        print(f"[batch] {len(videos)} videos\n")
        total = 0.0
        for v in videos:
            t, _ = process_video(
                v,
                args.style,
                args.lang,
                output_dir,
                args.model,
                args.words_per_group,
                use_emojis=args.emojis,
                use_popups=args.popups,
                pop=args.pop,
                rebote=rebote,
                preset=args.preset,
                intensidad=args.intensidad,
                densidad=args.densidad,
                qa_opts=qa_opts,
                fx_preset=args.fx,
                motion_opts=motion_opts,
            )
            total += t
        print(f"[batch] Total: {total:.1f}s")
    elif input_path.is_file():
        try:
            process_video(
                input_path,
                args.style,
                args.lang,
                output_dir,
                args.model,
                args.words_per_group,
                args.out_stem,
                use_emojis=args.emojis,
                use_popups=args.popups,
                pop=args.pop,
                rebote=rebote,
                preset=args.preset,
                intensidad=args.intensidad,
                densidad=args.densidad,
                qa_opts=qa_opts,
                fx_preset=args.fx,
                srt_path=srt_path,
                srt_parcial=args.srt_parcial,
                srt_offset_ms=int(args.srt_offset),
                srt_min_coverage=args.srt_min_coverage,
                motion_opts=motion_opts,
            )
        except _SrtUserError as exc:
            # Errores de USUARIO del SRT: mensaje corto con basename, exit no cero (no traceback).
            print(f"[ERROR] SRT invalido ({input_path.name}): {exc}")
            sys.exit(1)
    else:
        print(f"[ERROR] No existe: {input_path}")
        sys.exit(1)


if __name__ == "__main__":
    main()
