"""Contrato de pieza HF-1: esquema estricto, canonicalizacion y hash.

Fija el JSON canonico y el hash del JSON. NUNCA fija pixeles ni sha256 de un MOV
(regla dura 3 de HF-1): el hash aqui es sobre TEXTO, no sobre video.
"""

from __future__ import annotations

import pytest
from hf_dobles import ENTORNO, PIEZA_OK
from hf_dobles import pieza as _pieza

from hyperframes import contrato as ct
from hyperframes.errores import ContratoInvalido

# ─────────────────────────── canonicalizacion ────────────────────────────


def test_canonico_no_depende_del_orden_de_claves():
    """Dos dicts semanticamente iguales con distinto orden dan el MISMO texto canonico."""
    revuelto = dict(reversed(list(PIEZA_OK.items())))
    assert ct.canonicalizar(revuelto) == ct.canonicalizar(PIEZA_OK)


def test_canonico_es_utf8_sin_escapes_ni_espacios_ni_salto_final():
    """ensure_ascii=False, separadores compactos, sin newline final."""
    texto = ct.canonicalizar(_pieza(texto={"titulo": "Configuración", "subtitulo": "año"}))
    assert "Configuración" in texto  # sin ó
    assert ", " not in texto and '": ' not in texto  # separadores compactos
    assert not texto.endswith("\n")
    texto.encode("utf-8")  # codificable sin perdida


def test_canonico_ordena_claves_anidadas():
    """El orden estable alcanza a los diccionarios anidados, no solo al nivel raiz."""
    revuelto = _pieza(marca={"texto": "#FFFFFF", "secundario": "#111111", "primario": "#FF5A2B"})
    assert ct.canonicalizar(revuelto) == ct.canonicalizar(PIEZA_OK)


# ──────────────────────────────── hash ───────────────────────────────────


def test_hash_estable_para_el_mismo_contrato_y_entorno():
    a = ct.calcular_hash(PIEZA_OK, ENTORNO)
    b = ct.calcular_hash(dict(reversed(list(PIEZA_OK.items()))), ENTORNO)
    assert a == b
    assert len(a) == 64 and all(c in "0123456789abcdef" for c in a)


def test_hash_cambia_si_cambia_un_color():
    otro = _pieza(marca={"primario": "#FF5A2C", "secundario": "#111111", "texto": "#FFFFFF"})
    assert ct.calcular_hash(otro, ENTORNO) != ct.calcular_hash(PIEZA_OK, ENTORNO)


def test_hash_cambia_si_cambia_la_version_de_la_plantilla():
    otro = _pieza(plantilla={"nombre": "hook", "version": "1.0.1"})
    assert ct.calcular_hash(otro, ENTORNO) != ct.calcular_hash(PIEZA_OK, ENTORNO)


@pytest.mark.parametrize("clave", ["hyperframes", "node", "chromium", "ffmpeg"])
def test_hash_cambia_si_cambia_cualquier_version_del_entorno(clave):
    """Las CUATRO versiones del entorno entran al hash: un Chrome nuevo invalida la cache."""
    otro_entorno = dict(ENTORNO, **{clave: ENTORNO[clave] + ".9"})
    assert ct.calcular_hash(PIEZA_OK, otro_entorno) != ct.calcular_hash(PIEZA_OK, ENTORNO)


def test_hash_no_colisiona_por_concatenacion_ambigua():
    """Mover un caracter entre dos versiones no puede dar el mismo hash (separador real)."""
    a = dict(ENTORNO, node="v24.18", chromium="0152.0.7928.2")
    b = dict(ENTORNO, node="v24.180", chromium="152.0.7928.2")
    assert ct.calcular_hash(PIEZA_OK, a) != ct.calcular_hash(PIEZA_OK, b)


# ─────────────────────────── esquema estricto ────────────────────────────


def test_contrato_valido_pasa_y_devuelve_los_campos():
    c = ct.validar_contrato(PIEZA_OK)
    assert c["pieza_id"] == "hook_principal"
    assert c["duracion_ms"] == 6000


def test_campo_desconocido_es_error_no_se_ignora():
    with pytest.raises(ContratoInvalido) as exc:
        ct.validar_contrato(_pieza(color_favorito="azul"))
    assert "color_favorito" in str(exc.value)


def test_campo_faltante_es_error_y_lo_nombra():
    d = _pieza()
    del d["duracion_ms"]
    with pytest.raises(ContratoInvalido) as exc:
        ct.validar_contrato(d)
    assert "duracion_ms" in str(exc.value)


def test_version_de_contrato_distinta_dice_recibida_y_soportada():
    with pytest.raises(ContratoInvalido) as exc:
        ct.validar_contrato(_pieza(contrato=2))
    mensaje = str(exc.value)
    assert "2" in mensaje and "1" in mensaje


@pytest.mark.parametrize("malo", ["FF5A2B", "#FF5A2", "#GGGGGG", "rojo", "#ff5a2b22", 123])
def test_color_mal_formado_es_error(malo):
    with pytest.raises(ContratoInvalido):
        ct.validar_contrato(
            _pieza(marca={"primario": malo, "secundario": "#111111", "texto": "#FFFFFF"})
        )


def test_color_acepta_minusculas_y_mayusculas():
    ct.validar_contrato(
        _pieza(marca={"primario": "#ff5a2b", "secundario": "#111111", "texto": "#FFFFFF"})
    )


@pytest.mark.parametrize(
    "campo,valor", [("duracion_ms", 0), ("duracion_ms", -1), ("fps", 0), ("fps", -30)]
)
def test_duracion_y_fps_deben_ser_positivos(campo, valor):
    with pytest.raises(ContratoInvalido) as exc:
        ct.validar_contrato(_pieza(**{campo: valor}))
    assert campo in str(exc.value)


def test_duracion_y_fps_deben_ser_enteros_no_flotantes():
    with pytest.raises(ContratoInvalido):
        ct.validar_contrato(_pieza(fps=29.97))


def test_booleano_audio_no_acepta_enteros():
    """True/False estrictos: 0 y 1 no son booleanos aqui (evita paquetes ambiguos en HF-2)."""
    with pytest.raises(ContratoInvalido):
        ct.validar_contrato(_pieza(audio=0))


def test_pieza_id_debe_ser_basename_seguro():
    """Reutiliza path_safety: un pieza_id con separador jamas construye una ruta."""
    with pytest.raises(ContratoInvalido):
        ct.validar_contrato(_pieza(pieza_id="../fuga"))


@pytest.mark.parametrize("modo", ["caja", "cuadro_completo"])
def test_posicion_modo_admite_los_dos_valores_del_esquema(modo):
    """El ESQUEMA admite caja; el perfil de capacidad la rechaza aparte (son capas distintas)."""
    pos = {"modo": "caja", "x": 0, "y": 0, "ancho": 100, "alto": 100, "anclaje": "arriba_izquierda"}
    ct.validar_contrato(_pieza(posicion=pos if modo == "caja" else {"modo": "cuadro_completo"}))


def test_posicion_modo_desconocido_es_error():
    with pytest.raises(ContratoInvalido):
        ct.validar_contrato(_pieza(posicion={"modo": "flotante"}))


def test_posicion_caja_exige_sus_campos():
    with pytest.raises(ContratoInvalido) as exc:
        ct.validar_contrato(_pieza(posicion={"modo": "caja", "x": 0}))
    assert "ancho" in str(exc.value) or "alto" in str(exc.value)


def test_posicion_cuadro_completo_no_admite_campos_de_caja():
    with pytest.raises(ContratoInvalido):
        ct.validar_contrato(_pieza(posicion={"modo": "cuadro_completo", "x": 10}))


@pytest.mark.parametrize("fit", ["nativo", "cover", "contain"])
def test_fit_admite_los_tres_del_esquema(fit):
    ct.validar_contrato(_pieza(fit=fit))


def test_fit_desconocido_es_error():
    with pytest.raises(ContratoInvalido):
        ct.validar_contrato(_pieza(fit="estirar"))


def test_semilla_debe_ser_entero_no_negativo():
    with pytest.raises(ContratoInvalido):
        ct.validar_contrato(_pieza(semilla=-1))


def test_tamano_exige_ancho_y_alto_positivos():
    with pytest.raises(ContratoInvalido):
        ct.validar_contrato(_pieza(tamano={"ancho": 1920, "alto": 0}))


def test_texto_debe_ser_diccionario_de_cadenas():
    with pytest.raises(ContratoInvalido):
        ct.validar_contrato(_pieza(texto={"titulo": 42}))


def test_validar_no_muta_la_entrada():
    """El validador es puro: HF-2 puede reusar su dict despues de validar."""
    original = _pieza()
    copia = ct.canonicalizar(original)
    ct.validar_contrato(original)
    assert ct.canonicalizar(original) == copia
