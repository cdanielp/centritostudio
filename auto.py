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

ROOT = Path(__file__).parent
TRANSCRIPTS = ROOT / "transcripts"
CLIPS_DIR = ROOT / "output" / "clips"
PAQUETES_DIR = ROOT / "output" / "paquetes"

# Umbral de aviso para C1v2 en tramos single (heuristica inicial, D17)
C1V2_AVISO = 80.0

OBJETIVOS = ("clips",)  # v1: solo "Clips virales"; roadmap en PREGUNTAS #29
STYLE_AUTO = "hormozi"  # estilo del paquete v1 (95/100 de K en s26, D16)


def _fmt_t(segundos: float) -> str:
    """0:39 a partir de 39.2. Puro."""
    m, s = divmod(int(segundos), 60)
    return f"{m}:{s:02d}"


def avisos_de_segmentos(segmentos: list[dict]) -> list[dict]:
    """Traduce el seg_reporte del modo escenas a avisos humanos. Puro.

    Entrada: entradas {t_ini, t_fin, tipo, n_caras, c1v2, ...} tal como las
    devuelve reframe_escenas (via reframe_clip result['segmentos']).
    Salida: [{t_ini, t_fin, texto}] solo para tramos que requieren revision.
    """
    avisos = []
    for s in segmentos:
        rango = f"{_fmt_t(s['t_ini'])}-{_fmt_t(s['t_fin'])}"
        if s.get("tipo") == "multi":
            avisos.append(
                {
                    "t_ini": s["t_ini"],
                    "t_fin": s["t_fin"],
                    "texto": (
                        f"revisa {rango}: {s.get('n_caras', 2)} personas en cuadro, "
                        "el sistema solo siguio a una"
                    ),
                }
            )
        elif s.get("tipo") == "none":
            avisos.append(
                {
                    "t_ini": s["t_ini"],
                    "t_fin": s["t_fin"],
                    "texto": f"revisa {rango}: sin cara detectada, encuadre centrado fijo",
                }
            )
        elif s.get("c1v2") is not None and s["c1v2"] < C1V2_AVISO:
            avisos.append(
                {
                    "t_ini": s["t_ini"],
                    "t_fin": s["t_fin"],
                    "texto": (
                        f"revisa {rango}: el seguimiento pudo perder a la persona "
                        f"(fiabilidad {s['c1v2']:.0f}%)"
                    ),
                }
            )
    return avisos


def resumen_paquete(clips_info: list[dict]) -> str:
    """Resumen de una linea para el Studio. Puro.

    Ej.: "2 clips listos, 1 con aviso (clip 2 en 0:16)".
    """
    n = len(clips_info)
    if n == 0:
        return "0 clips generados"
    con_aviso = [(i + 1, c) for i, c in enumerate(clips_info) if c.get("avisos")]
    if not con_aviso:
        return f"{n} clip(s) listos, sin avisos"
    partes = [f"clip {i} en {_fmt_t(c['avisos'][0]['t_ini'])}" for i, c in con_aviso]
    return f"{n} clip(s) listos, {len(con_aviso)} con aviso ({', '.join(partes)})"


def generar_reporte_md(name: str, clips_info: list[dict], meta: dict) -> str:
    """REPORTE.md del paquete. Puro."""
    lineas = [
        f"# Paquete Modo Automatico — {name}",
        "",
        f"Generado: {meta.get('fecha', '?')} · Objetivo: Clips virales · "
        f"Estilo: {STYLE_AUTO} · Tracker: escenas",
        "",
        f"**Resumen: {resumen_paquete(clips_info)}.**",
        "",
        "REVISION HUMANA REQUERIDA antes de publicar (regla MAESTRO #19).",
        "",
        "## Clips",
        "",
    ]
    for i, c in enumerate(clips_info, 1):
        lineas += [
            f"### {i}. {c.get('titulo', '(sin titulo)')} — score IA {c.get('score', '?')}/100",
            "",
            f"- Archivo: `{c['archivo']}`",
            f"- Duracion: {c.get('dur_s', 0):.1f}s ({_fmt_t(c.get('dur_s', 0))})",
            f"- Razon IA: {c.get('razon', '')}",
            f"- Emojis: {c.get('emojis_msg', 'sin overlays')}",
        ]
        avisos = c.get("avisos", [])
        if avisos:
            lineas.append("- Calidad por tramos:")
            lineas += [f"  - {a['texto']}" for a in avisos]
        else:
            lineas.append("- Calidad por tramos: OK en todo el clip")
        lineas.append("")
    lineas += [
        "## Telemetria",
        "",
        f"- Transcripcion: {meta.get('t_transcripcion_s', 0):.1f}s"
        + (" (reutilizada, voto #10)" if meta.get("transcript_reutilizado") else ""),
        f"- Clipper: {meta.get('t_clipper_s', 0):.1f}s · costo LLM ${meta.get('costo_usd', 0):.4f}",
        f"- Reframe + captions: {meta.get('t_render_s', 0):.1f}s",
        f"- Total: {meta.get('t_total_s', 0):.1f}s",
        "",
    ]
    return "\n".join(lineas)


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
    stem_9x16 = f"{stem}_9x16"
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

    final_path = paquete_dir / f"{stem_9x16}_{STYLE_AUTO}.mp4"
    core.burn_video_with_emojis(clip_9x16, ass_path, final_path, overlays, style_cfg)

    return {
        "archivo": final_path.name,
        "titulo": clip.get("titulo", ""),
        "razon": clip.get("razon", ""),
        "score": clip.get("score"),
        "dur_s": clip.get("dur_s", 0),
        "avisos": avisos_de_segmentos(rf.get("segmentos", [])),
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
    """
    import clipper  # noqa: PLC0415

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
    resultado = clipper.generar_clips(video_path, words, "ambos")
    t_clip = time.time() - t1
    if resultado.get("error"):
        raise RuntimeError(resultado["error"])
    clips = resultado.get("clips", [])

    fecha = time.strftime("%Y%m%d-%H%M")
    paquete_dir = PAQUETES_DIR / f"{name}_{fecha}"
    paquete_dir.mkdir(parents=True, exist_ok=True)

    clips_info: list[dict] = []
    t1 = time.time()
    for i, clip in enumerate(clips, 1):
        progress(
            30 + int(60 * (i - 1) / max(len(clips), 1)),
            f"Etapa 3-4/4: reencuadre + captions (clip {i}/{len(clips)})...",
        )
        clips_info.append(_procesar_clip(clip, paquete_dir))
    t_render = time.time() - t1

    progress(95, "Armando paquete...")
    meta = {
        "fecha": fecha,
        "objetivo": objetivo,
        "transcript_reutilizado": reutilizado,
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
