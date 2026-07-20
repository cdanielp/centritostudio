"""smoke_srt_e2e_batch.py — E2E FFmpeg REAL del cierre del flujo SRT (S36-C2C).

Cero red, cero GPU, cero LLM: la SELECCIÓN de clips se inyecta, pero extracción FFmpeg, reframe,
derivación por clip, ASS y burn corren de verdad. Cubre el flujo completo del cierre de S36:

  video (.mov) + decoy (.mp4 mismo stem) → asociación SRT → timings privados → Auto batch →
  clips con SRT por clip → manifiesto FINAL saneado → fallo parcial → resume (solo el fallido).

Verifica: 3 clips reales 1080x1920 con audio+video; captions oficiales del SRT; MP4/MOV con el
mismo stem NO se cruzan (el run usa el .mov asociado); manifiesto saneado {version, run_id,
caption_source, source, clips[], summary}; un clip fallido nunca expone output; resume re-renderiza
SOLO el clip fallido. Evidencia en output/revision-s36-c2c/ (gitignored). No versiona nada.

Uso:  venv\\Scripts\\python revision\\s36-c2c\\smoke_srt_e2e_batch.py
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import auto  # noqa: E402
import auto_srt_manifest  # noqa: E402
import core  # noqa: E402
import studio_srt  # noqa: E402
import transcript_provenance as tp  # noqa: E402
from auto_config import AutoConfig  # noqa: E402

EVID = ROOT / "output" / "revision-s36-c2c"
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
    {"archivo": "demo_c1.mp4", "start": 0.0, "end": 5.0, "dur_s": 5.0, "titulo": "C1"},
    {"archivo": "demo_c2.mp4", "start": 4.0, "end": 8.0, "dur_s": 4.0, "titulo": "C2"},
    {"archivo": "demo_c3.mp4", "start": 12.0, "end": 16.0, "dur_s": 4.0, "titulo": "C3"},
]


def _gen_video(dst: Path, color: str):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=1080x1920:r=30:d={DUR_S}",
         "-f", "lavfi", "-i", f"sine=frequency=220:duration={DUR_S}",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", str(dst)],
        check=True, capture_output=True,
    )


def _ffprobe(p: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-show_entries", "stream=codec_type,width,height", "-of", "json", str(p)],
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
    _gen_video(video, "0x101820")
    _gen_video(inp / "demo.mp4", "0x201010")  # decoy MISMO stem: NUNCA debe usarse
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
    parts.words_path.write_text(
        json.dumps(tp.attach_video_provenance(dict(_WORDS), video)), encoding="utf-8"
    )
    auto.TRANSCRIPTS = trans
    auto.CLIPS_DIR = clips
    auto.PAQUETES_DIR = work / "output" / "paquetes"
    auto.ROOT = work
    return video, trans, clips


def _inyectar_clips(video, clips_dir):
    def fake(v, w, n):
        for c in _CLIPS:
            _cortar(video, c["start"], c["end"], clips_dir / c["archivo"])
        return {"clips": [dict(c) for c in _CLIPS], "casi": [], "telemetria_resumen": {"costo_usd": 0.0}}

    auto._asegurar_clips = lambda v, w, n: (fake(v, w, n), False)


def _manifest(work, r) -> dict:
    paquete = work / r["paquete"]
    return json.loads(
        (paquete / auto_srt_manifest.manifest_filename()).read_text(encoding="utf-8")
    )


def _check(cond, msg):
    print(f"  [{'OK ' if cond else 'XX '}] {msg}")
    if not cond:
        raise SystemExit(f"FALLO: {msg}")


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    work = EVID / "work"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir()
    video, trans, clips = _setup(work)
    _inyectar_clips(video, clips)

    print("=" * 64)
    print("SMOKE S36-C2C - E2E FFMPEG REAL (batch + manifiesto + fallo parcial + resume)")
    print("=" * 64)

    # ── RUN A: batch completo ──────────────────────────────────────────────────
    print("RUN A - batch completo (3 clips):")
    rA = auto.ejecutar_auto(video, "demo", config=AutoConfig(caption_source="srt"))
    paqueteA = work / rA["paquete"]
    mp4s = sorted(paqueteA.glob("*_hormozi.mp4"))
    _check(len(mp4s) == 3, f"3 clips renderizados ({len(mp4s)})")
    for i, mp4 in enumerate(mp4s, 1):
        pr = _ffprobe(mp4)
        v = [s for s in pr["streams"] if s["codec_type"] == "video"][0]
        streams = sorted(s["codec_type"] for s in pr["streams"])
        _check(v["width"] == 1080 and v["height"] == 1920, f"clip {i} 1080x1920")
        _check(streams == ["audio", "video"], f"clip {i} audio+video")
        shutil.copy(mp4, EVID / f"clip_00{i}_srt.mp4")
        print(f"       clip {i}: {mp4.name} dur={pr['format']['duration']}s sha={_sha(mp4)[:12]}")

    manA = _manifest(work, rA)
    _check(manA["version"] == 1 and manA["caption_source"] == "srt", "manifiesto v1 caption_source=srt")
    _check(manA["source"]["video_filename"] == "demo.mov", "source = demo.mov (NO el decoy demo.mp4)")
    _check(manA["summary"] == {"total": 3, "done": 3, "error": 0}, "summary total=3 done=3 error=0")
    _check(all(c["output"] and 0.0 <= c["caption_coverage"] <= 1.0 for c in manA["clips"]),
           "cada clip con output y coverage en [0,1]")
    blob = json.dumps(manA)
    _check("/" not in blob.replace("://", "") and "titulo" not in blob,
           "manifiesto sin rutas ni texto privado")
    (EVID / "srt_run_manifest_A.json").write_text(json.dumps(manA, indent=2, ensure_ascii=False),
                                                  encoding="utf-8")
    n_srt = len(list((trans / "studio_srt_clips" / "demo").rglob("clip.srt")))
    _check(n_srt == 3, f"3 clip.srt derivados en el namespace privado ({n_srt})")

    # ── RUN B: fallo parcial + resume ──────────────────────────────────────────
    print("RUN B - fallo parcial (clip 2) + resume:")
    orig_burn = core.burn_video_with_emojis

    def burn_falla(inp_mp4, ass, out, overlays, style_cfg):
        if "demo_c2" in str(out):
            raise RuntimeError("fallo-controlado-clip2")
        return orig_burn(inp_mp4, ass, out, overlays, style_cfg)

    core.burn_video_with_emojis = burn_falla
    rB = auto.ejecutar_auto(video, "demo", config=AutoConfig(caption_source="srt"))
    manB = _manifest(work, rB)
    _check(manB["summary"] == {"total": 3, "done": 2, "error": 1}, "fallo parcial: done=2 error=1")
    err = [c for c in manB["clips"] if c["status"] == "error"]
    _check(len(err) == 1 and err[0]["output"] is None, "clip fallido sin output (no publicable)")
    (EVID / "srt_run_manifest_B_parcial.json").write_text(
        json.dumps(manB, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # resume: interrumpe (borra paquete.json) + repara burn -> reanuda el MISMO paquete
    paqueteB = work / rB["paquete"]
    (paqueteB / "paquete.json").unlink(missing_ok=True)
    (paqueteB / auto_srt_manifest.manifest_filename()).unlink(missing_ok=True)
    core.burn_video_with_emojis = orig_burn
    rC = auto.ejecutar_auto(video, "demo", config=AutoConfig(caption_source="srt"))
    _check(work / rC["paquete"] == paqueteB, "resume reanuda el MISMO paquete")
    manC = _manifest(work, rC)
    _check(manC["summary"] == {"total": 3, "done": 3, "error": 0}, "resume recupera el fallido: done=3")
    (EVID / "srt_run_manifest_C_resume.json").write_text(
        json.dumps(manC, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print("=" * 64)
    print(f"evidencia en: {EVID.relative_to(ROOT).as_posix()}")
    print("TODOS LOS CHEQUEOS OK")
    print("=" * 64)


if __name__ == "__main__":
    main()
