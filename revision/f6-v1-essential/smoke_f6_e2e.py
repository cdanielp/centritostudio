"""smoke_f6_e2e.py — E2E FFmpeg REAL de F6 esencial (spans / center / avoid_faces / preset).

Cero red, cero GPU, cero LLM: el pipeline CVE (aplicar_preset -> build_ass -> burn) corre de
verdad sobre un video 1080x1920 con audio generado por FFmpeg. Produce la evidencia visual que
K revisa. NADA se versiona (output/ esta en .gitignore).

Demos:
  1. demo_phrase_span.mp4   — [strong]/[big] marcan CADA palabra del span.
  2. demo_center.mp4        — [center] centra el caption (an5) sin mostrar la marca.
  3. demo_avoid_faces.mp4   — trayectoria con cara abajo -> caption sube (an8), respeta safe area.
  4. demo_custom_preset.mp4 — preset de usuario (cve_presets.json) con style_overrides + position.
  5. demo_span_center.mp4   — combinacion phrase span + [center].
  6. demo_avoid_safe.mp4    — combinacion avoid_faces + safe area (cara arriba -> caption abajo).
  + contact_sheet.png (un frame por demo) + CHECKLIST_VISUAL.md.

Uso:  venv\\Scripts\\python revision\\f6-v1-essential\\smoke_f6_e2e.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import core  # noqa: E402
import cve  # noqa: E402
import cve_presets  # noqa: E402
import styles  # noqa: E402

OUT = ROOT / "output" / "revision-f6-v1-essential"
DUR_S = 5
W, H = 1080, 1920


def _run(args: list) -> None:
    subprocess.run(args, check=True, capture_output=True)


def _gen_base(dst: Path) -> None:
    _run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x14141e:s={W}x{H}:r=30:d={DUR_S}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=220:duration={DUR_S}",
            "-c:v",
            "libx264",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(dst),
        ]
    )


def _grupo(palabras, texto=None, start=0.0, dur=DUR_S):
    n = len(palabras)
    paso = dur / max(n, 1)
    words = [
        {"text": p, "start": start + i * paso, "end": start + (i + 1) * paso, "line_idx": 0}
        for i, p in enumerate(palabras)
    ]
    return {
        "id": 0,
        "start": start,
        "end": start + dur,
        "text": texto if texto is not None else " ".join(palabras),
        "words": words,
    }


def _tray_csv(dst: Path, y: float) -> Path:
    filas = "\n".join(f"{t / 10:.4f},540.0,540.0,0.0,0.900,{y:.3f}" for t in range(0, DUR_S * 10))
    dst.write_text(
        "t,cam_center_x,face_x_asignada,distancia,conf_asignada,face_y_asignada\n" + filas,
        encoding="utf-8",
    )
    return dst


def _render(base: Path, groups, plan, dst: Path, tray=None) -> None:
    g2, plan2, _aviso = cve.aplicar_preset(groups, plan, None, W, H, None, tray)
    ass = dst.with_suffix(".ass")
    core.build_ass(g2, W, H, plan2.style_cfg, ass)
    core.burn_video(base, ass, dst)
    ass.unlink(missing_ok=True)


def _frame(video: Path, t: float, dst: Path) -> None:
    _run(["ffmpeg", "-y", "-ss", str(t), "-i", str(video), "-vframes", "1", str(dst)])


def _probe(p: Path) -> str:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,codec_name,r_frame_rate",
            "-of",
            "csv=p=0",
            str(p),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    base = OUT / "_base.mp4"
    _gen_base(base)

    demos: list[tuple[str, Path]] = []

    # 1. phrase span
    g = _grupo(["esto", "cambio", "todo"], texto="[strong]esto cambio todo[/strong]")
    d = OUT / "demo_phrase_span.mp4"
    _render(base, [g], cve.resolve_preset("keyword_punch", "viral"), d)
    demos.append(("phrase span [strong]cada palabra[/strong]", d))

    # 2. center
    g = _grupo(["la", "frase", "principal"], texto="[center]la frase principal[/center]")
    d = OUT / "demo_center.mp4"
    _render(base, [g], cve.resolve_preset("clean_podcast"), d)
    demos.append(("[center] centra el caption (an5)", d))

    # 3. avoid_faces (cara abajo -> caption sube)
    g = _grupo(["evita", "la", "cara"])
    d = OUT / "demo_avoid_faces.mp4"
    _render(
        base,
        [g],
        cve.resolve_preset("clean_podcast"),
        d,
        tray=_tray_csv(OUT / "_t_abajo.csv", 0.85),
    )
    demos.append(("avoid_faces: cara abajo -> caption arriba (an8)", d))

    # 4. custom preset (cve_presets.json)
    reg = cve_presets.construir_presets(
        cve._PRESETS_BUILTIN,
        {"mi_preset": {"base": "keyword_punch", "posicion": "center", "style": {"font_size": 110}}},
        set(styles.STYLES),
    )
    cve._PRESETS = reg
    g = _grupo(["preset", "de", "usuario"], texto="[strong]preset de usuario[/strong]")
    d = OUT / "demo_custom_preset.mp4"
    _render(base, [g], cve.resolve_preset("mi_preset", "viral"), d)
    demos.append(("preset de usuario (cve_presets.json): font 110 + center", d))
    cve._PRESETS = dict(cve._PRESETS_BUILTIN)  # restaura

    # 5. span + center
    g = _grupo(["clave", "total", "ya"], texto="[center][big]clave total ya[/big][/center]")
    d = OUT / "demo_span_center.mp4"
    _render(base, [g], cve.resolve_preset("keyword_punch", "viral"), d)
    demos.append(("span + center: [big] cada palabra + centrado", d))

    # 6. avoid_faces + safe area (cara arriba -> caption abajo, respeta safe bottom)
    g = _grupo(["arriba", "esta", "la", "cara"])
    d = OUT / "demo_avoid_safe.mp4"
    _render(
        base,
        [g],
        cve.resolve_preset("clean_podcast"),
        d,
        tray=_tray_csv(OUT / "_t_arriba.csv", 0.18),
    )
    demos.append(("avoid_faces + safe area: cara arriba -> caption abajo", d))

    # contact sheet
    frames = []
    for i, (_desc, d) in enumerate(demos):
        f = OUT / f"_frame{i}.png"
        _frame(d, DUR_S / 2, f)
        frames.append(f)
    args = ["ffmpeg", "-y"]
    for f in frames:
        args += ["-i", str(f)]
    args += [
        "-filter_complex",
        f"hstack=inputs={len(frames)},scale=1620:-1",
        str(OUT / "contact_sheet.png"),
    ]
    _run(args)

    # checklist
    lineas = ["# CHECKLIST VISUAL — F6 esencial\n", f"Base: {_probe(base)} + audio AAC\n"]
    for desc, d in demos:
        lineas.append(f"- [ ] **{d.name}** — {desc} · {_probe(d)}")
    (OUT / "CHECKLIST_VISUAL.md").write_text("\n".join(lineas) + "\n", encoding="utf-8")

    for tmp in [base, *frames, OUT / "_t_abajo.csv", OUT / "_t_arriba.csv"]:
        tmp.unlink(missing_ok=True)

    print(f"[smoke-f6] OK -> {OUT}")
    for _desc, d in demos:
        print(f"  {d.name}: {_probe(d)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
