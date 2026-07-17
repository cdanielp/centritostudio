r"""gen_evidencia.py - Evidencia real del b-roll de CLIP de video Pexels como cutaway (PR B).

Camino probado (el mismo del pipeline, sin atajos):
  query -> resolver_cutaway_video_pexels() -> ClipOverlay -> burn_video_with_emojis(clips=[...])

Renderiza 6s sobre input/reel01.mp4: 0-1s persona original, 1-5s clip Pexels (cover full-frame,
captions ENCIMA), 5-6s persona original. El audio del clip va SILENCIADO; el audio original se
conserva (regla #19). Extrae 6 frames (antes / 4x durante / despues) y corre ffprobe. Verifica DURO
el audio: el comando mapea solo 0:a (sin amix/amerge/N:a) y compara el audio original vs el de
salida (codec/duracion/paquetes). NUNCA imprime la API key.

Requiere PEXELS_API_KEY (en .env o entorno). Sin key se niega limpiamente.
Uso (desde la raiz del repo):
  $env:PYTHONIOENCODING="utf-8"
  .\venv\Scripts\python revision\broll-pexels-video-cutaway\gen_evidencia.py

Nota: el MP4 de 6s, el clip descargado y los frames NO se commitean (contienen material Pexels).
El MP4 se deja en disco (ruta reportada) para que K revise la COSTURA DEL LOOP en el video completo.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import broll_video_cutaway as bvc  # noqa: E402
import broll_video_stock as bvs  # noqa: E402
import clip_overlay  # noqa: E402
import core_ass  # noqa: E402
import core_overlays as co  # noqa: E402
import styles  # noqa: E402

OUT = Path(__file__).resolve().parent
QUERY = "snowy mountains vertical video"
T0, T1, DUR = 1.0, 5.0, 6.0
CAPTION_LINEAS = ["B-ROLL DE VIDEO PEXELS", "EL AUDIO ORIGINAL SE CONSERVA"]
BASE_REAL = ROOT / "input" / "reel01.mp4"


def run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"[X] fallo: {' '.join(cmd[:5])}...\n{r.stderr[-700:]}")


def _probe(video: Path, entries: str, stream: str | None = None) -> str:
    cmd = ["ffprobe", "-v", "error"]
    if stream:
        cmd += ["-select_streams", stream]
    cmd += ["-show_entries", entries, "-of", "default=nw=1", str(video)]
    return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()


def _dims(video: Path) -> tuple[int, int]:
    out = _probe(video, "stream=width,height", "v:0").splitlines()
    w = int([x for x in out if x.startswith("width=")][0].split("=")[1])
    h = int([x for x in out if x.startswith("height=")][0].split("=")[1])
    return w, h


def preparar_base(dst: Path) -> tuple[int, int, bool]:
    if BASE_REAL.exists():
        run(["ffmpeg", "-y", "-i", str(BASE_REAL), "-t", f"{DUR}", "-c:v", "libx264",
             "-pix_fmt", "yuv420p", "-c:a", "aac", str(dst)])  # fmt: skip
        w, h = _dims(dst)
        print(f"[base] video REAL: {BASE_REAL.name} recortado a {DUR}s ({w}x{h})")
        return w, h, True
    w, h = 1080, 1920
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=size={w}x{h}:rate=30:duration={DUR}",
         "-f", "lavfi", "-i", f"sine=frequency=220:duration={DUR}", "-shortest",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(dst)])  # fmt: skip
    print(
        f"[base] AVISO: sin input/reel01.mp4, se uso testsrc {w}x{h} (no prueba 'tapa la persona')."
    )
    return w, h, False


def caption_ass(dst: Path, w: int, h: int) -> None:
    words, t = [], T0 + 0.1
    for li, linea in enumerate(CAPTION_LINEAS):
        for tok in linea.split():
            words.append(
                {"text": tok, "start": round(t, 3), "end": round(t + 0.28, 3), "line_idx": li}
            )
            t += 0.28
    grupo = {"start": T0, "end": T1, "text": " ".join(CAPTION_LINEAS), "words": words}
    core_ass.build_ass([grupo], w, h, styles.get_style("hormozi"), dst)


def _audio_sig(video: Path) -> str:
    """Firma del audio: codec + duracion + numero de paquetes (cuenta real)."""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-count_packets",
         "-show_entries", "stream=codec_name,duration,nb_read_packets", "-of", "default=nw=1",
         str(video)],  # fmt: skip
        capture_output=True,
        text=True,
    )
    return r.stdout.strip().replace("\n", " ")


def verificar_audio(base: Path, out: Path, clip: clip_overlay.ClipOverlay, w: int, h: int) -> None:
    """Verificacion DURA (regla #19): el comando mapea SOLO 0:a (sin amix/amerge/N:a) y el audio de
    salida coincide con el original (codec/duracion/paquetes)."""
    cmd = co.construir_comando(
        base, "cap.ass", out, [], 216, int(h * 0.6), 0.12, w, h, clips=[clip], fps=30.0
    )
    fc = cmd[cmd.index("-filter_complex") + 1]
    mapea_0a = "0:a" in cmd
    sin_mezcla = "amix" not in fc and "amerge" not in fc and "1:a" not in fc and "[1:a]" not in fc
    print(f"[audio] comando mapea 0:a: {mapea_0a} | sin amix/amerge/N:a: {sin_mezcla}")
    a_base, a_out = _audio_sig(base), _audio_sig(out)
    print(f"[audio] original (base 6s): {a_base}")
    print(f"[audio] salida            : {a_out}")
    print(f"[audio] IDENTICO (codec/dur/paquetes): {a_base == a_out}")
    if not (mapea_0a and sin_mezcla):
        raise SystemExit("[X] FALLA DE AUDIO: el clip contamina el audio original (revisar #19).")


def main() -> int:
    if not bvs.estado_pexels_video()["habilitado"]:
        print("[X] PEXELS_API_KEY ausente: no se puede generar evidencia real.")
        print("  -> Accion: agrega PEXELS_API_KEY a .env (ver .env.example) y reintenta.")
        return 1

    base = OUT / "_base.mp4"
    w, h, es_real = preparar_base(base)
    orientation, destino = bvc.orientacion_para_video(w, h)
    print(f"[pexels] query={QUERY!r} orientation={orientation} destino={destino} target={w}x{h}")

    t_inicio = time.time()
    res = bvc.resolver_cutaway_video_pexels(
        QUERY, T0, T1, orientation=orientation, target_width=w, target_height=h,
        loop=True, fit="cover", size_pct=1.0,
    )  # fmt: skip
    if res.clip is None:
        print(f"[X] no se pudo resolver el b-roll (code={res.codigo}): {res.mensaje}")
        return 1
    a = res.asset
    fresco = a.local_path.stat().st_mtime >= t_inicio
    print("[pexels] " + ("DESCARGA NUEVA" if fresco else "CACHE HIT (video ya estaba en disco)"))
    print(f"  video_id    : {a.asset_id}")
    print(f"  file_id     : {a.selected_file_id}")
    print(f"  autor       : {a.author}")
    print(f"  duration    : {a.duration}s")
    print(f"  dimensiones : {a.selected_width}x{a.selected_height} (video {a.width}x{a.height})")
    print(f"  clip        : {a.local_path}")
    print(f"[ffprobe clip] video stream OK: {bvs.verificar_mp4_ffprobe(a.local_path)}")

    ass = OUT / "_caption.ass"
    caption_ass(ass, w, h)
    out = OUT / "pexels_video_cutaway_demo.mp4"
    elapsed = core_ass.burn_video_with_emojis(
        base, ass, out, [], styles.get_style("hormozi"), clips=[res.clip]
    )
    print(f"[render] {out.name} en {elapsed}s")

    dur_clip = float(a.duration or 0)
    seam = (
        round(T0 + dur_clip, 2) if 0 < dur_clip < (T1 - T0) else 3.0
    )  # cerca de la costura del loop
    momentos = [("antes", 0.5), ("durante_1", 1.5), ("durante_2", 2.5),
                ("durante_3", min(seam, 4.6)), ("durante_4", 4.5), ("despues", 5.5)]  # fmt: skip
    for etiqueta, t in momentos:
        run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{t}",
                "-i",
                str(out),
                "-frames:v",
                "1",
                str(OUT / f"frame_{etiqueta}.png"),
            ]
        )
        print(f"[frame] frame_{etiqueta}.png @ {t}s")

    ow, oh = _dims(out)
    odur = _probe(out, "format=duration")
    tipos = _probe(out, "stream=codec_type")
    print(f"[ffprobe] salida {ow}x{oh} | {odur} | streams: {tipos.replace(chr(10), ',')}")
    verificar_audio(base, out, res.clip, w, h)
    print(f"[ok] evidencia lista. MP4 de 6s (NO commiteado): {out}")
    print("  -> K debe VER EL MP4 COMPLETO para juzgar la costura del loop (los frames no bastan).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
