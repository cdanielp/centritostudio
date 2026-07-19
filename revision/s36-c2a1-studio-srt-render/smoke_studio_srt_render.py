"""smoke_studio_srt_render.py — E2E sintetico del render SRT de Studio (S36-C2A1, D38).

Cero red, cero GPU, cero Auto. Genera un video sintetico, asocia el SRT fixture con el
BACKEND REAL de C1, resuelve el runtime y ejecuta el worker de render de Studio DOS veces:
  A) estilo clasico SRT limpio;
  B) preset CVE + emojis (offline: ComfyUI apagado -> 0 overlays, fail-open).
Verifica salida, duracion, audio, sidecar, SHA de la fuente y que el SRT original queda
intacto; extrae frames representativos. NO imprime texto de cues ni rutas absolutas.

El MP4/los frames van a output/revision-s36-c2a1/ (gitignored). Nada se sube al PR.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import core  # noqa: E402
import jobs_registry  # noqa: E402
import jobs_render  # noqa: E402
import studio_srt  # noqa: E402
import studio_srt_runtime as rt  # noqa: E402
from gen_fixture import generar_video  # noqa: E402

HERE = Path(__file__).parent
FIXTURES = HERE / "fixtures"
EVID = ROOT / "output" / "revision-s36-c2a1"
DUR_MS = 4000


def _ffprobe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-show_entries", "stream=codec_type", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    return json.loads(out)


def _frame(mp4: Path, t: float, dst: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(t), "-i", str(mp4), "-frames:v", "1", str(dst)],
        check=True, capture_output=True,
    )


def _setup(work: Path) -> rt.SelectedSrtRuntime:
    inp = work / "input"
    trans = work / "transcripts"
    inp.mkdir(parents=True)
    trans.mkdir(parents=True)
    generar_video(inp / "demo.mp4", dur=DUR_MS / 1000)
    (trans / "demo_words.json").write_text(
        (FIXTURES / "demo_words.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    data = (FIXTURES / "demo.srt").read_bytes()
    doc, diags = studio_srt.parse_and_validate(data, source_name="demo.srt", video_duration_ms=DUR_MS)
    studio_srt.store_and_associate(
        doc, diags, video_stem="demo", video_filename="demo.mp4", video_duration_ms=DUR_MS,
        data=data, storage_root=trans / "studio_srt", manifest_dir=trans,
    )
    jobs_render.TRANSCRIPTS = trans
    jobs_render.OUTPUT_DIR = EVID
    return rt.resolve_selected_srt("demo", storage_root=trans / "studio_srt", manifest_dir=trans)


def _render(sel, mp4: Path, label: str, **kw) -> dict:
    jid = jobs_registry.new_job(f"smoke {label}")
    jobs_render.run_render(jid, mp4, None, "demo", "hormozi", None, srt_selection=sel, **kw)
    job = jobs_registry.get_job(jid)
    if job["status"] != "done":
        raise SystemExit(f"[FAIL] render {label}: {job['message']}")
    return job


def _dur(path: Path) -> float:
    return float(_ffprobe(path)["format"]["duration"])


def smoke_p2_identity() -> None:
    """P2: SRT asociado a demo.mov + decoy demo.mp4 de OTRA duracion. El render usa el MOV."""
    import shutil

    work = EVID / "work_p2"
    out_p2 = EVID / "out_p2"
    if work.exists():
        shutil.rmtree(work)
    inp = work / "input"
    trans = work / "transcripts"
    inp.mkdir(parents=True)
    trans.mkdir(parents=True)
    out_p2.mkdir(parents=True, exist_ok=True)
    generar_video(inp / "demo.mov", dur=4.0)  # video ASOCIADO
    generar_video(inp / "demo.mp4", dur=2.0)  # decoy con el mismo stem, OTRA duracion
    (trans / "demo_words.json").write_text(
        (FIXTURES / "demo_words.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    data = (FIXTURES / "demo.srt").read_bytes()
    doc, diags = studio_srt.parse_and_validate(data, source_name="demo.srt", video_duration_ms=DUR_MS)
    studio_srt.store_and_associate(
        doc, diags, video_stem="demo", video_filename="demo.mov", video_duration_ms=DUR_MS,
        data=data, storage_root=trans / "studio_srt", manifest_dir=trans,
    )
    jobs_render.TRANSCRIPTS = trans
    jobs_render.OUTPUT_DIR = out_p2
    sel = rt.resolve_selected_srt("demo", storage_root=trans / "studio_srt", manifest_dir=trans)
    video = rt.resolve_selected_video(sel, input_dir=inp)
    job = _render(sel, video, "P2-mov")
    out = out_p2 / job["result"]["output"]
    dur_out = _dur(out)

    assert sel.video_filename == "demo.mov", "filename autoritativo perdido"
    assert video.name == "demo.mov", f"resolve_selected_video eligio {video.name}, no el MOV"
    assert abs(dur_out - 4.0) < 0.35, f"el output NO corresponde al MOV (dur={dur_out}, decoy=2s)"

    print("-" * 60)
    print("P2 — IDENTIDAD VIDEO<->SRT (OK)")
    print(f"asociado          : demo.mov (4s)  |  decoy: demo.mp4 (2s)")
    print(f"video_filename    : {sel.video_filename}")
    print(f"resolve_video     : {video.name} (nunca el decoy .mp4)")
    print(f"output            : {out.name}  dur={dur_out}s (~4s del MOV, NO 2s del decoy)")
    print("-" * 60)
    shutil.rmtree(work)  # limpia los videos/fixtures generados (no se versionan)


def main() -> None:
    EVID.mkdir(parents=True, exist_ok=True)
    work = EVID / "work"
    if work.exists():
        import shutil

        shutil.rmtree(work)
    sel = _setup(work)
    mp4 = work / "input" / "demo.mp4"
    sha_fuente = hashlib.sha256(sel.managed_path.read_bytes()).hexdigest()

    # A) SRT clasico limpio
    job_a = _render(sel, mp4, "A-clasico")
    out_a = EVID / job_a["result"]["output"]
    sum_a = job_a["result"]["srt"]

    # B) preset CVE + emojis (offline)
    job_b = _render(sel, mp4, "B-preset-emojis", preset="viral_bounce", use_emojis=True)
    out_b = EVID / job_b["result"]["output"]

    # Verificaciones
    probe = _ffprobe(out_a)
    dur = float(probe["format"]["duration"])
    tipos = {s["codec_type"] for s in probe["streams"]}
    sidecar = json.loads((work / "transcripts" / "demo_srt_alignment.json").read_text(encoding="utf-8"))
    sha_despues = hashlib.sha256(sel.managed_path.read_bytes()).hexdigest()

    # Frames: inicio (word_aligned), sustitucion (~2.6s), fallback (~3.5s), final
    for t, nombre in [(0.5, "word_aligned"), (1.5, "word_aligned2"), (2.6, "substitution"), (3.5, "fallback")]:
        _frame(out_a, t, EVID / f"frame_A_{nombre}.png")
    _frame(out_b, 0.5, EVID / "frame_B_preset.png")

    assert "video" in tipos and "audio" in tipos, "falta audio o video"
    assert abs(dur - DUR_MS / 1000) < 0.35, f"duracion fuera de tolerancia: {dur}"
    assert "_srt" in out_a.name and "_srt" in out_b.name, "output no lleva _srt"
    assert sum_a["word_aligned"] + sum_a["cue_fallback"] == sum_a["n_cues"], "summary inconsistente"
    assert sum_a["source_sha256"] == sha_fuente == sha_despues, "SHA de la fuente cambio"
    assert "cues" not in sum_a and "text" not in json.dumps(sum_a), "el summary expone contenido"

    print("=" * 60)
    print("SMOKE S36-C2A1 — RENDER SRT DE STUDIO (OK)")
    print("=" * 60)
    print(f"video fuente      : {mp4.name} ({probe['format']['duration']}s, {sorted(tipos)})")
    print(f"n_cues            : {sum_a['n_cues']}")
    print(f"word_aligned      : {sum_a['word_aligned']}")
    print(f"cue_fallback      : {sum_a['cue_fallback']}")
    print(f"exact_matches     : {sum_a['exact_matches']}")
    print(f"substitution      : {sum_a['substitution_matches']}")
    print(f"rejected_subs      : {sum_a['rejected_substitutions']}")
    print(f"coverage          : {sum_a['coverage']}")
    print(f"n_warnings        : {sum_a['n_warnings']}")
    print(f"source_sha256     : {sum_a['source_sha256'][:12]}... (fuente intacta: {sha_fuente == sha_despues})")
    print(f"sidecar           : {sum_a['alignment_sidecar']} (n_cues={sidecar['summary']['n_cues']})")
    print(f"render A (limpio) : {out_a.name}")
    print(f"render B (preset) : {out_b.name}")
    print(f"job result keys A : {sorted(job_a['result'])}  (sin rutas ni texto)")
    print(f"frames            : output/revision-s36-c2a1/frame_*.png")
    print("=" * 60)

    smoke_p2_identity()


if __name__ == "__main__":
    main()
