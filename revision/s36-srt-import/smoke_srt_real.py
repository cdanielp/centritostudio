"""smoke_srt_real.py — Smoke del importador SRT contra el SRT REAL del usuario (S36-A).

PRIVACIDAD: no imprime frases del archivo, no lo copia a revision/, no lo commitea.
Verifica el contrato contra los datos conocidos del archivo, hace round-trip semantico
sobre un temp dir y confirma que el original queda intacto (mismo sha256 antes/despues).

Uso (local, el .srt real esta gitignoreado):
    venv\\Scripts\\python revision\\s36-srt-import\\smoke_srt_real.py input\\0717_corregido.srt
"""

from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
from pathlib import Path

# Permite ejecutar el script desde la raiz del repo sin instalar el paquete.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from srt_import import (  # noqa: E402
    load_srt,
    parse_srt_text,
    serialize_srt,
    validate_srt,
    write_srt_contract,
)

# Datos conocidos del archivo real (NO ajustar para forzar el PASS; si no coinciden, es FAIL).
EXPECTED_N_CUES = 1072
EXPECTED_LAST_INDEX = 1072
EXPECTED_LAST_START_MS = 2_473_300
EXPECTED_LAST_END_MS = 2_474_600


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _semantic_key(doc):
    return [(c.index, c.start_ms, c.end_ms, c.lines) for c in doc.cues]


def _check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {label}{(' - ' + detail) if detail else ''}")
    return ok


def run(path: Path) -> bool:
    ok = True
    sha_before = _sha256(path)
    doc = load_srt(path)
    diags = validate_srt(doc)
    n_err = sum(1 for d in diags if d.severity == "error")
    n_warn = sum(1 for d in diags if d.severity == "warning")

    last = doc.cues[-1] if doc.cues else None
    ok &= _check("n_cues", len(doc.cues) == EXPECTED_N_CUES, f"{len(doc.cues)}")
    ok &= _check(
        "ultimo index",
        bool(last) and last.index == EXPECTED_LAST_INDEX,
        str(last.index if last else "-"),
    )
    ok &= _check(
        "ultimo start_ms",
        bool(last) and last.start_ms == EXPECTED_LAST_START_MS,
        str(last.start_ms if last else "-"),
    )
    ok &= _check(
        "ultimo end_ms",
        bool(last) and last.end_ms == EXPECTED_LAST_END_MS,
        str(last.end_ms if last else "-"),
    )
    ok &= _check(
        "orden fuente", [c.source_position for c in doc.cues] == list(range(len(doc.cues)))
    )
    ok &= _check("sin errores de validacion", n_err == 0, f"errors={n_err}")

    # Round-trip semantico via temp dir (no toca el input).
    tmp = Path(tempfile.mkdtemp(prefix="srt_smoke_"))
    try:
        norm = tmp / "normalizado.srt"
        norm.write_text(serialize_srt(doc), encoding="utf-8", newline="")
        reparsed = parse_srt_text(norm.read_text(encoding="utf-8"))
        ok &= _check("round-trip semantico", _semantic_key(reparsed) == _semantic_key(doc))
        write_srt_contract(doc, tmp / "contrato.json")
        ok &= _check("contrato JSON escrito", (tmp / "contrato.json").exists())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    full_text = "\n".join(c.text for c in doc.cues)
    ok &= _check("contiene Unicode no-ASCII", any(ord(ch) > 127 for ch in full_text))
    ok &= _check(
        "ninguna linea vacia por error", all(any(ln.strip() for ln in c.lines) for c in doc.cues)
    )
    ok &= _check("original intacto (sha256)", _sha256(path) == sha_before)

    print(f"resumen: cues={len(doc.cues)} warnings={n_warn} errors={n_err} encoding={doc.encoding}")
    if diags:
        from collections import Counter

        counts = Counter(f"{d.severity}:{d.code}" for d in diags)
        for code in sorted(counts):
            print(f"  {code} x{counts[code]}")
    return ok


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("uso: python smoke_srt_real.py <ruta_al_srt_real>")
        return 2
    path = Path(argv[0])
    if not path.is_file():
        print(f"[FAIL] no existe el archivo real: {path.name} (smoke NO ejecutado)")
        return 2
    ok = run(path)
    print("RESULTADO: PASS" if ok else "RESULTADO: FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
