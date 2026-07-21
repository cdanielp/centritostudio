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


def procesar_clip_v2(
    clip: dict,
    paquete_dir: Path,
    config: AutoConfig,
    *,
    transcripts: Path,
    clips_dir: Path,
    root: Path,
) -> dict:
    """Un clip del clipper -> clip 9:16 con captions + b-roll + FX, verificado A/V.

    Orquestacion de motores existentes (regla #19): reframe.reframe_clip, brain fail-open,
    plan_broll, fetchers via auto_broll, fx via auto_fx, core.build_ass /
    burn_video_with_emojis, y auto_av como compuerta final. AV FAIL -> excepcion tipada
    (el checkpoint de exito NO se escribe; auto.py no captura estos errores).
    """
    import core  # noqa: PLC0415
    import reframe  # noqa: PLC0415
    from auto import _final_path  # noqa: PLC0415 (fuente unica del naming del clip final)
    from auto_report import STYLE_AUTO, avisos_de_segmentos  # noqa: PLC0415
    from styles import get_style  # noqa: PLC0415

    stem = clip["archivo"].replace(".mp4", "")
    stem_9x16, final_path = _final_path(clip, paquete_dir)
    rf = reframe.reframe_clip(
        clips_dir / clip["archivo"], clips_dir / f"{stem_9x16}.mp4", tracker="escenas"
    )
    groups, brain_data = _grupos_y_brain(stem, stem_9x16, transcripts)
    groups_captions = core.apply_brain(groups, brain_data) if brain_data else groups

    import assets_comfy as ac  # noqa: PLC0415

    overlays = ac.resolver_overlays(
        transcripts / f"{stem_9x16}_groups.json", transcripts / f"{stem_9x16}.brain.json"
    )

    clip_9x16 = clips_dir / f"{stem_9x16}.mp4"
    vinfo = core.get_video_info(clip_9x16)
    w, h = vinfo["width"], vinfo["height"]
    dur = float(vinfo.get("duration") or 0.0)
    clip_meta = {
        "duration_s": round(dur, 3),
        "width": w,
        "height": h,
        "fps": round(float(vinfo.get("fps") or 30.0), 4),
    }

    plan = plan_broll(groups, brain_data or {}, dur, broll_config_de(config))
    manual_popups, manual_clips, resol, _resolved = _resolver_broll_v2(
        plan, config, stem_9x16, transcripts, w, h, clip_meta
    )

    fx_plan = auto_fx.generar_fx_v2(
        dur,
        config.fx_preset,
        transcripts / f"{stem_9x16}.brain.json",
        enabled=config.fx_enabled,
    )
    final_popups = sorted([*manual_popups, *resol.auto_popups], key=lambda p: p.t0)
    final_clips = sorted([*manual_clips, *resol.auto_clips], key=lambda c: c.t0)
    arb = auto_fx.arbitrar_fx(fx_plan, auto_fx.intervalos_cutaway(final_popups, final_clips))
    fx_final = None if arb.plan.vacio() else arb.plan

    style_cfg = get_style(STYLE_AUTO)
    ass_path = root / "output" / f"{stem_9x16}_{STYLE_AUTO}.ass"
    core.build_ass(groups_captions, w, h, style_cfg, ass_path)
    core.burn_video_with_emojis(
        clip_9x16,
        ass_path,
        final_path,
        overlays,
        style_cfg,
        popups=final_popups,
        fx_plan=fx_final,
        clips=final_clips,
    )

    av = auto_av.verificar_av(clip_9x16, final_path) if config.verify_av else {"skipped": True}

    try:
        import caption_qa  # noqa: PLC0415

        info_qa = caption_qa.qa_para_reporte(stem_9x16)  # fail-open interno (regla 15)
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
        "pipeline_mode": "v2",
        "pipeline_version": PIPELINE_VERSION,
        "config_fingerprint": config.fingerprint(),
        "brain_ok": brain_data is not None,
        "broll": {
            **_resumen_broll(resol, plan),
            "manual_popups": len(manual_popups),
            "manual_clips": len(manual_clips),
            "plan_sidecar": f"{stem_9x16}_broll_plan.json",
            "auto_sidecar": f"{stem_9x16}_popups.auto.json",
            "resolved_sidecar": f"{stem_9x16}_broll_resolved.json",
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
    }


__all__ = ["broll_config_de", "checkpoint_v2_valido", "procesar_clip_v2"]
