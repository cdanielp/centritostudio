"""Perfil de capacidad: que puede consumir HOY la ruta de clips de Centrito.

El perfil vive en UNA constante (`capacidad.PERFIL_RUTA_CLIPS`). Cada rechazo nombra el
campo, el valor recibido y quien impone el limite.

HF-3 levanto tres de los cuatro limites de HF-1: `fit` admite ahora `nativo` y `cover`,
`posicion.modo` admite `caja`, y el tamano exigido depende de donde se coloque la pieza.
El del audio sigue en pie y NO lo impone `clip_overlay`, sino el mapeo `-map 0:a` del render.
"""

from __future__ import annotations

import pytest
from hf_dobles import DESTINO, PIEZA_OK
from hf_dobles import pieza as _pieza

import clip_overlay
from hyperframes import capacidad
from hyperframes.errores import CapacidadNoSoportada

CAJA = {"modo": "caja", "x": 40, "y": 60, "ancho": 400, "alto": 300, "anclaje": "arriba_izquierda"}


def test_pieza_conforme_pasa_sin_error():
    capacidad.verificar_capacidad(PIEZA_OK, DESTINO)


def test_posicion_caja_es_admitida_si_el_tamano_es_el_de_la_caja():
    """HF-3 1.3: la caja se desbloqueo, y la pieza debe medir lo que mide la caja."""
    dato = _pieza(posicion=CAJA, tamano={"ancho": 400, "alto": 300})
    capacidad.verificar_capacidad(dato, DESTINO)


def test_posicion_caja_con_tamano_de_cuadro_completo_es_rechazada():
    """Con fit nativo no hay escalado: una pieza de 1920x1080 en una caja de 400x300 mentiria."""
    with pytest.raises(CapacidadNoSoportada) as exc:
        capacidad.verificar_capacidad(_pieza(posicion=CAJA), DESTINO)
    mensaje = str(exc.value)
    assert "tamano" in mensaje
    assert "400x300" in mensaje


def test_posicion_modo_desconocido_sigue_rechazandose():
    pos = {"modo": "diagonal"}
    with pytest.raises(CapacidadNoSoportada) as exc:
        capacidad.verificar_capacidad(_pieza(posicion=pos), DESTINO)
    assert "posicion.modo" in str(exc.value)


@pytest.mark.parametrize("fit", ["nativo", "cover"])
def test_fit_soportado_por_la_ruta_de_clips_es_admitido(fit):
    capacidad.verificar_capacidad(_pieza(fit=fit), DESTINO)


def test_fit_contain_sigue_rechazado_porque_la_cadena_no_lo_implementa():
    with pytest.raises(CapacidadNoSoportada) as exc:
        capacidad.verificar_capacidad(_pieza(fit="contain"), DESTINO)
    mensaje = str(exc.value)
    assert "fit" in mensaje
    assert "contain" in mensaje


def test_la_lista_de_fit_no_se_duplica_se_lee_de_clip_overlay():
    """Dos listas separadas se desincronizan y el perfil terminaria mintiendo.

    Se comprueba en negativo: un fit que `clip_overlay` NO admite tampoco puede pasar aqui.
    """
    assert "contain" not in clip_overlay.FIT_VALIDOS
    with pytest.raises(CapacidadNoSoportada):
        capacidad.verificar_capacidad(_pieza(fit="contain"), DESTINO)


def test_audio_true_es_rechazado_y_nombra_a_quien_lo_impone():
    with pytest.raises(CapacidadNoSoportada) as exc:
        capacidad.verificar_capacidad(_pieza(audio=True), DESTINO)
    mensaje = str(exc.value)
    assert "audio" in mensaje
    assert "0:a" in mensaje


def test_tamano_distinto_del_destino_es_rechazado():
    with pytest.raises(CapacidadNoSoportada) as exc:
        capacidad.verificar_capacidad(PIEZA_OK, (1080, 1920))
    mensaje = str(exc.value)
    assert "tamano" in mensaje
    assert "1920x1080" in mensaje and "1080x1920" in mensaje


def test_los_cuatro_limites_estan_declarados_en_una_sola_constante():
    """El perfil no se dispersa en ifs: es dato inspeccionable que dice que falta abrir."""
    perfil = capacidad.PERFIL_RUTA_CLIPS
    assert set(perfil) == {"posicion_modo", "fit", "audio", "tamano"}
    for limite in perfil.values():
        assert limite.referencia
        assert limite.motivo


def test_mensaje_de_rechazo_no_lleva_em_dash():
    """Regla dura 6 de HF-1: sin em dashes en mensajes de error."""
    with pytest.raises(CapacidadNoSoportada) as exc:
        capacidad.verificar_capacidad(_pieza(audio=True), DESTINO)
    assert "—" not in str(exc.value)
