"""gen_evidencia.py — Evidencia LOCAL del Modo Automatico v2 (S37-B). Sin red, sin GPU.

Genera en output/revision-s37b/ (NO versionado):
  demo_source.mp4 / demo_auto_v2.mp4 / demo_classic.mp4        (par principal 30 fps)
  demo_source_cfr_2997.mp4 / demo_auto_v2_cfr_2997.mp4         (CFR 30000/1001 real)
  demo_source_vfr.mp4 / demo_auto_v2_vfr.mp4                   (VFR real por concat)
  auditoria/ (plan.json, popups.auto.json, resolved.json, info.json, av.json)

Todo sintetico y distinguible: imagen naranja "B-ROLL IMAGEN", video en movimiento
"B-ROLL VIDEO", fuente con patron animado. Los resolvers son LOCALES (cero Pexels).
El render usa el motor real (build_ass + burn_video_with_emojis) y la verificacion
A/V es la compuerta dura de auto_av. Salida: resumen ASCII; exit 0 = PASS.

Uso (desde la raiz del repo):
    venv\\Scripts\\python revision\\s37-auto-v2-render\\gen_evidencia.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import auto_av  # noqa: E402
import auto_broll  # noqa: E402
import auto_fx  # noqa: E402
import core  # noqa: E402
from auto_config import AutoConfig  # noqa: E402
from auto_v2 import broll_config_de  # noqa: E402
from broll_plan_io import broll_plan_to_dict  # noqa: E402
from broll_planner import plan_broll  # noqa: E402
from core_overlays import Popup  # noqa: E402
from styles import get_style  # noqa: E402

OUT = ROOT / "output" / "revision-s37b"
AUD = OUT / "auditoria"
DUR = 24  # segundos de cada demo


def _ffmpeg(*args) -> None:
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg fallo: {r.stderr[-400:]}")


def _texto_png(path: Path, texto: str, color: str, size=(540, 400)) -> None:
    """PNG distinguible con texto grande (PIL, sin depender de fuentes de ffmpeg)."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", size, color)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arialbd.ttf", 54)
    except OSError:
        font = ImageFont.load_default(size=48)
    box = draw.textbbox((0, 0), texto, font=font)
    xy = ((size[0] - box[2]) // 2, (size[1] - box[3]) // 2)
    draw.text(xy, texto, fill="white", font=font)
    img.save(path)


def _fuentes() -> dict[str, Path]:
    """Genera assets y fuentes sinteticas. Devuelve {etiqueta: ruta_fuente}."""
    OUT.mkdir(parents=True, exist_ok=True)
    AUD.mkdir(exist_ok=True)
    img = OUT / "_broll_imagen.png"
    _texto_png(img, "B-ROLL IMAGEN", "#d2691e")
    overlay = OUT / "_broll_label.png"
    _texto_png(overlay, "B-ROLL VIDEO", "#111111", size=(540, 120))
    vid = OUT / "_broll_video.mp4"
    _ffmpeg("-f", "lavfi", "-i", "testsrc=size=540x960:rate=30", "-i", str(overlay),
            "-filter_complex", "[0:v][1:v]overlay=(W-w)/2:80[v]", "-map", "[v]",
            "-t", "8", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-pix_fmt", "yuv420p", str(vid))

    base = ("-f", "lavfi", "-i", "testsrc2=size=540x960:rate={fps}",
            "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=44100")
    tail = ("-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest")

    def fuente(path: Path, fps: str, dur: int = DUR) -> None:
        args = [a.format(fps=fps) for a in base] + ["-t", str(dur), *tail, str(path)]
        _ffmpeg(*args)

    src_main = OUT / "demo_source.mp4"
    fuente(src_main, "30")
    src_cfr = OUT / "demo_source_cfr_2997.mp4"
    fuente(src_cfr, "30000/1001")
    # VFR REAL: dos mitades de fps distinto unidas con el FILTRO concat (preserva los
    # deltas por frame) + -fps_mode passthrough al mux. Verificado: dos deltas de PTS
    # genuinamente distintos (~1/23.976 y ~1/29.97). NOTA: el concat DEMUXER con
    # -c copy o passthrough fuerza los parametros del primer stream y corrompe la
    # duracion; setpts no altera el muxing: ninguno sirve como VFR real.
    src_vfr = OUT / "demo_source_vfr.mp4"
    mitad = DUR // 2
    _ffmpeg(
        "-f", "lavfi", "-i", f"testsrc2=size=540x960:rate=24000/1001:duration={mitad}",
        "-f", "lavfi", "-i", f"testsrc2=size=540x960:rate=30000/1001:duration={mitad}",
        "-f", "lavfi", "-i", f"sine=frequency=330:sample_rate=44100:duration={DUR}",
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]", "-map", "2:a",
        "-fps_mode", "passthrough", "-c:v", "libx264", "-preset", "ultrafast",
        "-crf", "28", "-pix_fmt", "yuv420p", "-c:a", "aac", str(src_vfr),
    )
    return {"": src_main, "_cfr_2997": src_cfr, "_vfr": src_vfr}


def _grupos_sinteticos() -> tuple[list, dict]:
    """Groups + brain 100% inventados (taller de cafe). kw_ts en 4.25/10.25/15.5/20.0."""
    frases = [
        (0, 0.0, 3.5, "Bienvenidos al taller de cafe artesanal"),
        (1, 3.5, 8.5, "Ahora conectamos la maquina de tostado"),
        (2, 8.5, 13.5, "El aroma inunda toda la cocina entera"),
        (3, 13.5, 18.5, "La taza perfecta requiere granos frescos"),
        (4, 18.5, 24.0, "Disfruta tu bebida favorita cada dia"),
    ]
    groups = []
    for gid, start, end, texto in frases:
        palabras = texto.split()
        paso = (end - start) / len(palabras)
        words = [
            {"text": w, "start": round(start + i * paso, 3),
             "end": round(start + (i + 1) * paso, 3), "line_idx": 0 if i < 3 else 1}
            for i, w in enumerate(palabras)
        ]
        groups.append({"id": gid, "start": start, "end": end, "text": texto, "words": words})
    brain = {"groups": [
        {"g": 1, "kw": 1, "kw_ts": 4.25, "emoji": None},   # "conectamos" -> video
        {"g": 2, "kw": 1, "kw_ts": 10.25, "emoji": None},  # "aroma" -> image
        {"g": 3, "kw": 1, "kw_ts": 15.5, "emoji": None},
        {"g": 4, "kw": 2, "kw_ts": 20.0, "emoji": None},
    ]}
    return groups, brain


def _resolvers_locales():
    img = OUT / "_broll_imagen.png"
    vid = OUT / "_broll_video.mp4"

    def resolve_image(query, t0, t1, w, h):
        asset = SimpleNamespace(provider="local", asset_id="demo-img", author="sintetico",
                                width=540, height=400, local_path=img)
        popup = Popup(png=img, t0=t0, t1=t1, pos="center", size_pct=1.0,
                      behind_text=True, cutaway=True, fit="cover")
        return SimpleNamespace(popup=popup, codigo="ok", mensaje="asset local", asset=asset)

    asset_v = SimpleNamespace(provider="local", asset_id="demo-vid", author="sintetico",
                              width=540, height=960, duration=8, selected_file_id="f1",
                              local_path=vid)

    def search(query, w, h):
        return SimpleNamespace(error=None, assets=(asset_v,))

    return resolve_image, search, (lambda a, w, h: a)


def _render_v2(source: Path, etiqueta: str, groups, brain, *, fx: bool = True) -> dict:
    """Pipeline v2 local sobre una fuente: planner + resolucion + FX + render + A/V.

    fx=False para la fuente VFR: el punch-in (zoompan) re-temporiza a fps fijo y
    desincronizaria una fuente VFR. En el pipeline REAL el input del render siempre
    es CFR (sale del reframe re-encodeado); la limitacion queda documentada en el
    README y la compuerta A/V la vigila.
    """
    config = AutoConfig(mode="v2", fx_enabled=fx)
    vinfo = core.get_video_info(source)
    dur, w, h = float(vinfo["duration"]), vinfo["width"], vinfo["height"]
    plan = plan_broll(groups, brain, dur, broll_config_de(config))
    r_img, r_search, r_down = _resolvers_locales()
    resol = auto_broll.resolver_plan(
        plan, [], [], w, h, resolve_image_fn=r_img,
        search_video_fn=r_search, download_video_fn=r_down,
    )
    brain_sidecar = AUD / f"demo{etiqueta}.brain.json"
    brain_sidecar.write_text(json.dumps(brain, ensure_ascii=False), encoding="utf-8")
    fx_plan = auto_fx.generar_fx_v2(dur, "express", brain_sidecar, enabled=fx)
    popups = sorted(resol.auto_popups, key=lambda p: p.t0)
    clips = sorted(resol.auto_clips, key=lambda c: c.t0)
    arb = auto_fx.arbitrar_fx(fx_plan, auto_fx.intervalos_cutaway(popups, clips))
    fx_final = None if arb.plan.vacio() else arb.plan

    style = get_style("hormozi")
    ass = OUT / f"demo{etiqueta}.ass"
    core.build_ass(core.apply_brain(groups, brain), w, h, style, ass)
    salida = OUT / f"demo_auto_v2{etiqueta}.mp4"
    core.burn_video_with_emojis(source, ass, salida, [], style,
                                popups=popups, fx_plan=fx_final, clips=clips)
    av = auto_av.verificar_av(source, salida)

    plan_dict = broll_plan_to_dict(plan)
    clip_meta = {"duration_s": round(dur, 3), "width": w, "height": h,
                 "fps": round(float(vinfo.get("fps") or 30.0), 4)}
    resolved = auto_broll.construir_resolved(plan_dict, resol, [], [], clip_meta,
                                             config.fingerprint())
    auto_broll.escribir_json_atomico(AUD / f"plan{etiqueta}.json", plan_dict)
    auto_broll.escribir_json_atomico(
        AUD / f"popups.auto{etiqueta}.json", auto_broll.entradas_popups_auto(resol.decisiones)
    )
    auto_broll.escribir_json_atomico(AUD / f"resolved{etiqueta}.json", resolved)
    auto_broll.escribir_json_atomico(AUD / f"av{etiqueta}.json", av)
    info = {
        "salida": salida.name,
        "windows": len(plan.windows),
        "videos": sum(1 for c in clips),
        "images": sum(1 for p in popups),
        "fx_antes": arb.before,
        "fx_despues": arb.after,
        "fx_eliminados": [r["code"] for r in arb.removed],
        "av": av,
        "primer_broll_s": min((w_.start_s for w_ in plan.windows), default=None),
    }
    auto_broll.escribir_json_atomico(AUD / f"info{etiqueta}.json", info)
    return info


def _render_classic(source: Path, groups, brain) -> Path:
    """Comparativa classic: solo captions (sin b-roll, sin FX)."""
    style = get_style("hormozi")
    vinfo = core.get_video_info(source)
    ass = OUT / "demo_classic.ass"
    core.build_ass(core.apply_brain(groups, brain), vinfo["width"], vinfo["height"], style, ass)
    salida = OUT / "demo_classic.mp4"
    core.burn_video(source, ass, salida)
    return salida


def _fps_stream(path: Path) -> str:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-select_streams", "v:0", "-show_entries",
         "stream=r_frame_rate", "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    return json.loads(r.stdout)["streams"][0]["r_frame_rate"]


def _deltas_pts(path: Path) -> set[float]:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-select_streams", "v:0", "-show_packets",
         "-show_entries", "packet=pts_time", "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    pts = sorted(float(p["pts_time"]) for p in json.loads(r.stdout)["packets"]
                 if p.get("pts_time"))
    return {round(b - a, 5) for a, b in zip(pts, pts[1:])}


def main() -> int:
    fallos: list[str] = []
    groups, brain = _grupos_sinteticos()
    fuentes = _fuentes()

    cfr = _fps_stream(fuentes["_cfr_2997"])
    if cfr != "30000/1001":
        fallos.append(f"CFR esperado 30000/1001, real {cfr}")
    deltas = _deltas_pts(fuentes["_vfr"])
    vfr_real = len(deltas) >= 2
    if not vfr_real:
        fallos.append(f"VFR resulto CFR (deltas={sorted(deltas)})")  # registrar, no abortar

    infos = {}
    for etiqueta, fuente in fuentes.items():
        con_fx = etiqueta != "_vfr"  # VFR sin punch-in (zoompan exige CFR; ver docstring)
        infos[etiqueta] = _render_v2(fuente, etiqueta, groups, brain, fx=con_fx)
    _render_classic(fuentes[""], groups, brain)

    for etiqueta, info in infos.items():
        av_i = info["av"]["integrity"]["status"]
        av_s = info["av"]["sync"]["status"]
        if av_i != "pass" or av_s != "pass":
            fallos.append(f"A/V fallo en demo{etiqueta}: {av_i}/{av_s}")
        if info["videos"] > 1:
            fallos.append(f"demo{etiqueta}: mas de un video")
        if info["primer_broll_s"] is not None and info["primer_broll_s"] < 3.0:
            fallos.append(f"demo{etiqueta}: b-roll invade el hook")

    print("S37-B AUTO V2 EVIDENCIA")
    print(f"cfr_2997: {cfr}")
    print(f"vfr_deltas_distintos: {len(deltas)} ({'VFR REAL' if vfr_real else 'NO VFR'})")
    for etiqueta, info in infos.items():
        nombre = f"demo_auto_v2{etiqueta}"
        print(f"{nombre}: windows={info['windows']} img={info['images']} "
              f"vid={info['videos']} fx_out={sum(info['fx_despues'].values())} "
              f"fx_removed={len(info['fx_eliminados'])} "
              f"av={info['av']['integrity']['status']}/{info['av']['sync']['status']}")
    print("classic: demo_classic.mp4 (solo captions, para comparar)")
    print(f"auditoria: {AUD.relative_to(ROOT)}")
    print(f"RESULT: {'PASS' if not fallos else 'FAIL -> ' + '; '.join(fallos)}")
    return 0 if not fallos else 1


if __name__ == "__main__":
    raise SystemExit(main())
