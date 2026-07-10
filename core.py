"""
core.py — Pipeline de transcripcion, agrupacion y coordinacion de render.
Usada por caption.py (CLI) y app.py (web). Sin estado global, sin I/O de red.
Las funciones de generacion ASS y quemado viven en core_ass.py.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

# Re-exportar funciones de core_ass para mantener compatibilidad de imports
from core_ass import (  # noqa: F401
    apply_brain,
    build_ass,
    burn_video,
    burn_video_with_emojis,
    extract_thumb,
)

LOCAL_MEDIUM_PATH = Path(__file__).parent / "models" / "medium"
PUNCT_SENTENCE = frozenset(".!?…")  # Pausa obligatoria después de estas
VOCAB_PATH = Path(__file__).parent / "vocabulario.txt"

# ─────────────────────────────────────────────────────────────────────────────
# Entorno / modelo
# ─────────────────────────────────────────────────────────────────────────────


def detect_device() -> tuple[str, str]:
    """Devuelve (device, compute_type)."""
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16"
    except Exception:  # ctranslate2 no instalado o sin CUDA — fallback silencioso a CPU
        pass
    return "cpu", "int8"


def resolve_model(model_arg: str) -> tuple[str, str]:
    """Devuelve (model_path_or_name, label)."""
    if model_arg == "medium":
        if LOCAL_MEDIUM_PATH.exists():
            return str(LOCAL_MEDIUM_PATH), "medium-local"
        return "small", "small-fallback"
    if model_arg == "auto":
        if LOCAL_MEDIUM_PATH.exists():
            return str(LOCAL_MEDIUM_PATH), "medium-auto"
        return "small", "small-auto"
    return model_arg, model_arg


def _load_initial_prompt() -> str | None:
    if VOCAB_PATH.exists():
        return VOCAB_PATH.read_text(encoding="utf-8").strip()
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Info del video
# ─────────────────────────────────────────────────────────────────────────────


def _probe_volume(video_path: Path) -> float:
    """Devuelve mean_volume en dBFS via ffmpeg volumedetect; -99.0 si no se detecta."""
    vol = subprocess.run(
        [
            "ffmpeg",
            "-i",
            str(video_path),
            "-af",
            "volumedetect",
            "-vn",
            "-sn",
            "-dn",
            "-f",
            "null",
            "NUL",
        ],
        capture_output=True,
        text=True,
    )
    for line in vol.stderr.splitlines():
        if "mean_volume:" in line:
            try:
                return float(line.split("mean_volume:")[1].split("dB")[0].strip())
            except ValueError:
                pass
    return -99.0


def get_video_info(video_path: Path) -> dict:
    """Devuelve width, height, duration, mean_volume, has_audio."""
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(video_path),
        ],
        capture_output=True,
        text=True,
    )
    data = json.loads(probe.stdout)
    info: dict[str, Any] = {
        "width": 0,
        "height": 0,
        "duration": 0.0,
        "mean_volume": -99.0,
        "has_audio": False,
    }
    for s in data.get("streams", []):
        if s.get("codec_type") == "video":
            info["width"] = int(s["width"])
            info["height"] = int(s["height"])
        elif s.get("codec_type") == "audio":
            info["has_audio"] = True
    info["duration"] = float(data.get("format", {}).get("duration", 0))
    if info["has_audio"]:
        info["mean_volume"] = _probe_volume(video_path)
    return info


# ─────────────────────────────────────────────────────────────────────────────
# Transcripcion
# ─────────────────────────────────────────────────────────────────────────────


def transcribe_video(
    video_path: Path,
    lang: str,
    device: str,
    compute_type: str,
    model_path: str,
    initial_prompt: str | None = None,
) -> dict:
    """Devuelve {"words": [{"w", "s", "e", "prob"}], "language": str}."""
    from faster_whisper import WhisperModel

    if initial_prompt is None:
        initial_prompt = _load_initial_prompt()

    model = WhisperModel(model_path, device=device, compute_type=compute_type)
    segments, info = model.transcribe(
        str(video_path),
        language=lang,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300},
        condition_on_previous_text=False,
        beam_size=5,
        initial_prompt=initial_prompt,
    )

    words: list[dict] = []
    for seg in segments:
        for w in seg.words or []:
            prob = getattr(w, "probability", 1.0)
            if prob < 0.05:
                continue
            text = w.word.strip()
            if not text:
                continue
            words.append(
                {"w": text, "s": round(w.start, 3), "e": round(w.end, 3), "prob": round(prob, 3)}
            )

    return {"words": words, "language": info.language}


# ─────────────────────────────────────────────────────────────────────────────
# Agrupacion de palabras con pausas naturales
# ─────────────────────────────────────────────────────────────────────────────


def _flush_group(groups: list[dict], st: dict) -> None:
    """Cierra el grupo actual, lo añade a groups y resetea el estado."""
    cw = st["cur_words"]
    if not cw:
        return
    groups.append(
        {
            "id": len(groups),
            "start": cw[0]["start"],
            "end": cw[-1]["end"],
            "text": " ".join(w["text"] for w in cw),
            "words": list(cw),
        }
    )
    st["cur_words"] = []
    st["line_chars"] = [0]
    st["line_idx"] = 0
    st["word_count"] = 0


def _start_group(st: dict, w_text: str, w_start: float, w_end: float) -> None:
    """Inicia un grupo nuevo con la primera palabra."""
    st["cur_words"] = [{"text": w_text, "start": w_start, "end": w_end, "line_idx": 0}]
    st["line_chars"] = [len(w_text)]
    st["line_idx"] = 0
    st["word_count"] = 1


def _add_word(
    st: dict, w_text: str, w_start: float, w_end: float, max_chars: int, max_lines: int
) -> None:
    """Añade una palabra al grupo actual, cambiando de linea si es necesario."""
    char_overflow = st["line_chars"][st["line_idx"]] + 1 + len(w_text) > max_chars
    if char_overflow and st["line_idx"] + 1 < max_lines:
        st["line_idx"] += 1
        st["line_chars"].append(len(w_text))
    else:
        st["line_chars"][st["line_idx"]] += 1 + len(w_text)
    st["cur_words"].append(
        {"text": w_text, "start": w_start, "end": w_end, "line_idx": st["line_idx"]}
    )
    st["word_count"] += 1


def _merge_orphan(
    groups: list[dict], max_chars: int, max_lines: int, max_words: int | None
) -> None:
    """Fusiona el ultimo grupo de 1 palabra con el anterior si cabe."""
    if len(groups) < 2 or len(groups[-1]["words"]) != 1:
        return
    prev, last = groups[-2], groups[-1]
    if max_words is not None and len(prev["words"]) >= max_words:
        return
    last_word = last["words"][0]
    last_line = max(w["line_idx"] for w in prev["words"])
    last_line_chars = sum(len(w["text"]) + 1 for w in prev["words"] if w["line_idx"] == last_line)
    fits = last_line_chars + len(last_word["text"]) <= max_chars + 4
    if not fits and last_line + 1 >= max_lines:
        return
    groups.pop()
    prev["end"] = last["end"]
    prev["text"] = prev["text"] + " " + last_word["text"]
    last_word["line_idx"] = last_line if fits else last_line + 1
    prev["words"].append(last_word)


def group_words(
    words: list[dict],
    max_chars: int = 18,
    max_lines: int = 2,
    max_words: int | None = None,
    pause_threshold: float = 0.4,
) -> list[dict]:
    """Convierte lista de words en grupos de subtitulo."""
    if not words:
        return []

    groups: list[dict] = []
    st: dict = {"cur_words": [], "line_chars": [0], "line_idx": 0, "word_count": 0}

    for raw in words:
        w_text, w_start, w_end = raw["w"], raw["s"], raw["e"]

        if not st["cur_words"]:
            _start_group(st, w_text, w_start, w_end)
            continue

        pause = w_start - st["cur_words"][-1]["end"]
        count_break = max_words is not None and st["word_count"] >= max_words
        char_overflow = st["line_chars"][st["line_idx"]] + 1 + len(w_text) > max_chars
        line_overflow = char_overflow and st["line_idx"] + 1 >= max_lines

        if pause > pause_threshold or count_break or line_overflow:
            _flush_group(groups, st)
            _start_group(st, w_text, w_start, w_end)
        else:
            _add_word(st, w_text, w_start, w_end, max_chars, max_lines)

        if w_text.rstrip() and w_text.rstrip()[-1] in PUNCT_SENTENCE:
            _flush_group(groups, st)

    _flush_group(groups, st)
    _merge_orphan(groups, max_chars, max_lines, max_words)

    for i, g in enumerate(groups):
        g["id"] = i

    return groups


# ─────────────────────────────────────────────────────────────────────────────
# Re-alineacion de timestamps tras edicion de texto
# ─────────────────────────────────────────────────────────────────────────────


def rebalance_timestamps(group: dict) -> dict:
    """Redistribuye timestamps proporcional al editar texto de un grupo."""
    new_tokens = group["text"].split()
    old_words = group["words"]

    if len(new_tokens) == len(old_words):
        new_words = [{**w, "text": t} for w, t in zip(old_words, new_tokens, strict=False)]
    else:
        total_dur = group["end"] - group["start"]
        if len(new_tokens) == 0:
            new_words = []
        else:
            step = total_dur / len(new_tokens)
            new_words = []
            for i, token in enumerate(new_tokens):
                s = round(group["start"] + i * step, 3)
                e = round(group["start"] + (i + 1) * step, 3)
                line = i // max(1, (len(new_tokens) // 2 + 1))
                new_words.append({"text": token, "start": s, "end": e, "line_idx": min(line, 1)})

    return {**group, "words": new_words, "text": group["text"]}
