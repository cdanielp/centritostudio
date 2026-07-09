"""
caption.py — CLI para el pipeline de captions.
Toda la lógica vive en core.py. Esta es solo la interfaz de línea de comandos.
Uso: python caption.py input/video.mp4 --style hormozi --lang es
     python caption.py input/ --style karaoke --lang es   (batch)
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import core
from styles import get_style


def process_video(
    video_path: Path,
    style: str,
    lang: str,
    output_dir: Path,
    model_arg: str = "auto",
    max_words: int | None = None,
    out_stem: str | None = None,
) -> tuple[float, dict]:
    t0 = time.time()
    output_dir.mkdir(parents=True, exist_ok=True)

    device, compute = core.detect_device()
    model_path, label = core.resolve_model(model_arg)
    print(f"[model] {label} | {device} | {compute}")

    style_cfg = get_style(style)
    stem      = out_stem or video_path.stem
    ass_path  = output_dir / f"{stem}_{style}.ass"
    out_path  = output_dir / f"{stem}_{style}.mp4"

    transcript = core.transcribe_video(video_path, lang, device, compute, model_path)
    print(f"[whisper] {len(transcript['words'])} palabras | idioma: {transcript['language']}")

    groups = core.group_words(transcript["words"], max_words=max_words)
    print(f"[grupos] {len(groups)} bloques de subtitulo")

    width, height = core.get_video_info(video_path)["width"], core.get_video_info(video_path)["height"]
    print(f"[video] {width}x{height}")

    core.build_ass(groups, width, height, style_cfg, ass_path)
    print(f"[ass] {ass_path.name} generado ({sum(len(g['words']) for g in groups)} eventos)")

    elapsed = core.burn_video(video_path, ass_path, out_path)
    total = time.time() - t0
    print(f"[ok] {video_path.name} -> {out_path.name} en {total:.1f}s\n")
    return total, transcript


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Captions animados word-by-word — Centrito Studio CLI"
    )
    parser.add_argument("input",
                        help="Video .mp4 de entrada, o carpeta para batch")
    parser.add_argument("--style", default="hormozi",
                        choices=["hormozi", "karaoke", "bounce", "pms"])
    parser.add_argument("--lang", default="es")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--model", default="auto",
                        choices=["auto", "small", "medium"])
    parser.add_argument("--words-per-group", type=int, default=None, metavar="N")
    parser.add_argument("--out-stem", default=None)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    input_path = Path(args.input)

    if input_path.is_dir():
        videos = sorted(v for v in input_path.glob("*.mp4") if not v.stem.startswith("test_"))
        if not videos:
            print(f"[!] No hay .mp4 en {input_path}")
            sys.exit(1)
        print(f"[batch] {len(videos)} videos\n")
        total = 0.0
        for v in videos:
            t, _ = process_video(v, args.style, args.lang, output_dir,
                                  args.model, args.words_per_group)
            total += t
        print(f"[batch] Total: {total:.1f}s")
    elif input_path.is_file():
        process_video(input_path, args.style, args.lang, output_dir,
                      args.model, args.words_per_group, args.out_stem)
    else:
        print(f"[ERROR] No existe: {input_path}")
        sys.exit(1)


if __name__ == "__main__":
    main()
