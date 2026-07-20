"""tray_resolve.py — resolucion unica del CSV de trayectoria del reframe (F6 avoid_faces).

Helper puro y sin dependencias pesadas: el renderer (CLI `caption.py` y worker
`jobs_render.py`) resuelve la trayectoria con la MISMA logica para no divergir. El reframe
productivo escribe `trayectoria_<stem_del_mp4>.csv` junto al MP4 reframado (BLOQUEO 1);
el fallback legacy vive en `transcripts/`. Ausencia -> None (fail-open: el render sigue
sin mover captions). No lee ni valida el contenido: eso es responsabilidad de cve.py.
"""

from __future__ import annotations

from pathlib import Path


def nombre_tray(stem: str) -> str:
    """Nombre canonico del CSV de trayectoria para un stem de video. Puro."""
    return f"trayectoria_{stem}.csv"


def resolver_tray_csv(mp4: Path, transcripts_dir: Path, name: str | None = None) -> Path | None:
    """Ruta del CSV de trayectoria consumible para `mp4`, o None si no existe.

    Orden de candidatos (unico para CLI y Studio):
      1. junto al video que se va a quemar:  mp4.parent / trayectoria_<mp4.stem>.csv
         (lo que produce el worker reframe con tray_dir=output_path.parent).
      2. fallback legacy:  transcripts_dir / trayectoria_<name>.csv
         (name por defecto = mp4.stem).
    Devuelve el primero que exista; None si ninguno (fail-open).
    """
    mp4 = Path(mp4)
    name = name or mp4.stem
    candidatos = [
        mp4.parent / nombre_tray(mp4.stem),
        Path(transcripts_dir) / nombre_tray(name),
    ]
    for c in candidatos:
        if c.exists():
            return c
    return None
