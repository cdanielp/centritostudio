"""Mapeo de variables y transporte UTF-8 (HF-1, addendum D50).

Por que existe este archivo: el render devolvia codigo 0, `pix_fmt`, fps y duracion
correctos, y aun asi la pieza salia con el TEXTO POR DEFECTO de la plantilla. Las
variables de HyperFrames son PLANAS por id (`{"titulo":"..."}`), y se estaban enviando
anidadas (`{"texto":{"titulo":"..."}}`), asi que ninguna plantilla recibia sus slots.
Ninguna verificacion automatica podia verlo: solo se vio extrayendo un frame y mirandolo.

Estos tests fijan el MAPEO y los BYTES, que es lo que si se puede automatizar.
"""

from __future__ import annotations

import json

import pytest
from hf_dobles import PIEZA_OK, ProcesoFalso, adaptador, pieza, salida_de

from hyperframes import contrato as ct
from hyperframes import invocador as inv
from hyperframes.catalogo import Plantilla
from hyperframes.errores import ContratoInvalido

PLANTILLA = Plantilla(
    nombre="hook", version="1.0.0", slots_texto=("titulo", "subtitulo"), proyecto="motion/hook"
)

TITULO = "Configuración básica de ComfyUI"
SUBTITULO = 'año 2026 · ñ á é í ó ú ü ¿? ¡! "comillas"'
ACENTUADA = pieza(texto={"titulo": TITULO, "subtitulo": SUBTITULO})


# ─────────────────────────── mapeo plano ─────────────────────────────────


def test_los_slots_de_texto_van_planos_no_anidados():
    """La regresion que costo un render entero: `texto` anidado nunca llega a la plantilla."""
    v = inv.variables_de(PIEZA_OK)
    assert v["titulo"] == "Configuracion basica"
    assert v["subtitulo"] == "ano 2026"
    assert "texto" not in v


def test_la_marca_va_plana_con_prefijo():
    v = inv.variables_de(PIEZA_OK)
    assert v["marca_primario"] == "#FF5A2B"
    assert v["marca_secundario"] == "#111111"
    assert v["marca_texto"] == "#FFFFFF"
    assert "marca" not in v


def test_el_tamano_va_plano():
    v = inv.variables_de(PIEZA_OK)
    assert v["tamano_ancho"] == 1920 and v["tamano_alto"] == 1080
    assert "tamano" not in v


def test_las_claves_planas_son_exactamente_las_esperadas():
    """Contrato que HF-2 declara en `data-composition-variables`."""
    assert set(inv.variables_de(PIEZA_OK)) == {
        "titulo",
        "subtitulo",
        "marca_primario",
        "marca_secundario",
        "marca_texto",
        "duracion_ms",
        "fps",
        "tamano_ancho",
        "tamano_alto",
        "semilla",
    }


def test_ningun_valor_de_variable_es_un_objeto_anidado():
    """HyperFrames solo admite string/number/color/boolean/enum: un dict no es declarable."""
    for clave, valor in inv.variables_de(PIEZA_OK).items():
        assert isinstance(valor, str | int | float | bool), f"{clave} es {type(valor).__name__}"


def test_las_variables_son_estables_ante_el_orden_de_claves():
    revuelta = dict(reversed(list(PIEZA_OK.items())))
    assert inv.variables_json(revuelta) == inv.variables_json(PIEZA_OK)


# ─────────────────── slots que chocan con claves reservadas ──────────────


@pytest.mark.parametrize("reservada", ["fps", "semilla", "marca_primario", "tamano_ancho"])
def test_un_slot_que_choca_con_una_clave_reservada_es_contrato_invalido(reservada):
    """Sin esto, un slot llamado `fps` pisaria el fps real al aplanar, en silencio."""
    with pytest.raises(ContratoInvalido) as exc:
        ct.validar_slots(pieza(texto={"titulo": "a", reservada: "b"}), ("titulo", reservada))
    assert reservada in str(exc.value)


def test_los_slots_normales_no_se_ven_afectados():
    ct.validar_slots(PIEZA_OK, ("titulo", "subtitulo"))


# ──────────────────────── transporte por archivo ─────────────────────────


def test_el_comando_pasa_las_variables_por_archivo(tmp_path):
    """`--variables-file` evita el escapado de comillas y el techo de 32767 caracteres
    de la linea de comandos de Windows."""
    cmd = inv.construir_comando(
        PIEZA_OK, PLANTILLA, tmp_path / "p.mov", tmp_path / "vars.json", binario="npx"
    )
    assert "--variables" not in cmd
    assert cmd[cmd.index("--variables-file") + 1] == str(tmp_path / "vars.json")


def test_el_archivo_de_variables_se_escribe_en_utf8_y_es_json_valido(tmp_path):
    destino = tmp_path / "vars.json"
    inv.escribir_variables(ACENTUADA, destino)
    crudo = destino.read_bytes()
    assert crudo.decode("utf-8")  # utf-8 estricto, sin BOM ni cp1252
    assert not crudo.startswith(b"\xef\xbb\xbf")
    datos = json.loads(destino.read_text(encoding="utf-8"))
    assert datos["titulo"] == TITULO
    assert datos["subtitulo"] == SUBTITULO


def test_los_bytes_del_archivo_llevan_los_acentos_como_utf8(tmp_path):
    """Fija los BYTES: 'ó' es c3b3 en UTF-8 y f3 en cp1252. Si alguien cambia el encoding
    del write, esto se pone rojo antes de que un render salga con texto roto."""
    destino = tmp_path / "vars.json"
    inv.escribir_variables(ACENTUADA, destino)
    crudo = destino.read_bytes()
    assert b"Configuraci\xc3\xb3n b\xc3\xa1sica" in crudo  # o acentuada + a acentuada
    assert b"a\xc3\xb1o 2026" in crudo  # enie
    assert b"\xc2\xbf?" in crudo and b"\xc2\xa1!" in crudo  # signos de apertura
    assert b"\xc2\xb7" in crudo  # punto medio
    assert b'\\"comillas\\"' in crudo  # comillas dobles escapadas por JSON


def test_el_json_no_escapa_los_no_ascii_a_secuencias_unicode(tmp_path):
    """ensure_ascii=False: el archivo se lee a ojo cuando HF-2 depure una plantilla."""
    destino = tmp_path / "vars.json"
    inv.escribir_variables(ACENTUADA, destino)
    assert "\\u00f3" not in destino.read_text(encoding="utf-8")


def test_renderizar_escribe_el_archivo_de_variables_y_lo_borra(tmp_path):
    visto = {}
    original = ProcesoFalso()

    class Espia(ProcesoFalso):
        def __call__(self, cmd, timeout):
            ruta = cmd[cmd.index("--variables-file") + 1]
            visto["existia"] = True
            visto["contenido"] = json.loads(open(ruta, encoding="utf-8").read())
            visto["ruta"] = ruta
            return original(cmd, timeout)

    inv.renderizar(ACENTUADA, PLANTILLA, tmp_path / "p.mov", adaptador(Espia()), timeout_s=180)
    assert visto["existia"] is True
    assert visto["contenido"]["titulo"] == TITULO
    from pathlib import Path

    assert not Path(visto["ruta"]).exists(), "el archivo de variables debe borrarse al terminar"


def test_el_archivo_de_variables_se_borra_aunque_el_render_falle(tmp_path):
    visto = {}

    class Espia(ProcesoFalso):
        def __call__(self, cmd, timeout):
            visto["ruta"] = cmd[cmd.index("--variables-file") + 1]
            return super().__call__(cmd, timeout)

    inv.renderizar(
        ACENTUADA, PLANTILLA, tmp_path / "p.mov", adaptador(Espia(codigo=1)), timeout_s=180
    )
    from pathlib import Path

    assert not Path(visto["ruta"]).exists()


def test_el_archivo_de_variables_no_queda_dentro_de_la_salida(tmp_path):
    """Va junto al temporal, no en la carpeta publicada de la cache."""
    proceso = ProcesoFalso()
    inv.renderizar(ACENTUADA, PLANTILLA, tmp_path / "p.mov", adaptador(proceso), timeout_s=180)
    cmd = proceso.llamadas[0]
    vars_ruta = cmd[cmd.index("--variables-file") + 1]
    assert salida_de(cmd).parent == type(salida_de(cmd))(vars_ruta).parent
