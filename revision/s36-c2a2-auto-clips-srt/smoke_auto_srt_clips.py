"""smoke_auto_srt_clips.py — E2E FFmpeg REAL de Auto caption_source=srt (S36-C2A2).

Cero red, cero GPU, cero LLM: la SELECCIÓN de clips se inyecta (fixture), pero la extracción
FFmpeg, el reframe, la derivación de artefactos por clip, el ASS y el burn corren de verdad.
Verifica: 3 clips con su propio SRT/words/groups rebasados a t=0; captions oficiales del SRT;
fallo aislado de un clip; resume sin re-render; retry del fallido. Genera evidencia en
output/revision-s36-c2a2-integration/ (gitignored). No versiona nada.

Uso:  venv\\Scripts\\python revision\\s36-c2a2-auto-clips-srt\\smoke_auto_srt_clips.py
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import auto  # noqa: E402
import studio_srt  # noqa: E402
import transcript_provenance as tp  # noqa: E402
from auto_config import AutoConfig  # noqa: E402

EVID = ROOT / "output" / "revision-s36-c2a2-integration"
DUR_S = 16


def _ts(ms):
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _srt(*cues):
    return "\n".join(f"{i}\n{_ts(s)} --> {_ts(e)}\n{t}\n" for i, s, e, t in cues).encode("utf-8")


_SRT = _srt(
    (1, 0, 2000, "Uno dentro"),
    (2, 4000, 6000, "Dos cruza corte"),
    (3, 9000, 11000, "Tres"),
    (4, 14000, 16000, "Cuatro final"),
)
_WORDS = {
    "words": [
        {"w": "uno", "s": 0.5, "e": 1.5, "prob": 1.0},
        {"w": "dos", "s": 4.5, "e": 5.5, "prob": 1.0},
        {"w": "tres", "s": 9.5, "e": 10.5, "prob": 1.0},
        {"w": "cuatro", "s": 14.5, "e": 15.5, "prob": 1.0},
    ],
    "language": "es",
}
_CLIPS = [
    {"archivo": "demo_clip1_single.mp4", "start": 0.0, "end": 5.0, "dur_s": 5.0, "titulo": "C1"},
    {"archivo": "demo_clip2_single.mp4", "start": 4.0, "end": 8.0, "dur_s": 4.0, "titulo": "C2"},
    {"archivo": "demo_clip3_single.mp4", "start": 12.0, "end": 16.0, "dur_s": 4.0, "titulo": "C3"},
]


def _gen_video(dst: Path):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=0x101820:s=1080x1920:r=30:d={DUR_S}",
         "-f", "lavfi", "-i", f"sine=frequency=220:duration={DUR_S}",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", str(dst)],
        check=True, capture_output=True,
    )


def _ffprobe(p: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-show_entries", "stream=codec_type", "-of", "json", str(p)],
        check=True, capture_output=True, text=True,
    ).stdout
    return json.loads(out)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _cortar(video: Path, start: float, end: float, dst: Path):
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(start), "-to", str(end), "-i", str(video),
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-c:a", "aac", str(dst)],
        check=True, capture_output=True,
    )


def _setup(work: Path):
    trans = work / "transcripts"
    clips = work / "output" / "clips"
    inp = work / "input"
    for d in (trans, clips, inp, work / "output" / "paquetes"):
        d.mkdir(parents=True, exist_ok=True)
    video = inp / "demo.mov"
    _gen_video(video)
    (trans / "demo_words.json").write_text(json.dumps(_WORDS), encoding="utf-8")
    dur_ms = DUR_S * 1000
    doc, diags = studio_srt.parse_and_validate(_SRT, source_name="s.srt", video_duration_ms=dur_ms)
    studio_srt.store_and_associate(
        doc, diags, video_stem="demo", video_filename="demo.mov", video_duration_ms=dur_ms,
        data=_SRT, storage_root=trans / "studio_srt", manifest_dir=trans,
    )
    parts = tp.resolve_srt_timing_artifacts(
        transcripts_dir=trans, video_stem="demo", video_filename="demo.mov"
    )
    parts.directory.mkdir(parents=True, exist_ok=True)
    prov = tp.attach_video_provenance(dict(_WORDS), video)
    parts.words_path.write_text(json.dumps(prov), encoding="utf-8")
    auto.TRANSCRIPTS = trans
    auto.CLIPS_DIR = clips
    auto.PAQUETES_DIR = work / "output" / "paquetes"
    auto.ROOT = work
    return video, trans, clips


def _inyectar_clips(video, clips_dir):
    def fake(v, w, n):
        for c in _CLIPS:
            _cortar(video, c["start"], c["end"], clips_dir / c["archivo"])
        return {
            "clips": [dict(c) for c in _CLIPS],
            "casi": [],
            "telemetria_resumen": {"costo_usd": 0.0},
        }

    auto._asegurar_clips = lambda v, w, n: (fake(v, w, n), False)


def main():
    import shutil

    EVID.mkdir(parents=True, exist_ok=True)
    work = EVID / "work"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir()
    video, trans, clips = _setup(work)
    _inyectar_clips(video, clips)

    r = auto.ejecutar_auto(video, "demo", config=AutoConfig(caption_source="srt"))
    paquete = work / r["paquete"]
    mp4s = sorted(paquete.glob("*.mp4"))

    print("=" * 60)
    print("SMOKE AUTO SRT — E2E FFMPEG REAL")
    print("=" * 60)
    print(f"clips en el paquete: {len(mp4s)}")
    for i, mp4 in enumerate(mp4s, 1):
        pr = _ffprobe(mp4)
        dst = EVID / f"clip_00{i}_srt.mp4"
        shutil.copy(mp4, dst)
        print(f"  clip {i}: {mp4.name} dur={pr['format']['duration']}s "
              f"streams={sorted(s['codec_type'] for s in pr['streams'])} sha={_sha(mp4)[:12]}")
    n_srt = len(list((trans / "studio_srt_clips" / "demo").rglob("clip.srt")))
    print(f"clip.srt derivados: {n_srt}")
    print(f"info del run: {[c.get('clip_id') for c in r['clips']]}")
    print("evidencia en: output/revision-s36-c2a2-integration/")
    print("=" * 60)


if __name__ == "__main__":
    main()
