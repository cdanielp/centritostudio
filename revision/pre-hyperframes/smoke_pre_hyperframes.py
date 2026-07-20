"""Smoke de readiness pre-HyperFrames — arnes SINTETICO, AISLADO, sin red, sin GPU.

Corre un subconjunto reproducible de comprobaciones sobre el Studio via TestClient (no abre
puerto). A diferencia del primer arnes (que tenia un defecto de aislamiento detectado en review),
esta version monta la app sobre un SANDBOX temporal completo: TODOS los directorios reales del
repo (input/ transcripts/ output/ clips/ thumbs/ static/) se redirigen a un TemporaryDirectory y
los mounts StaticFiles se reconstruyen para apuntar ahi. NO se abre, imprime ni versiona
`input/0717_corregido.srt` ni ningun archivo real bajo input/ transcripts/ output/.

Contrato de resultados (probes de seguridad):
    - 2xx con escape/exposicion            -> BLOCKER
    - 4xx explicito y SIN efecto lateral   -> PASS
    - 5xx                                  -> FAIL
    - excepcion interna propagada          -> FAIL
    - rechazo del transporte (no llega)    -> PASS (sin efecto, sin escape)
    - respuesta inesperada                 -> FAIL
Una excepcion NUNCA es PASS.

Uso:
    $env:PYTHONIOENCODING="utf-8"
    .\\venv\\Scripts\\python revision\\pre-hyperframes\\smoke_pre_hyperframes.py
    .\\venv\\Scripts\\python revision\\pre-hyperframes\\smoke_pre_hyperframes.py --self-test

Salida: matriz PASS/FAIL/BLOCKER + evidencia JSON (NO versionada) en
output/revision-pre-hyperframes/smoke_report.json. Exit code != 0 si hay BLOCKERs/FAILs.

Nota: el E2E completo (render classic/CVE/reframe/Auto/SRT/resume/editor) requiere FFmpeg y esta
DIFERIDO hasta cerrar H1-H3 (hoy fallaria por los propios P0/P1 auditados). Este arnes cubre
salud, contratos de endpoints y las probes de seguridad/exposicion que definen readiness.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import urllib.parse
from pathlib import Path

REAL_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REAL_ROOT))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

# La evidencia se computa contra el ROOT REAL (unico archivo que el arnes puede escribir fuera
# del sandbox). Todo lo demas ocurre dentro del TemporaryDirectory.
EVID_DIR = REAL_ROOT / "output" / "revision-pre-hyperframes"
ALLOWED_REAL_WRITE = EVID_DIR / "smoke_report.json"

TOKEN = "_SMOKE_PRE_HF_SENTINEL"
SYNTH_ASS_TEXT = "texto-sintetico-de-prueba-no-privado"

results: list[dict] = []


def record(name: str, status: str, detail: str) -> None:
    """status in {PASS, FAIL, BLOCKER, SKIP}."""
    results.append({"check": name, "status": status, "detail": detail})
    icon = {"PASS": "[OK]", "FAIL": "[X ]", "BLOCKER": "[!!]", "SKIP": "[--]"}[status]
    print(f"{icon} {name}: {detail}")


# ─────────────────────────────────────────────────────────────────────────────
# Funciones PURAS de clasificacion (testeables sin red).
# ─────────────────────────────────────────────────────────────────────────────
_SEV = {"PASS": 0, "SKIP": 0, "FAIL": 1, "BLOCKER": 2}


def classify_traversal(kind: str, status: int | None, escaped: bool) -> str:
    """Clasifica una probe de traversal. `kind` in {response, exception, transport}.

    Una excepcion interna del server NUNCA es PASS. Un escape SIEMPRE es BLOCKER.
    """
    if escaped:
        return "BLOCKER"  # escribio/leyo fuera del directorio permitido
    if kind == "transport":
        return "PASS"  # el payload ni siquiera llego al server; sin efecto lateral
    if kind == "exception":
        return "FAIL"  # excepcion interna no manejada (p.ej. un fix que la vuelve 500/crash)
    if status is None:
        return "FAIL"
    if 200 <= status < 300:
        return "FAIL"  # acepto un nombre invalido (sin escape aqui, pero deberia ser 4xx)
    if 400 <= status < 500:
        return "PASS"  # rechazo explicito y sin efecto lateral
    return "FAIL"  # 3xx/5xx/otros


def classify_exposure(kind: str, status: int | None, served: bool) -> str:
    """Clasifica una probe de exposicion (un mount sirviendo texto/binario privado)."""
    if served:
        return "BLOCKER"
    if kind == "transport":
        return "PASS"
    if kind == "exception":
        return "FAIL"
    if status is None:
        return "FAIL"
    if status == 404:
        return "PASS"
    if 400 <= status < 500:
        return "PASS"
    return "FAIL"  # 2xx-no-servido / 5xx / otros inesperados


def worst(statuses: list[str]) -> str:
    if not statuses:
        return "FAIL"
    return max(statuses, key=lambda s: _SEV.get(s, 1))


# ─────────────────────────────────────────────────────────────────────────────
# Sandbox: redirige globals + reconstruye mounts sobre un TemporaryDirectory.
# ─────────────────────────────────────────────────────────────────────────────
_MOUNT_DIR = {
    "input": ("INPUT_DIR", "input"),
    "output": ("OUTPUT_DIR", "output"),
    "clips": ("CLIPS_DIR", "output/clips"),
    "thumbs": ("THUMBS_DIR", "thumbs"),
    "static": ("STATIC_DIR", "static"),
}


@contextlib.contextmanager
def sandboxed_app():
    """Devuelve (app_mod, client, sandbox_root, escape_catch) con TODO redirigido al sandbox.

    Restaura globals y mounts al salir. Usa raise_server_exceptions=True para poder distinguir
    una respuesta HTTP controlada de una excepcion interna propagada por TestClient.
    """
    from fastapi.staticfiles import StaticFiles
    from fastapi.testclient import TestClient
    from starlette.routing import Mount

    import app as app_mod

    with (
        tempfile.TemporaryDirectory(prefix="smoke_hf_sandbox_") as sb,
        tempfile.TemporaryDirectory(prefix="smoke_hf_escape_") as ec,
    ):
        sandbox = Path(sb).resolve()
        escape_catch = Path(ec).resolve()
        subdirs = {
            "input": sandbox / "input",
            "transcripts": sandbox / "transcripts",
            "output": sandbox / "output",
            "clips": sandbox / "output" / "clips",
            "thumbs": sandbox / "thumbs",
            "static": sandbox / "static",
        }
        for d in subdirs.values():
            d.mkdir(parents=True, exist_ok=True)
        # index.html sintetico para que GET / responda sin tocar el static real.
        (subdirs["static"] / "index.html").write_text(
            "<!doctype html><title>smoke</title>ok", encoding="utf-8"
        )

        # 1) Redirigir globals del modulo (los endpoints los resuelven en cada llamada).
        saved_globals = {
            k: getattr(app_mod, k)
            for k in (
                "ROOT",
                "INPUT_DIR",
                "TRANSCRIPTS",
                "OUTPUT_DIR",
                "CLIPS_DIR",
                "THUMBS_DIR",
                "STATIC_DIR",
            )
        }
        app_mod.ROOT = sandbox
        app_mod.INPUT_DIR = subdirs["input"]
        app_mod.TRANSCRIPTS = subdirs["transcripts"]
        app_mod.OUTPUT_DIR = subdirs["output"]
        app_mod.CLIPS_DIR = subdirs["clips"]
        app_mod.THUMBS_DIR = subdirs["thumbs"]
        app_mod.STATIC_DIR = subdirs["static"]

        # 2) Reconstruir los mounts StaticFiles (creados al importar app, apuntaban a lo real).
        saved_mounts: list[tuple] = []
        for route in app_mod.app.router.routes:
            if isinstance(route, Mount) and route.name in _MOUNT_DIR:
                _, sub = _MOUNT_DIR[route.name]
                target = str(sandbox / sub)
                # /output conserva el bloqueo de paquetes/ (misma clase de produccion).
                cls = type(route.app)
                if route.name == "output":
                    new_app = app_mod._OutputSinPaquetes(directory=target)  # noqa: SLF001
                elif cls is StaticFiles or issubclass(cls, StaticFiles):
                    new_app = StaticFiles(directory=target)
                else:  # pragma: no cover - mounts inesperados
                    continue
                saved_mounts.append((route, route.app))
                route.app = new_app

        client = TestClient(app_mod.app, raise_server_exceptions=True)
        try:
            yield app_mod, client, sandbox, escape_catch
        finally:
            client.close()
            for route, old in saved_mounts:
                route.app = old
            for k, v in saved_globals.items():
                setattr(app_mod, k, v)


# ─────────────────────────────────────────────────────────────────────────────
# Deteccion / limpieza de centinelas fuera del directorio permitido.
# ─────────────────────────────────────────────────────────────────────────────
def _escape_scan_dirs(sandbox: Path, escape_catch: Path) -> list[Path]:
    """Directorios candidatos donde un traversal podria depositar el centinela (metadata-only).

    Incluye la RAIZ del disco (`sandbox.anchor` = `C:\\` / `/`): un filename multipart tipo
    `/x.mp4` resuelve a `INPUT_DIR / "/x.mp4"` = `<drive>:\\x.mp4`, es decir la raiz. En este
    equipo ese write lo bloquea el SO por permisos (se reporta FAIL, nunca PASS), pero si corriera
    con privilegios o un fix futuro habilitara el vector, el escape se clasifica BLOCKER y se
    limpia igual. Duplicados entre entradas son inofensivos (el escaneo deduplica por `seen`).
    """
    dirs = [
        escape_catch,
        sandbox,  # un solo `../` desde un subdir cae aqui (fuera del subdir permitido)
        sandbox.parent,  # `../../` cae en el tempdir raiz del SO
        REAL_ROOT,
        REAL_ROOT.parent,
    ]
    for anchor in (sandbox.anchor, REAL_ROOT.anchor):
        if anchor:
            dirs.append(Path(anchor))
    return dirs


def _token_in_dir(d: Path) -> bool:
    """True si algun archivo del dir lleva el TOKEN (solo nombres, nunca contenido)."""
    try:
        return any(TOKEN in c.name for c in d.iterdir())
    except OSError:
        return False


def _find_and_clean(sandbox: Path, escape_catch: Path, allowed_dir: Path) -> list[str]:
    """Devuelve rutas (str) de centinelas hallados FUERA de `allowed_dir` y los borra.

    Solo inspecciona NOMBRES de archivo (iterdir), nunca contenido. `allowed_dir` es el unico
    subdir donde el endpoint deberia escribir; cualquier centinela fuera de el es un escape.
    """
    escapes: list[str] = []
    seen: set[str] = set()
    allowed = allowed_dir.resolve()
    for d in _escape_scan_dirs(sandbox, escape_catch):
        try:
            children = list(d.iterdir())
        except OSError:
            continue
        for child in children:
            if TOKEN not in child.name:
                continue
            rp = str(child.resolve())
            if rp in seen:
                continue
            with contextlib.suppress(OSError):
                if child.resolve().parent == allowed:
                    continue  # dentro del directorio permitido: no es escape
            seen.add(rp)
            escapes.append(rp)
            with contextlib.suppress(OSError):
                child.unlink()
    # Limpieza de restos DENTRO del directorio permitido (p.ej. nombre con backslash literal en
    # POSIX): no cuenta como escape, pero no debe quedar basura.
    with contextlib.suppress(OSError):
        for child in allowed_dir.iterdir():
            if TOKEN in child.name:
                with contextlib.suppress(OSError):
                    child.unlink()
    return escapes


def _do_request(fn) -> tuple[str, int | None, object]:
    """Ejecuta una request y normaliza a (kind, status, resp). Distingue transporte vs server."""
    try:
        import httpx  # noqa: PLC0415

        transport_errs = (httpx.InvalidURL, httpx.LocalProtocolError, UnicodeError, ValueError)
    except Exception:  # noqa: BLE001
        transport_errs = (UnicodeError, ValueError)
    try:
        resp = fn()
        return "response", resp.status_code, resp
    except transport_errs:
        return "transport", None, None
    except Exception:  # noqa: BLE001 - excepcion interna del server propagada por TestClient
        return "exception", None, None


# ─────────────────────────────────────────────────────────────────────────────
# Probes de seguridad.
# ─────────────────────────────────────────────────────────────────────────────
def probe_traversal_write(client, sandbox: Path, escape_catch: Path) -> dict:
    """P0-1: PUT /api/videos/{name}/transcript con nombres de traversal (Win + POSIX + absolutos).

    Escribe `{name}_groups.json`. El sufijo `_groups.json` se anexa; el token va en `{name}`.
    """
    transcripts = sandbox / "transcripts"
    abs_win = str(escape_catch / f"{TOKEN}_win")  # absoluto real de este SO (sirve de "absoluto")
    payloads = {
        "win_backslash": f"..\\..\\{TOKEN}_a",
        "posix_slash": f"../../{TOKEN}_b",
        "absoluto": abs_win,
        "dot_segments": f"....//....//{TOKEN}_c",
        "nul_byte": f"{TOKEN}_d\x00",
    }
    per: dict[str, str] = {}
    for label, name in payloads.items():
        quoted = urllib.parse.quote(name, safe="")
        kind, status, _ = _do_request(
            lambda q=quoted: client.put(
                f"/api/videos/{q}/transcript", json=[{"id": 0, "text": "x", "edited": False}]
            )
        )
        escapes = _find_and_clean(sandbox, escape_catch, transcripts)
        per[label] = classify_traversal(kind, status, bool(escapes))
    verdict = worst(list(per.values()))
    detail = "; ".join(f"{k}={v}" for k, v in per.items())
    if verdict == "BLOCKER":
        record(
            "traversal_escritura_bloqueada",
            "BLOCKER",
            f"P0-1: escape de escritura reproducido ({detail})",
        )
    else:
        record("traversal_escritura_bloqueada", verdict, f"PUT traversal ({detail})")
    return {"verdict": verdict, "per": per}


def probe_traversal_upload(client, sandbox: Path, escape_catch: Path) -> dict:
    """P0-2: POST /api/videos/upload con filenames de traversal en el multipart."""
    inp = sandbox / "input"
    abs_win = str(escape_catch / f"{TOKEN}_up_win.mp4")
    filenames = {
        "win_backslash": f"..\\..\\{TOKEN}_up_a.mp4",
        "posix_slash": f"../../{TOKEN}_up_b.mp4",
        "absoluto": abs_win,
        "root_posix": f"/{TOKEN}_up_c.mp4",
    }
    per: dict[str, str] = {}
    for label, fname in filenames.items():
        kind, status, _ = _do_request(
            lambda fn=fname: client.post(
                "/api/videos/upload",
                files={"file": (fn, io.BytesIO(b"\x00\x00fake"), "video/mp4")},
            )
        )
        # Detectar (antes de limpiar) si el archivo quedo DENTRO del sandbox: en algunas versiones
        # de Starlette el parser multipart neutraliza el path del filename a un basename, asi que
        # payloads absolutos/root NO escapan y se escriben contenidos (defensa del transporte).
        wrote_inside = _token_in_dir(inp)
        escapes = _find_and_clean(sandbox, escape_catch, inp)
        # upload_video corre ffprobe sobre bytes falsos -> excepcion incidental posterior a la
        # escritura. El escape (si lo hubo) prima; una escritura contenida en el sandbox es un
        # rechazo efectivo del traversal por el transporte (PASS), no un fallo del server.
        if escapes:
            per[label] = "BLOCKER"
        elif wrote_inside:
            per[label] = "PASS"
        else:
            per[label] = classify_traversal(kind, status, False)
    verdict = worst(list(per.values()))
    detail = "; ".join(f"{k}={v}" for k, v in per.items())
    if verdict == "BLOCKER":
        record(
            "traversal_upload_bloqueada",
            "BLOCKER",
            f"P0-2: escape via multipart filename ({detail})",
        )
    else:
        record("traversal_upload_bloqueada", verdict, f"upload traversal ({detail})")
    return {"verdict": verdict, "per": per}


def probe_output_ass(client, sandbox: Path) -> dict:
    """P0-3: el mount /output NO debe servir texto de captions (.ass sintetico)."""
    probe = sandbox / "output" / f"{TOKEN}_caption.ass"
    probe.write_text(f"[Events]\nDialogue: {SYNTH_ASS_TEXT}\n", encoding="utf-8")
    verdict = "FAIL"  # default defensivo si _do_request cambiara y propagara
    try:
        kind, status, resp = _do_request(lambda: client.get(f"/output/{probe.name}"))
        served = kind == "response" and status == 200 and SYNTH_ASS_TEXT in resp.text
        verdict = classify_exposure(kind, status, served)
        if verdict == "BLOCKER":
            record(
                "output_no_sirve_ass",
                "BLOCKER",
                "P0-3: /output sirvio el .ass con texto de captions",
            )
        else:
            record("output_no_sirve_ass", verdict, f"/output/*.ass -> {status} (no expone texto)")
    finally:
        with contextlib.suppress(OSError):
            probe.unlink()
    return {"verdict": verdict}


def probe_input_exposure(client, sandbox: Path) -> dict:
    """P0-4 (LAN): el mount /input sirve el binario fuente crudo a cualquiera en la red."""
    probe = sandbox / "input" / f"{TOKEN}_source.mp4"
    probe.write_bytes(b"SYNTHSRC0123456789")
    verdict = "FAIL"  # default defensivo si _do_request cambiara y propagara
    try:
        kind, status, resp = _do_request(lambda: client.get(f"/input/{probe.name}"))
        served = kind == "response" and status == 200 and resp.content == b"SYNTHSRC0123456789"
        verdict = classify_exposure(kind, status, served)
        if verdict == "BLOCKER":
            record(
                "input_no_expuesto_lan",
                "BLOCKER",
                "P0-4: /input sirve el binario fuente sin auth (exposicion LAN)",
            )
        else:
            record("input_no_expuesto_lan", verdict, f"/input/<src> -> {status}")
    finally:
        with contextlib.suppress(OSError):
            probe.unlink()
    return {"verdict": verdict}


# ─────────────────────────────────────────────────────────────────────────────
# Defensa: snapshot de directorios reales (metadata-only, sin leer contenido).
# ─────────────────────────────────────────────────────────────────────────────
def _snapshot_real() -> dict[str, tuple[int, int]]:
    snap: dict[str, tuple[int, int]] = {}
    reales = [REAL_ROOT / d for d in ("input", "transcripts", "output", "thumbs", "static")]
    for base in reales:
        if not base.exists():
            continue
        for dirpath, _dirs, files in os.walk(base):
            for fn in files:
                p = Path(dirpath) / fn
                try:
                    if p.resolve() == ALLOWED_REAL_WRITE.resolve():
                        continue  # el reporte de evidencia es la unica escritura permitida
                except OSError:
                    pass
                # excluir todo el arbol de evidencia
                with contextlib.suppress(OSError):
                    if EVID_DIR.resolve() in p.resolve().parents:
                        continue
                try:
                    st = p.stat()
                    snap[str(p)] = (st.st_size, st.st_mtime_ns)
                except OSError:
                    continue
    return snap


def _diff_snapshots(before: dict, after: dict) -> list[str]:
    diffs = []
    for k in after.keys() - before.keys():
        diffs.append(f"CREADO {k}")
    for k in before.keys() - after.keys():
        diffs.append(f"BORRADO {k}")
    for k in before.keys() & after.keys():
        if before[k] != after[k]:
            diffs.append(f"MODIFICADO {k}")
    return diffs


# ─────────────────────────────────────────────────────────────────────────────
# Corrida principal.
# ─────────────────────────────────────────────────────────────────────────────
def run_smoke() -> int:
    EVID_DIR.mkdir(parents=True, exist_ok=True)
    results.clear()
    snap_before = _snapshot_real()

    try:
        with sandboxed_app() as (app_mod, client, sandbox, escape_catch):
            record("sandbox_activo", "PASS", f"app redirigida a sandbox temporal ({sandbox.name})")

            # 1. Salud: la UI (sintetica) responde.
            kind, status, _ = _do_request(lambda: client.get("/"))
            record("health_ui", "PASS" if status == 200 else "FAIL", f"GET / -> {status}")

            # 2. Contrato jobs: inexistente -> 404 distinguible.
            kind, status, _ = _do_request(lambda: client.get("/api/jobs/no-existe-xyz"))
            record(
                "job_inexistente_404",
                "PASS" if status == 404 else "FAIL",
                f"GET /api/jobs/no-existe -> {status} (esperado 404)",
            )

            # 3. Listado de videos: solo fixtures sinteticos del sandbox.
            # Fixture: un mp4 sintetico + su info.json + thumb precacheados (sin ffprobe/ffmpeg).
            (sandbox / "input" / "demo.mp4").write_bytes(b"SYNTH")
            (sandbox / "transcripts" / "demo_info.json").write_text(
                json.dumps({"duration": 1.0, "width": 1080, "height": 1920, "has_audio": True}),
                encoding="utf-8",
            )
            (sandbox / "thumbs" / "demo.jpg").write_bytes(b"JPG")
            kind, status, resp = _do_request(lambda: client.get("/api/videos"))
            names = (
                [v.get("name") for v in resp.json()]
                if kind == "response" and status == 200
                else None
            )
            ok_videos = names == ["demo"]
            record(
                "listar_videos_sandbox",
                "PASS" if ok_videos else "FAIL",
                f"GET /api/videos -> {status}, nombres={names} (solo fixtures del sandbox)",
            )

            # 4. Probes de seguridad P0.
            probe_traversal_write(client, sandbox, escape_catch)
            probe_traversal_upload(client, sandbox, escape_catch)
            probe_output_ass(client, sandbox)
            probe_input_exposure(client, sandbox)

            # 5. E2E diferido.
            import shutil  # noqa: PLC0415

            motivo = "FFmpeg ausente" if shutil.which("ffmpeg") is None else "P1-OUT abiertos"
            record("e2e_render", "SKIP", f"E2E render diferido a H1-H3 ({motivo})")

            # Limpieza final de centinelas: no debe quedar ninguno.
            leftovers = []
            for d in _escape_scan_dirs(sandbox, escape_catch):
                try:
                    leftovers += [str(c) for c in d.iterdir() if TOKEN in c.name]
                except OSError:
                    continue
            record(
                "sin_centinelas_residuales",
                "PASS" if not leftovers else "FAIL",
                "sin centinelas fuera del sandbox" if not leftovers else f"residuos: {leftovers}",
            )
    finally:
        snap_after = _snapshot_real()
        diffs = _diff_snapshots(snap_before, snap_after)
        record(
            "aislamiento_datos_reales",
            "PASS" if not diffs else "BLOCKER",
            "cero cambios en directorios reales"
            if not diffs
            else f"el arnes toco datos reales: {diffs}",
        )

    return _flush()


def _flush() -> int:
    blockers = [r for r in results if r["status"] == "BLOCKER"]
    fails = [r for r in results if r["status"] == "FAIL"]
    report = {
        "base": "4a378d8",
        "harness": "sandboxed-v2",
        "total": len(results),
        "blockers": len(blockers),
        "fails": len(fails),
        "results": results,
    }
    (EVID_DIR / "smoke_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\n=== RESUMEN ===")
    print(f"checks={len(results)} blockers={len(blockers)} fails={len(fails)}")
    print(f"evidencia (no versionada): {EVID_DIR / 'smoke_report.json'}")
    if blockers:
        print("VEREDICTO: NO LISTO — hay BLOCKERs P0 abiertos.")
        return 1
    if fails:
        print("VEREDICTO: revisar FAILs.")
        return 1
    print("VEREDICTO: subconjunto de readiness verde.")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Self-test del propio arnes (PASO 7). Verde aunque el smoke principal salga NO LISTO.
# ─────────────────────────────────────────────────────────────────────────────
def self_test() -> int:
    checks: list[tuple[str, bool]] = []

    def ck(name: str, cond: bool) -> None:
        checks.append((name, bool(cond)))
        print(f"{'[OK]' if cond else '[X ]'} self-test: {name}")

    # Funciones puras (items 4/5/6 del contrato de excepciones).
    ck("04_excepcion_no_es_pass", classify_traversal("exception", None, False) == "FAIL")
    ck("04b_upload_exc_no_pass", classify_exposure("exception", None, False) == "FAIL")
    ck(
        "05_500_es_fail",
        classify_traversal("response", 500, False) == "FAIL"
        and classify_exposure("response", 500, False) == "FAIL",
    )
    ck(
        "06_404_sin_efecto_es_pass",
        classify_traversal("response", 404, False) == "PASS"
        and classify_exposure("response", 404, False) == "PASS",
    )
    ck("06b_2xx_con_escape_es_blocker", classify_traversal("response", 200, True) == "BLOCKER")
    ck("06c_transporte_no_es_fail", classify_traversal("transport", None, False) == "PASS")
    ck("worst_prioriza_blocker", worst(["PASS", "FAIL", "BLOCKER"]) == "BLOCKER")

    with sandboxed_app() as (app_mod, client, sandbox, escape_catch):
        # item 1: TestClient apunta al sandbox.
        ck(
            "01_globals_en_sandbox",
            app_mod.INPUT_DIR == sandbox / "input" and str(sandbox) in str(app_mod.OUTPUT_DIR),
        )
        # item 2: /api/videos lista solo fixtures sinteticos.
        (sandbox / "input" / "solo.mp4").write_bytes(b"S")
        (sandbox / "transcripts" / "solo_info.json").write_text(
            json.dumps({"duration": 1, "width": 10, "height": 10, "has_audio": False}),
            encoding="utf-8",
        )
        (sandbox / "thumbs" / "solo.jpg").write_bytes(b"J")
        r = client.get("/api/videos")
        names = [v["name"] for v in r.json()]
        ck("02_videos_solo_fixtures", names == ["solo"])
        # item 3: un archivo real ficticio FUERA del sandbox no aparece.
        (escape_catch / "fantasma.mp4").write_bytes(b"G")
        r2 = client.get("/api/videos")
        ck("03_archivo_externo_no_aparece", "fantasma" not in [v["name"] for v in r2.json()])
        # item 7/8: payloads Win/POSIX reproducidos y limpiados (main vulnerable -> BLOCKER).
        wr = probe_traversal_write(client, sandbox, escape_catch)
        ck("07_08_traversal_write_detecta_blocker", wr["verdict"] == "BLOCKER")
        # item 9: upload traversal cubierto (main vulnerable -> BLOCKER).
        up = probe_traversal_upload(client, sandbox, escape_catch)
        ck("09_upload_traversal_detecta_blocker", up["verdict"] == "BLOCKER")
        # item 10: /output/*.ass sintetico -> BLOCKER en el codigo actual.
        oa = probe_output_ass(client, sandbox)
        ck("10_output_ass_blocker", oa["verdict"] == "BLOCKER")
        # item 11: /input/<video sintetico> accesible -> BLOCKER (mount presente).
        ie = probe_input_exposure(client, sandbox)
        ck("11_input_expuesto_blocker", ie["verdict"] == "BLOCKER")
        # item 12: no queda ningun centinela tras las probes.
        leftovers = []
        for d in _escape_scan_dirs(sandbox, escape_catch):
            with contextlib.suppress(OSError):
                leftovers += [str(c) for c in d.iterdir() if TOKEN in c.name]
        ck("12_sin_centinelas_residuales", not leftovers)

    ok = all(c for _, c in checks)
    passed = sum(c for _, c in checks)
    print(f"\n=== SELF-TEST: {'VERDE' if ok else 'ROJO'} ({passed}/{len(checks)}) ===")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--self-test" in argv:
        return self_test()
    return run_smoke()


if __name__ == "__main__":
    raise SystemExit(main())
