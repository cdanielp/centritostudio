"""system_preflight.py — Diagnostico central de entorno de Centrito Studio (H3).

Fuente UNICA para saber si el Studio puede arrancar de forma segura y que capacidades tiene.
Puro y testeable: todas las dependencias externas se INYECTAN (version de Python, ejecutable,
`shutil.which`, rutas de modelos, probe de imports, checker de puerto). No hace I/O de red.

Privacidad (H1/H3): los mensajes publicos usan rutas RELATIVAS al proyecto y NUNCA imprimen
secretos, contenido de `.env`, variables de entorno completas ni rutas absolutas del usuario.

Contrato:
    check_environment(...) -> {
        "status": "ready" | "degraded" | "blocked",
        "checks": [ {id, status, required_for, message, action}, ... ],
        "capabilities": { nombre: {available: bool, message: str}, ... },
    }

Reglas de `status`:
    ready    -> todas las capacidades instaladas (ningun check en error ni warning).
    degraded -> la UI arranca pero falta una capacidad concreta (ffmpeg/ffprobe/modelos).
    blocked  -> no se puede iniciar de forma segura: venv invalido, Python no soportado o
                import critico ausente. FFmpeg o modelos ausentes NUNCA son 'blocked'.

CLI:
    python -m system_preflight            # informe legible, exit 0 salvo blocked
    python -m system_preflight --json     # informe JSON
    python -m system_preflight --strict-local
        # modo para check.bat: exige el entorno LOCAL completo del producto (Python soportado,
        # ejecucion desde el venv, ffmpeg, ffprobe, al menos un detector, imports criticos).
        # exit 1 si algo necesario falta.
"""

from __future__ import annotations

import importlib.util
import shutil
import socket
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import model_assets

ROOT = Path(__file__).resolve().parent

# Version soportada del proyecto. mediapipe==0.10.35 y las demas deps estan validadas en 3.12.x.
SUPPORTED_PYTHON = (3, 12)

# Imports criticos MINIMOS para servir la UI. Su ausencia es 'blocked' (no hay app sin ellos).
CRITICAL_IMPORTS = ("fastapi", "uvicorn")

# Directorios esenciales que la app crea/usa.
ESSENTIAL_DIRS = ("input", "output", "transcripts", "thumbs", "static")


# ── Helpers de presentacion segura ────────────────────────────────────────────
def _rel(path: Path, root: Path) -> str:
    """Ruta RELATIVA a la raiz (con separadores nativos) para mensajes publicos.

    Si por algun motivo la ruta cae fuera de la raiz, se devuelve SOLO el basename: nunca se
    filtra una ruta absoluta del usuario.
    """
    try:
        return str(Path(path).resolve().relative_to(root))
    except (ValueError, OSError):
        return Path(path).name


def _default_import_probe(module: str) -> bool:
    """True si el modulo es importable (sin ejecutarlo). Inyectable en tests."""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _default_port_in_use(host: str, port: int) -> bool:
    """True si algo ya escucha en host:port. Conexion local, sin red externa."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            return s.connect_ex((host, port)) == 0
        except OSError:
            return False


def _check(id_: str, status: str, required_for: list[str], message: str, action: str) -> dict:
    return {
        "id": id_,
        "status": status,
        "required_for": required_for,
        "message": message,
        "action": action,
    }


# ── Checks individuales ────────────────────────────────────────────────────────
def _check_python(version: tuple[int, int, int]) -> dict:
    major, minor = version[0], version[1]
    exact = f"{version[0]}.{version[1]}.{version[2]}"
    if (major, minor) == SUPPORTED_PYTHON:
        return _check(
            "python",
            "ok",
            ["ui"],
            f"Python {exact} (soportado {SUPPORTED_PYTHON[0]}.{SUPPORTED_PYTHON[1]}.x).",
            "",
        )
    return _check(
        "python",
        "error",
        ["ui"],
        (
            f"Python {exact} no es la version soportada "
            f"({SUPPORTED_PYTHON[0]}.{SUPPORTED_PYTHON[1]}.x)."
        ),
        (
            f"Centrito Studio requiere Python {SUPPORTED_PYTHON[0]}.{SUPPORTED_PYTHON[1]}. "
            f"Crea el entorno con: py -{SUPPORTED_PYTHON[0]}.{SUPPORTED_PYTHON[1]} -m venv venv"
        ),
    )


def _check_venv(executable: str, venv_dir: Path, root: Path) -> dict:
    """Valida que el proceso corra con el interprete del venv del proyecto.

    No basta con 'activar' el venv: se comprueba que `sys.executable` este DENTRO de `venv/`.
    """
    try:
        exe = Path(executable).resolve()
        vroot = venv_dir.resolve()
        dentro = vroot == exe or vroot in exe.parents
    except OSError:
        dentro = False
    if dentro:
        return _check(
            "venv",
            "ok",
            ["ui"],
            f"Ejecutando desde el entorno virtual del proyecto ({_rel(venv_dir, root)}).",
            "",
        )
    return _check(
        "venv",
        "error",
        ["ui"],
        "El proceso no se esta ejecutando desde el entorno virtual del proyecto.",
        "Usa venv\\Scripts\\python.exe (no confies solo en 'activate'). Crea el venv: "
        "py -3.12 -m venv venv && venv\\Scripts\\python.exe -m pip install -r requirements.txt",
    )


def _check_binario(
    nombre: str, which: Callable[[str], str | None], required_for: list[str]
) -> dict:
    """Check de un binario multimedia (ffmpeg/ffprobe). Ausente -> warning (degradable)."""
    if which(nombre) is not None:
        return _check(nombre, "ok", required_for, f"{nombre} disponible en el PATH.", "")
    return _check(
        nombre,
        "warning",
        required_for,
        f"{nombre} no esta en el PATH; las funciones que lo usan quedan deshabilitadas.",
        "Instala FFmpeg (incluye ffmpeg y ffprobe) y reinicia Centrito Studio. "
        "En Windows: choco install ffmpeg. Comprueba con: ffmpeg -version",
    )


def _check_modelo(asset: model_assets.ModelAsset, root: Path) -> dict:
    """Check de un modelo de deteccion. Ausente -> warning (reframe degradable)."""
    if model_assets.model_present(asset, root):
        return _check(
            f"model_{asset.id}",
            "ok",
            ["reframe", f"detector_{asset.id}"],
            f"Modelo {asset.id} presente ({asset.rel_path}).",
            "",
        )
    return _check(
        f"model_{asset.id}",
        "warning",
        ["reframe", f"detector_{asset.id}"],
        f"Modelo {asset.id} ausente (esperado en {asset.rel_path}).",
        f"Instalalo con: {asset.install_hint}",
    )


def _check_imports(modules: Sequence[str], probe: Callable[[str], bool]) -> dict:
    faltantes = [m for m in modules if not probe(m)]
    if not faltantes:
        return _check(
            "imports",
            "ok",
            ["ui"],
            f"Imports criticos disponibles ({', '.join(modules)}).",
            "",
        )
    return _check(
        "imports",
        "error",
        ["ui"],
        f"Faltan imports criticos: {', '.join(faltantes)}.",
        "Reinstala dependencias: venv\\Scripts\\python.exe -m pip install -r requirements.txt",
    )


def _check_dirs(dirs: Sequence[str], root: Path) -> dict:
    faltantes = [d for d in dirs if not (root / d).is_dir()]
    if not faltantes:
        return _check("dirs", "ok", ["ui"], "Directorios esenciales presentes.", "")
    # La app los crea al importarse; si faltan aqui es informativo (warning, no bloquea).
    return _check(
        "dirs",
        "warning",
        ["ui"],
        f"Directorios ausentes (se crearan al arrancar): {', '.join(faltantes)}.",
        "",
    )


# ── Capacidades derivadas ──────────────────────────────────────────────────────
def _cap(available: bool, ok_msg: str, ko_msg: str) -> dict:
    return {"available": available, "message": ok_msg if available else ko_msg}


def _build_capabilities(*, ffmpeg: bool, ffprobe: bool, yunet: bool, blazeface: bool) -> dict:
    render = ffmpeg and ffprobe
    reframe = render and (yunet or blazeface)
    return {
        "ffmpeg": _cap(ffmpeg, "FFmpeg disponible.", "FFmpeg no esta instalado."),
        "ffprobe": _cap(ffprobe, "ffprobe disponible.", "ffprobe no esta instalado."),
        "video_metadata": _cap(
            ffprobe, "Analisis de metadata de video disponible.", "Requiere ffprobe."
        ),
        "upload_validation": _cap(
            ffprobe, "Validacion de subidas disponible.", "Requiere ffprobe."
        ),
        "render": _cap(render, "Render de captions disponible.", "Requiere ffmpeg y ffprobe."),
        "auto": _cap(render, "Modo Automatico disponible.", "Requiere ffmpeg y ffprobe."),
        "clips": _cap(render, "Generacion de clips disponible.", "Requiere ffmpeg y ffprobe."),
        "reframe": _cap(
            reframe,
            "Reframe 9:16 con seguimiento facial disponible.",
            "Requiere ffmpeg, ffprobe y al menos un detector (YuNet o BlazeFace).",
        ),
        "detector_yunet": _cap(yunet, "Detector YuNet disponible.", "Modelo YuNet ausente."),
        "detector_blazeface": _cap(
            blazeface, "Detector BlazeFace disponible.", "Modelo BlazeFace ausente."
        ),
    }


# ── Informe global ─────────────────────────────────────────────────────────────
def check_environment(
    *,
    version: tuple[int, int, int] | None = None,
    executable: str | None = None,
    venv_dir: Path | None = None,
    which: Callable[[str], str | None] | None = None,
    import_probe: Callable[[str], bool] | None = None,
    port_in_use: Callable[[str, int], bool] | None = None,
    root: Path = ROOT,
    port: tuple[str, int] | None = None,
) -> dict:
    """Informe estructurado del entorno. Ver contrato en el docstring del modulo."""
    version = version if version is not None else tuple(sys.version_info[:3])  # type: ignore[assignment]
    executable = executable if executable is not None else sys.executable
    venv_dir = venv_dir if venv_dir is not None else (root / "venv")
    which = which if which is not None else shutil.which
    import_probe = import_probe if import_probe is not None else _default_import_probe

    checks: list[dict] = [
        _check_python(version),
        _check_venv(executable, venv_dir, root),
        _check_imports(CRITICAL_IMPORTS, import_probe),
        _check_binario("ffmpeg", which, ["render", "auto", "clips", "reframe", "video_metadata"]),
        _check_binario("ffprobe", which, ["render", "video_metadata", "upload_validation"]),
    ]
    checks += [_check_modelo(m, root) for m in model_assets.MODELS]
    checks.append(_check_dirs(ESSENTIAL_DIRS, root))

    ffmpeg = which("ffmpeg") is not None
    ffprobe = which("ffprobe") is not None
    yunet = model_assets.model_present(model_assets.YUNET, root)
    blazeface = model_assets.model_present(model_assets.BLAZEFACE_SHORT, root)
    capabilities = _build_capabilities(
        ffmpeg=ffmpeg, ffprobe=ffprobe, yunet=yunet, blazeface=blazeface
    )

    if port is not None:
        pic = port_in_use if port_in_use is not None else _default_port_in_use
        host, pnum = port
        ocupado = pic(host, pnum)
        checks.append(
            _check(
                "port",
                "warning" if ocupado else "ok",
                ["ui"],
                (f"El puerto {pnum} esta ocupado." if ocupado else f"El puerto {pnum} esta libre."),
                (
                    "Cierra la aplicacion que lo usa o inicia en modo diagnostico con otro puerto."
                    if ocupado
                    else ""
                ),
            )
        )

    status = _global_status(checks)
    return {"status": status, "checks": checks, "capabilities": capabilities}


def _global_status(checks: Sequence[dict]) -> str:
    """blocked si hay algun check en error; degraded si hay warnings; ready en caso contrario.

    Los checks 'error' solo los emiten python/venv/imports (fatales). ffmpeg/ffprobe/modelos/
    puerto son 'warning' -> a lo sumo 'degraded'.
    """
    if any(c["status"] == "error" for c in checks):
        return "blocked"
    if any(c["status"] == "warning" for c in checks):
        return "degraded"
    return "ready"


# ── CLI ────────────────────────────────────────────────────────────────────────
def _print_report(report: dict) -> None:
    icon = {"ok": "[OK]", "warning": "[!]", "error": "[X]"}
    print(f"Estado del entorno: {report['status'].upper()}")
    for c in report["checks"]:
        print(f"  {icon.get(c['status'], '[?]')} {c['id']}: {c['message']}")
        if c["status"] != "ok" and c["action"]:
            print(f"      -> {c['action']}")


def _strict_local_ok(report: dict) -> tuple[bool, list[str]]:
    """Entorno LOCAL completo del producto: sin 'blocked' + ffmpeg + ffprobe + >=1 detector.

    Devuelve (ok, motivos_de_fallo). Usado por check.bat (modo estricto local).
    """
    motivos: list[str] = []
    if report["status"] == "blocked":
        motivos += [
            f"{c['id']}: {c['action'] or c['message']}"
            for c in report["checks"]
            if c["status"] == "error"
        ]
    caps = report["capabilities"]
    if not caps["ffmpeg"]["available"]:
        motivos.append("ffmpeg ausente (instala FFmpeg).")
    if not caps["ffprobe"]["available"]:
        motivos.append("ffprobe ausente (instala FFmpeg).")
    if not (caps["detector_yunet"]["available"] or caps["detector_blazeface"]["available"]):
        motivos.append("sin detector funcional (corre scripts\\setup_models.py).")
    return (len(motivos) == 0, motivos)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    strict = "--strict-local" in argv
    as_json = "--json" in argv
    report = check_environment()

    if as_json:
        import json  # noqa: PLC0415

        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_report(report)

    if strict:
        ok, motivos = _strict_local_ok(report)
        if not ok:
            print("\n[X] Entorno local incompleto para el producto:")
            for m in motivos:
                print(f"    - {m}")
            return 1
        print("\n[OK] Entorno local listo (Python, venv, ffmpeg, ffprobe, detector, imports).")
        return 0

    # Modo normal: solo 'blocked' es exit != 0.
    return 1 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
