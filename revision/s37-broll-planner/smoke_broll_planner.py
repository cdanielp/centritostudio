"""smoke_broll_planner.py — Verificacion manual del planner de b-roll (S37-A).

Uso (desde la raiz del repo):

    venv\\Scripts\\python revision\\s37-broll-planner\\smoke_broll_planner.py

Carga las fixtures SINTETICAS (nada real del usuario), corre el planner, valida los
invariantes duros (hook 3s, cobertura <=35%, maximo un video, cero solapes, queries no
vacias, IDs estables, inputs intactos), escribe el sidecar a un temporal, lo relee, lo
compara consigo mismo en dos corridas y borra el temporal. Solo imprime un resumen ASCII.

Sin red, sin FFmpeg, sin Pexels, sin GPU. Exit 0 = PASS, 1 = FAIL.
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from broll_plan_io import broll_plan_to_dict, load_broll_inputs, write_broll_plan  # noqa: E402
from broll_plan_types import BrollConfig  # noqa: E402
from broll_planner import plan_broll  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CLIP_DURATION_S = 32.0


def _check(cond: bool, label: str, fails: list[str]) -> None:
    if not cond:
        fails.append(label)


def main() -> int:
    groups, brain = load_broll_inputs(
        FIXTURES / "groups_sinteticos.json", FIXTURES / "brain_sintetico.json"
    )
    groups_snapshot = copy.deepcopy(groups)
    brain_snapshot = copy.deepcopy(brain)
    cfg = BrollConfig()

    plan = plan_broll(groups, brain, CLIP_DURATION_S, cfg)
    d = broll_plan_to_dict(plan)
    summary = d["summary"]
    fails: list[str] = []

    _check(d["version"] == 1, "version==1", fails)
    _check(summary["coverage_pct"] <= 0.35 + 1e-9, "coverage<=35%", fails)
    _check(summary["target_coverage_pct"] == 0.27, "target==27%", fails)
    hooks = [z for z in d["protected_zones"] if z["kind"] == "hook"]
    _check(len(hooks) == 1 and hooks[0]["end_s"] == 3.0, "hook==3.0s", fails)
    _check(summary["video_windows"] <= 1, "max 1 video", fails)
    _check(all(w["query"] for w in d["windows"]), "queries no vacias", fails)
    ids = [w["id"] for w in d["windows"]]
    _check(ids == [f"broll-{i:04d}" for i in range(1, len(ids) + 1)], "IDs estables", fails)

    ws = sorted(d["windows"], key=lambda w: w["start_s"])
    overlaps = sum(1 for a, b in zip(ws, ws[1:], strict=False) if a["end_s"] > b["start_s"] + 1e-6)
    _check(overlaps == 0, "cero solapes", fails)
    for w in d["windows"]:
        _check(0.0 <= w["start_s"] < w["end_s"] <= CLIP_DURATION_S + 1e-9, "ventana en clip", fails)

    _check(groups == groups_snapshot and brain == brain_snapshot, "inputs intactos", fails)

    # Determinismo: segunda corrida identica semanticamente.
    d2 = broll_plan_to_dict(plan_broll(groups, brain, CLIP_DURATION_S, cfg))
    deterministic = d == d2
    _check(deterministic, "determinista", fails)

    # Sidecar: escribir a temporal, releer, comparar, borrar.
    sidecar_ok = _roundtrip_sidecar(plan, d)
    _check(sidecar_ok, "sidecar roundtrip", fails)

    print("S37-A BROLL PLANNER SMOKE")
    print(f"signals: {summary['signals_total']}")
    print(f"candidates: {summary['candidates_valid']}")
    print(f"windows: {summary['windows_planned']}")
    print(f"image: {summary['image_windows']}")
    print(f"video: {summary['video_windows']}")
    print(f"coverage: {summary['coverage_pct'] * 100:.1f}%")
    print(f"rejected: {len(d['rejected'])}")
    print(f"overlaps: {overlaps}")
    print(f"deterministic: {'PASS' if deterministic else 'FAIL'}")
    print(f"sidecar: {'PASS' if sidecar_ok else 'FAIL'}")
    print(f"RESULT: {'PASS' if not fails else 'FAIL -> ' + ', '.join(fails)}")
    return 0 if not fails else 1


def _roundtrip_sidecar(plan, expected: dict) -> bool:
    """Escribe el plan a un .json temporal, lo relee y confirma que el temporal se limpia."""
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "sintetico_broll_plan.json"
        out = write_broll_plan(plan, dest)
        reloaded = json.loads(out.read_text(encoding="utf-8"))
        temps = list(Path(tmp).glob("*.tmp"))
        return reloaded == expected and not temps


if __name__ == "__main__":
    raise SystemExit(main())
