"""Runner de evidencia end-to-end del motor Submagic (S37).

Sube 1 clip real ES <=60s, poll async, descarga el MP4 y escribe REPORTE.md.
NO pasa por caption.py ni core.py: solo usa submagic.py. Nunca imprime la key.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import submagic  # noqa: E402

CLIP = Path("output/clips/mariosoto_clip1_corto.mp4")
OUT = Path("output/mariosoto_clip1_corto_submagic.mp4")
REPORTE = Path("revision/submagic/REPORTE.md")


def main() -> int:
    eventos: list[str] = []

    def log(msg: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        line = f"[{stamp}] {msg}"
        print(line, flush=True)
        eventos.append(line)

    log(f"Clip: {CLIP.name} ({CLIP.stat().st_size} bytes)")
    key_ok = submagic.probar_key()
    log(f"probar_key -> ok={key_ok['ok']} msg={key_ok['message']}")

    t0 = time.monotonic()
    pid, rate_up = submagic.enviar_video(CLIP, title="Centrito Submagic evidencia S37")
    up_s = round(time.monotonic() - t0, 1)
    log(f"upload OK en {up_s}s | project_id parcial={pid[:8]}... | rate={rate_up}")

    def prog(texto: str, pct: int) -> None:
        log(f"poll: {texto}")

    t1 = time.monotonic()
    try:
        url = submagic.esperar_download_url(pid, progress=prog)
    except TimeoutError:
        log("sin downloadUrl tras timeout -> export fallback")
        submagic.exportar(pid)
        url = submagic.esperar_download_url(pid, progress=prog)
    poll_s = round(time.monotonic() - t1, 1)
    log(f"downloadUrl disponible en {poll_s}s")

    t2 = time.monotonic()
    nbytes = submagic.descargar(url, OUT)
    dl_s = round(time.monotonic() - t2, 1)
    log(f"descarga OK {nbytes} bytes en {dl_s}s -> {OUT}")

    reporte = f"""# Evidencia motor Submagic (nube) — S37

## Resultado
- Clip fuente: `{CLIP}` (38.6s, español, con audio)
- MP4 descargado: `{OUT}` ({nbytes} bytes)
- Project id (parcial/redactado): `{pid[:8]}...`
- **NO pasó por caption.py ni core.py**: el flujo solo usó `submagic.py`.

## Tiempos
- Upload: {up_s}s
- Poll (transcripción + render en nube): {poll_s}s
- Descarga: {dl_s}s

## Rate limit (headers, sin secretos)
- Upload: `{rate_up}`

## Traza del flujo real
```
{chr(10).join(eventos)}
```

## Seguridad
- Key leída de `SUBMAGIC_API_KEY` (.env, en .gitignore). Nunca impresa.
- El MP4 no se commitea (output/ y *.mp4 en .gitignore); se adjunta frame.
"""
    REPORTE.write_text(reporte, encoding="utf-8")
    log(f"REPORTE escrito en {REPORTE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
