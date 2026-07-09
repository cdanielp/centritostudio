"""
Pipeline de captions animados — Prompt Models Studio
Uso: python caption.py input/video.mp4 --style hormozi --lang es
     python caption.py input/ --style karaoke --lang es   (batch)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import pysubs2

from styles import StyleConfig, get_style


# ─── Detección de GPU ─────────────────────────────────────────────────────
def _detect_device() -> tuple[str, str, str]:
    """
    Devuelve (device, model_size, compute_type).
    Usa small+cuda si hay GPU (rapido y sin descarga extra).
    Modelo medium requiere descarga; activar con --model medium.
    """
    try:
        import ctranslate2
        n = ctranslate2.get_cuda_device_count()
        if n > 0:
            print(f"[gpu] {n} GPU CUDA disponible - usando cuda+float16")
            return "cuda", "small", "float16"
    except Exception:
        pass
    print("[gpu] Sin GPU CUDA - usando CPU+int8")
    return "cpu", "small", "int8"


# ─── Transcripción ────────────────────────────────────────────────────────
def transcribe(audio_path: Path, lang: str, device: str,
               model_size: str, compute_type: str) -> dict:
    from faster_whisper import WhisperModel

    print(f"[whisper] Cargando modelo '{model_size}' en {device} ({compute_type})...")
    model = WhisperModel(model_size, device=device, compute_type=compute_type)

    print(f"[whisper] Transcribiendo {audio_path.name}...")
    t0 = time.time()
    segments, info = model.transcribe(
        str(audio_path),
        language=lang,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300},
    )

    transcript: dict = {"language": info.language, "segments": []}
    for seg in segments:
        seg_dict: dict = {"start": seg.start, "end": seg.end,
                          "text": seg.text.strip(), "words": []}
        for word in (seg.words or []):
            seg_dict["words"].append({
                "word": word.word,
                "start": word.start,
                "end": word.end,
            })
        transcript["segments"].append(seg_dict)

    total_words = sum(len(s["words"]) for s in transcript["segments"])
    elapsed = time.time() - t0
    print(f"[whisper] {total_words} palabras | idioma: {info.language} | {elapsed:.1f}s")
    return transcript


# ─── Dimensiones del video ────────────────────────────────────────────────
def get_video_dimensions(video_path: Path) -> tuple[int, int]:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", str(video_path)],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(result.stdout)
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            return int(stream["width"]), int(stream["height"])
    raise ValueError(f"No se encontró stream de video en {video_path}")


# ─── Agrupación de palabras en bloques de subtítulo ───────────────────────
def _flatten_words(transcript: dict) -> list[tuple[str, float, float]]:
    words: list[tuple[str, float, float]] = []
    for seg in transcript.get("segments", []):
        for w in seg.get("words", []):
            text = w["word"].strip()
            if text and w.get("end") is not None and w.get("start") is not None:
                words.append((text, float(w["start"]), float(w["end"])))
    return words


def build_blocks(
    transcript: dict,
    max_chars: int = 18,
    max_lines: int = 2,
) -> list[tuple[float, float, list[tuple[str, float, float, int]]]]:
    """
    Devuelve lista de (block_start, block_end, [(word, start, end, line_idx), ...])
    Agrupa palabras en bloques de max_lines líneas con max_chars por línea.
    """
    all_words = _flatten_words(transcript)
    if not all_words:
        return []

    blocks: list[tuple[float, float, list]] = []
    # current_lines: lista de líneas; cada línea es lista de (word, start, end)
    current_lines: list[list[tuple[str, float, float]]] = [[]]
    current_line_chars: list[int] = [0]

    for (word, start, end) in all_words:
        word_len = len(word)
        line_idx = len(current_lines) - 1
        current_chars = current_line_chars[line_idx]
        has_words_on_line = bool(current_lines[line_idx])
        space = 1 if has_words_on_line else 0

        block_empty = not any(current_lines)

        if block_empty:
            current_lines = [[(word, start, end)]]
            current_line_chars = [word_len]
        elif current_chars + space + word_len <= max_chars:
            current_lines[line_idx].append((word, start, end))
            current_line_chars[line_idx] += space + word_len
        elif line_idx + 1 < max_lines:
            current_lines.append([(word, start, end)])
            current_line_chars.append(word_len)
        else:
            _commit_block(blocks, current_lines)
            current_lines = [[(word, start, end)]]
            current_line_chars = [word_len]

    if any(current_lines):
        _commit_block(blocks, current_lines)

    return blocks


def _commit_block(
    blocks: list,
    lines: list[list[tuple[str, float, float]]],
) -> None:
    flat: list[tuple[str, float, float, int]] = []
    for li, line in enumerate(lines):
        for item in line:
            flat.append(item + (li,))
    if not flat:
        return
    block_start = flat[0][1]
    block_end = flat[-1][2]
    blocks.append((block_start, block_end, flat))


# ─── Helpers de color / ASS ────────────────────────────────────────────────
def _ass_to_pysubs2(ass_color: str) -> pysubs2.Color:
    """Convierte &HAABBGGRR a pysubs2.Color(r, g, b, a)"""
    h = ass_color.replace("&H", "").replace("&", "").zfill(8)
    a, b, g, r = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16)
    return pysubs2.Color(r, g, b, a)


def _escape_ass(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")


def _build_word_text(
    flat: list[tuple[str, float, float, int]],
    active_idx: int,
    style_cfg: StyleConfig,
) -> str:
    """Construye el texto ASS del evento con el highlight en la palabra active_idx."""
    parts: list[str] = []
    prev_line_idx: int | None = None
    hl = style_cfg.highlight_color
    anim = style_cfg.animation_type

    for i, (w, w_start, w_end, line_idx) in enumerate(flat):
        if prev_line_idx is not None and line_idx != prev_line_idx:
            # Salto de línea entre partes (sin espacio extra)
            if parts and parts[-1] != "\\N":
                parts.append("\\N")

        w_disp = w.upper() if style_cfg.uppercase else w
        w_esc = _escape_ass(w_disp)

        if i == active_idx:
            if anim == "karaoke":
                dur_cs = max(int((w_end - w_start) * 100), 5)
                tag = f"{{\\kf{dur_cs}\\c{hl}}}{w_esc}{{\\r}}"
            elif anim == "bounce":
                tag = (
                    f"{{\\t(0,80,\\fscx122\\fscy122)"
                    f"\\t(80,160,\\fscx100\\fscy100)"
                    f"\\c{hl}}}{w_esc}{{\\r}}"
                )
            elif anim == "scale":
                tag = f"{{\\fscx115\\fscy115\\c{hl}}}{w_esc}{{\\r}}"
            else:  # highlight
                tag = f"{{\\c{hl}}}{w_esc}{{\\r}}"
            parts.append(tag)
        else:
            parts.append(w_esc)

        prev_line_idx = line_idx

    # Unir palabras con espacio, respetando los saltos de línea
    result: list[str] = []
    for p in parts:
        if p == "\\N":
            # Quitar espacio de cola antes del salto
            if result and result[-1] == " ":
                result.pop()
            result.append("\\N")
        else:
            if result and result[-1] != "\\N":
                result.append(" ")
            result.append(p)
    return "".join(result)


# ─── Generación del archivo .ass ──────────────────────────────────────────
def generate_ass(
    transcript: dict,
    video_width: int,
    video_height: int,
    style_cfg: StyleConfig,
    output_path: Path,
) -> None:
    # Escala de fuente relativa a la resolución
    ref_height = 1920 if video_height >= video_width else 1080
    dim_scale = max(video_height / ref_height, 0.4)

    blocks = build_blocks(
        transcript,
        max_chars=style_cfg.max_chars_per_line,
        max_lines=style_cfg.max_lines,
    )
    if not blocks:
        print("[ass] ADVERTENCIA: no se encontraron palabras con timestamps")

    subs = pysubs2.SSAFile()
    subs.info.update({
        "WrapStyle": "3",
        "ScaledBorderAndShadow": "yes",
        "PlayResX": str(video_width),
        "PlayResY": str(video_height),
        "ScriptType": "v4.00+",
    })

    base = pysubs2.SSAStyle()
    base.fontname = style_cfg.font_name
    base.fontsize = max(int(style_cfg.font_size * dim_scale), 20)
    base.primarycolor = _ass_to_pysubs2(style_cfg.primary_color)
    base.bold = style_cfg.bold
    base.outline = round(style_cfg.outline_size * dim_scale, 1)
    base.outlinecolor = _ass_to_pysubs2(style_cfg.outline_color)
    base.shadow = round(style_cfg.shadow_depth * dim_scale, 1)
    base.shadowcolor = _ass_to_pysubs2(style_cfg.shadow_color)
    base.alignment = pysubs2.Alignment.BOTTOM_CENTER
    base.marginl = int(50 * dim_scale)
    base.marginr = int(50 * dim_scale)
    base.marginv = int(video_height * style_cfg.margin_pct)
    subs.styles["Default"] = base

    for (block_start, block_end, flat) in blocks:
        for idx, (_, word_start, _, _) in enumerate(flat):
            event_end = flat[idx + 1][1] if idx < len(flat) - 1 else block_end
            # Asegurar que end > start (mínimo 50ms)
            event_end = max(event_end, word_start + 0.05)

            text = _build_word_text(flat, idx, style_cfg)
            event = pysubs2.SSAEvent(
                start=pysubs2.make_time(s=word_start),
                end=pysubs2.make_time(s=event_end),
                text=text,
            )
            subs.events.append(event)

    subs.save(str(output_path))
    print(f"[ass] {output_path.name} generado ({len(subs.events)} eventos)")


# ─── Quemado con FFmpeg ───────────────────────────────────────────────────
def _ffmpeg_ass_path(ass_path: Path) -> str:
    """Convierte ruta a formato compatible con el filtro ass de FFmpeg en Windows."""
    try:
        # Intentar ruta relativa (más simple, sin problemas de colon)
        rel = ass_path.resolve().relative_to(Path.cwd())
        return str(rel).replace("\\", "/")
    except ValueError:
        pass
    # Ruta absoluta con colon escapado (Windows: C: → C\:)
    abs_str = str(ass_path.resolve()).replace("\\", "/")
    if len(abs_str) >= 2 and abs_str[1] == ":":
        abs_str = abs_str[0] + "\\:" + abs_str[2:]
    return abs_str


def burn_subtitles(input_video: Path, ass_path: Path, output_video: Path) -> None:
    ass_filter = f"ass={_ffmpeg_ass_path(ass_path)}"
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_video),
        "-vf", ass_filter,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-c:a", "copy",
        str(output_video),
    ]
    print(f"[ffmpeg] Quemando -> {output_video.name}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[ERROR ffmpeg stderr]:\n{result.stderr[-2000:]}")
        sys.exit(1)


# ─── Pipeline completo para un video ─────────────────────────────────────
def process_video(
    video_path: Path,
    style: str,
    lang: str,
    output_dir: Path,
    device: str,
    model_size: str,
    compute_type: str,
) -> float:
    t0 = time.time()
    output_dir.mkdir(parents=True, exist_ok=True)

    style_cfg = get_style(style)
    stem = video_path.stem
    ass_path = output_dir / f"{stem}_{style}.ass"
    out_path = output_dir / f"{stem}_{style}.mp4"

    transcript = transcribe(video_path, lang, device, model_size, compute_type)
    width, height = get_video_dimensions(video_path)
    print(f"[video] Resolución: {width}x{height}")

    generate_ass(transcript, width, height, style_cfg, ass_path)
    burn_subtitles(video_path, ass_path, out_path)

    elapsed = time.time() - t0
    print(f"[ok] {video_path.name} -> {out_path.name} en {elapsed:.1f}s\n")
    return elapsed


# ─── CLI ──────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Captions animados word-by-word — Prompt Models Studio"
    )
    parser.add_argument("input",
                        help="Video .mp4 de entrada, o carpeta para modo batch")
    parser.add_argument("--style", default="hormozi",
                        choices=["hormozi", "karaoke", "bounce", "pms"],
                        help="Estilo de captions (default: hormozi)")
    parser.add_argument("--lang", default="es",
                        help="Código de idioma del audio (default: es)")
    parser.add_argument("--output-dir", default="output",
                        help="Carpeta de salida (default: output/)")
    args = parser.parse_args()

    device, model_size, compute_type = _detect_device()
    output_dir = Path(args.output_dir)
    input_path = Path(args.input)

    if input_path.is_dir():
        videos = sorted(input_path.glob("*.mp4"))
        if not videos:
            print(f"[!] No se encontraron archivos .mp4 en {input_path}")
            sys.exit(1)
        print(f"[batch] {len(videos)} videos encontrados en {input_path}\n")
        total = 0.0
        for v in videos:
            total += process_video(v, args.style, args.lang, output_dir,
                                   device, model_size, compute_type)
        print(f"[batch] Completado. Tiempo total: {total:.1f}s")
    elif input_path.is_file():
        process_video(input_path, args.style, args.lang, output_dir,
                      device, model_size, compute_type)
    else:
        print(f"[ERROR] No existe: {input_path}")
        sys.exit(1)


if __name__ == "__main__":
    main()
