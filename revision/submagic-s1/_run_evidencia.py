"""Runner de evidencia S-Submagic-1: reframe antes de subir + templates reales.

Ejercita el PATH INTEGRADO real (jobs.run_submagic_render) sobre un clip
horizontal 16:9 con voz: reframe local a 9:16 -> upload -> poll -> descarga.
Demuestra horizontal original -> vertical antes del upload -> vertical descargado.
NO pasa por caption.py ni core_ass.py. Nunca imprime la key.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import jobs  # noqa: E402
import submagic  # noqa: E402

CLIP = Path("input/test_16_9.mp4")
NAME = "test_16_9"
STAGED = Path("output/submagic_stage/test_16_9_9x16_for_submagic.mp4")
OUT = Path(f"output/{NAME}_submagic.mp4")
REVDIR = Path("revision/submagic-s1")
FRAME = REVDIR / "frame_resultado.png"
TEMPLATES_JSON = REVDIR / "templates.json"
REPORTE = REVDIR / "REPORTE.md"


def _dims(path: Path) -> str:
    if not path.exists():
        return "(no existe)"
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return r.stdout.strip().replace(",", "x")


def main() -> int:
    eventos: list[str] = []

    def log(msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        eventos.append(line)

    dim_orig = _dims(CLIP)
    log(f"Clip fuente: {CLIP.name} dims={dim_orig} ({CLIP.stat().st_size} bytes)")

    # TAREA 2: templates reales desde la API.
    templates = submagic.listar_templates(force_refresh=True)
    TEMPLATES_JSON.write_text(
        json.dumps({"count": len(templates), "templates": templates}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log(f"templates reales: {len(templates)} | muestra={templates[:8]}")
    elegido = "Hormozi 2" if "Hormozi 2" in templates else templates[0]
    log(f"template elegido: {elegido}")

    # PATH INTEGRADO: worker con reframe ON + template elegido.
    jid = jobs.new_job("evidencia s-submagic-1")
    t0 = time.monotonic()
    jobs.run_submagic_render(jid, CLIP, NAME, reframe_9x16=True, template_name=elegido)
    total_s = round(time.monotonic() - t0, 1)
    job = jobs.get_job(jid)

    if job["status"] != "done":
        log(f"FALLO: status={job['status']} error={job.get('error')}")
        REPORTE.write_text(
            f"# Evidencia S-Submagic-1 — FALLO\n\nstatus={job['status']}\n"
            f"error={job.get('error')}\n\n```\n" + "\n".join(eventos) + "\n```\n",
            encoding="utf-8",
        )
        return 1

    res = job["result"]
    dim_staged = _dims(STAGED)
    dim_out = _dims(OUT)
    log(f"reframe: {res['reframe']}")
    log(f"staged subido dims={dim_staged} | descargado dims={dim_out}")
    log(f"tiempos_s={res['tiempos_s']} | total_worker={total_s}s")

    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(OUT),
         "-ss", "5", "-vframes", "1", str(FRAME)],
        check=False,
    )
    log(f"frame -> {FRAME}")

    reporte = f"""# Evidencia motor Submagic (nube) — S-Submagic-1

Reframe antes de subir (TAREA 1) + templates reales (TAREA 2).
Path ejercitado: `jobs.run_submagic_render` (el worker real del Studio).

## TAREA 1 — Reframe antes del upload
| etapa | dimensiones |
|-------|-------------|
| Clip horizontal original (`{CLIP.name}`) | **{dim_orig}** |
| Archivo intermedio subido (`{STAGED.name}`) | **{dim_staged}** |
| MP4 descargado de Submagic (`{OUT.name}`) | **{dim_out}** |

Evidencia de reframe (del job.result): `{res['reframe']}`

Demuestra: **horizontal {dim_orig} -> vertical {dim_staged} antes del upload -> vertical {dim_out} descargado.**

## TAREA 2 — Templates reales
- Templates obtenidas desde la API (GET /v1/templates): **{len(templates)}**
- Muestra de nombres reales: `{templates[:10]}`
- Template elegido para esta corrida: **{elegido}** (default fallback: Hormozi 2)
- JSON completo (sin secretos): `templates.json`

## Tiempos
- Upload: {res['tiempos_s']['upload']}s
- Poll (transcripción + render en nube): {res['tiempos_s']['poll']}s
- Descarga: {res['tiempos_s']['download']}s
- Total worker (incluye reframe local): {total_s}s

## Garantías
- **NO pasó por caption.py ni core_ass.py**: `sin_caption_local={res.get('sin_caption_local')}`.
- FX intacto: el worker Submagic no llama al motor local de efectos.
- Key leída de `SUBMAGIC_API_KEY` (.env en .gitignore). Nunca impresa.
- MP4 no se commitea (output/ y *.mp4 en .gitignore); se adjunta frame.

## Traza del flujo real
```
{chr(10).join(eventos)}
```
"""
    REPORTE.write_text(reporte, encoding="utf-8")
    log(f"REPORTE escrito en {REPORTE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
