"""
core.py — Funciones puras del pipeline de captions.
Usadas por caption.py (CLI) y app.py (web). Sin estado global, sin I/O de red.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pysubs2

from styles import StyleConfig, get_style

# ─────────────────────────────────────────────────────────────────────────────
# Tipos
# ─────────────────────────────────────────────────────────────────────────────

# Word como sale de faster-whisper (serializable a JSON)
# {"w": str, "s": float, "e": float, "prob": float}

# Group: bloque de subtítulo editable
# {"id": int, "start": float, "end": float, "text": str,
#  "words": [{"text": str, "start": float, "end": float, "line_idx": int}]}

LOCAL_MEDIUM_PATH = Path(__file__).parent / "models" / "medium"
PUNCT_SENTENCE   = frozenset(".!?…")  # Pausa obligatoria después de estas
VOCAB_PATH       = Path(__file__).parent / "vocabulario.txt"


# ─────────────────────────────────────────────────────────────────────────────
# Entorno / modelo
# ─────────────────────────────────────────────────────────────────────────────

def detect_device() -> tuple[str, str]:
    """Devuelve (device, compute_type)."""
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16"
    except Exception:
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

def get_video_info(video_path: Path) -> dict:
    """Devuelve width, height, duration, mean_volume, has_audio."""
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", "-show_format", str(video_path)],
        capture_output=True, text=True,
    )
    data = json.loads(probe.stdout)
    info: dict[str, Any] = {"width": 0, "height": 0, "duration": 0.0,
                              "mean_volume": -99.0, "has_audio": False}
    for s in data.get("streams", []):
        if s.get("codec_type") == "video":
            info["width"] = int(s["width"])
            info["height"] = int(s["height"])
        elif s.get("codec_type") == "audio":
            info["has_audio"] = True
    info["duration"] = float(data.get("format", {}).get("duration", 0))

    if info["has_audio"]:
        vol = subprocess.run(
            ["ffmpeg", "-i", str(video_path), "-af", "volumedetect",
             "-vn", "-sn", "-dn", "-f", "null", "NUL"],
            capture_output=True, text=True,
        )
        for line in vol.stderr.splitlines():
            if "mean_volume:" in line:
                try:
                    info["mean_volume"] = float(line.split("mean_volume:")[1].split("dB")[0].strip())
                except ValueError:
                    pass
    return info


# ─────────────────────────────────────────────────────────────────────────────
# Transcripción
# ─────────────────────────────────────────────────────────────────────────────

def transcribe_video(
    video_path: Path,
    lang: str,
    device: str,
    compute_type: str,
    model_path: str,
    initial_prompt: str | None = None,
) -> dict:
    """
    Devuelve {"words": [{"w", "s", "e", "prob"}], "language": str}.
    """
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
        for w in (seg.words or []):
            prob = getattr(w, "probability", 1.0)
            if prob < 0.05:  # solo filtrar palabras casi-nulas; vad_filter ya maneja el silencio
                continue
            text = w.word.strip()
            if not text:
                continue
            words.append({"w": text, "s": round(w.start, 3), "e": round(w.end, 3), "prob": round(prob, 3)})

    return {"words": words, "language": info.language}


# ─────────────────────────────────────────────────────────────────────────────
# Agrupación de palabras con pausas naturales
# ─────────────────────────────────────────────────────────────────────────────

def group_words(
    words: list[dict],
    max_chars: int = 18,
    max_lines: int = 2,
    max_words: int | None = None,
    pause_threshold: float = 0.4,
) -> list[dict]:
    """
    Convierte lista de words en grupos de subtítulo.
    Corta en: pausa > pause_threshold, puntuación final, límite de chars, o max_words.
    """
    if not words:
        return []

    groups: list[dict] = []
    cur_words: list[dict] = []   # {"text", "start", "end", "line_idx"}
    line_chars: list[int] = [0]
    line_idx = 0
    word_count = 0

    def _flush():
        nonlocal cur_words, line_chars, line_idx, word_count
        if not cur_words:
            return
        g_start = cur_words[0]["start"]
        g_end   = cur_words[-1]["end"]
        g_text  = " ".join(w["text"] for w in cur_words)
        groups.append({
            "id":    len(groups),
            "start": g_start,
            "end":   g_end,
            "text":  g_text,
            "words": list(cur_words),
        })
        cur_words  = []
        line_chars = [0]
        line_idx   = 0
        word_count = 0

    for raw in words:
        w_text  = raw["w"]
        w_start = raw["s"]
        w_end   = raw["e"]
        w_len   = len(w_text)

        if not cur_words:
            cur_words.append({"text": w_text, "start": w_start, "end": w_end, "line_idx": 0})
            line_chars[0] = w_len
            word_count = 1
            continue

        # ── Condiciones de corte ANTES de añadir la nueva palabra ──
        pause       = w_start - cur_words[-1]["end"]
        pause_break = pause > pause_threshold
        count_break = max_words is not None and word_count >= max_words

        cur_line_chars = line_chars[line_idx]
        space          = 1  # siempre hay espacio entre palabras de la misma línea
        char_overflow  = cur_line_chars + space + w_len > max_chars
        line_overflow  = char_overflow and (line_idx + 1 >= max_lines)

        if pause_break or count_break or line_overflow:
            _flush()
            cur_words.append({"text": w_text, "start": w_start, "end": w_end, "line_idx": 0})
            line_chars = [w_len]
            line_idx   = 0
            word_count = 1
        elif char_overflow:
            # Nueva línea dentro del mismo grupo
            line_idx += 1
            line_chars.append(w_len)
            cur_words.append({"text": w_text, "start": w_start, "end": w_end, "line_idx": line_idx})
            word_count += 1
        else:
            line_chars[line_idx] += space + w_len
            cur_words.append({"text": w_text, "start": w_start, "end": w_end, "line_idx": line_idx})
            word_count += 1

        # ── Corte DESPUÉS de la palabra si termina en puntuación final ──
        if w_text.rstrip() and w_text.rstrip()[-1] in PUNCT_SENTENCE:
            _flush()

    _flush()

    # Anti-huérfano: fusionar último grupo de 1 sola palabra con el anterior
    if len(groups) >= 2 and len(groups[-1]["words"]) == 1:
        prev = groups[-2]
        last = groups.pop()
        # Añadir la palabra al final del grupo anterior (misma línea si cabe)
        prev["end"]  = last["end"]
        prev["text"] = prev["text"] + " " + last["words"][0]["text"]
        last_word = last["words"][0]
        # Determinar line_idx del último grupo anterior
        last_line = max(w["line_idx"] for w in prev["words"])
        last_line_chars = sum(
            len(w["text"]) + 1 for w in prev["words"] if w["line_idx"] == last_line
        )
        if last_line_chars + len(last_word["text"]) <= max_chars + 4:
            last_word["line_idx"] = last_line
        else:
            last_word["line_idx"] = min(last_line + 1, max_lines - 1)
        prev["words"].append(last_word)

    # Re-numerar IDs
    for i, g in enumerate(groups):
        g["id"] = i

    return groups


# ─────────────────────────────────────────────────────────────────────────────
# Re-alineación de timestamps tras edición de texto
# ─────────────────────────────────────────────────────────────────────────────

def rebalance_timestamps(group: dict) -> dict:
    """
    Cuando el usuario edita el texto de un grupo, redistribuye los timestamps
    proporcionalmente. Si el conteo de palabras es idéntico, mantiene timestamps.
    """
    new_tokens = group["text"].split()
    old_words  = group["words"]

    if len(new_tokens) == len(old_words):
        # Mismo conteo → solo actualizar texto, conservar timestamps
        new_words = [
            {**w, "text": t} for w, t in zip(old_words, new_tokens)
        ]
    else:
        # Redistribuir proporcionalmente
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


# ─────────────────────────────────────────────────────────────────────────────
# Generación de archivo .ass
# ─────────────────────────────────────────────────────────────────────────────

def _ass_to_pysubs2(ass_color: str) -> pysubs2.Color:
    h = ass_color.replace("&H", "").replace("&", "").zfill(8)
    a, b, g, r = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16)
    return pysubs2.Color(r, g, b, a)


def _escape_ass(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")


def _word_event_text(group_words: list[dict], active_idx: int, style_cfg: StyleConfig) -> str:
    """Construye texto ASS de un evento: todas las palabras del grupo, la activa con color."""
    parts: list[str] = []
    prev_line = None
    hl   = style_cfg.highlight_color
    anim = style_cfg.animation_type

    for i, w in enumerate(group_words):
        if prev_line is not None and w["line_idx"] != prev_line:
            if parts and parts[-1] != "\\N":
                parts.append("\\N")

        disp = w["text"].upper() if style_cfg.uppercase else w["text"]
        esc  = _escape_ass(disp)

        if i == active_idx:
            if anim == "karaoke":
                dur_cs = max(int((w["end"] - w["start"]) * 100), 5)
                tag = f"{{\\kf{dur_cs}\\c{hl}}}{esc}{{\\r}}"
            elif anim == "bounce":
                tag = (f"{{\\t(0,80,\\fscx122\\fscy122)"
                       f"\\t(80,160,\\fscx100\\fscy100)"
                       f"\\c{hl}}}{esc}{{\\r}}")
            elif anim == "scale":
                tag = f"{{\\fscx115\\fscy115\\c{hl}}}{esc}{{\\r}}"
            else:
                tag = f"{{\\c{hl}}}{esc}{{\\r}}"
            parts.append(tag)
        else:
            parts.append(esc)

        prev_line = w["line_idx"]

    # Unir respetando saltos de línea
    result: list[str] = []
    for p in parts:
        if p == "\\N":
            if result and result[-1] == " ":
                result.pop()
            result.append("\\N")
        else:
            if result and result[-1] != "\\N":
                result.append(" ")
            result.append(p)
    return "".join(result)


def build_ass(
    groups: list[dict],
    video_width: int,
    video_height: int,
    style_cfg: StyleConfig,
    output_path: Path,
) -> None:
    """
    Genera el archivo .ass a partir de grupos editados.
    Escala SIEMPRE relativa a PlayResY para consistencia entre resoluciones.
    """
    # Escala relativa a altura (ref: 1920 para vertical, 1080 para horizontal)
    ref_h    = 1920 if video_height >= video_width else 1080
    dim_scale = max(video_height / ref_h, 0.40)

    subs = pysubs2.SSAFile()
    subs.info.update({
        "WrapStyle": "3",
        "ScaledBorderAndShadow": "yes",
        "PlayResX": str(video_width),
        "PlayResY": str(video_height),
        "ScriptType": "v4.00+",
    })

    base = pysubs2.SSAStyle()
    base.fontname     = style_cfg.font_name
    base.fontsize     = max(int(style_cfg.font_size * dim_scale), 20)
    base.primarycolor = _ass_to_pysubs2(style_cfg.primary_color)
    base.bold         = style_cfg.bold
    base.outline      = round(style_cfg.outline_size * dim_scale, 1)
    base.outlinecolor = _ass_to_pysubs2(style_cfg.outline_color)
    base.shadow       = round(style_cfg.shadow_depth * dim_scale, 1)
    base.shadowcolor  = _ass_to_pysubs2(style_cfg.shadow_color)
    base.alignment    = pysubs2.Alignment.BOTTOM_CENTER
    base.marginl      = int(50 * dim_scale)
    base.marginr      = int(50 * dim_scale)
    base.marginv      = int(video_height * style_cfg.margin_pct)
    subs.styles["Default"] = base

    for group in groups:
        gw = group["words"]
        for idx, word in enumerate(gw):
            ev_end = gw[idx + 1]["start"] if idx < len(gw) - 1 else group["end"]
            ev_end = max(ev_end, word["start"] + 0.05)

            text  = _word_event_text(gw, idx, style_cfg)
            event = pysubs2.SSAEvent(
                start=pysubs2.make_time(s=word["start"]),
                end=pysubs2.make_time(s=ev_end),
                text=text,
            )
            subs.events.append(event)

    subs.save(str(output_path))


# ─────────────────────────────────────────────────────────────────────────────
# Quemado con FFmpeg
# ─────────────────────────────────────────────────────────────────────────────

def _ffmpeg_ass_path(ass_path: Path) -> str:
    """Convierte ruta a formato compatible con filtro ass en Windows."""
    try:
        rel = ass_path.resolve().relative_to(Path.cwd())
        return str(rel).replace("\\", "/")
    except ValueError:
        pass
    s = str(ass_path.resolve()).replace("\\", "/")
    if len(s) >= 2 and s[1] == ":":
        s = s[0] + "\\:" + s[2:]
    return s


def burn_video(
    input_video: Path,
    ass_path: Path,
    output_video: Path,
) -> float:
    """Quema el .ass sobre el video. Devuelve el tiempo de proceso en segundos."""
    import time
    t0 = time.time()
    ass_filter = f"ass={_ffmpeg_ass_path(ass_path)}"
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_video),
        "-vf", ass_filter,
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "copy",
        str(output_video),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg error:\n{result.stderr[-1500:]}")
    return round(time.time() - t0, 2)


# ─────────────────────────────────────────────────────────────────────────────
# Miniatura de video
# ─────────────────────────────────────────────────────────────────────────────

def extract_thumb(video_path: Path, output_path: Path, at_sec: float = 1.0) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(at_sec), "-i", str(video_path),
         "-vframes", "1", "-vf", "scale=200:-1", str(output_path)],
        capture_output=True,
    )
