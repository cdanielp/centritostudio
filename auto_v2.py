"""auto_v2.py — Procesamiento de UN clip en Modo Automatico v2 (S37-B).

Coordina los motores EXISTENTES en el orden vinculante del pipeline v2: reframe ->
brain fail-open -> planner (S37-A) -> sidecar del plan -> manual (intocable) ->
resolucion automatica (#47a/b) -> materializacion (#47c) -> FX + arbitraje (#47e) ->
ASS + render en un pase -> verificacion A/V dura (#47d) -> info auditable.

`auto.ejecutar_auto` sigue siendo el unico orquestador publico: este modulo solo
procesa un clip y se importa LAZY desde auto.py cuando config.mode == "v2" (la ruta
clasica jamas lo importa). No re-transcribe, no vuelve a llamar al clipper, no toca
el sidecar manual y no escribe `{stem}_popups.json`.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import auto_av
import auto_broll
import auto_fx
from auto_config import PIPELINE_VERSION, AutoConfig
from broll_plan_io import broll_plan_to_dict, write_broll_plan
from broll_plan_types import BrollConfig
from broll_planner import plan_broll
from media_integrity import video_reanudable  # H2 P1-OUT-3: gate fail-closed del checkpoint v2


def broll_config_de(config: AutoConfig) -> BrollConfig:
    """AutoConfig -> BrollConfig del planner. Sin FX no se reserva outro (preset express)."""
    preset = config.fx_preset if config.fx_enabled else "express"
    return BrollConfig(
        enabled=config.broll_enabled,
        target_coverage_pct=config.target_coverage_pct,
        max_coverage_pct=config.max_coverage_pct,
        hook_protected_s=config.hook_protected_s,
        max_video_windows=config.max_video_windows,
        fx_preset=preset,
    )


def checkpoint_v2_valido(info: dict, fingerprint: str, final_path: Path, transcripts: Path) -> bool:
    """Un checkpoint v2 solo se reutiliza si es del MISMO pipeline y quedo verificado.

    Exige: pipeline_mode v2, fingerprint identico, A/V en pass/no_audio (o skipped si la
    config lo desactivo: el fingerprint incluye verify_av, asi que coincide por fuerza),
    output presente, los tres sidecars S37 presentes Y el resolved perteneciente al MISMO
    fingerprint (transcripts/ es compartido: otra corrida pudo sobreescribirlo). Un
    checkpoint clasico (sin pipeline_mode) jamas pasa; v2 jamas se reutiliza como clasico.
    """
    if not isinstance(info, dict) or info.get("pipeline_mode") != "v2":
        return False
    if info.get("config_fingerprint") != fingerprint:
        return False
    av = info.get("av") or {}
    if not av.get("skipped"):  # verify_av=False -> "skipped" es valido (mismo fingerprint)
        ok_av = {"pass", "no_audio"}
        if (av.get("integrity") or {}).get("status") not in ok_av:
            return False
        if (av.get("sync") or {}).get("status") not in ok_av:
            return False
    if not video_reanudable(final_path):  # P1-OUT-3: 0-byte/truncado/sin stream -> re-render
        return False
    broll = info.get("broll") or {}
    for clave in ("plan_sidecar", "auto_sidecar", "resolved_sidecar"):
        nombre = broll.get(clave)
        if not nombre or not (Path(transcripts) / nombre).exists():
            return False
    try:
        resolved = json.loads(
            (Path(transcripts) / broll["resolved_sidecar"]).read_text(encoding="utf-8")
        )
    except (ValueError, OSError):
        return False
    return resolved.get("config_fingerprint") == fingerprint


def _resumen_broll(resol: auto_broll.ResolucionBroll, plan) -> dict:
    dec = resol.decisiones
    finales = [d for d in dec if d.get("final_media_type") in ("image", "video")]
    return {
        "planned": len(plan.windows),
        "resolved": len(finales),
        "images": sum(1 for d in finales if d["final_media_type"] == "image"),
        "videos": sum(1 for d in finales if d["final_media_type"] == "video"),
        "fallbacks": sum(1 for d in dec if d.get("status") == "fallback"),
        "blocked": sum(1 for d in dec if d.get("status") == "blocked"),
        "omitted": sum(1 for d in dec if d.get("status") == "omitted"),
    }


def _grupos_y_brain(stem: str, stem_9x16: str, transcripts: Path) -> tuple[list, dict | None]:
    """Copia el transcript rebasado al stem 9x16 y ejecuta brain fail-open (motor intacto)."""
    from auto import _brain_fail_open  # noqa: PLC0415 (fuente unica del fail-open, sin duplicar)

    for suf in ("_words.json", "_groups.json"):
        src = transcripts / f"{stem}{suf}"
        if src.exists():
            shutil.copy(src, transcripts / f"{stem_9x16}{suf}")
    groups_path = transcripts / f"{stem_9x16}_groups.json"
    groups = json.loads(groups_path.read_text(encoding="utf-8")) if groups_path.exists() else []
    return groups, _brain_fail_open(groups, stem_9x16)


def _resolver_broll_v2(
    plan, config: AutoConfig, stem_9x16: str, transcripts: Path, w: int, h: int, clip_meta: dict
) -> tuple[list, list, auto_broll.ResolucionBroll, dict]:
    """Pasos 10-15: sidecar del plan, manual intocable, resolucion auto y materializacion."""
    write_broll_plan(plan, transcripts / f"{stem_9x16}_broll_plan.json", overwrite=True)
    if config.manual_sidecars:
        manual_popups, manual_clips = auto_broll.cargar_manual(stem_9x16, transcripts, w, h)
    else:
        manual_popups, manual_clips = [], []
    resol = auto_broll.resolver_plan(
        plan, manual_popups, manual_clips, w, h, broll_enabled=config.broll_enabled
    )
    auto_broll.escribir_json_atomico(
        transcripts / f"{stem_9x16}_popups.auto.json",
        auto_broll.entradas_popups_auto(resol.decisiones),
    )
    resolved = auto_broll.construir_resolved(
        broll_plan_to_dict(plan),
        resol,
        manual_popups,
        manual_clips,
        clip_meta,
        config.fingerprint(),
    )
    auto_broll.escribir_json_atomico(transcripts / f"{stem_9x16}_broll_resolved.json", resolved)
    return manual_popups, manual_clips, resol, resolved


def _opciones_motion(config: AutoConfig, clip: dict):
    """`OpcionesMotion` a partir de config+clip. Fuente unica: la usan la pierna primaria
    (`_capa_motion`) y cualquier pierna extra de formato (`_capa_motion_otro_formato`), para
    que las dos describan la misma marca/estilo sin duplicar los campos por separado."""
    import motion_capa  # noqa: PLC0415

    return motion_capa.OpcionesMotion(
        enabled=True,
        titulo=str(clip.get("titulo") or ""),
        nombre=config.motion_nombre,
        rol=config.motion_rol,
        cta=config.motion_cta,
        textos_llm=config.motion_textos_llm,
        estilo=config.motion_estilo,
    )


def _capa_motion(
    config: AutoConfig,
    clip: dict,
    paquete_dir: Path,
    clip_identidad: Path,
    groups: list,
    vinfo: dict,
    dur: float,
):
    """Letreros del Motor B para la pierna PRIMARIA de un clip (HF-3; HF-4 la llama "primaria").

    Apagada devuelve el resultado vacio sin tocar nada. El titulo del hook y del cierre es el
    que ya genero el clipper viral: es la unica frase del clip que esta escrita para
    engancharse, y volver a inventar una seria duplicar el trabajo del cerebro. El CSV de
    trayectoria es el que acaba de escribir el reframe junto al clip (si esta pierna reencuadro),
    que es donde `tray_resolve` lo busca primero. `clip_identidad` es el nombre CANONICO de esta
    salida (siempre con su sufijo de formato), no necesariamente el archivo del que se queman
    captions: ver el comentario en `procesar_clip_v2` sobre por que se separan los dos.
    """
    import motion_capa  # noqa: PLC0415 (aditiva: la ruta historica no lo importa)

    if not config.motion_enabled:
        return motion_capa.ResultadoMotion((), {"enabled": False})

    import tray_resolve  # noqa: PLC0415

    opciones = _opciones_motion(config, clip)
    return motion_capa.clips_de_motion(
        opciones=opciones,
        ancho=vinfo["width"],
        alto=vinfo["height"],
        fps=vinfo.get("fps") or 30.0,
        duracion_s=dur,
        raiz_cache=motion_capa.raiz_cache_de_paquete(paquete_dir),
        root=Path(__file__).resolve().parent,
        tramos=motion_capa.tramos_de_groups(groups),
        tray_csv=tray_resolve.resolver_tray_csv(Path(clip_identidad), Path(clip_identidad).parent),
        clip_mp4=Path(clip_identidad),
    )


def _capa_motion_otro_formato(
    config: AutoConfig,
    clip: dict,
    plan_base,
    paquete_dir: Path,
    clip_identidad: Path,
    groups: list,
    vinfo: dict,
    dur: float,
):
    """Letreros para una pierna EXTRA de formato (HF-4, Formato dual).

    CERO llamadas al LLM: reusa el plan TEMPORAL ya resuelto por la pierna primaria
    (`plan_base`, el `ResultadoMotion.plan` que devolvio `_capa_motion`) y solo redistribuye
    banda para esta orientacion via `motion_capa.plan_para_otro_formato`. Si la capa esta
    apagada o la primaria no produjo plan (apagada o fallo), no hay de donde derivar: vacio.

    `clip_identidad` es SIEMPRE el nombre con sufijo de formato (`{stem}_{sufijo}.mp4`), exista
    o no un archivo fisico ahi (una pierna sin reencuadre quema desde la fuente compartida, pero
    su sello de letreros tiene que vivir bajo SU PROPIO nombre para que el editor lo encuentre
    por el nombre final y para que nunca pise el sidecar de la fuente).
    """
    import motion_capa  # noqa: PLC0415

    if not config.motion_enabled or plan_base is None:
        return motion_capa.ResultadoMotion((), {"enabled": False})

    import tray_resolve  # noqa: PLC0415

    ancho, alto = vinfo["width"], vinfo["height"]
    orientacion = motion_capa.orientacion_de(ancho, alto)
    tray_csv = tray_resolve.resolver_tray_csv(Path(clip_identidad), Path(clip_identidad).parent)
    ruta_catalogo = Path(__file__).resolve().parent / motion_capa.CATALOGO_REL
    versiones = motion_capa.versiones_del_catalogo(ruta_catalogo)
    duracion_ms = int(round(dur * 1000))
    opciones = _opciones_motion(config, clip)
    tramos = motion_capa.tramos_de_groups(groups)
    # Misma huella que calcularia `resolver_plan` para esta orientacion: no gobierna ningun
    # reuso aqui (esta pierna siempre deriva fresco de `plan_base`, nunca vuelve a leer su
    # propio sello), pero deja el sidecar tan auditable como el de la pierna primaria.
    huella = motion_capa.huella_de_entrada(
        duracion_ms=duracion_ms,
        orientacion=orientacion,
        textos=opciones.textos(),
        tramos=tramos,
        tray_csv=tray_csv,
        catalogo=set(versiones),
        textos_llm=opciones.textos_llm,
        estilo=opciones.estilo,
    )

    plan, origen = motion_capa.plan_para_otro_formato(
        plan_base,
        clip_mp4=Path(clip_identidad),
        duracion_ms=duracion_ms,
        orientacion=orientacion,
        tray_csv=tray_csv,
        catalogo=set(versiones),
        huella_entrada=huella,
    )
    return motion_capa.clips_de_motion(
        opciones=opciones,
        ancho=ancho,
        alto=alto,
        fps=vinfo.get("fps") or 30.0,
        duracion_s=dur,
        raiz_cache=motion_capa.raiz_cache_de_paquete(paquete_dir),
        root=Path(__file__).resolve().parent,
        tramos=tramos,
        tray_csv=tray_csv,
        clip_mp4=Path(clip_identidad),
        plan_precomputado=(plan, origen),
    )


def procesar_clip_v2(
    clip: dict,
    paquete_dir: Path,
    config: AutoConfig,
    *,
    transcripts: Path,
    clips_dir: Path,
    root: Path,
) -> list[dict]:
    """Un clip del clipper -> clip(s) con captions + b-roll + FX, verificado A/V, uno por cada
    formato pedido (`config.formato`).

    Orquestacion de motores existentes (regla #19): reframe.reframe_clip, brain fail-open,
    plan_broll, fetchers via auto_broll, fx via auto_fx, core.build_ass /
    burn_video_with_emojis, y auto_av como compuerta final. AV FAIL -> excepcion tipada
    (el checkpoint de exito NO se escribe; auto.py no captura estos errores).

    HF-4 (Formato dual): la pierna "9:16", cuando esta pedida, es SIEMPRE la PRIMERA de
    `auto_formato.formatos_pedidos` y corre por el codigo EXACTO de siempre (protege la
    byte-identidad historica). El transcript, el brain, el broll (planner + Pexels) y el FX se
    resuelven UNA sola vez, en esa pierna primaria, y se reusan tal cual en cualquier pierna
    extra (su geometria de overlay es resolucion-independiente, ver auto_broll/core_overlays).
    Solo el letrero se re-deriva por formato (`_capa_motion_otro_formato`), porque HyperFrames
    renderiza un MOV -- y un desplazamiento de banda en pixeles -- distinto por lienzo, pero esa
    re-derivacion NUNCA vuelve a llamar al LLM: reusa el plan temporal ya resuelto.
    """
    import auto_formato  # noqa: PLC0415
    import core  # noqa: PLC0415
    import reframe  # noqa: PLC0415
    from auto_report import STYLE_AUTO, avisos_de_segmentos  # noqa: PLC0415
    from styles import get_style  # noqa: PLC0415

    stem = clip["archivo"].replace(".mp4", "")
    clip_path = clips_dir / clip["archivo"]
    info_fuente = core.get_video_info(clip_path)
    pedidos = auto_formato.formatos_pedidos(
        config.formato, src_ancho=info_fuente["width"], src_alto=info_fuente["height"]
    )

    resultados: list[dict] = []
    # Estado resuelto UNA vez en la pierna primaria y reusado en cualquier pierna extra.
    groups = groups_captions = brain_data = overlays = palabras_path = None
    plan_broll_obj = manual_popups = manual_clips = resol = None
    fx_plan = arb = fx_final = None
    motion_primaria = None
    stem_fmt_primaria = None

    for salida in pedidos.salidas:
        stem_fmt, final_path = auto_formato.ruta_final(
            clip, paquete_dir, salida.sufijo, estilo=STYLE_AUTO
        )
        es_primaria = groups is None

        # Identidad de ESTA salida para el sello de letreros (HF-4, Paso 3): SIEMPRE nombrada
        # por formato, exista o no un archivo fisico ahi. `clip_listo` (mas abajo) es de donde
        # se queman captions/overlays de VERDAD, y para la pierna sin reencuadre es la fuente
        # tal cual (sin sufijo) -- pero sellar el plan bajo ESE nombre pisaria el sidecar de la
        # fuente compartida y nunca lo encontraria el editor, que pide el plan por el nombre
        # final (`stem_fmt`). Los dos conceptos se separan a proposito.
        clip_identidad = clips_dir / f"{stem_fmt}.mp4"

        if salida.necesita_reframe:
            # `tray_dir` SOLO con la capa de letreros encendida (regla historica intacta): el
            # reframe escribe entonces `trayectoria_{stem_fmt}.csv` junto al clip, que es de
            # donde el planificador saca la zona de la cara.
            rf = reframe.reframe_clip(
                clip_path,
                clip_identidad,
                tracker="escenas",
                **({"tray_dir": clips_dir} if config.motion_enabled else {}),
            )
            clip_listo = clip_identidad
        else:
            rf = {}
            clip_listo = clip_path  # sin reencuadre: la fuente TAL CUAL, para el burn

        vinfo = core.get_video_info(clip_listo)
        w, h = vinfo["width"], vinfo["height"]
        dur = float(vinfo.get("duration") or 0.0)

        if es_primaria:
            stem_fmt_primaria = stem_fmt
            clip_meta = {
                "duration_s": round(dur, 3),
                "width": w,
                "height": h,
                "fps": round(float(vinfo.get("fps") or 30.0), 4),
            }
            groups, brain_data = _grupos_y_brain(stem, stem_fmt, transcripts)
            groups_captions = core.apply_brain(groups, brain_data) if brain_data else groups

            import assets_comfy as ac  # noqa: PLC0415

            overlays = ac.resolver_overlays(
                transcripts / f"{stem_fmt}_groups.json", transcripts / f"{stem_fmt}.brain.json"
            )
            palabras_path = transcripts / f"{stem_fmt}_words.json"

            plan_broll_obj = plan_broll(groups, brain_data or {}, dur, broll_config_de(config))
            manual_popups, manual_clips, resol, _resolved = _resolver_broll_v2(
                plan_broll_obj, config, stem_fmt, transcripts, w, h, clip_meta
            )
            fx_plan = auto_fx.generar_fx_v2(
                dur,
                config.fx_preset,
                transcripts / f"{stem_fmt}.brain.json",
                enabled=config.fx_enabled,
            )
            final_popups = sorted([*manual_popups, *resol.auto_popups], key=lambda p: p.t0)
            final_clips_broll = sorted([*manual_clips, *resol.auto_clips], key=lambda c: c.t0)
            arb = auto_fx.arbitrar_fx(
                fx_plan, auto_fx.intervalos_cutaway(final_popups, final_clips_broll)
            )
            fx_final = None if arb.plan.vacio() else arb.plan

            # Capa de letreros (Motor B). Aditiva y default OFF. Va DESPUES del b-roll para que
            # el letrero se pinte encima del cutaway, y con behind_text=True para que los
            # captions se pinten encima del letrero.
            motion_primaria = _capa_motion(
                config, clip, paquete_dir, clip_identidad, groups_captions, vinfo, dur
            )
            motion_resultado = motion_primaria
        else:
            # PIERNA EXTRA: reusa transcript/brain/overlays/broll/fx YA resueltos por la
            # primaria (geometria resolucion-independiente, confirmado). Solo el letrero se
            # re-deriva para este formato, sin llamar al LLM.
            final_popups = sorted([*manual_popups, *resol.auto_popups], key=lambda p: p.t0)
            final_clips_broll = sorted([*manual_clips, *resol.auto_clips], key=lambda c: c.t0)
            motion_resultado = _capa_motion_otro_formato(
                config,
                clip,
                motion_primaria.plan if motion_primaria else None,
                paquete_dir,
                clip_identidad,
                groups,
                vinfo,
                dur,
            )

        final_clips = [*final_clips_broll, *motion_resultado.clips]

        if config.motion_enabled and motion_resultado.plan is not None:
            # Segunda copia del sello, junto al MP4 FINAL publicado (no el clip de identidad
            # interno): es por ahi que el editor busca el plan de este clip
            # (studio_motion.resolver_clip resuelve por el nombre publicado, con estilo).
            import motion_capa  # noqa: PLC0415

            motion_capa.sellar_copia_para_editor(
                final_path,
                motion_resultado.plan,
                int(round(dur * 1000)),
                motion_resultado.informe.get("origen", "automatico"),
            )

        style_cfg = get_style(STYLE_AUTO)
        ass_path = root / "output" / f"{stem_fmt}_{STYLE_AUTO}.ass"
        core.build_ass(groups_captions, w, h, style_cfg, ass_path)
        core.burn_video_with_emojis(
            clip_listo,
            ass_path,
            final_path,
            overlays,
            style_cfg,
            popups=final_popups,
            fx_plan=fx_final,
            clips=final_clips,
        )

        av = auto_av.verificar_av(clip_listo, final_path) if config.verify_av else {"skipped": True}

        try:
            import caption_qa  # noqa: PLC0415

            info_qa = caption_qa.qa_para_reporte(stem_fmt, words_path=palabras_path)
        except ImportError:
            info_qa = None

        resultados.append(
            {
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
                "pipeline_mode": "v2",
                "pipeline_version": PIPELINE_VERSION,
                "config_fingerprint": config.fingerprint(),
                "brain_ok": brain_data is not None,
                "broll": {
                    **_resumen_broll(resol, plan_broll_obj),
                    "manual_popups": len(manual_popups),
                    "manual_clips": len(manual_clips),
                    "plan_sidecar": f"{stem_fmt_primaria}_broll_plan.json",
                    "auto_sidecar": f"{stem_fmt_primaria}_popups.auto.json",
                    "resolved_sidecar": f"{stem_fmt_primaria}_broll_resolved.json",
                },
                "fx": {
                    "enabled": config.fx_enabled,
                    "preset": config.fx_preset if config.fx_enabled else None,
                    "before": arb.before,
                    "after": arb.after,
                    "removed": list(arb.removed),
                    "warnings": list(arb.warnings),
                },
                "av": av,
                # Solo cuando la capa esta encendida: con `motion_enabled=False` la clave no
                # aparece y el checkpoint de un paquete historico queda con la misma forma
                # exacta que antes.
                **({"motion": motion_resultado.informe} if config.motion_enabled else {}),
            }
        )
    return resultados


__all__ = ["broll_config_de", "checkpoint_v2_valido", "procesar_clip_v2"]
