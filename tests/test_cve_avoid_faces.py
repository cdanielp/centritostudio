"""Tests de avoid_faces real (F6 esencial, PASO C).

Conecta la senal de caras del reframe al posicionamiento de captions SIN duplicar
deteccion: reutiliza el CSV de trayectoria (`trayectoria_{stem}.csv`). Contrato:
- Evitar captions sobre una cara cuando exista una zona valida.
- Sin saltos violentos: una posicion por caption (decidida una sola vez).
- Respetar safe areas; fail-open sobrio si no hay senal; nunca bloquea el render.
- Determinista. La ruta historica (bottom, sin CSV) queda byte-identica.

Senal: columna `conf_asignada` (presencia viva) + `face_y_asignada` opcional
(fraccion 0..1 del alto). Sin `face_y_asignada` -> presencia = zona "center"
(caso talking-head). El export vertical del reframe es deuda post-esencial.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import core_ass
import cve


def _grupo(palabras: list[str], g_id: int = 0, start: float = 0.0) -> dict:
    words = [
        {"text": p, "start": start + i * 0.5, "end": start + i * 0.5 + 0.4, "line_idx": 0}
        for i, p in enumerate(palabras)
    ]
    return {
        "id": g_id,
        "start": start,
        "end": start + len(palabras) * 0.5,
        "text": " ".join(palabras),
        "words": words,
    }


def _csv(tmp_path: Path, filas: list[tuple], face_y: bool = True) -> Path:
    """Escribe un trayectoria CSV sintetico. filas: (t, conf, y|None)."""
    p = tmp_path / "trayectoria_test.csv"
    cols = ["t", "cam_center_x", "face_x_asignada", "distancia", "conf_asignada"]
    if face_y:
        cols.append("face_y_asignada")
    lineas = [",".join(cols)]
    for t, conf, y in filas:
        row = [f"{t:.4f}", "500.0", "500.0", "0.0", ("" if conf is None else f"{conf:.3f}")]
        if face_y:
            row.append("" if y is None else f"{y:.3f}")
        lineas.append(",".join(row))
    p.write_text("\n".join(lineas), encoding="utf-8")
    return p


# ── zona_cara_en_rango ────────────────────────────────────────────────────────


def test_zona_cara_superior(tmp_path):
    csv = _csv(tmp_path, [(0.0, 0.9, 0.20), (0.5, 0.9, 0.22)])
    assert cve.zona_cara_en_rango(csv, 0.0, 1.0) == "top"


def test_zona_cara_central(tmp_path):
    csv = _csv(tmp_path, [(0.0, 0.9, 0.50), (0.5, 0.9, 0.52)])
    assert cve.zona_cara_en_rango(csv, 0.0, 1.0) == "center"


def test_zona_cara_inferior(tmp_path):
    csv = _csv(tmp_path, [(0.0, 0.9, 0.82), (0.5, 0.9, 0.85)])
    assert cve.zona_cara_en_rango(csv, 0.0, 1.0) == "bottom"


def test_zona_sin_cara_es_none(tmp_path):
    csv = _csv(tmp_path, [(0.0, None, None), (0.5, None, None)])
    assert cve.zona_cara_en_rango(csv, 0.0, 1.0) is None


def test_zona_presencia_sin_columna_vertical_es_center(tmp_path):
    csv = _csv(tmp_path, [(0.0, 0.9, None)], face_y=False)
    assert cve.zona_cara_en_rango(csv, 0.0, 1.0) == "center"


def test_zona_csv_ausente_es_none(tmp_path):
    assert cve.zona_cara_en_rango(tmp_path / "no_existe.csv", 0.0, 1.0) is None


def test_zona_fuera_de_rango_es_none(tmp_path):
    csv = _csv(tmp_path, [(9.0, 0.9, 0.85)])
    assert cve.zona_cara_en_rango(csv, 0.0, 1.0) is None


# ── resolver_posicion_captions ────────────────────────────────────────────────


def test_avoid_cara_inferior_mueve_caption_a_top(tmp_path):
    csv = _csv(tmp_path, [(0.0, 0.9, 0.85), (0.5, 0.9, 0.85)])
    plan = cve.resolve_preset("clean_podcast")  # position bottom, avoid_faces True
    out = cve.resolver_posicion_captions([_grupo(["hola", "mundo"])], plan, csv)
    assert out[0]["caption_pos"] == "top"


def test_avoid_cara_superior_mantiene_bottom(tmp_path):
    csv = _csv(tmp_path, [(0.0, 0.9, 0.20)])
    plan = cve.resolve_preset("clean_podcast")
    out = cve.resolver_posicion_captions([_grupo(["hola", "mundo"])], plan, csv)
    assert out[0].get("caption_pos") in (None, "bottom")  # bottom no choca con cara alta


def test_avoid_cara_central_mantiene_bottom(tmp_path):
    csv = _csv(tmp_path, [(0.0, 0.9, 0.50)])
    plan = cve.resolve_preset("clean_podcast")
    out = cve.resolver_posicion_captions([_grupo(["hola", "mundo"])], plan, csv)
    assert out[0].get("caption_pos") in (None, "bottom")


def test_avoid_sin_cara_fail_open_bottom(tmp_path):
    csv = _csv(tmp_path, [(0.0, None, None)])
    plan = cve.resolve_preset("clean_podcast")
    out = cve.resolver_posicion_captions([_grupo(["hola"])], plan, csv)
    assert out[0].get("caption_pos") in (None, "bottom")


def test_avoid_detector_fallido_no_rompe(tmp_path):
    faltante = tmp_path / "no_hay.csv"
    plan = cve.resolve_preset("clean_podcast")
    out = cve.resolver_posicion_captions([_grupo(["hola"])], plan, faltante)
    assert out[0].get("caption_pos") in (None, "bottom")


def test_avoid_off_no_mueve_aunque_haya_cara(tmp_path):
    from dataclasses import replace

    csv = _csv(tmp_path, [(0.0, 0.9, 0.85)])
    plan = replace(cve.resolve_preset("clean_podcast"), avoid_faces=False)
    out = cve.resolver_posicion_captions([_grupo(["hola"])], plan, csv)
    assert out[0].get("caption_pos") in (None, "bottom")


def test_avoid_center_solicitado_con_cara_central_cae_a_bottom(tmp_path):
    from dataclasses import replace

    csv = _csv(tmp_path, [(0.0, 0.9, 0.50)])
    plan = replace(cve.resolve_preset("clean_podcast"), position="center")
    out = cve.resolver_posicion_captions([_grupo(["hola"])], plan, csv)
    assert out[0]["caption_pos"] == "bottom"


def test_avoid_determinista(tmp_path):
    csv = _csv(tmp_path, [(0.0, 0.9, 0.85), (0.5, 0.9, 0.85)])
    plan = cve.resolve_preset("clean_podcast")
    g = [_grupo(["hola", "mundo"])]
    a = cve.resolver_posicion_captions(g, plan, csv)
    b = cve.resolver_posicion_captions(g, plan, csv)
    assert a[0]["caption_pos"] == b[0]["caption_pos"] == "top"


def test_avoid_una_sola_posicion_por_grupo(tmp_path):
    # sin saltos violentos: el resultado es un escalar por grupo, no una secuencia
    csv = _csv(tmp_path, [(0.0, 0.9, 0.85), (0.5, 0.9, 0.20)])  # cara baja luego alta
    plan = cve.resolve_preset("clean_podcast")
    out = cve.resolver_posicion_captions([_grupo(["hola", "mundo"])], plan, csv)
    assert isinstance(out[0].get("caption_pos", "bottom"), str)


# ── build_ass consume caption_pos ─────────────────────────────────────────────


def test_build_ass_top_emite_an8(tmp_path):
    g = _grupo(["hola", "mundo"])
    g["caption_pos"] = "top"
    plan = cve.resolve_preset("clean_podcast")
    ass = tmp_path / "top.ass"
    core_ass.build_ass([g], 1080, 1920, plan.style_cfg, ass)
    assert "\\an8" in ass.read_text(encoding="utf-8")


def test_build_ass_bottom_byte_identico(tmp_path):
    # Sin caption_pos (o bottom): ninguna override \an -> ruta historica intacta
    g = _grupo(["hola", "mundo"])
    plan = cve.resolve_preset("clean_podcast")
    a = tmp_path / "sin.ass"
    core_ass.build_ass([g], 1080, 1920, plan.style_cfg, a)
    g2 = {**g, "caption_pos": "bottom"}
    b = tmp_path / "bottom.ass"
    core_ass.build_ass([g2], 1080, 1920, plan.style_cfg, b)
    contenido = a.read_text(encoding="utf-8")
    assert "\\an5" not in contenido and "\\an8" not in contenido
    assert contenido == b.read_text(encoding="utf-8")  # bottom == sin marca


def test_aplicar_preset_sin_csv_no_pone_caption_pos(tmp_path):
    # Ruta historica: sin tray_csv el render queda byte-identico (no caption_pos)
    g = _grupo(["hola", "mundo", "claro"])
    plan = cve.resolve_preset("clean_podcast")
    out, _plan, _aviso = cve.aplicar_preset([g], plan, None, 1080, 1920)
    assert all("caption_pos" not in gg for gg in out)


def test_aplicar_preset_con_csv_mueve_y_publica_sidecar(tmp_path):
    import cve_sidecar

    csv = _csv(tmp_path, [(0.0, 0.9, 0.85), (0.5, 0.9, 0.85)])  # cara inferior
    g = _grupo(["gana", "500", "pesos"])  # keyword_punch marca -> sidecar aplica
    plan = cve.resolve_preset("keyword_punch")
    out, plan2, _aviso = cve.aplicar_preset([g], plan, None, 1080, 1920, None, csv)
    assert out[0]["caption_pos"] == "top"
    data = cve_sidecar.construir_seleccion(out, plan2)
    assert data["posiciones"] == [{"grupo": 0, "posicion": "top"}]
    for entrada in data["posiciones"]:  # saneado: sin rutas ni datos del detector
        assert set(entrada) == {"grupo", "posicion"}
