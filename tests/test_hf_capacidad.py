"""Perfil de capacidad HF-1: que puede consumir HOY la ruta de clips de Centrito.

El perfil vive en UNA constante (`capacidad.PERFIL_RUTA_CLIPS`). Cada rechazo nombra el
campo, el valor recibido y la linea de clip_overlay.py que impone el limite, para que HF-3
sepa exactamente que desbloquear.
"""

from __future__ import annotations

import pytest
from hf_dobles import DESTINO, PIEZA_OK
from hf_dobles import pieza as _pieza

from hyperframes import capacidad
from hyperframes.errores import CapacidadNoSoportada


def test_pieza_conforme_pasa_sin_error():
    capacidad.verificar_capacidad(PIEZA_OK, DESTINO)


def test_posicion_caja_es_rechazada_y_nombra_la_linea():
    pos = {"modo": "caja", "x": 0, "y": 0, "ancho": 100, "alto": 100, "anclaje": "arriba_izquierda"}
    with pytest.raises(CapacidadNoSoportada) as exc:
        capacidad.verificar_capacidad(_pieza(posicion=pos), DESTINO)
    mensaje = str(exc.value)
    assert "posicion.modo" in mensaje
    assert "caja" in mensaje
    assert "clip_overlay.py:144" in mensaje


@pytest.mark.parametrize("fit", ["cover", "contain"])
def test_fit_distinto_de_nativo_es_rechazado_y_nombra_la_linea(fit):
    with pytest.raises(CapacidadNoSoportada) as exc:
        capacidad.verificar_capacidad(_pieza(fit=fit), DESTINO)
    mensaje = str(exc.value)
    assert "fit" in mensaje
    assert fit in mensaje
    assert "clip_overlay.py:20" in mensaje


def test_audio_true_es_rechazado_y_nombra_la_linea():
    with pytest.raises(CapacidadNoSoportada) as exc:
        capacidad.verificar_capacidad(_pieza(audio=True), DESTINO)
    mensaje = str(exc.value)
    assert "audio" in mensaje
    assert "clip_overlay.py:73" in mensaje


def test_tamano_distinto_del_destino_es_rechazado():
    with pytest.raises(CapacidadNoSoportada) as exc:
        capacidad.verificar_capacidad(PIEZA_OK, (1080, 1920))
    mensaje = str(exc.value)
    assert "tamano" in mensaje
    assert "1920x1080" in mensaje and "1080x1920" in mensaje


def test_los_cuatro_limites_estan_declarados_en_una_sola_constante():
    """El perfil no se dispersa en ifs: es dato inspeccionable que HF-3 lee para saber que abrir."""
    perfil = capacidad.PERFIL_RUTA_CLIPS
    assert set(perfil) == {"posicion_modo", "fit", "audio", "tamano"}
    for limite in perfil.values():
        assert limite.referencia.startswith("clip_overlay.py:")
        assert limite.motivo


def test_mensaje_de_rechazo_no_lleva_em_dash():
    """Regla dura 6 de HF-1: sin em dashes en mensajes de error."""
    with pytest.raises(CapacidadNoSoportada) as exc:
        capacidad.verificar_capacidad(_pieza(audio=True), DESTINO)
    assert "—" not in str(exc.value)
