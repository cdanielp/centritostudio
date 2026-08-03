"""Control de modo parcial y offset en la UI de render con SRT (S41).

El default de la UI es **ACTIVADO** (es el comportamiento que K aprobó en D47/D48), con
escotilla para apagarlo. El default de la API sigue siendo OFF: lo que cambia es que la UI
manda el parámetro EXPLÍCITO en cada render.

El offset propuesto se muestra; aplicarlo es un clic, nunca automático.

Se ejecuta el JS REAL de `static/index.html` en un sandbox `vm` de Node.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

ROOT = Path(__file__).parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
HARNESS = Path(__file__).parent / "ui_render_harness.cjs"
NODE = shutil.which("node")

requires_node = pytest.mark.skipif(NODE is None, reason="Node no disponible para el harness de UI")


def _run(fixture: dict) -> dict:
    proc = subprocess.run(
        [NODE, str(HARNESS), str(ROOT / "static" / "index.html")],
        input=json.dumps(fixture),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert proc.returncode == 0, f"harness fallo: {proc.stderr}"
    data = json.loads(proc.stdout)
    assert not data["initerr"], f"init error: {data['initerr']}"
    assert not data["err"], f"call error: {data['err']}"
    return data


def _params(source: str, pre=None) -> dict:
    url = json.loads(_run({"fn": "render_params", "source": source, "pre": pre or {}})["out"])[
        "url"
    ]
    return parse_qs(urlparse(url).query)


# ─── Contrato estático: el control existe y nace ACTIVADO ──────────────────────


def test_existe_el_control_de_modo_parcial():
    assert 'id="render-srt-parcial"' in HTML


def test_el_control_nace_activado():
    """Es el comportamiento aprobado: el usuario tiene que APAGARLO a proposito."""
    i = HTML.index('id="render-srt-parcial"')
    etiqueta = HTML[HTML.rindex("<input", 0, i) : HTML.index(">", i) + 1]
    assert "checked" in etiqueta, etiqueta


def test_el_bloque_de_opciones_srt_esta_oculto_por_defecto():
    """Solo aparece con Fuente = SRT; en transcript no tiene sentido."""
    assert 'id="render-srt-opts"' in HTML
    bloque = HTML[HTML.index('id="render-srt-opts"') :][:200]
    assert "hidden" in bloque


def test_el_control_se_explica_en_espanol():
    assert "alineado parcial" in HTML.lower()


# ─── Comportamiento: el parametro viaja EXPLICITO ──────────────────────────────


@requires_node
def test_con_srt_manda_el_parametro_en_true(_=None):
    q = _params("srt", {"parcial": True})
    assert q.get("caption_source") == ["srt"]
    assert q.get("srt_alineado_parcial") == ["true"]


@requires_node
def test_apagarlo_manda_false_explicito(_=None):
    """La escotilla no es 'no mandar nada': se manda false, para que quede en el registro."""
    q = _params("srt", {"parcial": False})
    assert q.get("srt_alineado_parcial") == ["false"]


@requires_node
def test_sin_srt_no_se_manda_el_parametro(_=None):
    """La API rechaza los params SRT con caption_source=transcript: no se envian."""
    q = _params("transcript", {"parcial": True})
    assert "srt_alineado_parcial" not in q
    assert "srt_offset_ms" not in q


# ─── Offset: se propone, se aplica con un clic, nunca solo ─────────────────────


@requires_node
def test_el_offset_no_se_manda_si_no_se_acepto(_=None):
    """Hay propuesta, pero mientras no se acepte el render va sin desplazar (D45)."""
    q = _params("srt", {"parcial": True, "offsetPropuesto": 5284})
    assert "srt_offset_ms" not in q


@requires_node
def test_el_offset_aceptado_viaja_en_el_render(_=None):
    q = _params("srt", {"parcial": True, "offsetPropuesto": 5284, "offsetAceptado": 5284})
    assert q.get("srt_offset_ms") == ["5284"]


@requires_node
def test_el_offset_aceptado_no_se_manda_sin_srt(_=None):
    q = _params("transcript", {"offsetAceptado": 5284})
    assert "srt_offset_ms" not in q


# ─── La UI muestra la propuesta ────────────────────────────────────────────────


def test_la_tarjeta_srt_muestra_la_propuesta_de_offset():
    assert "srtPanel" in HTML
    assert "offset_propuesto" in HTML


def test_hay_accion_explicita_para_aplicar_el_offset():
    assert "aplicarOffset" in HTML


# ─── La invariante de D45: lo aceptado pertenece a ESTA propuesta ──────────────
#
# Aceptar un offset y renderizar OTRO es el fallo silencioso que D45 vino a evitar: el video
# sale desincronizado y solo se nota al verlo. Estos tests ejercitan el ciclo real
# (_guardarOffset / aplicarOffset), no un estado inyectado a mano.


def _ciclo(pasos) -> dict:
    return json.loads(_run({"fn": "offset_ciclo", "pasos": pasos})["out"])


@requires_node
def test_aceptar_guarda_exactamente_la_propuesta_vigente(_=None):
    estado = _ciclo(
        [{"guardar": {"offset_ms": 5284, "n_anclas": 60, "confianza": 0.99}}, "aplicar"]
    )
    assert estado["aceptado"] == 5284


@requires_node
def test_una_propuesta_nueva_caduca_lo_aceptado(_=None):
    """Cambió el par SRT/timings: el número viejo ya no describe este video."""
    estado = _ciclo(
        [
            {"guardar": {"offset_ms": 5284, "n_anclas": 60, "confianza": 0.99}},
            "aplicar",
            {"guardar": {"offset_ms": 120, "n_anclas": 30, "confianza": 0.8}},
        ]
    )
    assert estado["propuesto"] == 120
    assert estado["aceptado"] is None


@requires_node
def test_perder_la_propuesta_caduca_lo_aceptado(_=None):
    """Si el view model deja de proponer (SRT retirado, timings rotos), no queda residuo."""
    estado = _ciclo(
        [
            {"guardar": {"offset_ms": 5284, "n_anclas": 60, "confianza": 0.99}},
            "aplicar",
            {"guardar": None},
        ]
    )
    assert estado["propuesto"] is None and estado["aceptado"] is None


@requires_node
def test_cambiar_de_video_borra_la_propuesta_y_lo_aceptado(_=None):
    estado = _ciclo(
        [
            {"guardar": {"offset_ms": 5284, "n_anclas": 60, "confianza": 0.99}},
            "aplicar",
            "cambiar_video",
        ]
    )
    assert estado["propuesto"] is None and estado["aceptado"] is None


@requires_node
def test_abrir_el_render_desde_otra_vista_no_arrastra_offset(_=None):
    """`openRender(name)` entra por fuera del onchange del select: tambien tiene que limpiar."""
    estado = _ciclo(
        [
            {"guardar": {"offset_ms": 5284, "n_anclas": 60, "confianza": 0.99}},
            "aplicar",
            "open_render",
        ]
    )
    assert estado["aceptado"] is None


@requires_node
def test_si_el_view_falla_no_queda_un_offset_caduco(_=None):
    """El estado del panel no puede sobrevivir a un refresh que no pudo leer nada."""
    estado = _ciclo(
        [
            {"guardar": {"offset_ms": 5284, "n_anclas": 60, "confianza": 0.99}},
            "aplicar",
            "refresh_falla",
        ]
    )
    assert estado["propuesto"] is None and estado["aceptado"] is None


@requires_node
def test_quitar_deja_la_propuesta_pero_no_la_aplica(_=None):
    estado = _ciclo(
        [
            {"guardar": {"offset_ms": 5284, "n_anclas": 60, "confianza": 0.99}},
            "aplicar",
            "descartar",
        ]
    )
    assert estado["propuesto"] == 5284 and estado["aceptado"] is None


# ─── El desfase pertenece a UN video, por construcción ─────────────────────────
#
# Las caducidades de arriba dependen de que cada puerta de entrada se acuerde de avisar al
# panel — así se coló `openRender()` en la revisión anterior. Estos tests fijan la invariante
# de forma que ninguna puerta, presente o futura, pueda saltársela: lo aceptado lleva el nombre
# del video al que pertenece, y solo se aplica a ESE video.


@requires_node
def test_lo_aceptado_recuerda_a_que_video_pertenece(_=None):
    estado = _ciclo(
        [{"guardar": {"offset_ms": 5284, "n_anclas": 60, "confianza": 0.99}}, "aplicar"]
    )
    assert estado["aceptado_video"] == "v1"


@requires_node
def test_repoblar_el_selector_no_deja_la_tarjeta_afirmando_nada(_=None):
    """`populateSelects()` reescribe el <select> y vacía la selección SIN avisar al panel."""
    estado = _ciclo(
        [
            {"guardar": {"offset_ms": 5284, "n_anclas": 60, "confianza": 0.99}},
            "aplicar",
            "repoblar_selector",
        ]
    )
    assert estado["tarjeta_visible"] is False
    assert estado["tarjeta_html"] == ""


@requires_node
def test_un_desfase_de_otro_video_no_viaja_en_el_render(_=None):
    """Aunque el estado sobreviva por cualquier puerta, el render solo usa lo que es suyo."""
    q = _params("srt", {"parcial": True, "offsetAceptado": 5284, "offsetAceptadoVideo": "otro"})
    assert "srt_offset_ms" not in q


@requires_node
def test_el_desfase_del_video_correcto_si_viaja(_=None):
    q = _params("srt", {"parcial": True, "offsetAceptado": 5284, "offsetAceptadoVideo": "v1"})
    assert q.get("srt_offset_ms") == ["5284"]


# ─── Idioma de la UI ───────────────────────────────────────────────────────────


def _visibles(desde: str, hasta: str) -> str:
    """Texto del bloque de UI del desfase (el que ve una persona, no los identificadores)."""
    i = HTML.index(desde)
    return HTML[i : HTML.index(hasta, i)]


def test_los_botones_del_desfase_estan_en_espanol():
    bloque = _visibles("_pintarOffset(mode) {", "async associate(")
    assert ">Aplicar desfase<" in bloque
    assert ">Quitar desfase<" in bloque
    assert "Aplicar offset" not in bloque and "Quitar offset" not in bloque


def test_el_texto_visible_del_desfase_no_lleva_em_dash():
    """Regla del proyecto: nada de em dashes en texto visible, y menos en la UI."""
    bloque = _visibles("_pintarOffset(mode) {", "async associate(")
    for linea in bloque.splitlines():
        visible = linea.strip()
        if visible.startswith("//"):
            continue  # los comentarios de código no los ve nadie
        assert "—" not in visible, visible


def test_el_bloque_de_opciones_srt_no_lleva_em_dash():
    bloque = _visibles('id="render-srt-opts"', 'id="render-srt-incompat"')
    assert "—" not in bloque, bloque
