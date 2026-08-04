"""Invocador HF-1: comando construido, timeout y verificacion de la salida.

El comando construido SI se fija (es texto). El MOV producido NO se compara por bytes:
la regla dura 3 prohibe fijar pixeles o sha256 de video como asercion de correccion.
"""

from __future__ import annotations

import pytest
from hf_dobles import PIEZA_OK, ProcesoFalso, adaptador, sondeo_falso

from hyperframes import invocador as inv
from hyperframes.catalogo import Plantilla
from hyperframes.razones import Razon

PLANTILLA = Plantilla(
    nombre="hook",
    version="1.0.0",
    slots_texto=("titulo", "subtitulo"),
    proyecto="motion/hook",
)


# ─────────────────────────── comando construido ──────────────────────────


def test_comando_construido_es_el_esperado(tmp_path):
    salida = tmp_path / "pieza.mov"
    cmd = inv.construir_comando(PIEZA_OK, PLANTILLA, salida, binario="npx")
    assert cmd == [
        "npx",
        "hyperframes",
        "render",
        "motion/hook",
        "--format",
        "mov",
        "--quality",
        "high",
        "--fps",
        "30",
        "--output",
        str(salida),
        "--variables",
        inv.variables_json(PIEZA_OK),
        "--no-best-effort",
    ]


def test_el_comando_no_lleva_non_interactive():
    """Medido en HF-1: `render` rechaza --non-interactive (es un flag de `init`) con
    'Unknown flag'. El modo no interactivo lo auto-detecta la CLI por non-TTY."""
    cmd = inv.construir_comando(PIEZA_OK, PLANTILLA, "x.mov", binario="npx")
    assert "--non-interactive" not in cmd


def test_variables_llevan_texto_marca_y_semilla_en_json_canonico():
    crudo = inv.variables_json(PIEZA_OK)
    assert '"titulo":"Configuracion basica"' in crudo
    assert '"primario":"#FF5A2B"' in crudo
    assert '"semilla":0' in crudo
    assert ", " not in crudo  # canonico compacto, igual que el contrato


def test_variables_son_estables_ante_el_orden_de_claves():
    revuelta = dict(reversed(list(PIEZA_OK.items())))
    assert inv.variables_json(revuelta) == inv.variables_json(PIEZA_OK)


def test_el_comando_fuerza_mov_y_nunca_webm():
    """HF-0: WebM VP9 declara yuv420p y pierde el alfa en silencio. No se ofrece como opcion."""
    cmd = inv.construir_comando(PIEZA_OK, PLANTILLA, "x.mov", binario="npx")
    assert "webm" not in cmd
    assert cmd[cmd.index("--format") + 1] == "mov"


def test_el_comando_pide_el_fps_del_contrato_no_uno_fijo():
    """HF-0: la cadena de clips fuerza el fps del video base y descartaria frames."""
    cmd = inv.construir_comando(dict(PIEZA_OK, fps=24), PLANTILLA, "x.mov", binario="npx")
    assert cmd[cmd.index("--fps") + 1] == "24"


# ──────────────────────────────── render ─────────────────────────────────


def test_render_ok_devuelve_sondeo_y_sin_razon(tmp_path):
    proceso = ProcesoFalso()
    ad = adaptador(proceso)
    r = inv.renderizar(PIEZA_OK, PLANTILLA, tmp_path / "p.mov", ad, timeout_s=180)
    assert r.razon is None
    assert r.sondeo["pix_fmt"] == "yuva444p12le"
    assert proceso.veces == 1


def test_timeout_produce_timeout_render_y_borra_el_temporal(tmp_path):
    destino = tmp_path / "p.mov"
    ad = adaptador(ProcesoFalso(expiro=True))
    r = inv.renderizar(PIEZA_OK, PLANTILLA, destino, ad, timeout_s=1)
    assert r.razon is Razon.TIMEOUT_RENDER
    assert not destino.exists()


def test_codigo_distinto_de_cero_produce_render_fallido(tmp_path):
    ad = adaptador(ProcesoFalso(codigo=2, error="boom"))
    r = inv.renderizar(PIEZA_OK, PLANTILLA, tmp_path / "p.mov", ad, timeout_s=180)
    assert r.razon is Razon.RENDER_FALLIDO


def test_archivo_ausente_pese_a_codigo_cero_es_salida_invalida(tmp_path):
    ad = adaptador(ProcesoFalso(escribe=False))
    r = inv.renderizar(PIEZA_OK, PLANTILLA, tmp_path / "p.mov", ad, timeout_s=180)
    assert r.razon is Razon.SALIDA_INVALIDA


@pytest.mark.parametrize(
    "cambio",
    [
        {"pix_fmt": "yuv420p"},  # el fallo silencioso de WebM/VP9 de HF-0
        {"pix_fmt": "yuva420p"},
        {"fps": 24},
        {"ancho": 1080, "alto": 1920},
        {"duracion_ms": 4000},
    ],
)
def test_desvio_de_la_salida_es_salida_invalida_y_descarta_el_archivo(tmp_path, cambio):
    destino = tmp_path / "p.mov"
    ad = adaptador(ProcesoFalso(), sondeo=sondeo_falso(**cambio))
    r = inv.renderizar(PIEZA_OK, PLANTILLA, destino, ad, timeout_s=180)
    assert r.razon is Razon.SALIDA_INVALIDA
    assert not destino.exists()


def test_duracion_dentro_de_tolerancia_se_acepta(tmp_path):
    """Un MOV real no cae al milisegundo: se admite la tolerancia declarada."""
    ad = adaptador(ProcesoFalso(), sondeo=sondeo_falso(duracion_ms=6000 + inv.TOLERANCIA_MS))
    r = inv.renderizar(PIEZA_OK, PLANTILLA, tmp_path / "p.mov", ad, timeout_s=180)
    assert r.razon is None


def test_duracion_fuera_de_tolerancia_se_rechaza(tmp_path):
    ad = adaptador(ProcesoFalso(), sondeo=sondeo_falso(duracion_ms=6000 + inv.TOLERANCIA_MS + 1))
    r = inv.renderizar(PIEZA_OK, PLANTILLA, tmp_path / "p.mov", ad, timeout_s=180)
    assert r.razon is Razon.SALIDA_INVALIDA


def test_ffprobe_que_falla_es_salida_invalida_no_excepcion(tmp_path):
    def revienta(_ruta):
        raise OSError("ffprobe ausente")

    ad = adaptador(ProcesoFalso(), sondeo=revienta)
    r = inv.renderizar(PIEZA_OK, PLANTILLA, tmp_path / "p.mov", ad, timeout_s=180)
    assert r.razon is Razon.SALIDA_INVALIDA


def test_el_timeout_se_pasa_al_proceso(tmp_path):
    visto = {}

    class Espia(ProcesoFalso):
        def __call__(self, cmd, timeout):
            visto["timeout"] = timeout
            return super().__call__(cmd, timeout)

    inv.renderizar(PIEZA_OK, PLANTILLA, tmp_path / "p.mov", adaptador(Espia()), timeout_s=42)
    assert visto["timeout"] == 42


def test_timeout_default_es_180_segundos():
    """Referencia HF-0: un overlay de 6 s tardo 14.9 s. 180 s deja margen amplio."""
    assert inv.TIMEOUT_DEFAULT_S == 180


def test_el_adaptador_real_resuelve_el_binario_a_su_ruta_completa(monkeypatch):
    """Gotcha Windows (HF-1): `npx` es `npx.CMD` y CreateProcess no aplica PATHEXT, asi que
    subprocess falla con WinError 2 con el literal aunque `which` si lo encuentre."""
    import shutil

    monkeypatch.setattr(shutil, "which", lambda _n: "C:\\Program Files\\nodejs\\npx.CMD")
    visto = {}
    monkeypatch.setattr(
        "hyperframes.entorno.leer_entorno", lambda b: visto.setdefault("binario", b) or {}
    )
    inv.adaptador_real("npx").leer_entorno()
    assert visto["binario"] == "C:\\Program Files\\nodejs\\npx.CMD"


def test_el_adaptador_real_cae_al_literal_si_no_se_resuelve(monkeypatch):
    """Sin resolucion se conserva el literal: el fallo debe salir por binario_ausente."""
    import shutil

    monkeypatch.setattr(shutil, "which", lambda _n: None)
    visto = {}
    monkeypatch.setattr(
        "hyperframes.entorno.leer_entorno", lambda b: visto.setdefault("binario", b) or {}
    )
    inv.adaptador_real("npx").leer_entorno()
    assert visto["binario"] == "npx"
