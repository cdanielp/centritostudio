r"""gen_evidencia.py - Evidencia real de la integracion Pexels -> b-roll cutaway.

Camino probado (el mismo del pipeline, sin atajos):
  query -> resolver_cutaway_pexels() -> Popup(cutaway=True) -> core_ass.burn_video_with_emojis()

Renderiza un video corto de 5s: 0-1s video original, 1-4s cutaway Pexels (captions ENCIMA),
4-5s video original. Extrae 3 frames (antes / durante / despues), corre ffprobe y muestra solo
datos SEGUROS (asset_id, autor, dimensiones, variante, rutas, duracion). NUNCA imprime la API key.

Requiere PEXELS_API_KEY (en .env o entorno). Sin key se niega limpiamente (no inventa nada).
Usa un video base REAL con una persona si se le pasa/encuentra (el riesgo del cutaway es tapar
la cara y el microfono); si no hay, cae a testsrc sintetico y AVISA que no prueba ese caso.

Uso (desde la raiz del repo):
  $env:PYTHONIOENCODING="utf-8"
  .\venv\Scripts\python revision\broll-pexels-cutaway\gen_evidencia.py [ruta_base.mp4] [query]

Nota: los frames y el MP4 resultantes contienen la foto real de Pexels; NO se commitean
(regla del proyecto: la imagen descargada nunca entra al repo). Solo README.md y este script.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import broll_cutaway as bc  # noqa: E402
import broll_stock as bs  # noqa: E402
import core_ass  # noqa: E402
import styles  # noqa: E402

OUT = Path(__file__).resolve().parent
QUERY_DEFAULT = "cafe"  # termino inocuo
T0, T1 = 1.0, 4.0  # ventana del cutaway
DUR = 5.0  # duracion total del extracto
CAPTION_LINEAS = ["B-ROLL PEXELS CUTAWAY", "LOS CAPTIONS QUEDAN ENCIMA"]
# Candidatos de video base real (persona hablando). Se usa el primero que exista.
BASES_REALES = [ROOT / "input" / "reel01.mp4", ROOT / "input" / "reel02.mp4"]


def run(cmd: list[str], cwd: str | None = None) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if r.returncode != 0:
        raise SystemExit(f"[X] fallo: {' '.join(cmd[:5])}...\n{r.stderr[-700:]}")


def preparar_base(dst: Path, arg_base: str | None) -> tuple[int, int, bool]:
    """Devuelve (w, h, es_real). Recorta 5s de un video real si hay; si no, testsrc + aviso."""
    candidatos = [Path(arg_base)] if arg_base else []
    candidatos += BASES_REALES
    real = next((c for c in candidatos if c.exists()), None)
    if real is not None:
        run(["ffmpeg", "-y", "-i", str(real), "-t", f"{DUR}", "-c:v", "libx264",
             "-pix_fmt", "yuv420p", "-c:a", "aac", str(dst)])  # fmt: skip
        w, h = _dims(dst)
        print(f"[base] video REAL: {real.name} ({w}x{h}) - prueba el caso 'tapa la cara/mic'")
        return w, h, True
    w, h = 1080, 1920
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=size={w}x{h}:rate=30:duration={DUR}",
         "-f", "lavfi", "-i", f"sine=frequency=220:duration={DUR}", "-shortest",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(dst)])  # fmt: skip
    print(f"[base] AVISO: sin video real disponible, se uso testsrc {w}x{h}.")
    print("  -> La evidencia NO prueba el caso 'el cutaway tapa la cara/microfono'.")
    return w, h, False


def _dims(video: Path) -> tuple[int, int]:
    r = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0:s=x",
            str(video),
        ],  # fmt: skip
        capture_output=True,
        text=True,  # fmt: skip
    )
    w, h = r.stdout.strip().split("x")
    return int(w), int(h)


def caption_ass(dst: Path, w: int, h: int) -> None:
    """Quema un .ass real de 2 lineas con el pipeline existente (estilo hormozi)."""
    words, t = [], T0 + 0.1
    for li, linea in enumerate(CAPTION_LINEAS):
        for tok in linea.split():
            words.append(
                {"text": tok, "start": round(t, 3), "end": round(t + 0.25, 3), "line_idx": li}
            )
            t += 0.25
    grupo = {"id": 0, "start": T0, "end": T1, "text": " ".join(CAPTION_LINEAS), "words": words}
    core_ass.build_ass([grupo], w, h, styles.get_style("hormozi"), dst)


def extraer_frame(video: Path, t: float, dst: Path) -> None:
    run(["ffmpeg", "-y", "-ss", f"{t}", "-i", str(video), "-frames:v", "1", str(dst)])


def main() -> int:
    arg_base = sys.argv[1] if len(sys.argv) > 1 else None
    query = sys.argv[2] if len(sys.argv) > 2 else QUERY_DEFAULT

    if not bs.estado_pexels()["habilitado"]:
        print("[X] PEXELS_API_KEY ausente: no se puede generar evidencia real.")
        print("  -> Accion: agrega PEXELS_API_KEY a .env (ver .env.example) y reintenta.")
        return 1

    base = OUT / "_base.mp4"
    w, h, es_real = preparar_base(base, arg_base)
    orientation, destino = bc.orientacion_para_video(w, h)
    print(f"[pexels] query={query!r} orientation={orientation} destino={destino}")

    res = bc.resolver_cutaway_pexels(
        query, T0, T1, orientation=orientation, fit="cover", size_pct=1.0
    )
    if res.popup is None:
        print(f"[X] no se pudo resolver el b-roll (code={res.codigo}): {res.mensaje}")
        return 1
    a = res.asset
    print("[pexels] DESCARGA OK")
    print(f"  asset_id    : {a.asset_id}")
    print(f"  autor       : {a.author}")
    print(f"  dimensiones : {a.width}x{a.height}")
    print(f"  variante    : {a.selected_variant}")
    print(f"  imagen      : {a.local_path}")
    print(f"  sidecar     : {a.metadata_path}")

    ass = OUT / "_caption.ass"
    caption_ass(ass, w, h)
    out = OUT / "pexels_cutaway_demo.mp4"
    elapsed = core_ass.burn_video_with_emojis(
        base, ass, out, [], styles.get_style("hormozi"), [res.popup]
    )
    print(f"[render] {out.name} en {elapsed}s")

    for etiqueta, t in (("antes", 0.5), ("durante", 2.5), ("despues", 4.5)):
        extraer_frame(out, t, OUT / f"frame_{etiqueta}.png")
        print(f"[frame] frame_{etiqueta}.png @ {t}s")

    ow, oh = _dims(out)
    print(f"[ffprobe] salida {ow}x{oh} (base {w}x{h}), base_real={es_real}")
    print("[ok] evidencia lista. Frames: antes / durante / despues (NO se commitean).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
