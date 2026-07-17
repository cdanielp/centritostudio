"""broll_video_select.py - Seleccion determinista de un video_file MP4 de Pexels (PR A).

Unidad PURA (sin red ni IO): dado el arreglo `video_files` de un Video y un destino
(target_width x target_height), elige un unico `SeleccionVideo` de forma reproducible. Separada
de `broll_video_stock` (que orquesta HTTP/descarga/cache) por la regla anti-spaghetti y porque la
seleccion es un concern autonomo y facil de testear en aislamiento. Depende solo de los tipos de
`broll_video_stock_base`.

Politica V1 (documentada en el motivo del resultado):
  1. Filtra candidatos MP4 directos validos (descarta HLS, .m3u8, file_type != video/mp4,
     dimensiones <= 0 y links vacios).
  2. Prioriza los candidatos cuya orientacion coincide con la del destino.
  3. Entre los que ALCANZAN target_width y target_height: el de MENOR area suficiente
     (evita 4K si una Full HD ya cubre el destino).
  4. Si ninguno alcanza el destino: el de MAYOR area disponible.
  5. Desempate determinista: menor diferencia de aspect ratio, luego file_id.
Nunca elige al azar. Sin candidato valido -> PexelsVideoSinVariante.
"""

from __future__ import annotations

from broll_video_stock_base import (
    MP4_FILE_TYPE,
    PexelsVideoSinVariante,
    SeleccionVideo,
    VideoFileCandidate,
    orientacion_de,
)

DESTINOS_VALIDOS = frozenset({"vertical", "horizontal"})


def _candidato_valido(c: VideoFileCandidate) -> bool:
    """MP4 directo descargable: file_type video/mp4, sin HLS/.m3u8, dims>0 y link no vacio."""
    if (c.quality or "").lower() == "hls":
        return False
    if (c.file_type or "").lower() != MP4_FILE_TYPE:
        return False
    if ".m3u8" in (c.link or "").lower():
        return False
    return bool(c.link) and c.width > 0 and c.height > 0


def _orientacion_preferida(destino: str) -> str:
    """destino del pipeline ('vertical'/'horizontal') -> orientacion de video a priorizar."""
    if destino not in DESTINOS_VALIDOS:
        raise ValueError(f"destino invalido: {destino!r} (usa {sorted(DESTINOS_VALIDOS)})")
    return "portrait" if destino == "vertical" else "landscape"


def _fid_key(c: VideoFileCandidate):
    """Ultimo desempate determinista por file_id (numerico si aplica, si no lexico)."""
    s = str(c.file_id)
    return (0, int(s)) if s.isdigit() else (1, s)


def seleccionar_variante_video(
    video_files,
    *,
    destino: str,
    target_width: int,
    target_height: int,
) -> SeleccionVideo:
    """Elige el video_file MP4 de forma DETERMINISTA (nunca aleatoria). Ver politica en el modulo.

    Sin candidato MP4 directo valido -> PexelsVideoSinVariante. target invalido -> ValueError.
    """
    if target_width <= 0 or target_height <= 0:
        raise ValueError(f"target invalido: {target_width}x{target_height} (deben ser > 0)")
    pref = _orientacion_preferida(destino)
    candidatos = [c for c in (video_files or []) if _candidato_valido(c)]
    if not candidatos:
        raise PexelsVideoSinVariante("ningun video_file MP4 directo valido disponible")

    match = [c for c in candidatos if orientacion_de(c.width, c.height) == pref]
    pool = match or candidatos
    target_ar = target_width / target_height

    def _ar_diff(c: VideoFileCandidate) -> float:
        return abs(c.width / c.height - target_ar)

    suficientes = [c for c in pool if c.width >= target_width and c.height >= target_height]
    if suficientes:
        elegido = min(suficientes, key=lambda c: (c.width * c.height, _ar_diff(c), _fid_key(c)))
        cobertura = "alcanza el destino con la menor area suficiente (evita 4K si Full HD basta)"
    else:
        elegido = max(pool, key=lambda c: (c.width * c.height, -_ar_diff(c)))
        cobertura = "ninguna variante alcanza el destino; se usa la de mayor area disponible"
    orient_txt = "orientacion coincide" if match else "sin match de orientacion, mejor area"
    motivo = (
        f"{elegido.width}x{elegido.height} q={elegido.quality or '?'}: {orient_txt}; {cobertura}"
    )
    return SeleccionVideo(
        file_id=elegido.file_id,
        quality=elegido.quality,
        width=elegido.width,
        height=elegido.height,
        file_type=elegido.file_type,
        url=elegido.link,
        motivo=motivo,
    )
