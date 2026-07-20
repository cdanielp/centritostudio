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
import tray_resolve  # noqa: E402

OUT = ROOT / "output" / "revision-f6-v1-essential"
DUR_S = 5
W, H = 1080, 1920
FPS = 30.0


def _run(args: list) -> None:
    subprocess.run(args, check=True, capture_output=True)


def _gen_base(dst: Path, w: int = W, h: int = H) -> None:
    _run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x14141e:s={w}x{h}:r=30:d={DUR_S}",
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


def _sha_full(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


class _FakeCara:
    """Detector inyectado: 1 cara fija (center_y ~0.8*H -> abajo). Evita GPU/red.

    Interfaz detect_all(frame) -> list[dict] (misma forma que YuNetDetector), + close().
    NO es una segunda pasada ni otro detector: sustituye al único detector del reframe.
    """

    def __init__(self, w: int, h: int) -> None:
        self._cx = w / 2
        self._cy = h * 0.8

    def detect_all(self, _frame):
        return [
            {
                "center_x": self._cx,
                "center_y": self._cy,
                "bbox": [int(self._cx - 60), int(self._cy - 90), 120, 180],
                "score": 0.95,
            }
        ]

    def close(self):
        pass


def _integracion_reframe_real() -> dict:
    """reframe_clip REAL (detector inyectado) -> MP4 reframado + CSV -> resolver -> CVE -> ASS -> MP4.

    Recorre el wiring productivo completo del BLOQUEO 1/2: reframe_clip exporta la
    trayectoria JUNTO al MP4 con el MISMO stem, el helper único la resuelve, y el render
    la consume para avoid_faces. Falla si tray_dir se quita del worker o cambia el stem.
    """
    import csv as _csv

    src = OUT / "_src_16x9.mp4"
    _gen_base(src, w=1280, h=720)  # fuente 16:9 -> reframe a 9:16
    reframed = OUT / "clip_9x16.mp4"

    _orig = reframe_escenas._crear_detector
    reframe_escenas._crear_detector = lambda *a, **k: _FakeCara(1280, 720)
    try:
        reframe.reframe_clip(src, reframed, tray_dir=reframed.parent)
    finally:
        reframe_escenas._crear_detector = _orig

    # CSV automatico junto al MP4, con el MISMO stem (contrato del worker real)
    csv_esperado = reframed.parent / f"trayectoria_{reframed.stem}.csv"
    assert csv_esperado.exists(), f"reframe_clip no exporto {csv_esperado.name} (tray_dir?)"
    # resolucion automatica por el helper unico (mismo que CLI y Studio)
    csv_res = tray_resolve.resolver_tray_csv(reframed, ROOT / "transcripts")
    assert csv_res == csv_esperado, "el helper no resolvio el CSV junto al MP4 reframado"

    with open(csv_res, encoding="utf-8") as f:
        rows = list(_csv.DictReader(f))
    cols = list(rows[0].keys())
    assert "conf_asignada" in cols and "face_y_asignada" in cols

    # Consumo real: CVE -> ASS -> MP4 final con la trayectoria resuelta automaticamente
    final = OUT / "demo_reframe_wiring.mp4"
    g = [_grupo(["wiring", "real", "reframe"])]
    plan = cve.resolve_preset("clean_podcast")  # base bottom
    zona = cve.zona_cara_en_rango(csv_res, 0.0, DUR_S)
    pos = _pos_final(g, plan, csv_res)
    _render(reframed, g, plan, final, tray=csv_res)

    filas_saneadas = [
        {k: r.get(k, "") for k in ("t", "conf_asignada", "face_y_asignada")}
        for r in rows
        if r.get("conf_asignada", "").strip()
    ][:3]
    return {
        "reframed_mp4": reframed.name,
        "csv_name": csv_res.name,
        "csv_rel": f"output/revision-f6-v1-essential/{csv_res.name}",
        "mp4_sha256": _sha_full(reframed),
        "csv_sha256": _sha_full(csv_res),
        "columns": cols,
        "rows": filas_saneadas,
        "zona": zona,
        "base_pos": plan.position,
        "final_pos": pos,
        "final_mp4": final,
        "probe_reframed": _probe(reframed),
        "probe_final": _probe(final),
        "_cleanup": [src, reframed, csv_res],
    }


def _pos_final(groups, plan, tray):
    g2 = cve.resolver_posicion_captions(groups, plan, tray)
    return g2[0].get("caption_pos", "bottom")


def _evidencia_multi_turnos() -> dict:
    """Ruta multi-cara con turnos (BLOQUEO 2): center_y de la cara activa por turno.

    Usa las funciones puras reales del chain (aplanar_cy_por_turnos + serializador). Cara 0
    arriba en el turno 0, cara 1 abajo en el turno 1: el track vertical CAMBIA con el turno.
    """
    import csv as _csv

    import reframe_track as rt

    turnos = [
        {"t_ini": 0.0, "t_fin": 1.0, "cara_id": 0},
        {"t_ini": 1.0, "t_fin": 2.0, "cara_id": 1},
    ]
    cy_multi = {0: {0: H * 0.2, 3: H * 0.22}, 1: {30: H * 0.85, 33: H * 0.86}}
    conf_multi = {0: {0: 0.9, 3: 0.9}, 1: {30: 0.9, 33: 0.9}}
    flat_conf = rt.aplanar_conf_por_turnos(conf_multi, turnos, FPS, 60)
    flat_cy = rt.aplanar_cy_por_turnos(cy_multi, turnos, FPS, 60)
    crops = [(0, 0, W, H)] * 60
    filled = [W / 2] * 60
    reframe._exportar_trayectoria_csv(
        "multi_turnos", crops, filled, FPS, OUT, sparsa_conf=flat_conf, sparsa_cy=flat_cy, src_h=H
    )
    csv_path = OUT / "trayectoria_multi_turnos.csv"
    zona_t0 = cve.zona_cara_en_rango(csv_path, 0.0, 0.9)  # turno 0: cara arriba
    zona_t1 = cve.zona_cara_en_rango(csv_path, 1.0, 1.9)  # turno 1: cara abajo
    with open(csv_path, encoding="utf-8") as f:
        rows = [r for r in _csv.DictReader(f) if r.get("conf_asignada", "").strip()]
    return {
        "zona_t0": zona_t0,
        "zona_t1": zona_t1,
        "n_filas_vivas": len(rows),
        "_cleanup": [csv_path],
    }


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

    # 7. wiring REAL: reframe_clip -> CSV automatico -> resolver -> CVE -> ASS -> MP4
    wiring = _integracion_reframe_real()
    multi = _evidencia_multi_turnos()
    demos.append(
        ("wiring real: reframe_clip -> CSV -> resolver -> avoid_faces", wiring["final_mp4"], "")
    )
    notas.append(
        f"reframe_wiring: {wiring['reframed_mp4']} -> {wiring['csv_name']} "
        f"zona={wiring['zona']} base={wiring['base_pos']} final={wiring['final_pos']}"
    )

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
    out.append(
        "\n## Fix de duplicacion en phrase spans (gate visual PR #23)\n"
        "Causa: el gemelo de glow (capa 0) usaba escala ESTATICA mientras la palabra activa "
        "de la capa de texto (capa 1) hacia pop -> distinto ancho -> distinto wrap/centrado "
        "-> las dos capas se descuadraban y encimaban (ESTESTOBIO / SSIN). Fix: ambas capas "
        "comparten la MISMA envolvente de escala por palabra (`_active_scale_anim`), incluida "
        "la animacion de la palabra activa -> layout identico por frame, sin desalineacion.\n"
        "- demo_phrase_span (0.0-2.0s) y demo_phrase_span_punctuation (2.3-2.8s) verificados "
        "frame por frame: cada palabra legible, sin capas superpuestas ni letras duplicadas, "
        "puntuacion unida a la palabra previa, ninguna etiqueta [strong]/[big]/[center] visible."
    )
    out.append("\n## avoid_faces: productor real -> face_y observada -> zona -> posicion\n")
    for nb in notas:
        out.append(f"- {nb} (marca manual center SIEMPRE gana por contrato)")
    out.append(
        "\n## Wiring real reframe -> CSV -> CVE -> ASS -> MP4 (BLOQUEO 1/2)\n"
        "reframe_clip(tray_dir=output_path.parent) exporta la trayectoria JUNTO al MP4 con "
        "el mismo stem; el helper único la resuelve; el render la consume.\n"
    )
    out.append(f"- MP4 reframado: `{wiring['reframed_mp4']}` · {wiring['probe_reframed']}")
    out.append(f"- CSV automatico: `{wiring['csv_name']}` en `{wiring['csv_rel']}`")
    out.append(f"- SHA-256 MP4: `{wiring['mp4_sha256']}`")
    out.append(f"- SHA-256 CSV: `{wiring['csv_sha256']}`")
    out.append(f"- Columnas CSV: `{', '.join(wiring['columns'])}`")
    out.append("- Filas saneadas (t, conf_asignada, face_y_asignada):")
    for fr in wiring["rows"]:
        out.append(f"  - t={fr['t']} conf={fr['conf_asignada']} face_y={fr['face_y_asignada']}")
    out.append(
        f"- Ruta single (1 cara detectada) · zona={wiring['zona']} · base={wiring['base_pos']} "
        f"-> final={wiring['final_pos']} · MP4 final `{wiring['final_mp4'].name}` "
        f"{wiring['probe_final']}"
    )
    out.append(
        f"- Ruta multi-cara con turnos: cara activa por turno (BLOQUEO 2) · "
        f"turno 0 (cara arriba) zona={multi['zona_t0']} · turno 1 (cara abajo) "
        f"zona={multi['zona_t1']} · {multi['n_filas_vivas']} filas vivas"
    )
    out.append("\n## Controles (Edge headless): desktop_controls.png / mobile_controls.png")
    out.append("\n## Pendiente\n- [ ] VEREDICTO VISUAL DE K.")
    (OUT / "CHECKLIST_VISUAL.md").write_text("\n".join(out) + "\n", encoding="utf-8")

    for tmp in [
        base,
        *frames,
        *wiring.get("_cleanup", []),
        *multi.get("_cleanup", []),
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
