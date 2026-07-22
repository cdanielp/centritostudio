"""Smoke de contrato del gate remoto ligero H5 (pre-HyperFrames).

Verifica el WORKFLOW, la `requirements-ci.txt`, el manifiesto y el runner del gate remoto,
mas la coherencia de estado (H4 cerrado / H5 en curso / HyperFrames no iniciado). NO usa red,
GPU, FFmpeg, modelos ni archivos privados; solo parsea texto/YAML versionado.

Modos:
    python revision/pre-hyperframes/smoke_h5_ci.py --self-test
    python revision/pre-hyperframes/smoke_h5_ci.py --real

`--self-test` construye workflows/manifiestos/runners temporales FALSOS y demuestra que cada
deteccion dispara sobre su condicion prohibida. `--real` valida el repositorio actual.

Los errores muestran unicamente `archivo + categoria`; nunca vuelcan lineas completas del
workflow que pudieran contener datos sensibles.
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
REV = ROOT / "revision" / "pre-hyperframes"

# Reutilizamos detectores puros del smoke H4 (misma carpeta) para no duplicar contrato.
sys.path.insert(0, str(REV))
import smoke_h4_docs as h4  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "quality.yml"
REQ_CI = ROOT / "requirements-ci.txt"
MANIFIESTO = ROOT / "ci" / "pytest-light.txt"
RUNNER = ROOT / "ci" / "run_pytest_light.py"
PLUGIN = ROOT / "ci" / "_pytest_light_plugin.py"
ESTADO = ROOT / "ESTADO.md"

MERGE_H4 = "3cbac46"  # merge PR #29 (cierre H4) — prefijo estable

ACCIONES_PERMITIDAS = {"actions/checkout": "v6", "actions/setup-python": "v6"}

# Dependencias pesadas de render/IA que NUNCA deben aparecer en requirements-ci.txt.
DEPS_PESADAS = (
    "faster-whisper",
    "faster_whisper",
    "mediapipe",
    "rembg",
    "onnxruntime",
    "edge-tts",
    "edge_tts",
    "openai",
    "torch",
    "ctranslate2",
    "uvicorn",
    "opencv",
    "cuda",
)

# Comandos que el workflow real DEBE ejecutar (substrings deterministas).
COMANDOS_OBLIGATORIOS = (
    "pip install -r requirements-ci.txt",
    "ruff check .",
    "ruff format --check .",
    "smoke_h4_docs.py --self-test",
    "smoke_h4_docs.py --real",
    "smoke_h5_ci.py --self-test",
    "smoke_h5_ci.py --real",
    "ci/run_pytest_light.py",
)


# ── Analisis del workflow ─────────────────────────────────────────────────────────────────────


def _bloque_on(data: dict) -> dict:
    """Devuelve el bloque de triggers. YAML 1.1 parsea `on:` como booleano True."""
    bloque = data.get("on")
    if bloque is None:
        bloque = data.get(True)
    return bloque if isinstance(bloque, dict) else {}


def violaciones_workflow_texto(texto: str) -> set[str]:
    """Detecciones sobre el TEXTO crudo (independientes del parseo YAML).

    Ignora las lineas de comentario (`# ...`): mencionar `check.bat` en un comentario que
    aclara que el gate remoto NO lo ejecuta no es una violacion; ejecutarlo en un `run:` si.
    """
    activo = "\n".join(l for l in texto.splitlines() if not l.lstrip().startswith("#"))
    v: set[str] = set()
    if re.search(r"secrets\.", activo):
        v.add("secrets")
    if re.search(r"\b(curl|wget)\b", activo):
        v.add("curl-wget")
    if "check.bat" in activo:
        v.add("check-bat")
    if "requirements.txt" in activo:  # no matchea requirements-ci.txt
        v.add("requirements-txt")
    if re.search(r"\bpytest\b", activo):  # invocacion directa (run_pytest_light no matchea)
        v.add("pytest-completo")
    if re.search(r"(?m)^\s*continue-on-error\s*:", activo):
        v.add("continue-on-error")
    if re.search(r"(?m)^\s*cache\s*:", activo):
        v.add("cache")
    return v


def violaciones_workflow_estructura(data: dict) -> set[str]:
    """Detecciones sobre el YAML parseado (triggers, permisos, acciones, timeout...)."""
    v: set[str] = set()
    on = _bloque_on(data)
    if "pull_request_target" in on:
        v.add("pull-request-target")
    if "schedule" in on:
        v.add("schedule")

    # El contrato exige EXACTAMENTE `permissions: {contents: read}`. Cualquier otra forma es token
    # de mas: `contents: write`, un scope adicional, `read-all`/`write-all` (read-all concede lectura
    # de TODOS los scopes) o permisos ausentes (el default del repo puede ser read-write).
    perms = data.get("permissions")
    if perms != {"contents": "read"}:
        contents_val = perms.get("contents") if isinstance(perms, dict) else None
        if contents_val == "write":
            v.add("permiso-contents-write")
        if contents_val != "write" or (isinstance(perms, dict) and len(perms) > 1):
            v.add("permiso-write")

    if "concurrency" not in data:
        v.add("sin-concurrency")

    for job in (data.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        if "timeout-minutes" not in job:
            v.add("sin-timeout")
        for paso in job.get("steps") or []:
            usa = paso.get("uses")
            if usa:
                nombre, _, ref = usa.partition("@")
                if nombre not in ACCIONES_PERMITIDAS:
                    v.add("accion-no-permitida")
                elif ref != ACCIONES_PERMITIDAS[nombre]:
                    v.add("version-accion-no-admitida")
                if nombre == "actions/setup-python":
                    ver = str((paso.get("with") or {}).get("python-version", ""))
                    if ver and ver != "3.12":
                        v.add("python-no-312")
    return v


def analizar_workflow(path: Path) -> set[str]:
    """Une texto + estructura. `workflow-ausente`/`yaml-invalido` cortan el resto."""
    if not path.is_file():
        return {"workflow-ausente"}
    texto = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(texto)
    except yaml.YAMLError:
        return {"yaml-invalido"}
    if not isinstance(data, dict):
        return {"yaml-invalido"}
    return violaciones_workflow_texto(texto) | violaciones_workflow_estructura(data)


def faltan_comandos_obligatorios(path: Path) -> set[str]:
    if not path.is_file():
        return {"sin-comando-obligatorio"}
    texto = path.read_text(encoding="utf-8")
    return {"sin-comando-obligatorio"} if any(c not in texto for c in COMANDOS_OBLIGATORIOS) else set()


def triggers_exactos(path: Path) -> bool:
    if not path.is_file():
        return False
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    on = _bloque_on(data)
    if set(on) != {"pull_request", "push", "workflow_dispatch"}:
        return False
    ramas = (on.get("push") or {}).get("branches")
    return ramas == ["main"]


# ── Analisis de requirements-ci / manifiesto / runner ─────────────────────────────────────────


def violaciones_requirements_ci_texto(texto: str) -> set[str]:
    v: set[str] = set()
    bajo = texto.lower()
    # Ignoramos comentarios: una dep pesada solo cuenta si es un requisito real.
    requisitos = "\n".join(l for l in bajo.splitlines() if l.strip() and not l.lstrip().startswith("#"))
    for dep in DEPS_PESADAS:
        if dep in requisitos:
            v.add("dep-pesada")
    if "pytest-socket" not in requisitos:
        v.add("sin-pytest-socket")
    return v


def violaciones_requirements_ci(path: Path) -> set[str]:
    if not path.is_file():
        return {"requirements-ci-ausente"}
    return violaciones_requirements_ci_texto(path.read_text(encoding="utf-8"))


def violaciones_manifiesto(path: Path, root: Path) -> set[str]:
    """Valida el manifiesto contra `root/tests/`: duplicados, fuera de tests/, inexistentes."""
    if not path.is_file():
        return {"manifiesto-ausente"}
    tests_root = (root / "tests").resolve()
    v: set[str] = set()
    vistas: set[str] = set()
    for cruda in path.read_text(encoding="utf-8").splitlines():
        linea = cruda.strip()
        if not linea or linea.startswith("#"):
            continue
        norm = linea.replace("\\", "/")
        if norm in vistas:
            v.add("entrada-duplicada")
        vistas.add(norm)
        if not norm.startswith("tests/"):
            v.add("ruta-fuera-tests")
            continue
        resuelta = (root / norm).resolve()
        if resuelta != tests_root and tests_root not in resuelta.parents:
            v.add("ruta-fuera-tests")
        elif not resuelta.is_file():
            v.add("test-inexistente")
    if not vistas:
        v.add("manifiesto-vacio")
    return v


def violaciones_runner_texto(texto: str) -> set[str]:
    v: set[str] = set()
    if "shell=True" in texto:
        v.add("runner-shell-true")
    if "--disable-socket" not in texto:
        v.add("runner-sin-disable-socket")
    if "sys.executable" not in texto:
        v.add("runner-sin-mismo-interprete")
    return v


def violaciones_runner(path: Path) -> set[str]:
    if not path.is_file():
        return {"runner-ausente"}
    return violaciones_runner_texto(path.read_text(encoding="utf-8"))


# ── Modo self-test ─────────────────────────────────────────────────────────────────────────────

_WF_BASE = """\
name: Quality Gate
on:
  pull_request:
  push:
    branches: [main]
  workflow_dispatch:
permissions:
  contents: read
concurrency:
  group: quality-x
  cancel-in-progress: true
jobs:
  quality:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"
      - run: python -m pip install -r requirements-ci.txt
      - run: python ci/run_pytest_light.py
"""


def _wf(**cambios: str) -> str:
    """Workflow base con lineas mutadas/insertadas para los casos negativos."""
    texto = _WF_BASE
    for viejo, nuevo in cambios.items():
        texto = texto.replace(viejo.replace("__", " "), nuevo)
    return texto


def run_self_test() -> int:
    checks: list[tuple[str, bool]] = []

    def expect(nombre: str, cond: object) -> None:
        checks.append((nombre, bool(cond)))

    # Base sana: sin violaciones.
    expect("base_sana_estructura", not violaciones_workflow_estructura(yaml.safe_load(_WF_BASE)))
    expect("base_sana_texto", not violaciones_workflow_texto(_WF_BASE))

    def estruct(texto: str) -> set[str]:
        return violaciones_workflow_estructura(yaml.safe_load(texto))

    # 1. workflow ausente
    with tempfile.TemporaryDirectory() as td:
        expect("1_workflow_ausente", analizar_workflow(Path(td) / "no.yml") == {"workflow-ausente"})
    # 2. pull_request_target
    expect("2_prt", "pull-request-target" in estruct(_WF_BASE.replace("  pull_request:", "  pull_request_target:")))
    # 3. contents: write
    expect("3_contents_write", "permiso-contents-write" in estruct(_WF_BASE.replace("contents: read", "contents: write")))
    # 4. otro permiso write / read-all / write-all / scope extra (todo distinto de contents:read)
    expect("4_otro_write", "permiso-write" in estruct(_WF_BASE.replace("contents: read", "issues: write")))
    expect(
        "4_read_all",
        "permiso-write" in estruct(_WF_BASE.replace("permissions:\n  contents: read", "permissions: read-all")),
    )
    expect(
        "4_write_all",
        "permiso-write" in estruct(_WF_BASE.replace("permissions:\n  contents: read", "permissions: write-all")),
    )
    expect(
        "4_scope_extra",
        "permiso-write" in estruct(_WF_BASE.replace("  contents: read", "  contents: read\n  issues: write")),
    )
    # 5. secrets.*
    expect("5_secrets", "secrets" in violaciones_workflow_texto(_WF_BASE + "        env:\n          T: ${{ secrets.TOKEN }}\n"))
    # 6. accion no permitida
    expect("6_accion_no_permitida", "accion-no-permitida" in estruct(_WF_BASE.replace("actions/checkout@v6", "tercero/accion@v1")))
    # 7. version no admitida
    expect("7_version_no_admitida", "version-accion-no-admitida" in estruct(_WF_BASE.replace("actions/checkout@v6", "actions/checkout@v3")))
    # 8. python != 3.12
    expect("8_python_no_312", "python-no-312" in estruct(_WF_BASE.replace('"3.12"', '"3.11"')))
    # 9. sin timeout
    expect("9_sin_timeout", "sin-timeout" in estruct(_WF_BASE.replace("    timeout-minutes: 15\n", "")))
    # 10. sin concurrency
    expect("10_sin_concurrency", "sin-concurrency" in estruct(_WF_BASE.replace("concurrency:\n  group: quality-x\n  cancel-in-progress: true\n", "")))
    # 11. continue-on-error
    expect("11_continue_on_error", "continue-on-error" in violaciones_workflow_texto(_WF_BASE + "      - run: echo hi\n        continue-on-error: true\n"))
    # 12. curl/wget
    expect("12_curl", "curl-wget" in violaciones_workflow_texto(_WF_BASE + "      - run: curl http://x\n"))
    # 13. pytest completo
    expect("13_pytest_completo", "pytest-completo" in violaciones_workflow_texto(_WF_BASE + "      - run: python -m pytest\n"))
    # 14. check.bat (ejecutado). Un comentario que lo menciona NO es violacion.
    expect("14_check_bat", "check-bat" in violaciones_workflow_texto(_WF_BASE + "      - run: check.bat\n"))
    expect("14_check_bat_comentario_ok", "check-bat" not in violaciones_workflow_texto(_WF_BASE + "# no ejecuta check.bat\n"))
    # 15. requirements.txt
    expect("15_requirements_txt", "requirements-txt" in violaciones_workflow_texto(_WF_BASE + "      - run: pip install -r requirements.txt\n"))
    # tambien: cache prohibido
    expect("extra_cache", "cache" in violaciones_workflow_texto(_WF_BASE.replace('          python-version: "3.12"', '          python-version: "3.12"\n          cache: pip')))

    # Manifiesto / runner / requirements — con arbol temporal FALSO.
    with tempfile.TemporaryDirectory() as td:
        raiz = Path(td)
        (raiz / "tests").mkdir()
        real = raiz / "tests" / "test_real.py"
        real.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
        man = raiz / "manifest.txt"

        # 16. manifiesto inexistente
        expect("16_manifiesto_ausente", violaciones_manifiesto(raiz / "no.txt", raiz) == {"manifiesto-ausente"})
        # 17. entrada duplicada
        man.write_text("tests/test_real.py\ntests/test_real.py\n", encoding="utf-8")
        expect("17_duplicada", "entrada-duplicada" in violaciones_manifiesto(man, raiz))
        # 18. test inexistente
        man.write_text("tests/test_fantasma.py\n", encoding="utf-8")
        expect("18_inexistente", "test-inexistente" in violaciones_manifiesto(man, raiz))
        # 19. ruta fuera de tests/
        man.write_text("app.py\n", encoding="utf-8")
        expect("19_fuera_tests", "ruta-fuera-tests" in violaciones_manifiesto(man, raiz))
        man.write_text("tests/../app.py\n", encoding="utf-8")
        expect("19_fuera_tests_dotdot", "ruta-fuera-tests" in violaciones_manifiesto(man, raiz))
        # manifiesto sano
        man.write_text("tests/test_real.py\n", encoding="utf-8")
        expect("manifiesto_sano", not violaciones_manifiesto(man, raiz))

    # 20. dep pesada prohibida
    expect("20_dep_pesada", "dep-pesada" in violaciones_requirements_ci_texto("pytest\npytest-socket\nmediapipe==0.10.35\n"))
    # 21. sin pytest-socket
    expect("21_sin_pytest_socket", "sin-pytest-socket" in violaciones_requirements_ci_texto("pytest\nruff\n"))
    expect("req_ci_sano", not violaciones_requirements_ci_texto("ruff\npytest\npytest-socket\nPyYAML\n"))
    # 22. runner con shell=True
    expect("22_shell_true", "runner-shell-true" in violaciones_runner_texto("subprocess.run(cmd, shell=True)\n--disable-socket\nsys.executable\n"))
    expect("runner_sano", not violaciones_runner_texto("subprocess.run([sys.executable, '-m', 'pytest', '--disable-socket'], check=False)\n"))
    # 23. H5 / HyperFrames cerrado indebidamente
    expect("23_h5_cerrado", h4.detect_h5_hf_closed("H5 CERRADA y mergeada en main."))
    expect("23_hf_cerrado", h4.detect_h5_hf_closed("HyperFrames COMPLETA."))
    expect("23_no_marca_h5_pendiente", not h4.detect_h5_hf_closed("H5 en esta rama, pendiente de revision/merge."))

    ok = sum(1 for _, c in checks if c)
    total = len(checks)
    for nombre, cond in checks:
        if not cond:
            print(f"  FAIL self-test: {nombre}")
    print(f"self-test {ok}/{total}")
    if ok == total:
        print("VEREDICTO: self-test VERDE.")
        return 0
    print("VEREDICTO: self-test ROJO.")
    return 1


# ── Modo real ────────────────────────────────────────────────────────────────────────────────


def _r(results: list, ok: object, categoria: str, archivo: str) -> None:
    results.append((bool(ok), categoria, archivo))


def _checks_privacidad_ci(results: list) -> None:
    """Sin rutas personales ni secretos en los archivos del gate remoto."""
    for path in (WORKFLOW, REQ_CI, MANIFIESTO, RUNNER, PLUGIN):
        if not path.is_file():
            continue
        texto = path.read_text(encoding="utf-8")
        _r(results, not h4.detect_absolute_paths(texto), "ruta-personal", path.name)
        _r(results, not h4.detect_secrets(texto), "secreto-api-key", path.name)


def _checks_estado(results: list) -> None:
    estado_h = h4._estado_header(ESTADO.read_text(encoding="utf-8")) if ESTADO.is_file() else ""
    _r(results, re.search(r"H4[^\n]*CERRAD", estado_h, re.I), "h4-no-cerrado", "ESTADO.md#header")
    _r(results, MERGE_H4 in estado_h, "merge-h4-ausente", "ESTADO.md#header")
    _r(results, re.search(r"H5[^\n]*(pendiente|en esta rama|en curso)", estado_h, re.I), "h5-no-pendiente", "ESTADO.md#header")
    _r(results, "HyperFrames" in estado_h and "NO iniciado" in estado_h, "hyperframes-iniciado", "ESTADO.md#header")
    _r(results, not h4.detect_h5_hf_closed(estado_h), "h5-hf-cerrado-indebido", "ESTADO.md#header")


def run_real() -> int:
    results: list = []

    # Workflow.
    for cat in sorted(analizar_workflow(WORKFLOW)):
        _r(results, False, cat, "quality.yml")
    _r(results, triggers_exactos(WORKFLOW), "triggers-invalidos", "quality.yml")
    for cat in sorted(faltan_comandos_obligatorios(WORKFLOW)):
        _r(results, False, cat, "quality.yml")

    # requirements-ci.
    for cat in sorted(violaciones_requirements_ci(REQ_CI)):
        _r(results, False, cat, "requirements-ci.txt")

    # Manifiesto + existencia real de todos los archivos.
    for cat in sorted(violaciones_manifiesto(MANIFIESTO, ROOT)):
        _r(results, False, cat, "pytest-light.txt")

    # Runner.
    for cat in sorted(violaciones_runner(RUNNER)):
        _r(results, False, cat, "run_pytest_light.py")

    # Privacidad de los archivos del gate + estado documental.
    _checks_privacidad_ci(results)
    _checks_estado(results)

    fails = [r for r in results if not r[0]]
    for _ok, categoria, archivo in fails:
        print(f"  BLOCKER: [{categoria}] en {archivo}")
    print(f"checks={len(results)}")
    print(f"fails={len(fails)}")
    if fails:
        print("VEREDICTO: GATE H5 NO CONSISTENTE.")
        return 1
    print("VEREDICTO: contrato del gate H5 consistente.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Smoke de contrato del gate remoto H5")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--self-test", action="store_true")
    g.add_argument("--real", action="store_true")
    args = ap.parse_args()
    return run_self_test() if args.self_test else run_real()


if __name__ == "__main__":
    sys.exit(main())
