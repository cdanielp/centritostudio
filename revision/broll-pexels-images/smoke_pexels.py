r"""smoke_pexels.py - Smoke test manual del fetcher de b-roll Pexels (NO forma parte de pytest).

Requiere PEXELS_API_KEY en el entorno o en .env. Si falta, se niega limpiamente.
Busca un termino inocuo, descarga UN solo asset y imprime id, dimensiones, autor y ruta.
NUNCA imprime la API key.

Uso (desde la raiz del repo):
  $env:PYTHONIOENCODING="utf-8"
  .\venv\Scripts\python revision\broll-pexels-images\smoke_pexels.py
  .\venv\Scripts\python revision\broll-pexels-images\smoke_pexels.py "montanas nevadas"
"""

from __future__ import annotations

import sys
from pathlib import Path

# Permitir importar broll_stock desde la raiz del repo aunque se corra desde la subcarpeta.
RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

import broll_stock as bs  # noqa: E402


def main() -> int:
    query = sys.argv[1] if len(sys.argv) > 1 else "cafe"

    estado = bs.estado_pexels()
    if not estado["habilitado"]:
        print("[smoke] PEXELS_API_KEY ausente: no se puede correr el smoke test.")
        print("  -> Accion: agrega PEXELS_API_KEY a .env (ver .env.example) y reintenta.")
        return 1

    print(f"[smoke] buscando imagenes para: {query!r} (orientation=portrait)")
    resultado = bs.buscar_broll_seguro(query, orientation="portrait", per_page=5)
    if resultado.error is not None:
        print(f"[smoke] busqueda fallo (fail-open): code={resultado.error.code}")
        print(f"  -> {resultado.error.message}")
        return 1
    if not resultado.assets:
        print("[smoke] Pexels no devolvio resultados para ese termino. Prueba otro.")
        return 1

    if resultado.rate_limit is not None:
        rl = resultado.rate_limit
        print(f"[smoke] rate limit -> limit={rl.limit} remaining={rl.remaining} reset={rl.reset}")

    asset = resultado.assets[0]
    print(f"[smoke] elegido: id={asset.asset_id} {asset.width}x{asset.height} ({asset.orientation})")
    print(f"[smoke] autor: {asset.author} <{asset.author_url}>")

    try:
        descargado = bs.descargar_asset(asset, destino="vertical", fit="cover")
    except bs.PexelsDescargaError as e:
        print(f"[smoke] descarga fallo: {e}")
        return 1

    print("[smoke] DESCARGA OK")
    print(f"  id          : {descargado.asset_id}")
    print(f"  dimensiones : {descargado.width}x{descargado.height}")
    print(f"  autor       : {descargado.author}")
    print(f"  imagen      : {descargado.local_path}")
    print(f"  sidecar     : {descargado.metadata_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
