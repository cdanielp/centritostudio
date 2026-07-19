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

from gen_fixture import generar_video  # noqa: E402

import jobs_registry  # noqa: E402
import jobs_render  # noqa: E402
import studio_srt  # noqa: E402
import studio_srt_runtime as rt  # noqa: E402

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
    _write_words_prov(trans / "demo_words.json", inp / "demo.mp4")  # timings ligados a demo.mp4
    # brain sintetico: marca keywords (MUNDO@0.5, FUNCIONA@1.5) para que viral_bounce
    # (keywords="brain", D20) tenga enfasis semantico y NO coincida con hormozi limpio.
    (trans / "demo.brain.json").write_text(
        (FIXTURES / "demo.brain.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    data = (FIXTURES / "demo.srt").read_bytes()
    doc, diags = studio_srt.parse_and_validate(
        data, source_name="demo.srt", video_duration_ms=DUR_MS
    )
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


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_words_prov(dst: Path, video: Path) -> None:
    """Simula run_transcribe: words del fixture + procedencia (`source_video`) del video EXACTO."""
    import transcript_provenance as tp

    words = json.loads((FIXTURES / "demo_words.json").read_text(encoding="utf-8"))
    Path(dst).write_text(json.dumps(tp.attach_video_provenance(words, video)), encoding="utf-8")


def smoke_p2_provenance() -> None:
    """P2: video E identidad de timings. SRT asociado a demo.mov + decoy demo.mp4 (otra dur).
    Words de demo.mp4 -> render RECHAZADO; tras 'transcribir' el MOV -> render usa el MOV."""
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
    data = (FIXTURES / "demo.srt").read_bytes()
    doc, diags = studio_srt.parse_and_validate(
        data, source_name="demo.srt", video_duration_ms=DUR_MS
    )
    studio_srt.store_and_associate(
        doc, diags, video_stem="demo", video_filename="demo.mov", video_duration_ms=DUR_MS,
        data=data, storage_root=trans / "studio_srt", manifest_dir=trans,
    )
    jobs_render.TRANSCRIPTS = trans
    jobs_render.OUTPUT_DIR = out_p2
    sel = rt.resolve_selected_srt("demo", storage_root=trans / "studio_srt", manifest_dir=trans)
    video = rt.resolve_selected_video(sel, input_dir=inp)
    assert sel.video_filename == "demo.mov" and video.name == "demo.mov"

    # C+D: words con procedencia demo.mp4 (video equivocado) -> render RECHAZADO, sin output.
    _write_words_prov(trans / "demo_words.json", inp / "demo.mp4")
    jid = jobs_registry.new_job("P2-reject")
    jobs_render.run_render(jid, video, None, "demo", "hormozi", None, srt_selection=sel)
    rej = jobs_registry.get_job(jid)
    assert rej["status"] == "error", "el render con timings ajenos debio rechazarse"
    assert not list(out_p2.glob("*_srt*.mp4")), "no debe producir output con timings ajenos"
    assert not (trans / "demo_srt_alignment.json").exists(), "no debe escribir sidecar"

    # E: 'transcribir' el MOV exacto -> words con procedencia demo.mov. G: render OK, 4s.
    _write_words_prov(trans / "demo_words.json", inp / "demo.mov")
    saved = json.loads((trans / "demo_words.json").read_text(encoding="utf-8"))
    assert saved["source_video"]["filename"] == "demo.mov"
    job = _render(sel, video, "P2-ok")
    out = out_p2 / job["result"]["output"]
    dur_out = _dur(out)
    assert abs(dur_out - 4.0) < 0.35, f"el output NO corresponde al MOV (dur={dur_out}, decoy=2s)"

    print("-" * 60)
    print("P2 — IDENTIDAD VIDEO<->SRT + PROCEDENCIA DE TIMINGS (OK)")
    print("asociado          : demo.mov (4s)  |  decoy: demo.mp4 (2s)")
    print(f"video_filename    : {sel.video_filename}  |  resolve_video: {video.name}")
    print(f"words de demo.mp4 : render RECHAZADO ({rej['message']})")
    print(f"words de demo.mov : render OK -> {out.name} dur={dur_out}s (~4s del MOV)")
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

    # B) preset CVE viral_bounce + emojis (offline). Con brain sintetico marca keywords -> el
    # ASS/MP4 difiere del hormozi limpio (enfasis por keyword: pop mayor + color de keyword).
    job_b = _render(sel, mp4, "B-preset-emojis", preset="viral_bounce", use_emojis=True)
    out_b = EVID / job_b["result"]["output"]
    ass_a = EVID / "demo_hormozi_srt.ass"
    ass_b = EVID / "demo_viral_bounce_srt.ass"

    # Verificaciones
    probe = _ffprobe(out_a)
    dur = float(probe["format"]["duration"])
    tipos = {s["codec_type"] for s in probe["streams"]}
    sidecar_path = work / "transcripts" / "demo_srt_alignment.json"
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    sha_despues = hashlib.sha256(sel.managed_path.read_bytes()).hexdigest()
    sha_a, sha_b = _sha(out_a), _sha(out_b)

    # Frames A (hormozi limpio) y B (viral_bounce): word_aligned, keyword/bounce, sustitucion,
    # fallback, inicio, mitad, final.
    for t, nombre in [(0.5, "word_aligned"), (2.6, "substitution"), (3.5, "fallback")]:
        _frame(out_a, t, EVID / f"frame_A_{nombre}.png")
    for t, nombre in [
        (0.2, "inicio"),
        (0.7, "bounce_MUNDO"),  # keyword: pop mayor + color de keyword
        (0.5, "word_aligned"),
        (1.7, "bounce_FUNCIONA"),
        (2.6, "substitution"),
        (3.5, "fallback"),
        (3.9, "final"),
    ]:
        _frame(out_b, t, EVID / f"frame_B_{nombre}.png")

    assert "video" in tipos and "audio" in tipos, "falta audio o video"
    assert abs(dur - DUR_MS / 1000) < 0.35, f"duracion fuera de tolerancia: {dur}"
    assert "_srt" in out_a.name and "_srt" in out_b.name, "output no lleva _srt"
    assert sum_a["word_aligned"] + sum_a["cue_fallback"] == sum_a["n_cues"], "summary inconsistente"
    assert sum_a["source_sha256"] == sha_fuente == sha_despues, "SHA de la fuente cambio"
    assert "cues" not in sum_a and "text" not in json.dumps(sum_a), "el summary expone contenido"
    # GUARD anti-duplicacion (FASE 3): los dos renders NO pueden ser el mismo archivo/SHA.
    assert out_a.name == "demo_hormozi_srt.mp4", f"basename A inesperado: {out_a.name}"
    assert out_b.name == "demo_viral_bounce_srt_emojis.mp4", f"basename B inesperado: {out_b.name}"
    assert out_a.name != out_b.name, "los basenames deben diferir"
    assert sha_a != sha_b, "los dos renders son identicos (viral_bounce no difiere de hormozi)"
    assert _sha(ass_a) != _sha(ass_b), "los ASS son identicos (el preset no anima distinto)"
    _pmsg = job_b["result"].get("preset_msg")
    assert _pmsg is None, f"viral_bounce cayo a clasico: {_pmsg}"

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
    print(f"source_sha256     : {sum_a['source_sha256'][:12]}... (intacta: {sha_fuente == sha_despues})")  # noqa: E501
    print(f"sidecar           : {sum_a['alignment_sidecar']} (n_cues={sidecar['summary']['n_cues']})")  # noqa: E501
    print(f"render A (limpio) : {out_a.name}  sha={sha_a[:16]}")
    print(f"render B (preset) : {out_b.name}  sha={sha_b[:16]}")
    print(f"renders distintos : {sha_a != sha_b}  (ASS distintos: {_sha(ass_a) != _sha(ass_b)})")
    print(f"preset_msg B      : {_pmsg}  (None = sin fallback a clasico)")
    print(f"job result keys A : {sorted(job_a['result'])}  (sin rutas ni texto)")
    print("frames            : output/revision-s36-c2a1/frame_*.png")
    print("=" * 60)

    smoke_p2_provenance()


if __name__ == "__main__":
    main()
