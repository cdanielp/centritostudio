"""smoke_srt_roundtrip.py — E2E SINTETICO del round-trip SRT (S36-B).

Sin GPU, sin red, sin Whisper/DeepSeek reales. Requiere haber corrido antes:
    python revision/s36-b-srt-caption-roundtrip/gen_fixture.py --create

Flujo:
  1. Render principal: caption.py VIDEO --srt corregido_sintetico.srt (FFmpeg real).
  2. ffprobe del MP4 (duracion, resolucion, audio) + sidecar de alineacion.
  3. Round-trip de clip: slice+rebase del SRT -> corta un clip -> lo renderiza con su SRT.
  4. Verifica que el SRT fuente NO cambio y reporta metricas agregadas.

No versiona nada: todos los outputs viven en work/ (mp4/ass gitignored) o transcripts/.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORK = HERE / "work"
TRANSCRIPTS = ROOT / "transcripts"
PY = ROOT / "venv" / "Scripts" / "python.exe"
STEM = "s36b_fixture"
VIDEO = WORK / f"{STEM}.mp4"
SRT_FUENTE = HERE / "fixtures" / "corregido_sintetico.srt"

sys.path.insert(0, str(ROOT))
from srt_import import load_srt, serialize_srt  # noqa: E402
from srt_slice import slice_srt  # noqa: E402

SYNTH_WORDS = json.loads((TRANSCRIPTS / f"{STEM}_words.json").read_text(encoding="utf-8"))["words"]


def _run(cmd: list[str], label: str) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"[smoke] {label} FALLO\n{r.stdout[-500:]}\n{r.stderr[-800:]}")


def _ffprobe(path: Path) -> dict:
    r = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    data = json.loads(r.stdout)
    info = {"w": 0, "h": 0, "dur": 0.0, "audio": False}
    for s in data.get("streams", []):
        if s.get("codec_type") == "video":
            info["w"], info["h"] = int(s["width"]), int(s["height"])
        elif s.get("codec_type") == "audio":
            info["audio"] = True
    info["dur"] = float(data.get("format", {}).get("duration", 0))
    return info


def _check(cond: bool, msg: str) -> None:
    print(("  OK  " if cond else " FAIL ") + msg)
    if not cond:
        raise SystemExit(f"[smoke] check fallo: {msg}")


def render_principal() -> None:
    print("[smoke] 1) Render principal con --srt")
    _run(
        [
            str(PY),
            "caption.py",
            str(VIDEO),
            "--srt",
            str(SRT_FUENTE),
            "--style",
            "clean",
            "--output-dir",
            str(WORK),
        ],
        "render principal",
    )
    out = WORK / f"{STEM}_clean_srt.mp4"
    info = _ffprobe(out)
    _check(out.exists(), f"MP4 generado: {out.name}")
    _check(info["w"] == 1080 and info["h"] == 1920, f"resolucion 9:16 {info['w']}x{info['h']}")
    _check(5.0 <= info["dur"] <= 7.0, f"duracion ~6s: {info['dur']:.2f}s")
    _check(info["audio"], "audio presente")

    sidecar = json.loads((TRANSCRIPTS / f"{STEM}_srt_alignment.json").read_text(encoding="utf-8"))
    s = sidecar["summary"]
    _check(s["n_cues"] == 4, "4 cues en el sidecar")
    _check(s["word_aligned"] == 3, "3 cues word-aligned (exacto+sustitucion+acentos)")
    _check(s["cue_fallback"] == 1, "1 cue fallback honesto (sin audio)")
    print(f"[smoke] cobertura agregada: {s['coverage']:.2f}")


def _clip_words(start_s: float, end_s: float) -> list[dict]:
    out = []
    for w in SYNTH_WORDS:
        if start_s <= (w["s"] + w["e"]) / 2 < end_s:
            out.append({**w, "s": round(w["s"] - start_s, 3), "e": round(w["e"] - start_s, 3)})
    return out


def round_trip_clip() -> None:
    print("[smoke] 2) Round-trip de clip (slice + rebase + render)")
    doc = load_srt(SRT_FUENTE)
    start_s, end_s = 0.0, 3.0
    derived = slice_srt(doc, int(round(start_s * 1000)), int(round(end_s * 1000)))
    clip_srt = WORK / "clipA.srt"
    clip_srt.write_text(serialize_srt(derived), encoding="utf-8", newline="")
    _check(derived.cues[0].start_ms == 0, "SRT del clip rebasado a t=0")

    clip_mp4 = WORK / "clipA.mp4"
    _run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            "0",
            "-t",
            "3",
            "-i",
            str(VIDEO),
            "-c:v",
            "libx264",
            "-crf",
            "23",
            "-c:a",
            "aac",
            str(clip_mp4),
        ],
        "corte de clip",
    )
    # transcript sintetico del clip (rebasado), mas reciente que el clip
    (TRANSCRIPTS / "clipA_words.json").write_text(
        json.dumps({"words": _clip_words(0.0, 3.0), "language": "es"}, ensure_ascii=False),
        encoding="utf-8",
    )
    _run(
        [
            str(PY),
            "caption.py",
            str(clip_mp4),
            "--srt",
            str(clip_srt),
            "--style",
            "clean",
            "--output-dir",
            str(WORK),
        ],
        "render de clip",
    )
    out = WORK / "clipA_clean_srt.mp4"
    info = _ffprobe(out)
    _check(out.exists(), f"clip renderizado con su SRT: {out.name}")
    _check(2.0 <= info["dur"] <= 4.0, f"duracion del clip ~3s: {info['dur']:.2f}s")


def verificar_fuente_intacta(antes: bytes) -> None:
    print("[smoke] 3) Verificacion de integridad")
    _check(SRT_FUENTE.read_bytes() == antes, "el SRT fuente NO fue modificado")


def main() -> None:
    if not VIDEO.exists():
        raise SystemExit("[smoke] falta el fixture. Corre gen_fixture.py --create primero.")
    antes = SRT_FUENTE.read_bytes()
    render_principal()
    round_trip_clip()
    verificar_fuente_intacta(antes)
    print("\n[smoke] ===== ROUND-TRIP SRT OK (sintetico, offline) =====")
    print("[smoke] Revisa los MP4 en work/ para el veredicto visual (CHECKLIST_VISUAL.md).")


if __name__ == "__main__":
    main()
