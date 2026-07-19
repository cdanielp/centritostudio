"""smoke_api.py — Smoke E2E del contrato SRT de Studio (S36-C1) con TestClient.

Todo sintetico y efimero (tempdir): crea un MP4 corto con FFmpeg, reapunta los
directorios del router a ese tempdir, y recorre capabilities -> none -> upload ->
idempotencia -> reemplazo -> delete. Verifica que el archivo administrado no se sirve
por ningun mount y que NO se llamo a jobs/render/Auto. No deja nada versionado.

Uso:
    python revision/s36-c1-studio-srt-backend/smoke_api.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

DEMO_SRT = Path(__file__).resolve().parent / "fixtures" / "demo.srt"
_SRT_V2 = (
    "1\n00:00:00,000 --> 00:00:01,500\nSegunda version del SRT\n\n"
    "2\n00:00:01,500 --> 00:00:03,000\nContenido distinto para reemplazo\n"
)


def _make_mp4(dest: Path) -> None:
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", "color=c=0x08080f:size=320x568:rate=30",
        "-t", "8", "-c:v", "libx264", "-crf", "30", str(dest),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not dest.is_file():
        raise SystemExit(f"[smoke] FFmpeg no pudo crear el MP4 sintetico:\n{r.stderr[-400:]}")


def _fail(msg: str) -> None:
    raise SystemExit(f"[smoke] FALLO: {msg}")


def main() -> int:
    from fastapi.testclient import TestClient

    import app as studio_app
    import studio_srt_routes

    with tempfile.TemporaryDirectory(prefix="s36c1_smoke_") as td:
        base = Path(td)
        inp = base / "input"
        trans = base / "transcripts"
        storage = trans / "studio_srt"
        inp.mkdir()
        trans.mkdir()

        studio_srt_routes.INPUT_DIR = inp
        studio_srt_routes.TRANSCRIPTS = trans
        studio_srt_routes.STUDIO_SRT_DIR = storage

        # Sentinela: cualquier endpoint que lance render/Auto llama primero jobs.new_job;
        # si el flujo SRT lo tocara, el smoke aborta. (No tocamos threading: TestClient lo usa.)
        studio_app.jobs.new_job = lambda *_a, **_k: _fail("se inicio un job")

        _make_mp4(inp / "demo.mp4")
        srt_bytes = DEMO_SRT.read_bytes()

        client = TestClient(studio_app.app)

        # 1) capabilities
        caps = client.get("/api/srt/capabilities")
        assert caps.status_code == 200 and caps.json()["render"] is False, "capabilities"
        print("[smoke] capabilities OK")

        # 2) estado none
        none = client.get("/api/videos/demo/srt")
        assert none.status_code == 200 and none.json()["status"] == "none", "estado none"
        print("[smoke] estado none OK")

        # 3) upload valido -> ready (201)
        up = client.post("/api/videos/demo/srt", files={"file": ("demo.srt", srt_bytes, "x")})
        assert up.status_code == 201 and up.json()["status"] == "ready", "upload 201"
        managed = up.json()["selection"]["managed_file"]
        assert "/" not in managed and "\\" not in managed, "managed basename"
        print(f"[smoke] upload ready OK (managed={managed})")

        # 4) idempotencia -> 200
        dup = client.post("/api/videos/demo/srt", files={"file": ("demo.srt", srt_bytes, "x")})
        assert dup.status_code == 200, "idempotencia 200"
        print("[smoke] idempotencia OK")

        # 5) reemplazo -> 201
        rep = client.post(
            "/api/videos/demo/srt", files={"file": ("demo.srt", _SRT_V2.encode(), "x")}
        )
        assert rep.status_code == 201, "reemplazo 201"
        print("[smoke] reemplazo OK")

        # 6) el archivo administrado no se publica por ningun mount
        for prefix in ("/input", "/output", "/clips", "/static", "/transcripts"):
            r = client.get(f"{prefix}/studio_srt/demo/{managed}")
            assert r.status_code == 404, f"{prefix} no debe servir el SRT administrado"
        assert client.get("/transcripts/demo_srt_selection.json").status_code == 404, "manifest"
        print("[smoke] almacenamiento privado no publicado OK")

        # 7) delete -> none, idempotente
        d1 = client.delete("/api/videos/demo/srt")
        assert d1.status_code == 200 and d1.json()["status"] == "none", "delete"
        assert client.delete("/api/videos/demo/srt").status_code == 200, "delete idempotente"
        assert client.get("/api/videos/demo/srt").json()["status"] == "none", "post-delete none"
        # los archivos administrados NO se borran al desasociar
        assert list((storage / "demo").glob("*.srt")), "managed conservado tras delete"
        print("[smoke] delete idempotente + managed conservado OK")

    print("\n[smoke] TODO OK - S36-C1 API contract verde. Nada versionado, tempdir limpiado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
