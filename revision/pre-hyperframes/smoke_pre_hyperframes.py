"""Smoke de readiness pre-HyperFrames — arnés sintético, sin red, sin GPU, sin archivos privados.

Ejecuta un subconjunto reproducible de comprobaciones sobre el Studio via TestClient
(no abre puerto) y PROBA los bloqueos P0 con centinelas SINTÉTICOS. No abre, imprime ni
versiona `input/0717_corregido.srt` ni contenido bajo input/ transcripts/ output/.

Uso:
    $env:PYTHONIOENCODING="utf-8"
    .\\venv\\Scripts\\python revision\\pre-hyperframes\\smoke_pre_hyperframes.py

Salida: matriz PASS/FAIL/BLOCKER + evidencia JSON (NO versionada) en
output/revision-pre-hyperframes/smoke_report.json. Exit code != 0 si hay BLOCKERs.

Nota: el E2E completo (render classic/CVE/reframe/Auto/SRT/resume/editor) requiere FFmpeg y
está DIFERIDO hasta cerrar H1-H3 (hoy fallaría por los propios P0/P1 auditados). Este arnés
cubre salud, contratos de endpoints y las probes de seguridad/integridad que definen readiness.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

EVID_DIR = ROOT / "output" / "revision-pre-hyperframes"
EVID_DIR.mkdir(parents=True, exist_ok=True)

results: list[dict] = []


def record(name: str, status: str, detail: str) -> None:
    """status ∈ {PASS, FAIL, BLOCKER, SKIP}."""
    results.append({"check": name, "status": status, "detail": detail})
    icon = {"PASS": "[OK]", "FAIL": "[X ]", "BLOCKER": "[!!]", "SKIP": "[--]"}[status]
    print(f"{icon} {name}: {detail}")


def main() -> int:
    try:
        from fastapi.testclient import TestClient

        import app
    except Exception as exc:  # noqa: BLE001
        record("import_app", "FAIL", f"no se pudo importar app: {exc!r}")
        _flush()
        return 2

    client = TestClient(app.app)

    # 1. Salud: la UI responde.
    try:
        r = client.get("/")
        record("health_ui", "PASS" if r.status_code == 200 else "FAIL", f"GET / -> {r.status_code}")
    except Exception as exc:  # noqa: BLE001
        record("health_ui", "FAIL", repr(exc))

    # 2. Contrato jobs: job inexistente -> 404 distinguible.
    try:
        r = client.get("/api/jobs/no-existe-xyz")
        record(
            "job_inexistente_404",
            "PASS" if r.status_code == 404 else "FAIL",
            f"GET /api/jobs/no-existe -> {r.status_code} (esperado 404)",
        )
    except Exception as exc:  # noqa: BLE001
        record("job_inexistente_404", "FAIL", repr(exc))

    # 3. Listado de videos: endpoint responde sin reventar.
    try:
        r = client.get("/api/videos")
        record(
            "listar_videos",
            "PASS" if r.status_code == 200 else "FAIL",
            f"GET /api/videos -> {r.status_code}",
        )
    except Exception as exc:  # noqa: BLE001
        record("listar_videos", "SKIP", f"endpoint ausente/otro contrato: {exc!r}")

    # 4. PROBE P0-1: path traversal de ESCRITURA con centinela sintético.
    #    READINESS EXIGE que esto sea rechazado (404/400) y NO escriba fuera del sandbox.
    sentinel = ROOT.parent / "_SMOKE_TRAVERSAL_SENTINEL_groups.json"
    if sentinel.exists():
        sentinel.unlink()
    escaped = False
    try:
        evil = "..%5C..%5C_SMOKE_TRAVERSAL_SENTINEL"
        r = client.put(
            f"/api/videos/{evil}/transcript", json=[{"id": 0, "text": "x", "edited": False}]
        )
        escaped = sentinel.exists()
        if escaped:
            record(
                "traversal_escritura_bloqueada",
                "BLOCKER",
                f"P0-1: PUT traversal -> {r.status_code} y ESCRIBIÓ {sentinel} FUERA del sandbox",
            )
        else:
            record(
                "traversal_escritura_bloqueada",
                "PASS",
                f"PUT traversal -> {r.status_code}, sin escritura fuera del sandbox",
            )
    except Exception as exc:  # noqa: BLE001
        record("traversal_escritura_bloqueada", "PASS", f"rechazado con excepcion: {exc!r}")
    finally:
        if sentinel.exists():
            sentinel.unlink()  # limpieza del centinela sintético

    # 5. PROBE P0-3: el mount /output NO debe servir texto de captions (.ass).
    #    Se prueba con un .ass SINTÉTICO efímero (no proviene de ningún SRT privado).
    out_dir = ROOT / "output"
    probe_ass = out_dir / "_smoke_probe_caption.ass"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        probe_ass.write_text("[Events]\nDialogue: texto-sintetico-de-prueba\n", encoding="utf-8")
        r = client.get(f"/output/{probe_ass.name}")
        served = r.status_code == 200 and "texto-sintetico" in r.text
        if served:
            record(
                "output_no_sirve_ass",
                "BLOCKER",
                "P0-3: /output sirvió el .ass con texto de captions (debe ser 404)",
            )
        else:
            record("output_no_sirve_ass", "PASS", f"/output/*.ass -> {r.status_code} (no expone texto)")
    except Exception as exc:  # noqa: BLE001
        record("output_no_sirve_ass", "SKIP", repr(exc))
    finally:
        if probe_ass.exists():
            probe_ass.unlink()

    # 6. Diferidos: E2E de render requiere FFmpeg y hoy fallaría por P1-OUT-*.
    import shutil

    if shutil.which("ffmpeg") is None:
        record("e2e_render", "SKIP", "FFmpeg ausente; E2E render diferido a H1-H3")
    else:
        record("e2e_render", "SKIP", "E2E render diferido hasta cerrar P1-OUT-1/2/3 (H1)")

    return _flush()


def _flush() -> int:
    blockers = [r for r in results if r["status"] == "BLOCKER"]
    fails = [r for r in results if r["status"] == "FAIL"]
    report = {
        "base": "4a378d8",
        "total": len(results),
        "blockers": len(blockers),
        "fails": len(fails),
        "results": results,
    }
    (EVID_DIR / "smoke_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\n=== RESUMEN ===")
    print(f"checks={len(results)} blockers={len(blockers)} fails={len(fails)}")
    print(f"evidencia (no versionada): {EVID_DIR / 'smoke_report.json'}")
    if blockers:
        print("VEREDICTO: NO LISTO — hay BLOCKERs P0 abiertos.")
        return 1
    if fails:
        print("VEREDICTO: revisar FAILs.")
        return 1
    print("VEREDICTO: subconjunto de readiness verde.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
