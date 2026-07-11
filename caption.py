"""
caption.py — CLI para el pipeline de captions.
Toda la lógica vive en core.py. Esta es solo la interfaz de línea de comandos.
Uso: python caption.py input/video.mp4 --style hormozi --lang es
     python caption.py input/ --style karaoke --lang es   (batch)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import core
from styles import get_style

_TRANSCRIPTS_DIR = Path(__file__).parent / "transcripts"


def _load_or_transcribe(
    video_path: Path, stem: str, lang: str, device: str, compute: str, model_path: str
) -> dict:
    """Reutiliza el transcript existente si es mas reciente que el video (voto #10)."""
    words_path = _TRANSCRIPTS_DIR / f"{stem}_words.json"
    if words_path.exists():
        vid_mtime = video_path.stat().st_mtime
        words_mtime = words_path.stat().st_mtime
        if words_mtime >= vid_mtime:
            print(f"[whisper] reutilizando transcript existente: {words_path.name}")
            raw = json.loads(words_path.read_text(encoding="utf-8"))
            lang_str = raw.get("language", "?")
            print(f"[whisper] {len(raw.get('words', []))} palabras | idioma: {lang_str}")
            return raw
    transcript = core.transcribe_video(video_path, lang, device, compute, model_path)
    print(f"[whisper] {len(transcript['words'])} palabras | idioma: {transcript['language']}")
    return transcript


def _resolver_plan_preset(preset: str | None, intensidad: str | None):
    """RenderPlan del engine CVE o None. Fallo del engine -> None (captions simples)."""
    if not preset:
        return None
    try:
        import cve  # noqa: PLC0415

        return cve.resolve_preset(preset, intensidad)
    except Exception as e:
        print(f"[cve] preset no resuelto ({e}) - se usa el estilo clasico")
        return None


def _aplicar_preset(groups: list, plan, stem: str, width: int, height: int) -> list:
    """Marca los grupos con el engine CVE (brain.json fail-open si existe)."""
    import cve  # noqa: PLC0415

    brain_data = None
    brain_path = _TRANSCRIPTS_DIR / f"{stem}.brain.json"
    if brain_path.exists():
        try:
            brain_data = json.loads(brain_path.read_text(encoding="utf-8"))
            print(f"[cve] brain.json encontrado: enriquecimiento activo ({brain_path.name})")
        except (ValueError, OSError):  # ValueError cubre JSON invalido y encoding roto
            print(f"[cve] brain.json ilegible, se ignora: {brain_path.name}")
            brain_data = None
    return cve.aplicar_engine(groups, plan, width, height, brain_data)


def process_video(
    video_path: Path,
    style: str,
    lang: str,
    output_dir: Path,
    model_arg: str = "auto",
    max_words: int | None = None,
    out_stem: str | None = None,
    use_emojis: bool = False,
    pop: str | None = None,
    rebote: bool | None = None,
    preset: str | None = None,
    intensidad: str | None = None,
) -> tuple[float, dict]:
    t0 = time.time()
    output_dir.mkdir(parents=True, exist_ok=True)

    device, compute = core.detect_device()
    model_path, label = core.resolve_model(model_arg)
    print(f"[model] {label} | {device} | {compute}")

    plan = _resolver_plan_preset(preset, intensidad)
    style_cfg = plan.style_cfg if plan else get_style(style, pop, rebote)
    stem = out_stem or video_path.stem
    # pop, rebote y preset entran en el nombre para que las variantes no se pisen.
    if plan:
        variante = f"_{plan.preset}"
    else:
        pop_tag = f"_{pop}" if pop else ""
        reb_tag = "" if rebote is None else ("_reb" if rebote else "_plano")
        variante = f"_{style}{pop_tag}{reb_tag}"
    ass_path = output_dir / f"{stem}{variante}.ass"
    suffix = variante + ("_emojis" if use_emojis else "")
    out_path = output_dir / f"{stem}{suffix}.mp4"

    transcript = _load_or_transcribe(video_path, stem, lang, device, compute, model_path)

    groups = core.group_words(transcript["words"], max_words=max_words)
    print(f"[grupos] {len(groups)} bloques de subtitulo")

    vinfo = core.get_video_info(video_path)
    width, height = vinfo["width"], vinfo["height"]
    print(f"[video] {width}x{height}")

    if plan:
        groups = _aplicar_preset(groups, plan, stem, width, height)

    core.build_ass(groups, width, height, style_cfg, ass_path)
    print(f"[ass] {ass_path.name} generado ({sum(len(g['words']) for g in groups)} eventos)")

    if use_emojis:
        import assets_comfy as ac  # noqa: PLC0415

        groups_path = _TRANSCRIPTS_DIR / f"{stem}_groups.json"
        brain_path = _TRANSCRIPTS_DIR / f"{stem}.brain.json"
        overlays = ac.resolver_overlays(groups_path, brain_path)
        if overlays:
            print(f"[emojis] {len(overlays)} overlay(s) generados - ComfyUI OK")
        else:
            print("[emojis] Sin overlays disponibles (ComfyUI apagado o sin keywords)")
        core.burn_video_with_emojis(video_path, ass_path, out_path, overlays, style_cfg)
    else:
        core.burn_video(video_path, ass_path, out_path)

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


def _run_clips_cli(input_path: Path, tipos: str) -> None:
    """Genera clips virales desde la CLI."""
    if not input_path.is_file():
        print(f"[ERROR] No existe: {input_path}")
        sys.exit(1)

    words_path = _TRANSCRIPTS_DIR / f"{input_path.stem}_words.json"
    if not words_path.exists():
        print(f"[ERROR] Falta transcript: {words_path}. Transcribe el video primero.")
        sys.exit(1)

    import clipper  # noqa: PLC0415

    raw = json.loads(words_path.read_text(encoding="utf-8"))
    words = raw.get("words", [])
    print(f"[clips] {len(words)} palabras | tipos={tipos}")
    result = clipper.generar_clips(input_path, words, tipos)
    n = len(result.get("clips", []))
    err = result.get("error")
    if err:
        print(f"[clips] ERROR: {err}")
        sys.exit(1)
    print(f"[clips] {n} clip(s) generados en output/clips/")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Captions animados word-by-word — Centrito Studio CLI"
    )
    parser.add_argument("input", help="Video .mp4 de entrada, o carpeta para batch")
    parser.add_argument(
        "--style", default="hormozi", choices=["hormozi", "clean", "karaoke", "bounce", "pms"]
    )
    parser.add_argument(
        "--pop",
        choices=["off", "suave", "medio", "fuerte"],
        default=None,
        help="Intensidad del pop (off=1.0, suave=1.08, medio=1.30, fuerte=1.45)",
    )
    parser.add_argument(
        "--rebote",
        choices=["on", "off"],
        default=None,
        help="Rebote/overshoot de la palabra activa (on/off); default: el del estilo",
    )
    parser.add_argument(
        "--preset",
        choices=["clean_podcast", "viral_bounce", "keyword_punch"],
        default=None,
        help="Preset del caption_viral_engine (F6); si se da, --style/--pop se ignoran",
    )
    parser.add_argument(
        "--intensidad",
        choices=["minimal", "clean", "viral"],
        default=None,
        help="Intensidad del preset (default: la propia del preset)",
    )
    parser.add_argument("--lang", default="es")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--model", default="auto", choices=["auto", "small", "medium"])
    parser.add_argument("--words-per-group", type=int, default=None, metavar="N")
    parser.add_argument("--out-stem", default=None)
    parser.add_argument(
        "--depurar",
        choices=["seguro", "agresivo"],
        default=None,
        help="Depurar silencios (seguro) o tambien muletillas (agresivo)",
    )
    parser.add_argument(
        "--clips",
        choices=["cortos", "largos", "ambos"],
        default=None,
        help="Generar clips virales con IA (cortos|largos|ambos)",
    )
    parser.add_argument(
        "--emojis",
        action="store_true",
        default=False,
        help="Overlay de assets IA (ComfyUI) sobre palabras clave del brain.json",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    input_path = Path(args.input)
    rebote = None if args.rebote is None else (args.rebote == "on")

    if args.depurar:
        _run_depurar_cli(input_path, args.depurar, output_dir)
        return

    if args.clips:
        _run_clips_cli(input_path, args.clips)
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
                pop=args.pop,
                rebote=rebote,
                preset=args.preset,
                intensidad=args.intensidad,
            )
            total += t
        print(f"[batch] Total: {total:.1f}s")
    elif input_path.is_file():
        process_video(
            input_path,
            args.style,
            args.lang,
            output_dir,
            args.model,
            args.words_per_group,
            args.out_stem,
            use_emojis=args.emojis,
            pop=args.pop,
            rebote=rebote,
            preset=args.preset,
            intensidad=args.intensidad,
        )
    else:
        print(f"[ERROR] No existe: {input_path}")
        sys.exit(1)


if __name__ == "__main__":
    main()
