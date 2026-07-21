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

# Directorios de media reales que `app.py` crea (mkdir) en su init de import (`app.py:40-47`).
# En un checkout limpio no existen: importar `app` los crearia FUERA del sandbox. Se capturan
# antes del import y se limpian (si el arnes los creo y quedaron vacios) para no mutar el repo.
# `output/` (host de la evidencia) y `static/` (UI real) se excluyen a proposito.
_MEDIA_DIRS = [
    REAL_ROOT / "input",
    REAL_ROOT / "transcripts",
    REAL_ROOT / "thumbs",
    REAL_ROOT / "output" / "clips",
]

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

# Los routers montados (`app.include_router`) definen SUS PROPIOS globals de rutas reales, que el
# parcheo de `app` no cubre. Si el TestClient tocara esas rutas, leerian/escribirian el repo real
# -> fuga de privacidad. Se redirigen tambien (attr -> subruta relativa al sandbox; "" = raiz).
_ROUTER_MODULES = {
    "studio_srt_routes": {
        "ROOT": "",
        "INPUT_DIR": "input",
        "TRANSCRIPTS": "transcripts",
        "STUDIO_SRT_DIR": "transcripts/studio_srt",
    },
    "studio_packages": {
        "ROOT": "",
        "PAQUETES_DIR": "output/paquetes",
        "TRANSCRIPTS": "transcripts",
    },
}


def _make_sandbox_tree(sandbox: Path) -> None:
    """Crea la estructura de subdirs del sandbox + un index.html sintetico para GET /."""
    for sub in (
        "input",
        "transcripts",
        "output",
        "output/clips",
        "thumbs",
        "static",
        "transcripts/studio_srt",
        "output/paquetes",
    ):
        (sandbox / sub).mkdir(parents=True, exist_ok=True)
    (sandbox / "static" / "index.html").write_text(
        "<!doctype html><title>smoke</title>ok", encoding="utf-8"
    )


def _patch_app_globals(app_mod, sandbox: Path) -> dict:
    """Redirige los globals de directorios de `app` al sandbox. Devuelve los valores previos."""
    saved = {
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
    for attr, sub in _MOUNT_DIR.values():
        setattr(app_mod, attr, sandbox / sub)
    app_mod.TRANSCRIPTS = sandbox / "transcripts"
    return saved


def _rebuild_mounts(app_mod, sandbox: Path, static_cls, mount_cls) -> list[tuple]:
    """Reconstruye los mounts StaticFiles apuntando al sandbox, PRESERVANDO la clase real.

    Tras H1 los mounts /output //thumbs //clips son subclases con allowlist propia
    (`_OutputMedia`/`_ThumbsMedia`/`_ClipsMedia`); reconstruir con `StaticFiles` plano perderia
    esa allowlist y falsearia las probes. `type(route.app)(directory=...)` conserva la subclase.
    El mount abierto /input ya no existe (P0-4), asi que no aparece aqui. Devuelve (route, previa).
    """
    saved: list[tuple] = []
    for route in app_mod.app.router.routes:
        if isinstance(route, mount_cls) and route.name in _MOUNT_DIR:
            if not isinstance(route.app, static_cls):  # pragma: no cover - mount inesperado
                continue
            target = str(sandbox / _MOUNT_DIR[route.name][1])
            saved.append((route, route.app))
            route.app = type(route.app)(directory=target)
    return saved


def _patch_router_globals(sandbox: Path) -> list[tuple]:
    """Redirige los globals PROPIOS de los routers montados. Devuelve (modulo, attr, previo)."""
    import importlib  # noqa: PLC0415

    saved: list[tuple] = []
    for modname, attrs in _ROUTER_MODULES.items():
        try:
            mod = importlib.import_module(modname)
        except Exception:  # noqa: BLE001 - router opcional/ausente: nada que parchear
            continue
        for attr, rel in attrs.items():
            if hasattr(mod, attr):
                saved.append((mod, attr, getattr(mod, attr)))
                setattr(mod, attr, sandbox if rel == "" else sandbox / rel)
    return saved


@contextlib.contextmanager
def sandboxed_app():
    """Devuelve (app_mod, client, sandbox_root, escape_catch) con TODO redirigido al sandbox.

    Redirige globals de `app` Y de los routers montados, reconstruye los mounts StaticFiles y los
    restaura al salir. Usa raise_server_exceptions=True para distinguir una respuesta HTTP
    controlada de una excepcion interna propagada por TestClient.
    """
    from fastapi.staticfiles import StaticFiles
    from fastapi.testclient import TestClient
    from starlette.routing import Mount

    # `import app` ejecuta su init, que hace mkdir de los dirs de media reales. Se registra cuales
    # existian ANTES para poder revertir (borrar los vacios) los que cree el propio import.
    preexisting_media = {d for d in _MEDIA_DIRS if d.exists()}

    import app as app_mod

    with (
        tempfile.TemporaryDirectory(prefix="smoke_hf_sandbox_") as sb,
        tempfile.TemporaryDirectory(prefix="smoke_hf_escape_") as ec,
    ):
        sandbox = Path(sb).resolve()
        escape_catch = Path(ec).resolve()
        _make_sandbox_tree(sandbox)
        saved_globals = _patch_app_globals(app_mod, sandbox)
        saved_mounts = _rebuild_mounts(app_mod, sandbox, StaticFiles, Mount)
        saved_router_globals = _patch_router_globals(sandbox)

        client = TestClient(app_mod.app, raise_server_exceptions=True)
        try:
            yield app_mod, client, sandbox, escape_catch
        finally:
            client.close()
            for route, old in saved_mounts:
                route.app = old
            for k, v in saved_globals.items():
                setattr(app_mod, k, v)
            for mod, attr, old in saved_router_globals:
                setattr(mod, attr, old)
            # Revertir dirs de media que el import de `app` creo en el repo real (solo si quedaron
            # vacios). `output/clips` primero por si `output` estuviera involucrado.
            for d in reversed(_MEDIA_DIRS):
                if d not in preexisting_media and d.exists():
                    with contextlib.suppress(OSError):
                        d.rmdir()  # falla si no esta vacio -> no se borra nada con contenido


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
    """Ejecuta una request y normaliza a (kind, status, resp). Distingue transporte vs server.

    IMPORTANTE: `transport` SOLO abarca excepciones CONCRETAS del cliente httpx (la request no
    llega al server). NO se captura `ValueError`/`UnicodeError` genericos aqui: el server puede
    propagar un `ValueError` (p.ej. NUL byte -> `embedded null character` en `Path`, o
    `JSONDecodeError`) via TestClient, y clasificarlo como `transport`=PASS seria un FALSO PASS
    que enmascara un crash del endpoint. Esas caen a `exception` -> FAIL.
    """
    try:
        import httpx  # noqa: PLC0415

        transport_errs: tuple = (httpx.InvalidURL, httpx.LocalProtocolError)
    except Exception:  # noqa: BLE001 - sin httpx no hay transporte que distinguir
        transport_errs = ()
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
        # `wrote_inside`: en POSIX el backslash es un char literal, asi que `..\..\x` se escribe
        # CONTENIDO en el sandbox (200, sin escape) en vez de escapar como en Windows. Igual que en
        # el probe de upload, una escritura contenida es un rechazo efectivo del traversal (PASS),
        # no un fallo del server. El escape real (Windows) sigue primando como BLOCKER.
        wrote_inside = _token_in_dir(transcripts)
        escapes = _find_and_clean(sandbox, escape_catch, transcripts)
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


def _served_probe(client, rel_file: Path, url: str, content: bytes) -> str:
    """Escribe `content` en `rel_file`, hace GET `url` y clasifica exposicion. Limpia siempre."""
    rel_file.parent.mkdir(parents=True, exist_ok=True)
    rel_file.write_bytes(content)
    try:
        kind, status, resp = _do_request(lambda: client.get(url))
        served = kind == "response" and status == 200 and resp.content == content
        return classify_exposure(kind, status, served)
    finally:
        with contextlib.suppress(OSError):
            rel_file.unlink()


def probe_output_exposure(client, sandbox: Path) -> dict:
    """P0-3: el mount /output NO debe servir texto privado de captions. Cubre DOS tipos
    documentados: `.ass` (cues) y `.keyword_selection.json` (palabras/frases)."""
    out = sandbox / "output"
    txt = SYNTH_ASS_TEXT.encode()
    per = {
        "ass": _served_probe(
            client,
            out / f"{TOKEN}_caption.ass",
            f"/output/{TOKEN}_caption.ass",
            b"[Events]\nDialogue: " + txt + b"\n",
        ),
        "keyword_selection_json": _served_probe(
            client,
            out / f"{TOKEN}.keyword_selection.json",
            f"/output/{TOKEN}.keyword_selection.json",
            b'{"palabra":"' + txt + b'"}',
        ),
    }
    verdict = worst(list(per.values()))
    detail = "; ".join(f"{k}={v}" for k, v in per.items())
    key = "output_no_expone_texto"
    if verdict == "BLOCKER":
        record(key, "BLOCKER", f"P0-3: /output sirvio texto privado de captions ({detail})")
    else:
        record(key, verdict, f"/output tipos privados -> ({detail})")
    return {"verdict": verdict, "per": per}


def probe_lan_exposure(client, sandbox: Path) -> dict:
    """P0-4 (LAN) — contrato seguro de H1 (regresion de cierre):

    - `/input`: el mount ABIERTO queda ELIMINADO; aunque el binario fuente exista en disco, la
      ruta `/input/<src>.mp4` ya no tiene mount y responde 404 (el fuente se sirve solo por el
      endpoint validado `/api/videos/{name}/source`).
    - `/thumbs` y `/clips`: siguen sirviendo su tipo permitido (imagen / .mp4) porque la UI los
      consume, pero por ALLOWLIST estricta; un sidecar PRIVADO (.ass/.json) NO se sirve.

    Antes de H1 este probe reportaba BLOCKER porque `/input` servia el fuente byte-a-byte. La
    adaptacion al contrato seguro (mount eliminado + allowlist) es legitima, no oculta el P0.
    """
    src = sandbox / "input" / f"{TOKEN}_src.mp4"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(b"SYNTHSRC01")
    try:
        kind, status, resp = _do_request(lambda: client.get(f"/input/{TOKEN}_src.mp4"))
        served = kind == "response" and status == 200 and getattr(resp, "content", b"") == src.read_bytes()
        input_verdict = classify_exposure(kind, status, served)
    finally:
        with contextlib.suppress(OSError):
            src.unlink()

    priv = SYNTH_ASS_TEXT.encode()
    per = {
        "input_mount_eliminado": input_verdict,
        "thumbs_no_sirve_privado": _served_probe(
            client, sandbox / "thumbs" / f"{TOKEN}_t.ass", f"/thumbs/{TOKEN}_t.ass", priv
        ),
        "clips_no_sirve_privado": _served_probe(
            client,
            sandbox / "output" / "clips" / f"{TOKEN}_c.json",
            f"/clips/{TOKEN}_c.json",
            b'{"privado":1}',
        ),
    }
    verdict = worst(list(per.values()))
    detail = "; ".join(f"{k}={v}" for k, v in per.items())
    key = "mounts_no_expuestos_lan"
    if verdict == "BLOCKER":
        record(key, "BLOCKER", f"P0-4: mount privado servido sin auth en LAN ({detail})")
    else:
        record(key, verdict, f"/input eliminado; /thumbs //clips allowlist -> ({detail})")
    return {"verdict": verdict, "per": per}


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
    # Registrar tambien la EXISTENCIA de los dirs de media (no solo archivos): asi, si el import
    # de `app` crea un dir real y la limpieza no lo revierte, el diff lo marca como CREADO ->
    # BLOCKER. `os.walk` sobre archivos no detectaria un directorio vacio recien creado.
    for d in _MEDIA_DIRS:
        if d.exists():
            snap[f"DIR::{d}"] = (-1, -1)
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

            # 4. Probes de seguridad P0 (MUESTRA representativa por P0, no exhaustiva).
            probe_traversal_write(client, sandbox, escape_catch)
            probe_traversal_upload(client, sandbox, escape_catch)
            probe_output_exposure(client, sandbox)
            probe_lan_exposure(client, sandbox)

            # 4b. Honestidad de cobertura: el smoke NO es un gate EXHAUSTIVO de cierre H1. Las
            # probes muestrean UNA superficie por P0 (traversal solo en PUT transcript; el resto
            # de endpoints {name} no se prueba aqui). Un fix parcial que endurezca solo lo
            # muestreado podria dar verde dejando P0s documentados abiertos: ver AUDITORIA.md.
            record(
                "cobertura_p0_no_exhaustiva",
                "SKIP",
                "muestra: traversal solo en PUT /transcript aqui; el resto de endpoints {name} "
                "(brain/analyze/depurar/clips/reframe/turnos/render/auto/source) y el upload/"
                "integridad se cubren en tests/test_h1_*.py (regresiones parametrizadas de H1)",
            )

            # 5. E2E render completo (render classic/CVE/reframe/Auto/SRT) sigue DIFERIDO: requiere
            # FFmpeg + GPU + modelos; su cierre no es alcance de H1 (seguridad+integridad).
            import shutil  # noqa: PLC0415

            motivo = "FFmpeg ausente" if shutil.which("ffmpeg") is None else "requiere GPU/modelos"
            record("e2e_render", "SKIP", f"E2E render completo diferido ({motivo})")

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

    # Review 8efd294 · fix B: un ValueError propagado por el server (p.ej. NUL byte -> "embedded
    # null character") NO es transporte; debe caer a exception -> FAIL, nunca PASS.
    def _raise_value_error():
        raise ValueError("embedded null character")

    ck("B_server_valueerror_es_exception", _do_request(_raise_value_error)[0] == "exception")
    # Review 8efd294 · fix A: el snapshot registra la EXISTENCIA de los dirs de media, de modo que
    # crear un dir real (via import de app) se detectaria como cambio (no solo archivos).
    _snap = _snapshot_real()
    ck(
        "A_snapshot_cubre_media_dirs",
        all((f"DIR::{d}" in _snap) == d.exists() for d in _MEDIA_DIRS),
    )

    with sandboxed_app() as (app_mod, client, sandbox, escape_catch):
        # item 1: TestClient apunta al sandbox.
        ck(
            "01_globals_en_sandbox",
            app_mod.INPUT_DIR == sandbox / "input" and str(sandbox) in str(app_mod.OUTPUT_DIR),
        )
        # Review e618ba2 · fix D: los globals PROPIOS de los routers montados tambien se redirigen
        # al sandbox (si no, una ruta SRT/paquete tocaria el repo real -> fuga de privacidad).
        import importlib as _il  # noqa: PLC0415

        _srt = _il.import_module("studio_srt_routes")
        _pkg = _il.import_module("studio_packages")
        ck(
            "01b_router_globals_en_sandbox",
            _srt.INPUT_DIR == sandbox / "input"
            and _srt.STUDIO_SRT_DIR == sandbox / "transcripts" / "studio_srt"
            and _pkg.PAQUETES_DIR == sandbox / "output" / "paquetes",
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
        # Review 372cfa8/f36a908 · el self-test valida el ARNES, no el estado vulnerable de hoy ni
        # un SO concreto. La CORRECTUD real la prueban (i) las funciones puras de clasificacion y
        # (ii) el caso CONTROLADO de deteccion de escape (item 07, independiente de app/SO). Las
        # probes 08-11 contra la app viva solo confirman que corren y producen una clasificacion
        # VALIDA (no None/crash del arnes): el verdict observado depende del estado y del SO:
        #   - BLOCKER: vulnerable hoy (p.ej. escape via backslash en Windows);
        #   - PASS: endurecido tras H1, o traversal contenido/rechazado (p.ej. backslash literal en
        #     POSIX, o `/` rechazado por el routing del segmento {name});
        #   - FAIL: el endpoint no escapa pero falla de otro modo (p.ej. crash con NUL byte, o en
        #     POSIX donde la ruta {name} no es escapable por URL). Es un defecto real del endpoint,
        #     no del arnes; por eso tambien es una clasificacion valida aqui.
        # Caso controlado: un centinela plantado FUERA del dir permitido debe detectarse y borrarse.
        planted = escape_catch / f"{TOKEN}_controlado.json"
        planted.write_text("x", encoding="utf-8")
        detected = _find_and_clean(sandbox, escape_catch, sandbox / "transcripts")
        ck(
            "07_deteccion_escape_controlada",
            any(f"{TOKEN}_controlado" in e for e in detected) and not planted.exists(),
        )
        valid = {"BLOCKER", "PASS", "FAIL"}  # cualquier clasificacion valida (no None/crash)
        # items 8-11: la app viva corre y clasifica de forma valida (BLOCKER/PASS/FAIL segun SO).
        wr = probe_traversal_write(client, sandbox, escape_catch)
        ck(f"08_traversal_write_valido[{wr['verdict']}]", wr["verdict"] in valid)
        up = probe_traversal_upload(client, sandbox, escape_catch)
        ck(f"09_upload_traversal_valido[{up['verdict']}]", up["verdict"] in valid)
        oa = probe_output_exposure(client, sandbox)
        ck(f"10_output_expuesto_valido[{oa['verdict']}]", oa["verdict"] in valid)
        ie = probe_lan_exposure(client, sandbox)
        ck(f"11_lan_expuesto_valido[{ie['verdict']}]", ie["verdict"] in valid)
        # item 12: no queda ningun centinela tras las probes.
        leftovers = []
        for d in _escape_scan_dirs(sandbox, escape_catch):
            with contextlib.suppress(OSError):
                leftovers += [str(c) for c in d.iterdir() if TOKEN in c.name]
        ck("12_sin_centinelas_residuales", not leftovers)

    # Review e618ba2 · los globals de los routers se RESTAURAN al salir del context manager.
    import importlib as _il2  # noqa: PLC0415

    _srt2 = _il2.import_module("studio_srt_routes")
    ck("13_router_globals_restaurados", _srt2.INPUT_DIR == REAL_ROOT / "input")

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
