"""Smoke H2 — jobs y recuperacion pre-HyperFrames. Arnes SINTETICO, sin red, sin GPU, sin datos
privados. Todo en TemporaryDirectory; ffprobe se sustituye por un stub en memoria (no invoca
FFmpeg). NO abre, imprime ni versiona `input/video.srt`.

Cubre:
    A. Polling (motor real static/job_polling.js via Node): done / 404 lost / 500 recovery /
       network recovery / timeout / cancel / dedupe. Node ausente -> SKIP (no FAIL).
    B. Resume: MP4 valido conservado / 0-byte reprocesado / truncado reprocesado / checkpoint
       corrupto / paquete parcial (clip sano no reprocesado).
    C. Provenance classic: misma fuente reutiliza / mismo stem distinta fuente no reutiliza.
    D. Package dir: marker valido reanuda / directorio sin marker no reanuda.
    E. Atomicidad: fallo simulado no corrompe el final anterior.

Contrato: BLOCKER = invariante de seguridad/recuperacion violado; FAIL = comportamiento inesperado;
PASS = contrato cumplido; SKIP = dependencia ausente (Node). Exit != 0 si hay BLOCKERs o FAILs.

Uso:
    $env:PYTHONIOENCODING="utf-8"
    .\\venv\\Scripts\\python revision\\pre-hyperframes\\smoke_h2_jobs_resume.py
    .\\venv\\Scripts\\python revision\\pre-hyperframes\\smoke_h2_jobs_resume.py --self-test
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REAL_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REAL_ROOT))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

EVID_DIR = REAL_ROOT / "output" / "revision-pre-hyperframes" / "h2"
HARNESS = REAL_ROOT / "tests" / "job_polling_harness.cjs"
ENGINE = REAL_ROOT / "static" / "job_polling.js"

_VIDEO_OK = {"streams": [{"codec_type": "video", "duration": "3.0"}], "format": {"duration": "3.0"}}
_SIN_VIDEO = {"streams": [{"codec_type": "audio"}], "format": {"duration": "3.0"}}

results: list[dict] = []


def record(name: str, status: str, detail: str) -> None:
    icon = {"PASS": "[PASS]", "FAIL": "[FAIL]", "BLOCKER": "[BLOCKER]", "SKIP": "[SKIP]"}[status]
    results.append({"name": name, "status": status, "detail": detail})
    print(f"{icon} {name}: {detail}")


def _check(name: str, cond: bool, ok_detail: str, bad_detail: str, *, blocker: bool = False) -> None:
    if cond:
        record(name, "PASS", ok_detail)
    else:
        record(name, "BLOCKER" if blocker else "FAIL", bad_detail)


# ── A. Polling (motor real via Node) ──────────────────────────────────────────
def smoke_polling() -> None:
    node = shutil.which("node")
    if node is None:
        record("A.polling", "SKIP", "Node no disponible; el motor se prueba en pytest cuando exista")
        return
    proc = subprocess.run(
        [node, str(HARNESS), str(ENGINE)], capture_output=True, text=True, encoding="utf-8", timeout=60
    )
    if proc.returncode != 0:
        record("A.polling", "BLOCKER", f"harness Node fallo rc={proc.returncode}: {proc.stdout[-300:]}")
        return
    data = json.loads(proc.stdout)
    _check(
        "A.polling",
        data.get("ok") is True and data.get("passed", 0) >= 20,
        f"motor real: {data['passed']}/{data['total']} casos (done/404/500/red/timeout/cancel/dedupe)",
        f"casos fallidos: {[r for r in data.get('results', []) if not r.get('pass')]}",
        blocker=True,
    )


# ── B. Resume ─────────────────────────────────────────────────────────────────
def smoke_resume() -> None:
    import auto
    import media_integrity as mi

    orig_ffprobe = mi._ffprobe
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        valido = d / "ok.mp4"
        valido.write_bytes(b"REALISH-MP4-DATA")
        cero = d / "cero.mp4"
        cero.write_bytes(b"")
        trunc = d / "trunc.mp4"
        trunc.write_bytes(b"trunc")

        mi._ffprobe = lambda _p: _VIDEO_OK
        _check("B.mp4_valido_conservado", mi.video_reanudable(valido) is True,
               "MP4 valido -> reanudable", "MP4 valido rechazado", blocker=True)
        _check("B.mp4_0byte_reprocesado", mi.video_reanudable(cero) is False,
               "0-byte -> re-render", "0-byte aceptado como valido", blocker=True)
        mi._ffprobe = lambda _p: (_ for _ in ()).throw(mi.MediaIntegrityError("truncado"))
        _check("B.mp4_truncado_reprocesado", mi.video_reanudable(trunc) is False,
               "truncado -> re-render", "truncado aceptado", blocker=True)
        mi._ffprobe = lambda _p: _SIN_VIDEO
        _check("B.sin_stream_reprocesado", mi.video_reanudable(valido) is False,
               "sin stream de video -> re-render", "sin stream aceptado")

        # checkpoint corrupto -> se trata como inexistente (no revienta el resume)
        sidecar = d / "c.info.json"
        sidecar.write_text("{corrupto", encoding="utf-8")
        _check("B.checkpoint_corrupto", auto._cargar_checkpoint(sidecar) is None,
               "checkpoint corrupto -> None (no rompe resume)", "checkpoint corrupto no manejado")

        # paquete parcial: un clip sano se conserva, uno invalido se reprocesa (por clip)
        sano = d / "sano_9x16_hormozi.mp4"
        malo = d / "malo_9x16_hormozi.mp4"
        for f in (sano, malo):
            f.write_bytes(b"data")
            f.with_name(f.stem + ".info.json").write_text(
                json.dumps({"archivo": f.name, "status": "done"}), encoding="utf-8"
            )
        orig_vr = auto.video_reanudable
        auto.video_reanudable = lambda p: "sano" in str(p)
        try:
            sano_ok = auto._clip_incompleto({"archivo": sano.name, "status": "done"}, d) is False
            malo_re = auto._clip_incompleto({"archivo": malo.name, "status": "done"}, d) is True
        finally:
            auto.video_reanudable = orig_vr
        _check("B.paquete_parcial_clip_sano_no_reprocesado", sano_ok and malo_re,
               "clip sano conservado, invalido reprocesado (aislado por clip)",
               "un clip invalido contamino a los sanos", blocker=True)
    mi._ffprobe = orig_ffprobe


# ── C. Provenance classic ─────────────────────────────────────────────────────
def smoke_provenance() -> None:
    import auto_classic_provenance as acp

    with tempfile.TemporaryDirectory() as td:
        v = Path(td) / "vid.mp4"
        v.write_bytes(b"abcdef")
        prov = acp.build_provenance(v, lang="es", model="auto")
        _check("C.misma_fuente_reutiliza", acp.matches(prov, v, lang="es", model="auto") is True,
               "misma fuente -> reutiliza", "misma fuente rechazada")
        v.write_bytes(b"abcdef-DISTINTO")  # mismo stem, distinto tamano/mtime
        _check("C.distinta_fuente_no_reutiliza", acp.matches(prov, v, lang="es", model="auto") is False,
               "mismo stem distinta fuente -> no reutiliza", "reutilizo fuente ajena", blocker=True)


# ── D. Package dir (marker) ───────────────────────────────────────────────────
def smoke_package_dir() -> None:
    import auto
    import auto_classic_provenance as acp

    orig = auto.PAQUETES_DIR
    with tempfile.TemporaryDirectory() as td:
        paquetes = Path(td) / "paquetes"
        paquetes.mkdir()
        auto.PAQUETES_DIR = paquetes
        video = Path(td) / "vid.mp4"
        video.write_bytes(b"abcdef")
        try:
            # marker valido -> reanuda
            prev = paquetes / "vid_20260101-0000"
            prev.mkdir()
            (prev / "auto_classic.json").write_text(
                json.dumps({
                    "schema_version": acp.SCHEMA_VERSION, "pipeline_mode": "classic",
                    "video": acp.build_provenance(video, lang="es", model="auto"),
                    "created_at": "x", "run_id": "r",
                }), encoding="utf-8",
            )
            d1, reanudado1 = auto._paquete_dir("vid", video)
            _check("D.marker_valido_reanuda", reanudado1 is True and d1 == prev,
                   "marker classic valido -> reanuda el mismo dir", "no reanudo un marker valido")
            # directorio sin marker -> NO reanuda (crea nuevo)
            shutil.rmtree(prev)
            manual = paquetes / "vid_20260202-0000"
            manual.mkdir()
            d2, reanudado2 = auto._paquete_dir("vid", video)
            _check("D.sin_marker_no_reanuda", reanudado2 is False and d2 != manual,
                   "dir sin marker -> paquete nuevo", "reanudo un dir sin marker", blocker=True)
        finally:
            auto.PAQUETES_DIR = orig


# ── E. Atomicidad ─────────────────────────────────────────────────────────────
def smoke_atomic() -> None:
    import atomic_io

    with tempfile.TemporaryDirectory() as td:
        dst = Path(td) / "estado.json"
        atomic_io.atomic_write_text(dst, "ORIGINAL")
        orig_replace = atomic_io.os.replace
        atomic_io.os.replace = lambda *_a, **_k: (_ for _ in ()).throw(OSError("disk full"))
        fallo_manejado = False
        try:
            atomic_io.atomic_write_text(dst, "NUEVO")
        except OSError:
            fallo_manejado = True
        finally:
            atomic_io.os.replace = orig_replace
        preserva = dst.read_text(encoding="utf-8") == "ORIGINAL"
        sin_tmp = not any(".tmp" in p.name for p in Path(td).iterdir())
        _check("E.fallo_no_corrompe_final", fallo_manejado and preserva and sin_tmp,
               "fallo de publicacion -> final anterior intacto, sin temporales",
               "un fallo corrompio el final o dejo temporales", blocker=True)


def _run_all() -> None:
    smoke_polling()
    smoke_resume()
    smoke_provenance()
    smoke_package_dir()
    smoke_atomic()


def _summary_and_exit() -> int:
    blockers = [r for r in results if r["status"] == "BLOCKER"]
    fails = [r for r in results if r["status"] == "FAIL"]
    skips = [r for r in results if r["status"] == "SKIP"]
    report = {
        "harness": "h2-jobs-resume",
        "checks": len(results),
        "blockers": len(blockers),
        "fails": len(fails),
        "skips": len(skips),
        "results": results,
    }
    EVID_DIR.mkdir(parents=True, exist_ok=True)
    (EVID_DIR / "smoke_h2_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\n=== RESUMEN H2 ===")
    print(f"checks={len(results)} blockers={len(blockers)} fails={len(fails)} skips={len(skips)}")
    print(f"evidencia (no versionada): {EVID_DIR / 'smoke_h2_report.json'}")
    if blockers or fails:
        print("VEREDICTO: H2 NO LISTO.")
        return 1
    print("VEREDICTO: H2 jobs y recuperacion endurecidos (subconjunto verde).")
    return 0


# ── Self-test: verifica que el arnes DETECTA regresiones (no solo que pasa) ────
def _self_test() -> int:
    import auto_classic_provenance as acp
    import media_integrity as mi

    checks = []
    # el gate rechaza un 0-byte aunque ffprobe diga OK
    with tempfile.TemporaryDirectory() as td:
        orig = mi._ffprobe
        mi._ffprobe = lambda _p: _VIDEO_OK
        cero = Path(td) / "z.mp4"
        cero.write_bytes(b"")
        checks.append(("gate_rechaza_0byte", mi.video_reanudable(cero) is False))
        mi._ffprobe = orig
    # provenance distingue distinto tamano
    with tempfile.TemporaryDirectory() as td:
        v = Path(td) / "v.mp4"
        v.write_bytes(b"aaa")
        prov = acp.build_provenance(v, lang="es", model="auto")
        v.write_bytes(b"aaaaaa")
        checks.append(("prov_detecta_cambio", acp.matches(prov, v, lang="es", model="auto") is False))
    passed = sum(1 for _n, c in checks if c)
    for n, c in checks:
        print(f"{'[OK]' if c else '[X ]'} self-test: {n}")
    ok = passed == len(checks)
    print(f"\n=== SELF-TEST H2: {'VERDE' if ok else 'ROJO'} ({passed}/{len(checks)}) ===")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if "--self-test" in argv:
        return _self_test()
    _run_all()
    return _summary_and_exit()


if __name__ == "__main__":
    raise SystemExit(main())
