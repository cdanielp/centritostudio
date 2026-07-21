"""Smoke H3 — arranque y diagnostico de entorno pre-HyperFrames. Arnes SINTETICO, sin red, sin
GPU, sin datos privados. El entorno se simula con dependencias INYECTADAS (version, ejecutable,
which, rutas de modelos, puerto). NO abre puertos reales, NO abre el navegador y NO toca
`input/0717_corregido.srt`.

Cubre 12 checks:
    1. ready completo.
    2. falta ffmpeg -> degraded, la UI arranca.
    3. falta ffprobe -> degraded, mensaje correcto.
    4. faltan modelos -> solo reframe afectado.
    5. Python incompatible -> blocked.
    6. puerto libre.
    7. puerto ocupado por Centrito -> abre esa instancia, no inicia server.
    8. puerto ocupado por otra app -> mensaje accionable, sin traceback.
    9. navegador solo abre tras health 200.
    10. core sin ffprobe no produce JSONDecodeError (error tipado).
    11. reframe sin modelos da error accionable con rutas relativas.
    12. salida publica sin secretos ni rutas absolutas.

Contrato: BLOCKER = invariante de arranque/diagnostico violado; FAIL = comportamiento inesperado;
PASS = contrato cumplido. Exit != 0 si hay BLOCKERs o FAILs.

Uso:
    .\\venv\\Scripts\\python revision\\pre-hyperframes\\smoke_h3_environment.py
    .\\venv\\Scripts\\python revision\\pre-hyperframes\\smoke_h3_environment.py --self-test
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REAL_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REAL_ROOT))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import model_assets  # noqa: E402
import studio_launcher as sl  # noqa: E402
import system_preflight as sp  # noqa: E402

EVID_DIR = REAL_ROOT / "output" / "revision-pre-hyperframes" / "h3"
SUP = sp.SUPPORTED_PYTHON

results: list[dict] = []


def record(name: str, status: str, detail: str) -> None:
    icon = {"PASS": "[PASS]", "FAIL": "[FAIL]", "BLOCKER": "[BLOCKER]", "SKIP": "[SKIP]"}[status]
    results.append({"name": name, "status": status, "detail": detail})
    print(f"{icon} {name}: {detail}")


def _check(name, cond, ok, bad, *, blocker=False):
    record(name, "PASS", ok) if cond else record(name, "BLOCKER" if blocker else "FAIL", bad)


def _root(tmp: Path, *, yunet=True, blazeface=True) -> Path:
    """Prepara un root determinista: crea o BORRA cada modelo segun el flag (idempotente).

    Se llama varias veces sobre el mismo TemporaryDirectory; sin el borrado explicito, un modelo
    creado por un check anterior contaminaria un check que lo quiere ausente.
    """
    for d in sp.ESSENTIAL_DIRS:
        (tmp / d).mkdir(parents=True, exist_ok=True)
    for asset, presente, contenido in (
        (model_assets.YUNET, yunet, b"onnx"),
        (model_assets.BLAZEFACE_SHORT, blazeface, b"tflite"),
    ):
        p = tmp / asset.rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        if presente:
            p.write_bytes(contenido)
        elif p.exists():
            p.unlink()
    return tmp


def _report(tmp, *, which=lambda n: "x", version=None, executable=None, yunet=True,
            blazeface=True, port=None, port_in_use=None):
    root = _root(tmp, yunet=yunet, blazeface=blazeface)
    venv = root / "venv"
    return sp.check_environment(
        version=version or (SUP[0], SUP[1], 5),
        executable=executable or str(venv / "Scripts" / "python.exe"),
        venv_dir=venv, which=which, import_probe=lambda _m: True, root=root,
        port=port, port_in_use=port_in_use,
    )


# ── 1-5. Estados del preflight ─────────────────────────────────────────────────
def smoke_estados() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _check("1.ready_completo", _report(tmp)["status"] == "ready",
               "todo presente -> ready", "no dio ready con todo presente", blocker=True)

        r2 = _report(tmp, which=lambda n: None if n == "ffmpeg" else "x")
        _check("2.sin_ffmpeg_degraded", r2["status"] == "degraded"
               and r2["capabilities"]["render"]["available"] is False,
               "sin ffmpeg -> degraded (UI arranca)", "sin ffmpeg no degrado bien", blocker=True)

        r3 = _report(tmp, which=lambda n: None if n == "ffprobe" else "x")
        cap3 = r3["capabilities"]["upload_validation"]
        _check("3.sin_ffprobe_mensaje", r3["status"] == "degraded" and cap3["available"] is False
               and "ffprobe" in cap3["message"].lower(),
               "sin ffprobe -> degraded + mensaje", "sin ffprobe sin mensaje correcto")

        r4 = _report(tmp, yunet=False, blazeface=False)
        caps4 = r4["capabilities"]
        solo_reframe = (caps4["reframe"]["available"] is False
                        and caps4["render"]["available"] is True
                        and caps4["auto"]["available"] is True)
        _check("4.sin_modelos_solo_reframe", solo_reframe and r4["status"] == "degraded",
               "sin modelos -> solo reframe afectado", "modelos ausentes afectaron mas que reframe",
               blocker=True)

        r5 = _report(tmp, version=(SUP[0], SUP[1] - 1, 0))
        _check("5.python_incompatible_blocked", r5["status"] == "blocked",
               "Python no soportado -> blocked", "Python no soportado no bloqueo", blocker=True)


# ── 6-9. Puerto y navegador (launcher, inyectado) ──────────────────────────────
def smoke_launcher() -> None:
    ready = (200, {"status": "ready", "service": "Centrito Studio"})
    libre = sl.classify_port("127.0.0.1", 8787, port_in_use=lambda h, p: False,
                             http_get=lambda u: (0, None))
    _check("6.puerto_libre", libre == "free", "puerto libre detectado", "no detecto puerto libre")

    centrito = sl.classify_port("127.0.0.1", 8787, port_in_use=lambda h, p: True,
                                http_get=lambda u: ready)
    _check("7.puerto_centrito", centrito == "centrito",
           "puerto ocupado por Centrito identificado", "no identifico a Centrito", blocker=True)

    otra = sl.classify_port("127.0.0.1", 8787, port_in_use=lambda h, p: True,
                            http_get=lambda u: (200, {"x": 1}))
    _check("8.puerto_otra_app", otra == "other",
           "puerto ocupado por otra app -> 'other'", "confundio otra app con Centrito", blocker=True)

    abiertos: list[str] = []
    abrio = sl.open_browser_when_ready(
        "http://127.0.0.1:8787/", "http://127.0.0.1:8787/api/system/health",
        http_get=lambda u: ready, open_browser=abiertos.append, timeout=1.0,
        sleep=lambda _s: None, clock=lambda: 0.0, out=lambda _m: None,
    )
    _check("9.browser_tras_health", abrio and abiertos == ["http://127.0.0.1:8787/"],
           "navegador abre una vez tras health 200", "navegador no respeto el health", blocker=True)


# ── 10-11. Errores tipados en core/reframe ─────────────────────────────────────
def smoke_errores_tipados() -> None:
    import media_deps

    import core

    orig = media_deps.ffprobe_disponible
    media_deps.ffprobe_disponible = lambda which=None: False
    tipado = jsondecode = False
    try:
        core.get_video_info(Path("x.mp4"))
    except media_deps.FFprobeUnavailable:
        tipado = True
    except ValueError:
        jsondecode = True
    finally:
        media_deps.ffprobe_disponible = orig
    _check("10.core_sin_ffprobe_tipado", tipado and not jsondecode,
           "get_video_info sin ffprobe -> FFprobeUnavailable (sin JSONDecodeError)",
           "se filtro JSONDecodeError o no fue tipado", blocker=True)

    import reframe_detect

    orig_active = reframe_detect.ACTIVE_MODEL_PATH
    with tempfile.TemporaryDirectory() as td:
        reframe_detect.ACTIVE_MODEL_PATH = Path(td) / "no_existe.tflite"
        accionable = False
        try:
            reframe_detect._crear_detector_blazeface()
        except reframe_detect.DetectorUnavailable as exc:
            msg = str(exc)
            accionable = "setup_models.py" in msg and model_assets.YUNET.rel_path in msg
        finally:
            reframe_detect.ACTIVE_MODEL_PATH = orig_active
    _check("11.reframe_sin_modelos_accionable", accionable,
           "reframe sin modelos -> error tipado con setup + rutas relativas",
           "el error de reframe no fue accionable", blocker=True)


# ── 12. Privacidad de la salida ────────────────────────────────────────────────
def smoke_privacidad() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        r = _report(tmp, which=lambda n: None, yunet=False, blazeface=False,
                    executable="C:/Python312/python.exe", version=(SUP[0], SUP[1] - 1, 0))
        blob = json.dumps(r, ensure_ascii=False)
        sin_abs = (str(tmp) not in blob and "C:/Python312" not in blob
                   and "C:\\Python312" not in blob)
        rel_ok = model_assets.YUNET.rel_path in blob
        _check("12.salida_sin_secretos_ni_paths", sin_abs and rel_ok,
               "salida publica con rutas relativas, sin paths absolutos ni secretos",
               "se filtro una ruta absoluta o secreto", blocker=True)


def _run_all() -> None:
    smoke_estados()
    smoke_launcher()
    smoke_errores_tipados()
    smoke_privacidad()


def _summary_and_exit() -> int:
    blockers = [r for r in results if r["status"] == "BLOCKER"]
    fails = [r for r in results if r["status"] == "FAIL"]
    skips = [r for r in results if r["status"] == "SKIP"]
    report = {
        "harness": "h3-environment", "checks": len(results), "blockers": len(blockers),
        "fails": len(fails), "skips": len(skips), "results": results,
    }
    EVID_DIR.mkdir(parents=True, exist_ok=True)
    (EVID_DIR / "smoke_h3_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\n=== RESUMEN H3 ===")
    print(f"checks={len(results)} blockers={len(blockers)} fails={len(fails)} skips={len(skips)}")
    print(f"evidencia (no versionada): {EVID_DIR / 'smoke_h3_report.json'}")
    if blockers or fails:
        print("VEREDICTO: H3 NO LISTO.")
        return 1
    print("VEREDICTO: H3 arranque y diagnostico endurecidos.")
    return 0


def _self_test() -> int:
    """Verifica que el arnes DETECTA un fallo real (no solo que pasa)."""
    checks = []
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        # el gate detecta blocked cuando el Python no es soportado
        r = _report(tmp, version=(SUP[0], SUP[1] - 1, 0))
        checks.append(("detecta_blocked", r["status"] == "blocked"))
        # el gate detecta degraded cuando falta ffmpeg
        r2 = _report(tmp, which=lambda n: None if n == "ffmpeg" else "x")
        checks.append(("detecta_degraded", r2["status"] == "degraded"))
        # el gate detecta que reframe se cae sin modelos pero render NO
        r3 = _report(tmp, yunet=False, blazeface=False)
        checks.append(("modelos_solo_reframe",
                       r3["capabilities"]["reframe"]["available"] is False
                       and r3["capabilities"]["render"]["available"] is True))
    passed = sum(1 for _n, c in checks if c)
    for n, c in checks:
        print(f"{'[OK]' if c else '[X ]'} self-test: {n}")
    ok = passed == len(checks)
    print(f"\n=== SELF-TEST H3: {'VERDE' if ok else 'ROJO'} ({passed}/{len(checks)}) ===")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if "--self-test" in argv:
        return _self_test()
    _run_all()
    return _summary_and_exit()


if __name__ == "__main__":
    raise SystemExit(main())
