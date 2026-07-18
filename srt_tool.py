"""srt_tool.py — CLI local delgada sobre el importador SRT (S36-A).

Subcomandos: validate, inspect, normalize, contract. Salida ASCII (consola Windows),
sin emojis, sin texto completo del SRT, sin rutas absolutas. Errores de usuario ->
mensaje accionable + exit 1; los bugs de programacion NO se tragan (propagan).

Uso:
    python srt_tool.py validate  PATH [--video-duration-s SEG]
    python srt_tool.py inspect   PATH
    python srt_tool.py normalize PATH --output DEST [--reindex]
    python srt_tool.py contract  PATH --output DEST.json
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

from srt_import import (
    SrtError,
    format_timestamp,
    load_srt,
    serialize_srt,
    validate_srt,
    write_srt_contract,
)


def _all_diagnostics(document, video_ms):
    """Diagnosticos de parseo + validacion independiente, en orden estable."""
    return tuple(document.diagnostics) + validate_srt(document, video_duration_ms=video_ms)


def _print_summary(name, document, diags) -> int:
    n_err = sum(1 for d in diags if d.severity == "error")
    n_warn = sum(1 for d in diags if d.severity == "warning")
    first = document.cues[0] if document.cues else None
    last = document.cues[-1] if document.cues else None
    print(f"archivo:  {name}")
    print(f"encoding: {document.encoding}")
    print(f"cues:     {len(document.cues)}")
    if first and last:
        print(f"inicio:   {format_timestamp(first.start_ms)}")
        print(f"fin:      {format_timestamp(last.end_ms)}")
        print(f"duracion: {format_timestamp(last.end_ms - first.start_ms)}")
    print(f"warnings: {n_warn}")
    print(f"errors:   {n_err}")
    if diags:
        counts = Counter(f"{d.severity}:{d.code}" for d in diags)
        print("codigos:")
        for code in sorted(counts):
            print(f"  {code} x{counts[code]}")
    return n_err


def _cmd_validate(args) -> int:
    video_ms = int(round(args.video_duration_s * 1000)) if args.video_duration_s else None
    document = load_srt(Path(args.path))
    diags = _all_diagnostics(document, video_ms)
    n_err = _print_summary(Path(args.path).name, document, diags)
    return 1 if n_err else 0


def _cmd_inspect(args) -> int:
    document = load_srt(Path(args.path))
    _print_summary(Path(args.path).name, document, _all_diagnostics(document, None))
    if document.cues:
        first, last = document.cues[0], document.cues[-1]
        print(f"primer indice: {first.index} @ {format_timestamp(first.start_ms)}")
        print(f"ultimo indice: {last.index} @ {format_timestamp(last.start_ms)}")
    return 0


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="")
    os.replace(tmp, path)


def _cmd_normalize(args) -> int:
    src, dest = Path(args.path), Path(args.output)
    if src.resolve() == dest.resolve():
        raise SrtError("el destino no puede ser igual al origen (elige otro --output)")
    if dest.exists():
        raise SrtError(f"el destino ya existe (elige otro nombre): {dest.name}")
    document = load_srt(src)
    _atomic_write(dest, serialize_srt(document, reindex=args.reindex))
    print(f"normalizado: {dest.name} ({len(document.cues)} cues, reindex={args.reindex})")
    return 0


def _cmd_contract(args) -> int:
    document = load_srt(Path(args.path))
    write_srt_contract(document, Path(args.output))
    print(f"contrato:    {Path(args.output).name} ({len(document.cues)} cues)")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="srt_tool", description="Herramienta local de SRT (S36-A)"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_val = sub.add_parser("validate", help="valida un .srt (exit 1 si hay errores)")
    p_val.add_argument("path")
    p_val.add_argument("--video-duration-s", type=float, default=None)
    p_val.set_defaults(func=_cmd_validate)
    p_ins = sub.add_parser("inspect", help="resumen de un .srt (sin texto)")
    p_ins.add_argument("path")
    p_ins.set_defaults(func=_cmd_inspect)
    p_norm = sub.add_parser("normalize", help="serializa canonico a --output (nunca al origen)")
    p_norm.add_argument("path")
    p_norm.add_argument("--output", required=True)
    p_norm.add_argument("--reindex", action="store_true")
    p_norm.set_defaults(func=_cmd_normalize)
    p_con = sub.add_parser("contract", help="escribe el contrato JSON v1 a --output")
    p_con.add_argument("path")
    p_con.add_argument("--output", required=True)
    p_con.set_defaults(func=_cmd_contract)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        return args.func(args)
    except SrtError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
