r"""smoke_video_pexels.py - Smoke test manual del fetcher de VIDEOS Pexels (NO es parte de pytest).

Requiere PEXELS_API_KEY en el entorno o en .env. Si falta, se niega limpiamente. Busca un termino
inocuo (portrait), descarga UN video MP4, corre ffprobe real y imprime video_id, file_id, autor,
duration, dimensiones, quality, ruta y cuota. NUNCA imprime la API key ni el MP4 se commitea.

Uso (desde la raiz del repo):
  $env:PYTHONIOENCODING="utf-8"
  .\venv\Scripts\python revision\broll-pexels-video-fetcher\smoke_video_pexels.py
  .\venv\Scripts\python revision\broll-pexels-video-fetcher\smoke_video_pexels.py "montanas nevadas"
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

import broll_video_stock as bs  # noqa: E402

# Destino de prueba: reel vertical 1080x1920 (el caso real del pipeline).
DESTINO, TW, TH = "vertical", 1080, 1920


def _ffprobe(path: Path) -> str:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,codec_name,duration", "-of", "default=nw=1", str(path)],  # fmt: skip
        capture_output=True,
        text=True,
    )
    return r.stdout.strip() or r.stderr.strip()


def main() -> int:
    query = sys.argv[1] if len(sys.argv) > 1 else "montanas nevadas"

    if not bs.estado_pexels_video()["habilitado"]:
        print("[smoke] PEXELS_API_KEY ausente: no se puede correr el smoke test.")
        print("  -> Accion: agrega PEXELS_API_KEY a .env (ver .env.example) y reintenta.")
        return 1

    print(f"[smoke] buscando videos para: {query!r} (orientation=portrait)")
    resultado = bs.buscar_video_broll_seguro(query, orientation="portrait", per_page=5)
    if resultado.error is not None:
        print(f"[smoke] busqueda fallo (fail-open): code={resultado.error.code}")
        print(f"  -> {resultado.error.message}")
        return 1
    if not resultado.assets:
        print("[smoke] Pexels no devolvio resultados para ese termino. Prueba otro.")
        return 1
    if resultado.rate_limit is not None:
        rl = resultado.rate_limit
        print(f"[smoke] cuota -> limit={rl.limit} remaining={rl.remaining} reset={rl.reset}")

    asset = resultado.assets[0]
    print(
        f"[smoke] elegido: video_id={asset.asset_id} "
        f"{asset.width}x{asset.height} dur={asset.duration}s"
    )

    try:
        d = bs.descargar_video_asset(asset, destino=DESTINO, target_width=TW, target_height=TH)
    except bs.PexelsVideoError as e:
        print(f"[smoke] descarga fallo: {e}")
        return 1

    print("[smoke] DESCARGA OK")
    print(f"  video_id    : {d.asset_id}")
    print(f"  file_id     : {d.selected_file_id}")
    print(f"  autor       : {d.author}")
    print(f"  duration    : {d.duration}s")
    print(f"  dimensiones : {d.selected_width}x{d.selected_height} (video {d.width}x{d.height})")
    print(f"  quality     : {d.selected_quality}")
    print(f"  ruta        : {d.local_path}")
    print(f"  sidecar     : {d.metadata_path}")
    print(f"  seleccion   : {d.selection_reason}")

    ok = bs.verificar_mp4_ffprobe(d.local_path)
    print(f"[ffprobe] video stream OK: {ok}")
    print(f"[ffprobe] {_ffprobe(d.local_path)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
