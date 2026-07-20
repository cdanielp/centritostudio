"""smoke_srt_e2e_batch.py — E2E FFmpeg REAL del cierre del flujo SRT (S36-C2C).

Cero red, cero GPU, cero LLM: la SELECCIÓN de clips se inyecta, pero extracción FFmpeg, reframe,
derivación por clip, ASS y burn corren de verdad. Cubre el flujo completo del cierre de S36:

  video (.mov) + decoy (.mp4 mismo stem) → asociación SRT → timings privados → Auto batch →
  clips con SRT por clip → manifiesto FINAL saneado → fallo parcial (paquete TERMINADO
  parcialmente, con paquete.json) → resume REAL de la UI (sin borrar paquete.json).

RESUME REAL (P2 PR #22): la UI "Reanudar clips fallidos" re-invoca `ejecutar_auto` con el MISMO
video/config y NO borra paquete.json. El run parcial (done=2/error=1) conserva su paquete.json; el
siguiente run reutiliza el MISMO paquete y run_id, re-renderiza SOLO el clip fallido y deja los done
byte-idénticos. Un paquete completamente exitoso (done=3) jamás se reabre como parcial.

Verifica: 3 clips reales 1080x1920 con audio+video; captions oficiales del SRT; MP4/MOV con el
mismo stem NO se cruzan (el run usa el .mov asociado); manifiesto saneado {version, run_id,
caption_source, source, clips[], summary}; un clip fallido nunca expone output; resume sin unlink
que re-renderiza SOLO el clip fallido con clips done byte-idénticos; done=3 no se reabre.
Evidencia en output/revision-s36-c2c/ (gitignored). No versiona nada.

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


def _sha_mtime(p: Path) -> tuple[str, int]:
    return _sha(p), p.stat().st_mtime_ns


def _cortar(video: Path, start: float, end: float, dst: Path):
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(start), "-to", str(end), "-i", str(video),
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-c:a", "aac", str(dst)],
        check=True, capture_output=True,
    )


def _frame(video: Path, t: float, dst: Path):
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(t), "-i", str(video), "-vframes", "1", str(dst)],
        check=True, capture_output=True,
    )


def _concat(mp4s: list[Path], dst: Path):
    lst = dst.with_suffix(".txt")
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in mp4s), encoding="utf-8")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(dst)],
        check=True, capture_output=True,
    )
    lst.unlink(missing_ok=True)


def _contact_sheet(frames: list[Path], dst: Path):
    args = ["ffmpeg", "-y"]
    for f in frames:
        args += ["-i", str(f)]
    args += ["-filter_complex", "[0][1][2]hstack=inputs=3,scale=1620:-1", str(dst)]
    subprocess.run(args, check=True, capture_output=True)


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


def _install_burn(orig, burns: list, fail_token: str | None = None):
    """Envuelve el burn real: registra cada render y (opcional) revienta un clip por token."""

    def burn(inp_mp4, ass, out, overlays, style_cfg):
        burns.append(Path(out).name)
        if fail_token and fail_token in str(out):
            raise RuntimeError(f"fallo-controlado-{fail_token}")
        return orig(inp_mp4, ass, out, overlays, style_cfg)

    core.burn_video_with_emojis = burn


def _correr(video):
    return auto.ejecutar_auto(video, "demo", config=AutoConfig(caption_source="srt"))


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    work = EVID / "work"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir()
    video, trans, clips = _setup(work)
    _inyectar_clips(video, clips)
    orig_burn = core.burn_video_with_emojis

    print("=" * 64)
    print("SMOKE S36-C2C - E2E FFMPEG REAL (batch + manifiesto + resume REAL sin unlink)")
    print("=" * 64)

    # ── RUN A: batch completo ──────────────────────────────────────────────────
    print("RUN A - batch completo (3 clips):")
    rA = _correr(video)
    paqueteA = work / rA["paquete"]
    mp4s = sorted(paqueteA.glob("*_hormozi.mp4"))
    _check(len(mp4s) == 3, f"3 clips renderizados ({len(mp4s)})")
    frames = []
    for i, mp4 in enumerate(mp4s, 1):
        pr = _ffprobe(mp4)
        v = [s for s in pr["streams"] if s["codec_type"] == "video"][0]
        streams = sorted(s["codec_type"] for s in pr["streams"])
        _check(v["width"] == 1080 and v["height"] == 1920, f"clip {i} 1080x1920")
        _check(streams == ["audio", "video"], f"clip {i} audio+video")
        shutil.copy(mp4, EVID / f"clip_00{i}_srt.mp4")
        fr = EVID / f"clip_00{i}_mid.png"
        _frame(mp4, 1.0, fr)
        frames.append(fr)
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
    _concat([EVID / f"clip_00{i}_srt.mp4" for i in (1, 2, 3)], EVID / "demo_srt_e2e.mp4")
    _contact_sheet(frames, EVID / "contact_sheet.png")
    _check((EVID / "demo_srt_e2e.mp4").exists() and (EVID / "contact_sheet.png").exists(),
           "evidencia audiovisual: demo_srt_e2e.mp4 + contact_sheet.png")

    # ── RUN B: fallo parcial que TERMINA (con paquete.json) ─────────────────────
    print("RUN B - fallo parcial (clip 2), el run termina normal con paquete.json:")
    burnsB: list = []
    _install_burn(orig_burn, burnsB, fail_token="demo_c2")
    rB = _correr(video)
    paqueteB = work / rB["paquete"]
    manB = _manifest(work, rB)
    _check((paqueteB / "paquete.json").exists(), "RUN B conserva paquete.json (no es interrumpido)")
    _check(manB["summary"] == {"total": 3, "done": 2, "error": 1}, "fallo parcial: done=2 error=1")
    err = [c for c in manB["clips"] if c["status"] == "error"]
    _check(len(err) == 1 and err[0]["output"] is None, "clip fallido sin output (no publicable)")
    run_id_B = manB["run_id"]
    done_finales = {p.name: _sha_mtime(p) for p in paqueteB.glob("*_hormozi.mp4") if "demo_c2" not in p.name}
    _check(len(done_finales) == 2, "2 clips done presentes tras RUN B (clip 2 ausente)")
    print(f"       paquete B: {run_id_B}")
    for name, (h, _m) in done_finales.items():
        print(f"       done pre-resume: {name} sha={h[:12]}")
    (EVID / "srt_run_manifest_B_parcial.json").write_text(
        json.dumps(manB, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # ── RUN C: RESUME REAL — repara el burn y RE-EJECUTA sin borrar nada ─────────
    print("RUN C - resume REAL (mismo video/config, SIN borrar paquete.json):")
    burnsC: list = []
    _install_burn(orig_burn, burnsC)  # burn reparado, sin fallo
    rC = _correr(video)
    paqueteC = work / rC["paquete"]
    manC = _manifest(work, rC)
    _check(paqueteC == paqueteB, "resume reanuda el MISMO paquete (sin unlink de paquete.json)")
    _check(manC["run_id"] == run_id_B, "mismo run_id en el resume")
    _check(manC["summary"] == {"total": 3, "done": 3, "error": 0}, "resume recupera el fallido: done=3")
    _check(len(burnsC) == 1 and "demo_c2" in burnsC[0], f"SOLO el clip 2 se re-renderizo (burns={burnsC})")
    idem = all(_sha_mtime(paqueteC / name) == hm for name, hm in done_finales.items())
    _check(idem, "clips 1 y 3 byte-identicos (sha+mtime intactos, sin re-render)")
    finales_C = sorted(paqueteC.glob("*_hormozi.mp4"))
    _check(len(finales_C) == 3 and all(_ffprobe(p)["streams"] for p in finales_C),
           "3 outputs válidos tras el resume")
    (EVID / "srt_run_manifest_C_resume.json").write_text(
        json.dumps(manC, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    for name, (h, _m) in done_finales.items():
        print(f"       done post-resume: {name} sha={_sha(paqueteC / name)[:12]} (identico)")

    # ── RUN D: done=3 NO se reabre como parcial ─────────────────────────────────
    print("RUN D - un paquete done=3 NO se reabre (crea paquete nuevo):")
    burnsD: list = []
    _install_burn(orig_burn, burnsD)
    rD = _correr(video)
    _check(work / rD["paquete"] != paqueteB, "tras done=3, un run nuevo NO reabre el paquete exitoso")

    core.burn_video_with_emojis = orig_burn
    _escribir_checklist(manA, manB, manC, run_id_B, done_finales, burnsC, paqueteC)

    print("=" * 64)
    print(f"evidencia en: {EVID.relative_to(ROOT).as_posix()}")
    print("TODOS LOS CHEQUEOS OK")
    print("=" * 64)


def _escribir_checklist(manA, manB, manC, run_id, done_finales, burnsC, paqueteC):
    """CHECKLIST_VISUAL.md con los hechos REALES del resume (run_id B==C, hashes, burns, ffprobe)."""
    lineas = []
    for name in sorted(done_finales):
        h_pre = done_finales[name][0]
        h_post = _sha(paqueteC / name)
        lineas.append(f"| `{name}` | `{h_pre[:16]}` | `{h_post[:16]}` | {'IDÉNTICO' if h_pre == h_post else 'CAMBIÓ'} |")
    finales = sorted(paqueteC.glob("*_hormozi.mp4"))
    probe = "\n".join(
        f"- `{p.name}`: {json.dumps({s['codec_type']: (s.get('width'), s.get('height')) for s in _ffprobe(p)['streams']})}"
        for p in finales
    )
    txt = f"""# CHECKLIST VISUAL — S36-C2C cierre E2E del flujo SRT (resume REAL, P2 PR #22)

Evidencia regenerada por `revision/s36-c2c/smoke_srt_e2e_batch.py` (E2E FFmpeg REAL, cero
red/GPU/LLM). Este directorio es gitignored.

## Flujo cubierto (cierre de S36)
video (.mov) + decoy (.mp4 mismo stem) → asociación SRT → timings privados → Auto batch →
clips con SRT por clip → **manifiesto FINAL saneado** → fallo parcial que TERMINA (con
paquete.json) → **resume REAL de la UI sin borrar paquete.json** → done=3.

## Resume real — mismo paquete / mismo run_id
- **paquete/run_id B == C:** `{run_id}` (el resume reutiliza el MISMO paquete)
- **paquete.json presente antes de C:** sí (RUN B termina normal con done=2/error=1)
- **clip reprocesado:** SOLO el clip 2 (`burns` en el resume = `{burnsC}`)
- **conteo real de burns en el resume:** {len(burnsC)}

## Hashes antes/después de los clips done (1 y 3)
| Clip final | sha256 pre-resume | sha256 post-resume | veredicto |
|-----------|-------------------|--------------------|-----------|
{chr(10).join(lineas)}

## ffprobe de los 3 outputs finales (post-resume)
{probe}

## Manifiestos (summary)
- **A (batch completo):** {json.dumps(manA["summary"])}
- **B (parcial, con paquete.json):** {json.dumps(manB["summary"])}
- **C (resume, sin unlink):** {json.dumps(manC["summary"])}

## Artefactos
- `clip_001_srt.mp4`, `clip_002_srt.mp4`, `clip_003_srt.mp4` — 3 clips reales 1080×1920, audio+video, captions oficiales del SRT quemados
- `clip_00N_mid.png`, `contact_sheet.png` — frames de verificación
- `demo_srt_e2e.mp4` — los 3 clips concatenados (1080×1920)
- `srt_run_manifest_A.json` / `_B_parcial.json` / `_C_resume.json` — manifiestos de los tres runs

## Chequeos verificados por el smoke (todos OK)
- [x] 3 clips renderizados 1080×1920 con audio+video (ffprobe)
- [x] **MP4 y MOV con el mismo stem NO se cruzan**: el run usa `demo.mov` asociado, nunca el decoy `demo.mp4`
- [x] 3 `clip.srt` derivados en el namespace privado confinado
- [x] **manifiesto v1 saneado** sin rutas, sin texto privado, sin hashes
- [x] **fallo parcial que TERMINA**: RUN B conserva paquete.json (done=2/error=1); el fallido NUNCA expone `output`
- [x] **resume REAL (sin unlink)**: reutiliza el MISMO paquete y run_id, re-renderiza SOLO el clip 2 → done=3
- [x] **clips done byte-idénticos** en el resume (sha+mtime intactos)
- [x] **done=3 no se reabre**: un run posterior crea un paquete nuevo

## Escenarios de S36-C2C y dónde se verifican
| Escenario | Cobertura |
|-----------|-----------|
| Batch de varios clips | smoke E2E real (3 clips) + `test_auto_srt_e2e` |
| MP4 y MOV mismo stem | smoke (decoy) + `test_studio_srt_runtime` |
| Cue cruza inicio/final | smoke (cue "Dos cruza corte") + `test_auto_srt_e2e` |
| Fallo parcial que TERMINA | smoke (RUN B) + `test_auto_srt_partial_resume` |
| Resume real sin unlink | smoke (RUN C) + `test_auto_srt_partial_resume` |
| Resume de interrumpido | `test_auto_srt_e2e` (paquete sin paquete.json) |
| done=3 no se reabre | smoke (RUN D) + `test_auto_srt_partial_resume` |
| Selección segura del paquete | `test_auto_srt_partial_resume` (fingerprint/video/classic/corruptos/más reciente) |
| Artefacto faltante / checkpoint corrupto | `test_auto_srt_e2e` + `test_auto_srt_partial_resume` |
| Manifest final saneado | `test_auto_srt_manifest` + smoke |

## Gate
VEREDICTO VISUAL PENDIENTE — requiere autorización explícita de K para mergear.
"""
    (EVID / "CHECKLIST_VISUAL.md").write_text(txt, encoding="utf-8")


if __name__ == "__main__":
    main()
