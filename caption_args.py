"""caption_args.py - Definicion de la CLI de caption.py (split s34 B1, solo argparse).

La CLI publica NO cambia: mismos flags, mismos defaults, misma ayuda. caption.py
construye el parser desde aqui y conserva toda la logica de ejecucion.
"""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    """Parser completo de la CLI de captions (fuente unica de flags y ayuda)."""
    parser = argparse.ArgumentParser(
        description="Captions animados word-by-word — Centrito Studio CLI"
    )
    parser.add_argument("input", help="Video .mp4 de entrada, o carpeta para batch")
    parser.add_argument(
        "--style", default="hormozi", choices=["hormozi", "clean", "karaoke", "bounce", "pms"]
    )
    parser.add_argument(
        "--pop",
        choices=["off", "suave", "medio", "fuerte"],
        default=None,
        help="Intensidad del pop (off=1.0, suave=1.08, medio=1.30, fuerte=1.45)",
    )
    parser.add_argument(
        "--rebote",
        choices=["on", "off"],
        default=None,
        help="Rebote/overshoot de la palabra activa (on/off); default: el del estilo",
    )
    parser.add_argument(
        "--preset",
        choices=["clean_podcast", "viral_bounce", "keyword_punch", "karaoke_highlight"],
        default=None,
        help="Preset del caption_viral_engine (F6); si se da, --style/--pop se ignoran",
    )
    parser.add_argument(
        "--intensidad",
        choices=["minimal", "clean", "viral"],
        default=None,
        help="Intensidad del preset (default: la propia del preset)",
    )
    parser.add_argument(
        "--densidad",
        choices=["baja", "media", "alta"],
        default=None,
        help="Densidad de keywords automaticas del preset (doble freno D21; default: del preset)",
    )
    parser.add_argument("--lang", default="es")
    parser.add_argument(
        "--srt",
        default=None,
        metavar="PATH",
        help="Usa un SRT corregido como texto oficial; Whisper aporta unicamente timings (S36-B)",
    )
    parser.add_argument(
        "--srt-parcial",
        action="store_true",
        default=False,
        help=(
            "Anima tambien los cues con timing PARCIAL: lo anclado usa su tiempo medido y los "
            "huecos se reparten (S38/D45). Sin este flag, un cue que no ancla todos sus tokens "
            "queda estatico. Exige --srt"
        ),
    )
    parser.add_argument(
        "--srt-offset",
        type=int,
        default=0,
        metavar="MS",
        help=(
            "Desplaza el SRT sobre el timeline del video, en ms (positivo = el audio va despues "
            "de lo que dice el SRT). NUNCA se estima solo: el render propone y esto lo aplica. "
            "Exige --srt"
        ),
    )
    parser.add_argument(
        "--srt-min-coverage",
        type=float,
        default=None,
        metavar="F",
        help=(
            "Fraccion de tokens del cue que deben anclar para animarlo (0.0-1.0). Solo con "
            "--srt-parcial; sin este flag se usa el umbral con el que se aprobo la evidencia"
        ),
    )
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--model", default="auto", choices=["auto", "small", "medium"])
    parser.add_argument("--words-per-group", type=int, default=None, metavar="N")
    parser.add_argument("--out-stem", default=None)
    parser.add_argument(
        "--depurar",
        choices=["seguro", "agresivo"],
        default=None,
        help="Depurar silencios (seguro) o tambien muletillas (agresivo)",
    )
    parser.add_argument(
        "--clips",
        choices=["cortos", "largos", "ambos"],
        default=None,
        help="Generar clips virales con IA (cortos|largos|ambos)",
    )
    parser.add_argument(
        "--emojis",
        action="store_true",
        default=False,
        help="Overlay de assets IA (ComfyUI) sobre palabras clave del brain.json",
    )
    parser.add_argument(
        "--popups",
        action="store_true",
        default=False,
        help="Popups de imagen: assets/biblioteca/ por keyword + transcripts/{stem}_popups.json",
    )
    parser.add_argument(
        "--fx",
        choices=["express", "pro", "premium"],
        default=None,
        help="Capa FX local opcional (S36-FX): punch-in/flash/scanner/logo antes del ass",
    )
    parser.add_argument(
        "--motion",
        action="store_true",
        default=False,
        help=(
            "Letreros animados del Motor B (HyperFrames) sobre el video: hook, lower third, "
            "dato destacado y cierre, colocados solos. Capa aditiva y apagada por default; si "
            "falla, el video sale igual pero sin letreros"
        ),
    )
    parser.add_argument(
        "--motion-titulo",
        default=None,
        metavar="TEXTO",
        help="Titulo del hook y del cierre. Sin esto no se coloca ninguna pieza. Exige --motion",
    )
    parser.add_argument(
        "--motion-nombre",
        default=None,
        metavar="TEXTO",
        help="Nombre del lower third. Vacio omite esa pieza entera. Exige --motion",
    )
    parser.add_argument(
        "--motion-rol",
        default=None,
        metavar="TEXTO",
        help="Rol que acompana al nombre en el lower third. Exige --motion",
    )
    parser.add_argument(
        "--motion-cta",
        default=None,
        metavar="TEXTO",
        help="Llamada a la accion del cierre. Exige --motion",
    )
    parser.add_argument(
        "--caption-qa",
        action="store_true",
        default=False,
        help="QA de transcripcion: detecta palabras mal transcritas (glosario/guion)",
    )
    parser.add_argument(
        "--caption-qa-mode",
        choices=["alertas", "auto_seguro"],
        default="alertas",
        help="alertas = solo reporta; auto_seguro = aplica solo confianza alta",
    )
    parser.add_argument(
        "--guion",
        default=None,
        metavar="PATH",
        help="Guion opcional (texto/resumen/temario); default: transcripts/{stem}_guion.txt",
    )
    parser.add_argument(
        "--glosario",
        default=None,
        metavar="PATH",
        help="Glosario alterno para el QA (default: assets/glosario.json)",
    )
    parser.add_argument(
        "--caption-qa-llm",
        action="store_true",
        default=False,
        help="Auditor DeepSeek de alertas dudosas (opt-in, fail-open)",
    )
    return parser


def motion_opts_de_args(args: argparse.Namespace):
    """`motion_capa.OpcionesMotion` a partir de los args. Sin `--motion` devuelve la capa OFF.

    Los `--motion-*` sin `--motion` son un error del llamador, no algo que se ignore en silencio:
    quien los escribe espera letreros, y tragarselos produciria un video sin ellos y sin aviso.
    """
    import motion_capa  # noqa: PLC0415 (la ruta historica no importa la capa)

    sueltos = [
        f"--motion-{c}"
        for c in ("titulo", "nombre", "rol", "cta")
        if getattr(args, f"motion_{c}", None) is not None
    ]
    if not args.motion:
        if sueltos:
            raise SystemExit(f"{', '.join(sueltos)} exige --motion")
        return motion_capa.OpcionesMotion()
    return motion_capa.OpcionesMotion(
        enabled=True,
        titulo=args.motion_titulo or "",
        nombre=args.motion_nombre or "",
        rol=args.motion_rol or "",
        cta=args.motion_cta or "",
    )


def qa_opts_de_args(args: argparse.Namespace) -> dict | None:
    """Opciones del Caption QA a partir de los args (None si --caption-qa no se dio)."""
    if not args.caption_qa:
        return None
    return {
        "modo": args.caption_qa_mode,
        "guion": args.guion,
        "glosario": args.glosario,
        "llm": args.caption_qa_llm,
    }
