"""Tests del contrato + endurecimiento del Editor de Paquete (S35, D32).

Cubren las tres capas nuevas del PR A:
- Helpers puros de path-safety en paquete_editor (es_nombre_seguro y resolvers):
  rechazo de traversal, separadores, unidad de Windows y symlinks que escapan.
- El router studio_packages via TestClient: lista fail-open, detalle, 404 de
  traversal (incl. URL-encoded), servido de binario CONFINADO (solo .mp4 existente,
  nunca paquete.json/REPORTE.md/sidecars por la ruta del video) y reporte.
- Solo-lectura: la entrada no se muta y un error de programacion se propaga.

Sin GPU, sin red, sin FFmpeg: todo sobre tmp_path + monkeypatch.
"""

from __future__ import annotations

import json

import pytest

import auto_report
import paquete_editor as pe

# ── Helpers puros de path-safety ─────────────────────────────────────────────


def test_es_nombre_seguro_acepta_basename():
    assert pe.es_nombre_seguro("clip1_9x16_hormozi.mp4")
    assert pe.es_nombre_seguro("vid.brain.json")


@pytest.mark.parametrize(
    "malo",
    ["", ".", "..", "a/b", "a\\b", "/abs.mp4", "\\abs.mp4", "C:\\x.mp4", "../x", "sub/../x"],
)
def test_es_nombre_seguro_rechaza_inseguros(malo):
    assert pe.es_nombre_seguro(malo) is False
    assert pe.es_nombre_seguro(None) is False


def test_resolver_hijo_seguro_dentro_del_root(tmp_path):
    (tmp_path / "ok.mp4").write_bytes(b"\x00")
    p = pe.resolver_hijo_seguro(tmp_path, "ok.mp4")
    assert p is not None and p.name == "ok.mp4"


@pytest.mark.parametrize("malo", ["..", "a/b", "../evil.mp4", "/etc/passwd"])
def test_resolver_hijo_seguro_traversal_es_none(tmp_path, malo):
    assert pe.resolver_hijo_seguro(tmp_path, malo) is None


def test_resolver_hijo_seguro_symlink_que_escapa_es_none(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    fuera = tmp_path / "fuera.mp4"
    fuera.write_bytes(b"\x00")
    link = root / "link.mp4"
    try:
        link.symlink_to(fuera)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks no soportados en este sistema")
    # el basename pasa, pero resolve() apunta fuera del root -> rechazado
    assert pe.resolver_hijo_seguro(root, "link.mp4") is None


def test_resolvers_delegan_en_hijo_seguro(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"\x00")
    assert pe.resolver_archivo_paquete(tmp_path, "a.mp4") is not None
    assert pe.resolver_archivo_paquete(tmp_path, "../a.mp4") is None
    assert pe.resolver_sidecar_seguro(tmp_path, "../s.json") is None


# ── Router studio_packages via TestClient ────────────────────────────────────


def _clip(**kw):
    base = {
        "archivo": "vid_clip1_9x16_hormozi.mp4",
        "titulo": "Hook demo",
        "razon": "Arranque fuerte",
        "score": 88,
        "dur_s": 30.0,
        "avisos": [],
        "qa": {"n_alertas": 0, "aplicadas": 0, "pendientes": 0},
        "tramos_disponibles": True,
    }
    base.update(kw)
    return base


def _escribir_paquete(root, pkg_id, clips, con_reporte=True, con_mp4=True):
    d = root / pkg_id
    d.mkdir(parents=True)
    (d / "paquete.json").write_text(
        json.dumps({"clips": clips, "meta": {"fecha": pkg_id.rsplit("_", 1)[-1]}}),
        encoding="utf-8",
    )
    if con_reporte:
        (d / "REPORTE.md").write_text("# reporte\n", encoding="utf-8")
    if con_mp4:
        for c in clips:
            if pe.es_nombre_seguro(c.get("archivo")):
                (d / c["archivo"]).write_bytes(b"\x00")
    return d


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    """TestClient con PAQUETES_DIR/TRANSCRIPTS apuntando a tmp (sin tocar el repo)."""
    from fastapi.testclient import TestClient

    import studio_packages as sp
    from app import app

    paquetes = tmp_path / "paquetes"
    paquetes.mkdir()
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    monkeypatch.setattr(sp, "PAQUETES_DIR", paquetes)
    monkeypatch.setattr(sp, "TRANSCRIPTS", transcripts)
    return TestClient(app), paquetes, transcripts


def test_lista_vacia_sin_paquetes(cliente):
    c, _paquetes, _t = cliente
    r = c.get("/api/paquetes")
    assert r.status_code == 200 and r.json() == []


def test_lista_ordena_reciente_primero_y_omite_invalidos(cliente):
    c, paquetes, _t = cliente
    _escribir_paquete(paquetes, "a_20260101-0000", [_clip()])
    _escribir_paquete(paquetes, "b_20260103-0000", [_clip()])
    (paquetes / "sin_json").mkdir()  # dir sin paquete.json -> omitido
    corrupto = paquetes / "c_20260102-0000"
    corrupto.mkdir()
    (corrupto / "paquete.json").write_text("{no json", encoding="utf-8")  # omitido
    ids = [p["id"] for p in c.get("/api/paquetes").json()]
    assert ids == ["b_20260103-0000", "a_20260101-0000"]  # reciente primero, corruptos fuera


def test_lista_ordena_por_fecha_no_por_nombre(cliente):
    # nombre y fecha discrepan: "aaa" (fecha nueva) debe ir ANTES que "zzz" (fecha vieja).
    c, paquetes, _t = cliente
    _escribir_paquete(paquetes, "zzz_20260101-0000", [_clip()])
    _escribir_paquete(paquetes, "aaa_20260305-0000", [_clip()])
    ids = [p["id"] for p in c.get("/api/paquetes").json()]
    assert ids == ["aaa_20260305-0000", "zzz_20260101-0000"]  # por fecha desc, no por nombre


def test_lista_fallback_mtime_cuando_falta_fecha(cliente):
    # sin meta.fecha valida -> ordena por mtime del dir; con fecha valida, sin cambios.
    import os
    from datetime import datetime

    c, paquetes, _t = cliente
    _escribir_paquete(paquetes, "aaa_20250101-0000", [_clip()])  # fecha vieja (2025)
    _escribir_paquete(paquetes, "ccc_20260701-0000", [_clip()])  # fecha nueva (2026-07)
    # B: SIN meta.fecha; mtime intermedio (2026-06) -> debe quedar entre C y A
    db = paquetes / "paquetesinfecha"
    db.mkdir()
    (db / "paquete.json").write_text(json.dumps({"clips": [_clip()], "meta": {}}), encoding="utf-8")
    mt = datetime(2026, 6, 1, 12, 0).timestamp()
    os.utime(db, (mt, mt))
    ids = [p["id"] for p in c.get("/api/paquetes").json()]
    assert ids == ["ccc_20260701-0000", "paquetesinfecha", "aaa_20250101-0000"]


def test_escattr_escapa_ampersand_primero_y_comillas(tmp_path):
    # _escAttr (JS) debe escapar & PRIMERO, y luego < > " ' sin doble-escapar.
    import re
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if node is None:
        pytest.skip("node no disponible para ejercitar el helper JS")
    html = (Path(__file__).parent.parent / "static" / "index.html").read_text(encoding="utf-8")
    m = re.search(r"function _escAttr\(s\)\s*\{.*?\}", html, re.S)
    assert m, "no se encontro _escAttr en index.html"
    js = m.group(0) + (
        "\nconst cc = String.fromCharCode;\n"
        "const inp = 'Tom ' + cc(38) + ' A ' + cc(34) + 'x' + cc(34) + ' '"
        " + cc(60) + 'b' + cc(62) + ' ' + cc(39) + 'q' + cc(39);\n"
        "const out = _escAttr(inp);\n"
        "const exp = 'Tom &amp; A &quot;x&quot; &lt;b&gt; &#39;q&#39;';\n"
        "if (out !== exp) { console.error('got:' + out); process.exit(1); }\n"
        "process.exit(0);\n"
    )
    f = tmp_path / "escattr_check.js"
    f.write_text(js, encoding="utf-8")
    r = subprocess.run([node, str(f)], capture_output=True, text=True)  # noqa: S603 (node fijo, sin shell)
    assert r.returncode == 0, r.stderr or r.stdout


def test_lista_incluye_salud(cliente):
    c, paquetes, _t = cliente
    _escribir_paquete(paquetes, "ok_20260101-0000", [_clip()])
    _escribir_paquete(paquetes, "inc_20260102-0000", [_clip(tramos_disponibles=False)])
    salud = {p["id"]: p["salud"] for p in c.get("/api/paquetes").json()}
    assert salud["ok_20260101-0000"] == "completo"
    assert salud["inc_20260102-0000"] == "incompleto"


def test_detalle_inexistente_404(cliente):
    c, _paquetes, _t = cliente
    assert c.get("/api/paquetes/no_existe").status_code == 404


def test_detalle_paquete_valido(cliente):
    c, paquetes, _t = cliente
    _escribir_paquete(paquetes, "pkg_20260101-0000", [_clip()])
    r = c.get("/api/paquetes/pkg_20260101-0000")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == "pkg_20260101-0000"
    assert data["reporte_url"] == "/api/paquetes/pkg_20260101-0000/reporte"
    clip = data["clips"][0]
    assert clip["video_disponible"] is True
    assert clip["video_url"] == "/api/paquetes/pkg_20260101-0000/video/vid_clip1_9x16_hormozi.mp4"


@pytest.mark.parametrize("mal", ["..", "%2e%2e", "a%2Fb", "..%2f.."])
def test_detalle_traversal_404(cliente, mal):
    c, _paquetes, _t = cliente
    assert c.get(f"/api/paquetes/{mal}").status_code == 404


def test_clip_sin_mp4_video_url_null(cliente):
    c, paquetes, _t = cliente
    _escribir_paquete(paquetes, "pkg_20260101-0000", [_clip()], con_mp4=False)
    clip = c.get("/api/paquetes/pkg_20260101-0000").json()["clips"][0]
    assert clip["video_url"] is None and clip["video_disponible"] is False


def test_reporte_faltante_es_null(cliente):
    c, paquetes, _t = cliente
    _escribir_paquete(paquetes, "pkg_20260101-0000", [_clip()], con_reporte=False)
    assert c.get("/api/paquetes/pkg_20260101-0000").json()["reporte_url"] is None


def test_video_endpoint_sirve_mp4(cliente):
    c, paquetes, _t = cliente
    _escribir_paquete(paquetes, "pkg_20260101-0000", [_clip()])
    r = c.get("/api/paquetes/pkg_20260101-0000/video/vid_clip1_9x16_hormozi.mp4")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("video/mp4")


@pytest.mark.parametrize("interno", ["paquete.json", "REPORTE.md", "..%2fpaquete.json"])
def test_video_endpoint_no_sirve_internos(cliente, interno):
    # CONFINAMIENTO: la ruta del video jamas entrega json/md/sidecars ni traversal.
    c, paquetes, _t = cliente
    _escribir_paquete(paquetes, "pkg_20260101-0000", [_clip()])
    assert c.get(f"/api/paquetes/pkg_20260101-0000/video/{interno}").status_code == 404


def test_reporte_endpoint_sirve_y_404(cliente):
    c, paquetes, _t = cliente
    _escribir_paquete(paquetes, "pkg_20260101-0000", [_clip()])
    _escribir_paquete(paquetes, "sin_20260102-0000", [_clip()], con_reporte=False)
    assert c.get("/api/paquetes/pkg_20260101-0000/reporte").status_code == 200
    assert c.get("/api/paquetes/sin_20260102-0000/reporte").status_code == 404


def test_respuesta_sin_rutas_absolutas_y_serializable(cliente, tmp_path):
    c, paquetes, _t = cliente
    _escribir_paquete(paquetes, "pkg_20260101-0000", [_clip()])
    raw = c.get("/api/paquetes/pkg_20260101-0000").text
    json.loads(raw)  # serializable
    assert "C:\\" not in raw and str(tmp_path) not in raw


def test_texto_con_script_permanece_texto(cliente):
    c, paquetes, _t = cliente
    _escribir_paquete(paquetes, "pkg_20260101-0000", [_clip(titulo="<script>alert(1)</script>")])
    clip = c.get("/api/paquetes/pkg_20260101-0000").json()["clips"][0]
    assert clip["titulo"] == "<script>alert(1)</script>"  # texto crudo, sin procesar


# ── Solo-lectura: sin mutacion, sin catch-all ────────────────────────────────


def test_entrada_no_se_muta(tmp_path):
    clip = _clip(qa={"n_alertas": 1, "alerts_file": "x_caption_alerts.json"})
    data = {"clips": [clip], "meta": {}}
    pe.vista_paquete(data, "pkg", tmp_path, tmp_path)
    assert "alertas" not in clip["qa"]  # el qa original quedo intacto


def test_error_de_programacion_se_propaga(tmp_path, monkeypatch):
    def boom(_c):
        raise RuntimeError("bug interno")

    monkeypatch.setattr(auto_report, "estado_clip", boom)
    with pytest.raises(RuntimeError):
        pe.enriquecer_clip(_clip(), "pkg", tmp_path, tmp_path)


def test_mount_output_allowlist_y_confina_paquetes(tmp_path):
    """El mount /output (H1 `_OutputMedia`) SOLO sirve .mp4 publicos y bloquea paquetes/**.

    Cierra P0-3: .ass/.json/.txt privados dejan de servirse (allowlist). El paquete existe en
    disco: un 404 es por el contrato del mount, no por archivo ausente. Un render .mp4 fuera de
    paquetes/ se sigue sirviendo.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import app as studio

    (tmp_path / "paquetes").mkdir()
    (tmp_path / "paquetes" / "paquete.json").write_text('{"x": 1}', encoding="utf-8")
    (tmp_path / "paquetes" / "clip.mp4").write_bytes(b"\x00")
    (tmp_path / "render.mp4").write_bytes(b"\x00")
    (tmp_path / "captions.ass").write_text("[Events]", encoding="utf-8")
    (tmp_path / "sel.keyword_selection.json").write_text("{}", encoding="utf-8")
    mini = FastAPI()
    mini.mount("/output", studio._OutputMedia(directory=str(tmp_path)), name="output")
    c = TestClient(mini)
    # paquetes/** bloqueado (incluso .mp4), case-insensitive y con puntos/espacios finales.
    assert (tmp_path / "paquetes" / "paquete.json").is_file()  # existe en disco
    assert c.get("/output/paquetes/paquete.json").status_code == 404
    assert c.get("/output/Paquetes/clip.mp4").status_code == 404
    assert c.get("/output/PAQUETES/paquete.json").status_code == 404
    # P0-3: texto/JSON privado ya NO se sirve; el render .mp4 publico si.
    assert c.get("/output/captions.ass").status_code == 404
    assert c.get("/output/sel.keyword_selection.json").status_code == 404
    assert c.get("/output/render.mp4").status_code == 200
