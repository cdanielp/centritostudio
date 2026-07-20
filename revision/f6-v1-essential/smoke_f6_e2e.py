"""smoke_f6_e2e.py — E2E FFmpeg REAL de F6 esencial (spans / puntuacion / center / avoid_faces).

Cero red, cero GPU, cero LLM: el pipeline CVE (aplicar_preset -> build_ass -> burn) corre de
verdad sobre un video 1080x1920 con audio. La trayectoria de avoid_faces se produce con el
SERIALIZADOR REAL del reframe (`reframe._exportar_trayectoria_csv`) alimentado por el productor
real (`reframe_escenas._seg_single`, que elige la cara del detector inyectado) — el mismo formato
y columna `face_y_asignada` que emite el reframe de produccion (NO un CSV fabricado a mano).

Demos (evidencia en output/, gitignored, NO versionada):
  1. demo_phrase_span.mp4              — [strong]/[big] marcan CADA palabra del span.
  2. demo_phrase_span_punctuation.mp4  — [strong]sin costo[/strong]. / [big]gratis[/big], marcan
                                         ambas palabras y conservan punto y coma.
  3. demo_center.mp4                   — [center] centra (an5) sin mostrar la marca.
  4. demo_avoid_faces_top.mp4          — face_y abajo -> caption arriba (an8).
  5. demo_avoid_faces_bottom.mp4       — face_y arriba + base top -> caption abajo (an2).
  6. demo_custom_preset.mp4            — preset de usuario (cve_presets.json).
  + contact_sheet.png + desktop_controls.png + mobile_controls.png + CHECKLIST_VISUAL.md.

Uso:  venv\\Scripts\\python revision\\f6-v1-essential\\smoke_f6_e2e.py
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import core  # noqa: E402
import cve  # noqa: E402
import cve_presets  # noqa: E402
import reframe  # noqa: E402
import reframe_escenas  # noqa: E402
import styles  # noqa: E402

OUT = ROOT / "output" / "revision-f6-v1-essential"
DUR_S = 5
W, H = 1080, 1920
FPS = 30.0


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


def _grupo(palabras, texto=None):
    n = len(palabras)
    paso = DUR_S / max(n, 1)
    words = [
        {"text": p, "start": i * paso, "end": (i + 1) * paso, "line_idx": 0}
        for i, p in enumerate(palabras)
    ]
    return {
        "id": 0,
        "start": 0.0,
        "end": DUR_S,
        "text": texto if texto is not None else " ".join(palabras),
        "words": words,
    }


def _tray_real(stem: str, cy_norm: float) -> Path:
    """CSV con el SERIALIZADOR REAL del reframe, alimentado por el productor real (_seg_single).

    Inyecta la salida del detector existente (dicts {center_x, center_y, bbox, score}) — sin
    otro detector ni segunda pasada — y produce trayectoria_{stem}.csv con face_y_asignada real.
    """
    n = int(DUR_S * FPS)
    cy_px = cy_norm * H
    det = {
        "center_x": W / 2,
        "center_y": cy_px,
        "bbox": [W / 2 - 40, cy_px - 60, 80, 120],
        "score": 0.9,
    }
    dets = {fi: [det] for fi in range(0, n, 3)}
    si = {"f_ini": 0, "f_fin": n, "tipo": "single", "caras": [det]}
    crops, filled, conf, cy, _n = reframe_escenas._seg_single(si, dets, FPS, W, H)
    return reframe._exportar_trayectoria_csv(
        stem, crops, filled, FPS, OUT, sparsa_conf=conf, sparsa_cy=cy, src_h=H
    )


def _render(base: Path, groups, plan, dst: Path, tray=None) -> None:
    g2, plan2, _aviso = cve.aplicar_preset(groups, plan, None, W, H, None, tray)
    ass = dst.with_suffix(".ass")
    core.build_ass(g2, W, H, plan2.style_cfg, ass)
    core.burn_video(base, ass, dst)
    ass.unlink(missing_ok=True)


def _frame(video: Path, t: float, dst: Path) -> None:
    _run(["ffmpeg", "-y", "-ss", str(t), "-i", str(video), "-vframes", "1", str(dst)])


def _probe(p: Path) -> str:
    return subprocess.run(
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


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def _pos_final(groups, plan, tray):
    g2 = cve.resolver_posicion_captions(groups, plan, tray)
    return g2[0].get("caption_pos", "bottom")


def main() -> int:  # noqa: C901
    OUT.mkdir(parents=True, exist_ok=True)
    base = OUT / "_base.mp4"
    _gen_base(base)
    demos: list[tuple[str, Path, str]] = []
    notas: list[str] = []

    # 1. phrase span
    d = OUT / "demo_phrase_span.mp4"
    _render(
        base,
        [_grupo(["esto", "cambio", "todo"], "[strong]esto cambio todo[/strong]")],
        cve.resolve_preset("keyword_punch", "viral"),
        d,
    )
    demos.append(("phrase span: cada palabra destacada", d, ""))

    # 2. phrase span + puntuacion (dos lineas de grupo -> render de la primera)
    d = OUT / "demo_phrase_span_punctuation.mp4"
    _render(
        base,
        [_grupo(["sin", "costo."], "[strong]sin costo[/strong].")],
        cve.resolve_preset("keyword_punch", "viral"),
        d,
    )
    demos.append(("[strong]sin costo[/strong]. : ambas palabras + punto conservado", d, ""))

    # 3. center
    d = OUT / "demo_center.mp4"
    _render(
        base,
        [_grupo(["la", "frase", "principal"], "[center]la frase principal[/center]")],
        cve.resolve_preset("clean_podcast"),
        d,
    )
    demos.append(("[center] centra (an5), marca no visible", d, ""))

    # 4. avoid_faces top: cara abajo -> caption arriba
    tray = _tray_real("avoid_top", 0.85)
    g = [_grupo(["evita", "la", "cara"])]
    plan = cve.resolve_preset("clean_podcast")  # base bottom
    zona = cve.zona_cara_en_rango(tray, 0.0, DUR_S)
    final = _pos_final(g, plan, tray)
    d = OUT / "demo_avoid_faces_top.mp4"
    _render(base, g, plan, d, tray=tray)
    demos.append(("avoid_faces: cara abajo -> caption arriba", d, ""))
    notas.append(f"avoid_faces_top: face_y~0.85 -> zona={zona} base=bottom final={final}")

    # 5. avoid_faces bottom: cara arriba + base top -> caption abajo
    tray = _tray_real("avoid_bottom", 0.15)
    g = [_grupo(["arriba", "la", "cara"])]
    plan = replace(cve.resolve_preset("clean_podcast"), position="top")
    zona = cve.zona_cara_en_rango(tray, 0.0, DUR_S)
    final = _pos_final(g, plan, tray)
    d = OUT / "demo_avoid_faces_bottom.mp4"
    _render(base, g, plan, d, tray=tray)
    demos.append(("avoid_faces: cara arriba + base top -> caption abajo", d, ""))
    notas.append(f"avoid_faces_bottom: face_y~0.15 -> zona={zona} base=top final={final}")

    # 6. custom preset (cve_presets.json)
    cve._PRESETS = cve_presets.construir_presets(
        cve._PRESETS_BUILTIN,
        {"mi_preset": {"base": "keyword_punch", "posicion": "center", "style": {"font_size": 110}}},
        set(styles.STYLES),
    )
    d = OUT / "demo_custom_preset.mp4"
    _render(
        base,
        [_grupo(["preset", "de", "usuario"], "[strong]preset de usuario[/strong]")],
        cve.resolve_preset("mi_preset", "viral"),
        d,
    )
    demos.append(("preset de usuario (cve_presets.json): font 110 + center", d, ""))
    cve._PRESETS = dict(cve._PRESETS_BUILTIN)

    # contact sheet
    frames = []
    for i, (_desc, d, _h) in enumerate(demos):
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

    # checklist enriquecido
    out = [
        "# CHECKLIST VISUAL — F6 esencial (regenerado, PR #23)\n",
        f"Base: {_probe(base)} + audio AAC. Trayectorias por el serializador REAL del "
        "reframe (`_exportar_trayectoria_csv`) alimentado por `_seg_single` (productor real).\n",
        "## Demos\n",
    ]
    for desc, d, _h in demos:
        out.append(f"- [ ] **{d.name}** — {desc} · {_probe(d)} · sha={_sha(d)}")
    out.append("\n## avoid_faces: productor real -> face_y observada -> zona -> posicion\n")
    for nb in notas:
        out.append(f"- {nb} (marca manual center SIEMPRE gana por contrato)")
    out.append("\n## Controles (Edge headless): desktop_controls.png / mobile_controls.png")
    out.append("\n## Pendiente\n- [ ] VEREDICTO VISUAL DE K.")
    (OUT / "CHECKLIST_VISUAL.md").write_text("\n".join(out) + "\n", encoding="utf-8")

    for tmp in [
        base,
        *frames,
        OUT / "trayectoria_avoid_top.csv",
        OUT / "trayectoria_avoid_bottom.csv",
    ]:
        tmp.unlink(missing_ok=True)

    print(f"[smoke-f6] OK -> {OUT}")
    for _desc, d, _h in demos:
        print(f"  {d.name}: {_probe(d)}")
    for nb in notas:
        print(f"  {nb}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
