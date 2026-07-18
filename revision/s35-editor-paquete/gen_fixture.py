"""gen_fixture.py - Fixture LOCAL de evidencia para el Editor de Paquete (S35, PR B).

Crea un paquete sintetico `output/paquetes/_s35_fixture_alpha/` (3 clips) + sus
sidecars en `transcripts/` para poder levantar el Studio y revisar el Editor sin un
paquete real. NO usa red, NO requiere secrets, NO toca paquetes reales.

Cobertura pensada para el checklist visual (CHECKLIST_VISUAL.md):
- clip 1 LISTO con video (markers keyword + popup).
- clip 2 REQUIERE REVISION con video (tramos + Caption QA + keyword/popup, dos
  markers casi simultaneos) y titulo con comillas y `<script>` como TEXTO.
- clip 3 NO PUBLICAR AUN y SIN video (empty state del preview), titulo con acentos/ñ.

Uso (desde la raiz del repo):
  venv/Scripts/python revision/s35-editor-paquete/gen_fixture.py
  venv/Scripts/python revision/s35-editor-paquete/gen_fixture.py --clean

Los .mp4, el paquete.json de runtime y los sidecars quedan ignorados por git
(output/, transcripts/, *.mp4). Solo este script + README + checklist se commitean.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PAQUETES = REPO / "output" / "paquetes"
TRANSCRIPTS = REPO / "transcripts"
PKG_ID = "_s35_fixture_alpha"
PKG_DIR = PAQUETES / PKG_ID

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def _stem(archivo: str) -> str:
    """Stem del sidecar: quita .mp4 y el sufijo de estilo (igual que paquete_editor)."""
    return archivo.replace(".mp4", "").rsplit("_", 1)[0]


# Especificacion declarativa de los 3 clips. `video` marca si se genera el .mp4;
# `brain` y `alertas` van a los sidecars (no al paquete.json).
CLIPS = [
    {
        "archivo": "_s35_fixture_alpha_clip1_9x16_hormozi.mp4",
        "titulo": "Hook con dato: 207 minutos al día",
        "razon": "Arranque fuerte, autocontenido, cierra con cifra.",
        "score": 88,
        "dur_s": 8.0,
        "avisos": [],
        "qa": {"n_alertas": 0, "aplicadas": 0, "pendientes": 0, "con_guion": False},
        "emojis_msg": "sin overlays",
        "tramos_disponibles": True,
        "video": True,
        "brain": [
            {"g": 0, "kw": 1, "emoji": None, "kw_ts": 1.5},
            {"g": 1, "kw": None, "emoji": "✨", "kw_ts": 5.0},
        ],
        "alertas": [],
    },
    {
        "archivo": "_s35_fixture_alpha_clip2_9x16_hormozi.mp4",
        "titulo": 'El "mejor" consejo <script>alert(1)</script> que te dieron',
        "razon": "Comillas y etiqueta <script> a proposito: deben verse como TEXTO.",
        "score": 76,
        "dur_s": 10.0,
        "avisos": [
            {
                "t_ini": 2.0,
                "t_fin": 4.0,
                "tipo": "multi",
                "texto": "revisa 0:02-0:04: 2 personas en cuadro, el sistema solo siguio a una",
            },
            {
                "t_ini": 6.0,
                "t_fin": 9.0,
                "tipo": "none",
                "texto": "revisa 0:06-0:09: sin cara detectada, encuadre centrado fijo",
            },
        ],
        "qa": {
            "n_alertas": 2,
            "aplicadas": 0,
            "pendientes": 2,
            "con_guion": False,
            "alerts_file": "_s35_fixture_alpha_clip2_9x16_caption_alerts.json",
        },
        "emojis_msg": "2 overlay(s)",
        "tramos_disponibles": True,
        "video": True,
        "brain": [
            {"g": 0, "kw": 3, "emoji": None, "kw_ts": 5.05},
            {"g": 1, "kw": None, "emoji": "\U0001f525", "kw_ts": 8.0},
        ],
        "alertas": [
            {
                "timestamp": 3.2,
                "texto_detectado": "confeti",
                "sugerencia": "ComfyUI",
                "confianza": "alta",
                "aplicada": False,
            },
            {
                "timestamp": 5.0,
                "texto_detectado": "mira",
                "sugerencia": None,
                "confianza": "baja",
                "aplicada": False,
            },
        ],
    },
    {
        "archivo": "_s35_fixture_alpha_clip3_9x16_hormozi.mp4",
        "titulo": "Reflexión sobre el diseño y el año que viene",
        "razon": "Clip reutilizado: sin metricas de encuadre, no se puede avalar a ciegas.",
        "score": 81,
        "dur_s": 7.0,
        "avisos": [],
        "qa": None,
        "emojis_msg": "sin overlays",
        "tramos_disponibles": False,
        "video": False,
        "brain": [
            {"g": 0, "kw": 2, "emoji": None, "kw_ts": 2.0},
            {"g": 1, "kw": None, "emoji": "\U0001f4a1", "kw_ts": 4.5},
        ],
        "alertas": [],
    },
]

META = {
    "fecha": "20260717-1200",
    "objetivo": "clips",
    "t_transcripcion_s": 12.3,
    "t_clipper_s": 4.1,
    "t_render_s": 30.5,
    "t_total_s": 47.0,
    "costo_usd": 0.0031,
}


def _crear_mp4(destino: Path, dur: float) -> bool:
    """Clip sintetico 9:16 con patron en movimiento + tono. Sin shell. False si falla."""
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size=1080x1920:rate=30:duration={dur}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=220:duration={dur}",
        "-c:v",
        "libx264",
        "-crf",
        "32",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(destino),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)  # noqa: S603 (lista fija, sin shell)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def _escribir_sidecars(clip: dict) -> None:
    """brain.json (siempre) + caption_alerts.json (si el qa lo referencia)."""
    stem = _stem(clip["archivo"])
    brain = {"provider": "fixture", "latency_s": 0.0, "tokens": 0, "groups": clip["brain"]}
    (TRANSCRIPTS / f"{stem}.brain.json").write_text(
        json.dumps(brain, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    qa = clip.get("qa") or {}
    fname = qa.get("alerts_file")
    if fname and clip.get("alertas"):
        payload = {
            "stem": stem,
            "modo": "alertas",
            "n_alertas": len(clip["alertas"]),
            "aplicadas": 0,
            "pendientes": len(clip["alertas"]),
            "alertas": clip["alertas"],
        }
        (TRANSCRIPTS / fname).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def _clip_paquete(clip: dict) -> dict:
    """Proyecta la spec al esquema real de paquete.json (sin brain/alertas/video)."""
    campos = ["archivo", "titulo", "razon", "score", "dur_s", "avisos", "qa", "emojis_msg"]
    out = {k: clip[k] for k in campos}
    if not clip["tramos_disponibles"]:
        out["tramos_disponibles"] = False
    return out


def generar() -> int:
    """Crea el paquete + sidecars. Devuelve codigo de salida (0 OK)."""
    import auto_report  # noqa: PLC0415 (import diferido: necesita REPO en sys.path)

    if PKG_DIR.exists():
        print(f"[i] La fixture ya existe en {PKG_DIR.relative_to(REPO)} - usa --clean primero.")
        return 1
    PKG_DIR.mkdir(parents=True)
    TRANSCRIPTS.mkdir(exist_ok=True)
    tiene_ffmpeg = shutil.which("ffmpeg") is not None
    if not tiene_ffmpeg:
        print("[!] FFmpeg no encontrado: los clips se listan pero SIN .mp4 (todo empty state).")
    for clip in CLIPS:
        _escribir_sidecars(clip)
        if clip["video"] and tiene_ffmpeg:
            ok = _crear_mp4(PKG_DIR / clip["archivo"], clip["dur_s"])
            print(f"    {'[ok]' if ok else '[x] '} video {clip['archivo']}")
    clips_pkg = [_clip_paquete(c) for c in CLIPS]
    paquete = {"clips": clips_pkg, "meta": META}
    (PKG_DIR / "paquete.json").write_text(
        json.dumps(paquete, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    reporte = auto_report.generar_reporte_md(PKG_ID, clips_pkg, META)
    (PKG_DIR / "REPORTE.md").write_text(reporte, encoding="utf-8")
    print(f"[ok] Fixture creada en {PKG_DIR.relative_to(REPO)} ({len(CLIPS)} clips).")
    print(f"     Sidecars en {TRANSCRIPTS.relative_to(REPO)}/ (brain + caption_alerts).")
    print(f"     Abre el Studio y ve a Paquetes -> Revisar, o usa el hash #revision/{PKG_ID}")
    return 0


def limpiar() -> int:
    """Borra SOLO la fixture (dir del paquete + sus sidecars). Se niega a otras rutas."""
    # Guardarrail: el dir a borrar tiene que ser exactamente el de la fixture.
    if PKG_DIR.resolve().parent != PAQUETES.resolve() or PKG_DIR.name != PKG_ID:
        print("[x] Ruta inesperada; me niego a borrar. No se toco nada.")
        return 1
    borrados = 0
    if PKG_DIR.exists():
        shutil.rmtree(PKG_DIR)
        borrados += 1
        print(f"[ok] Borrado {PKG_DIR.relative_to(REPO)}")
    for clip in CLIPS:
        stem = _stem(clip["archivo"])
        for p in (TRANSCRIPTS / f"{stem}.brain.json", TRANSCRIPTS / f"{stem}_caption_alerts.json"):
            if p.exists() and p.name.startswith("_s35_fixture_alpha"):
                p.unlink()
                borrados += 1
    print(f"[ok] Limpieza completa ({borrados} elemento(s)).")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Fixture local del Editor de Paquete (S35).")
    ap.add_argument("--clean", action="store_true", help="Borra SOLO la fixture y sus sidecars.")
    args = ap.parse_args()
    return limpiar() if args.clean else generar()


if __name__ == "__main__":
    raise SystemExit(main())
