"""Smoke de consistencia documental H4 (pre-HyperFrames).

Documentación únicamente: NO usa red, GPU, FFmpeg, modelos ni archivos privados.

Modos:
    python revision/pre-hyperframes/smoke_h4_docs.py --self-test
    python revision/pre-hyperframes/smoke_h4_docs.py --real

`--self-test` construye documentos temporales falsos (nunca nombres/rutas reales privados) y
demuestra que las detecciones disparan sobre: cifra vieja de tests, H3 pendiente, GPU/NVENC abierto,
afirmación absoluta "nada se sube", ruta absoluta realista, input específico, enlace relativo roto y
H5/HyperFrames declarados cerrados indebidamente.

`--real` verifica el repositorio actual. Los errores muestran archivo + categoría, nunca el texto
sensible encontrado.

Salida:
    checks=<n>
    blockers=0
    fails=0
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REV = ROOT / "revision" / "pre-hyperframes"

# ── Detecciones puras (operan sobre texto; reutilizadas por self-test y real) ──────────────

# Cifras/estados históricos que NO deben aparecer en la documentación ACTUAL (fuera de blockquote).
FORBIDDEN_FIGURES = [
    "157 tests",
    "1894 passed",
    "2314 passed",
    "2315 passed",
    "2318 passed",
    "14 checks",
    "1894/3",
]
H3_PENDING_MARKERS = ["PENDIENTE MERGE", "H3 pendiente", "H3 no iniciad", "H3 sin iniciar"]
NVENC_OPEN_RX = re.compile(r"NVENC[^\n]{0,80}(PR abierto|abierto y no mergeado)", re.IGNORECASE)
ABS_CLAIM_RX = re.compile(
    r"nada\s+(se\s+sube|sale)|todo\s+corre\s+en\s+(esta|tu)\s+pc", re.IGNORECASE
)
ABS_EXCUSES = (
    "no afirmamos",
    "a menos que",
    "salvo",
    "opt-in",
    "explícit",
    "explicit",
    "puede subirse",
    "si activas",
    "si usas",
)
ABS_PATH_RX = re.compile(r"[A-Za-z]:\\Users\\|[A-Za-z]:\\CLAUDECODE", re.IGNORECASE)
SECRET_RX = re.compile(r"sk-[A-Za-z0-9]{20,}")
# Acepta separador POSIX y Windows: input/foo.srt e input\foo.srt (los docstrings son Windows).
INPUT_RX = re.compile(r"input[\\/]([\w-]+)\.(srt|mp4|mov)", re.IGNORECASE)
# Placeholders genéricos + fixtures de prueba históricos preservados como historia útil en las
# bitácoras. Cualquier input/<name> fuera de este conjunto (p. ej. el SRT privado) se marca.
INPUT_ALLOWED = {
    "video",
    "clase",
    "clase_larga",
    "clip",
    "audio",
    "test_9_16",
    "test_16_9",
    "ejemplo",
    "prueba",
    # fixtures históricos (videos de prueba del proyecto, ya versionados):
    "podcast_test_60s",
    "prueba2personasenmedio",
    "pruebaedicionvideoyo",
    "pruebaparaedicion",
    "pruebapodcast2personas",
    "qa_demo_s33",
    "reel01",
    "reel01-03",
    "reel02",
    "stack_test_estatico",
    "tacosjuan",
}
# "pre-HyperFrames" es etiqueta de fase, no cierre → se excluye con lookbehind.
H5HF_CLOSED_RX = re.compile(
    r"(\bH5\b|(?<!pre-)\bHyperFrames\b)[^\n]{0,20}(CERRAD[AO]|COMPLETA|MERGEAD[AO]|LISTA|TERMINAD)",
    re.IGNORECASE,
)
LINK_RX = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def _lines_no_blockquote(text: str) -> list[str]:
    """Líneas que NO son cita histórica (blockquote ni marcadas HISTÓRICO/SUPERADO)."""
    out = []
    for ln in text.splitlines():
        s = ln.lstrip()
        if s.startswith(">"):
            continue
        if "HISTÓRICO" in ln or "HISTORICO" in ln or "SUPERAD" in ln:
            continue
        out.append(ln)
    return out


def detect_stale_figures(text: str) -> list[str]:
    hits = []
    body = "\n".join(_lines_no_blockquote(text))
    for fig in FORBIDDEN_FIGURES:
        if fig in body:
            hits.append(f"cifra-historica:{fig}")
    return hits


def detect_h3_pending(text: str) -> list[str]:
    body = "\n".join(_lines_no_blockquote(text))
    return [f"h3-pendiente:{m}" for m in H3_PENDING_MARKERS if m in body]


def detect_nvenc_open(text: str) -> list[str]:
    body = "\n".join(_lines_no_blockquote(text))
    return ["nvenc-abierto"] if NVENC_OPEN_RX.search(body) else []


def detect_absolute_upload_claim(text: str) -> list[str]:
    hits = []
    for ln in _lines_no_blockquote(text):
        if ABS_CLAIM_RX.search(ln) and not any(x in ln.lower() for x in ABS_EXCUSES):
            hits.append("absoluto-nada-se-sube")
    return hits


def detect_absolute_paths(text: str) -> list[str]:
    return ["ruta-absoluta"] if ABS_PATH_RX.search(text) else []


def detect_secrets(text: str) -> list[str]:
    return ["secreto-api-key" for _ in SECRET_RX.findall(text)]


def detect_private_inputs(text: str) -> list[str]:
    hits = []
    for m in INPUT_RX.finditer(text):
        if m.group(1).lower() not in INPUT_ALLOWED:
            hits.append("input-privado")
    return hits


def detect_h5_hf_closed(text: str) -> list[str]:
    hits = []
    for ln in _lines_no_blockquote(text):
        m = H5HF_CLOSED_RX.search(ln)
        if m and " no " not in (" " + ln.lower()):
            hits.append("h5-hf-cerrado-indebido")
    return hits


def detect_broken_links(path: Path, text: str) -> list[str]:
    hits = []
    for m in LINK_RX.finditer(text):
        target = m.group(1).strip()
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        target = target.split("#", 1)[0].strip()
        if not target:
            continue
        if not (path.parent / target).exists():
            hits.append("enlace-roto")
    return hits


# ── Modo self-test ─────────────────────────────────────────────────────────────────────────


def run_self_test() -> int:
    checks = []

    def expect(name, cond):
        checks.append((name, bool(cond)))

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        good = d / "good.md"
        good.write_text("Todo bien. 2410 passed, 4 skipped. Ver [x](good.md).\n", encoding="utf-8")

        # 1. cifra vieja de tests
        expect("detecta_cifra_vieja", detect_stale_figures("La suite: 1894 passed hoy."))
        expect("detecta_157", detect_stale_figures("tests/ (157 tests)"))
        # 2. H3 pendiente
        expect("detecta_h3_pendiente", detect_h3_pending("H3 CERRADO, PENDIENTE MERGE."))
        # 3. GPU/NVENC abierto
        expect("detecta_nvenc_abierto", detect_nvenc_open("PR NVENC abierto y no mergeado."))
        # 4. afirmación absoluta "nada se sube"
        expect("detecta_absoluto", detect_absolute_upload_claim("Nada se sube a la nube nunca."))
        expect(
            "no_marca_negacion",
            not detect_absolute_upload_claim(
                'No afirmamos "nada se sube": si activas Submagic el video puede subirse.'
            ),
        )
        # 5. ruta absoluta realista (nombre ficticio, NUNCA real)
        expect(
            "detecta_ruta_abs", detect_absolute_paths(r"Guardado en C:\Users\Fulano\Videos\a.mp4")
        )
        # 6. input específico (nombre ficticio privado) — separador POSIX y Windows
        expect("detecta_input_privado", detect_private_inputs("usa input/reunion_privada_x.srt"))
        expect(
            "detecta_input_privado_win",
            detect_private_inputs(r"venv\Scripts\python smoke.py input\reunion_privada_x.srt"),
        )
        expect("no_marca_input_generico", not detect_private_inputs("usa input/video.srt"))
        expect("no_marca_input_generico_win", not detect_private_inputs(r"usa input\video.srt"))
        # 7. enlace relativo roto
        broken = d / "broken.md"
        broken.write_text("Ver [y](no_existe.md).\n", encoding="utf-8")
        expect(
            "detecta_enlace_roto", detect_broken_links(broken, broken.read_text(encoding="utf-8"))
        )
        expect(
            "no_marca_enlace_ok", not detect_broken_links(good, good.read_text(encoding="utf-8"))
        )
        # 8. H5/HyperFrames cerrado indebidamente
        expect("detecta_hf_cerrado", detect_h5_hf_closed("HyperFrames COMPLETA y mergeada."))
        expect("no_marca_hf_no_iniciado", not detect_h5_hf_closed("HyperFrames no iniciada."))
        # secretos
        expect("detecta_secreto", detect_secrets("DEEPSEEK_API_KEY=sk-abcdefghij0123456789xyz"))
        expect("no_marca_placeholder", not detect_secrets("DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxx"))

    ok = sum(1 for _, c in checks if c)
    total = len(checks)
    for name, cond in checks:
        if not cond:
            print(f"  FAIL self-test: {name}")
    print(f"self-test {ok}/{total}")
    if ok == total:
        print("VEREDICTO: self-test VERDE.")
        return 0
    print("VEREDICTO: self-test ROJO.")
    return 1


# ── Modo real ───────────────────────────────────────────────────────────────────────────────

# Superficie pública actual: aquí la documentación DEBE estar limpia de cifras viejas / absolutos /
# inputs privados. Los meta-documentos (H4_INVENTARIO/EVIDENCIA) y las bitácoras históricas quedan
# fuera de esta comprobación porque DISCUTEN las contradicciones a propósito.
SURFACE_STRICT = [
    ROOT / "README.md",
    ROOT / "docs" / "ALPHA_TESTERS.md",
    ROOT / "docs" / "ENTORNO.md",
    ROOT / "docs" / "GPU_NVENC.md",
    REV / "MATRIZ_READINESS.md",
    REV / "PLAN_DE_PR.md",
]
# Validación de enlaces markdown: solo documentos que autoré/actualicé con enlaces relativos.
LINK_DOCS = [
    ROOT / "README.md",
    ROOT / "MAESTRO.md",
    ROOT / "docs" / "ALPHA_TESTERS.md",
    ROOT / "docs" / "ENTORNO.md",
    REV / "MATRIZ_READINESS.md",
    REV / "PLAN_DE_PR.md",
    REV / "H4_INVENTARIO.md",
    REV / "H4_EVIDENCIA.md",
]
# Escaneo de privacidad: documentación del proyecto (raíz + docs/ + revision/), determinista.
REQUIRED_FILES = [
    ROOT / "README.md",
    ROOT / "ESTADO.md",
    ROOT / "DECISIONES.md",
    ROOT / "PREGUNTAS.md",
    ROOT / "MAESTRO.md",
    ROOT / "docs" / "ALPHA_TESTERS.md",
    ROOT / "docs" / "ENTORNO.md",
    ROOT / "docs" / "GPU_NVENC.md",
    REV / "MATRIZ_READINESS.md",
    REV / "PLAN_DE_PR.md",
    REV / "H4_INVENTARIO.md",
    REV / "H4_EVIDENCIA.md",
]

H1 = "4dab852185c8eb220c3da45e6af52cfd8610bb65"
H2 = "5779a77f0f46c861806a9d02c21b8e3b4d358a81"
H3 = "b59989f11a8a77cc8925ca066e7aaf1e8908a855"
NVENC = "cdcea7a9860043eb175972758e660895bf9df44c"


def _estado_header(text: str) -> str:
    """Región de estado actual de ESTADO.md (antes de `## Fases`)."""
    idx = text.find("## Fases")
    return text[:idx] if idx != -1 else text


def _r(results, ok, category, file, blocker=True):
    results.append((bool(ok), blocker, category, file))


def _checks_required_and_links(results):
    for f in REQUIRED_FILES:
        _r(results, f.exists(), "archivo-requerido-ausente", f.name)
    for f in LINK_DOCS:
        if not f.exists():
            _r(results, False, "archivo-requerido-ausente", f.name)
            continue
        broken = detect_broken_links(f, f.read_text(encoding="utf-8"))
        _r(results, not broken, "enlace-roto", f.name)


def _checks_surface(results, estado_h):
    for f in SURFACE_STRICT:
        t = f.read_text(encoding="utf-8") if f.exists() else ""
        _r(results, not detect_stale_figures(t), "cifra-historica", f.name)
        _r(results, not detect_h3_pending(t), "h3-pendiente", f.name)
        _r(results, not detect_nvenc_open(t), "nvenc-abierto", f.name)
        _r(results, not detect_absolute_upload_claim(t), "absoluto-nada-se-sube", f.name)
        _r(results, not detect_private_inputs(t), "input-privado", f.name)
        _r(results, not detect_h5_hf_closed(t), "h5-hf-cerrado-indebido", f.name)
    # ESTADO: región de estado actual (no la bitácora histórica)
    _r(results, not detect_stale_figures(estado_h), "cifra-historica", "ESTADO.md#header")
    _r(results, not detect_h3_pending(estado_h), "h3-pendiente", "ESTADO.md#header")
    _r(results, not detect_h5_hf_closed(estado_h), "h5-hf-cerrado-indebido", "ESTADO.md#header")


def _project_doc_mds():
    """Documentación del proyecto de forma DETERMINISTA (idéntica en un clon limpio):
    los `.md` de la raíz + `docs/` + `revision/`. Excluye dirs locales no versionados como
    `.claude/`, `.agents/`, etc., para que el conteo sea reproducible."""
    mds = sorted(ROOT.glob("*.md"))
    for sub in ("docs", "revision"):
        d = ROOT / sub
        if d.exists():
            mds += sorted(d.rglob("*.md"))
    return mds


def _checks_privacy(results):
    # Markdown del proyecto: rutas personales, secretos e inputs privados (0 en todo el alcance).
    for md in _project_doc_mds():
        t = md.read_text(encoding="utf-8", errors="replace")
        _r(results, not detect_absolute_paths(t), "ruta-personal", md.name)
        _r(results, not detect_secrets(t), "secreto-api-key", md.name)
        _r(results, not detect_private_inputs(t), "input-privado", md.name)
    # Smokes de pre-hyperframes: que no reintroduzcan el SRT privado ni rutas personales.
    # Se excluye este propio archivo (contiene fixtures de detección con nombres ficticios).
    for py in sorted((ROOT / "revision" / "pre-hyperframes").glob("*.py")):
        if py.name == "smoke_h4_docs.py":
            continue
        t = py.read_text(encoding="utf-8", errors="replace")
        _r(results, not detect_private_inputs(t), "input-privado", py.name)
        _r(results, not detect_absolute_paths(t), "ruta-personal", py.name)


def _checks_estado_header(results, estado_h):
    hdr = "ESTADO.md#header"
    _r(results, all(h in estado_h for h in (H1, H2, H3, NVENC)), "merges-en-encabezado", hdr)
    _r(results, "cerrad" in estado_h.lower(), "estado-hardening", hdr)
    _r(results, "pendiente de revisión/merge" in estado_h, "h4-pendiente", hdr)
    _r(results, "H5" in estado_h and "pendiente" in estado_h.lower(), "h5-pendiente", hdr)
    _r(
        results,
        "HyperFrames" in estado_h and "NO iniciado" in estado_h,
        "hyperframes-no-iniciado",
        hdr,
    )


def _checks_content(results, texts):
    readme, alpha, matriz, plan, estado_h = texts
    for f, t in (("ESTADO.md", estado_h), ("README.md", readme), ("MATRIZ_READINESS.md", matriz)):
        _r(results, "2410 passed" in t and "4 skipped" in t, "baseline-2410", f)
    _r(
        results,
        "Local/remoto" in readme or "Local por defecto" in readme,
        "privacidad-explicada",
        "README.md",
    )
    for svc in ("DeepSeek", "Pexels", "Submagic"):
        _r(results, svc in readme, f"servicio-{svc}", "README.md")
    for marker in ("Video probado:", "Encoder mostrado:", "¿Lo usarías en un trabajo real?:"):
        _r(results, marker in alpha, "formato-feedback", "ALPHA_TESTERS.md")
    for guide in ("docs/ENTORNO.md", "docs/ALPHA_TESTERS.md", "docs/GPU_NVENC.md"):
        _r(results, guide in readme, "readme-enlaces-guias", "README.md")
    _r(results, "16 checks" in matriz, "matriz-16-checks", "MATRIZ_READINESS.md")
    _r(
        results,
        NVENC[:7] in matriz and NVENC[:7] in plan,
        "consistencia-nvenc-merge",
        "MATRIZ/PLAN",
    )
    _r(results, "H4" in matriz and "H4" in plan, "consistencia-h4", "MATRIZ/PLAN")


def run_real() -> int:
    results = []  # (ok, blocker, category, file)
    read = {f: (f.read_text(encoding="utf-8") if f.exists() else "") for f in REQUIRED_FILES}
    estado_h = _estado_header(read[ROOT / "ESTADO.md"])
    texts = (
        read[ROOT / "README.md"],
        read[ROOT / "docs" / "ALPHA_TESTERS.md"],
        read[REV / "MATRIZ_READINESS.md"],
        read[REV / "PLAN_DE_PR.md"],
        estado_h,
    )
    _checks_required_and_links(results)
    _checks_surface(results, estado_h)
    _checks_privacy(results)
    _checks_estado_header(results, estado_h)
    _checks_content(results, texts)

    fails = [r for r in results if not r[0]]
    blockers = [r for r in fails if r[1]]
    for _ok, blocker, category, file in fails:
        tag = "BLOCKER" if blocker else "WARN"
        print(f"  {tag}: [{category}] en {file}")
    print(f"checks={len(results)}")
    print(f"blockers={len(blockers)}")
    print(f"fails={len(fails)}")
    if fails:
        print("VEREDICTO: DOCUMENTACIÓN NO CONSISTENTE.")
        return 1
    print("VEREDICTO: documentación H4 consistente.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Smoke de consistencia documental H4")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--self-test", action="store_true")
    g.add_argument("--real", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return run_self_test()
    return run_real()


if __name__ == "__main__":
    sys.exit(main())
