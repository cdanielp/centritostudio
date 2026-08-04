"""Claves reservadas del aplanado (HF-1, addendum D50.5).

El aplanado deja los slots de texto en el MISMO nivel raiz que las claves del sistema. Un
slot llamado `fps` NO llegaria nunca: la clave del sistema lo sobrescribe y la plantilla
pinta `30` donde esperaba una frase, con el render devolviendo codigo 0. Es exactamente la
misma clase de fallo silencioso que D50.1 elimino.

La reserva se DERIVA de las claves que genera el aplanado, no de un literal escrito a mano.
Un literal es correcto el dia que se escribe y se queda atras en cuanto el contrato crece:
quien anada un campo nuevo a `variables_de` no tiene por que acordarse de una segunda lista.
"""

from __future__ import annotations

import pytest
from hf_dobles import PIEZA_OK, pieza

from hyperframes import contrato as ct
from hyperframes.errores import ContratoInvalido
from hyperframes.invocador import claves_reservadas, variables_de

LAS_OCHO = (
    "duracion_ms",
    "fps",
    "marca_primario",
    "marca_secundario",
    "marca_texto",
    "semilla",
    "tamano_alto",
    "tamano_ancho",
)


# ───────────────────────────── la lista ──────────────────────────────────


def test_son_exactamente_las_ocho():
    assert set(claves_reservadas()) == set(LAS_OCHO)
    assert len(claves_reservadas()) == 8


def test_la_reserva_es_exactamente_lo_que_genera_el_aplanado_sin_slots():
    """Invariante: reservadas == claves del sistema. Ni una de menos (hueco por el que se
    cuela un slot que pisa) ni una de mas (rechazo de un nombre legitimo)."""
    del_sistema = set(variables_de(PIEZA_OK)) - set(PIEZA_OK["texto"])
    assert set(claves_reservadas()) == del_sistema


def test_la_reserva_se_deriva_y_no_es_un_literal(monkeypatch):
    """Si el contrato crece con un campo nuevo, la reserva lo recoge SOLA.

    Este es el punto del ejercicio: con una tupla escrita a mano, este test se pone rojo el
    dia que alguien anade una clave al aplanado y no toca la segunda lista.
    """
    import hyperframes.invocador as inv

    original = inv.variables_de
    monkeypatch.setattr(inv, "variables_de", lambda dato: {**original(dato), "campo_futuro": 1})
    assert "campo_futuro" in inv.claves_reservadas()


def test_la_reserva_no_depende_de_la_pieza_concreta():
    """Se calcula sobre la forma del contrato, no sobre los datos de una pieza."""
    assert claves_reservadas() == claves_reservadas()
    assert set(claves_reservadas()).isdisjoint(set(PIEZA_OK["texto"]))


def test_viene_ordenada_para_que_el_mensaje_sea_estable():
    assert list(claves_reservadas()) == sorted(claves_reservadas())


# ──────────────────────── rechazo por colision ───────────────────────────


@pytest.mark.parametrize("reservada", LAS_OCHO)
def test_un_slot_con_cada_clave_reservada_es_contrato_invalido(reservada):
    """Las OCHO, una por una: ninguna puede colarse como slot de texto."""
    with pytest.raises(ContratoInvalido) as exc:
        ct.validar_slots(
            pieza(texto={"titulo": "a", reservada: "valor pirata"}),
            ("titulo", reservada),
        )
    mensaje = str(exc.value)
    assert reservada in mensaje, f"el mensaje no nombra la clave {reservada}"
    assert "reservad" in mensaje.lower()


@pytest.mark.parametrize("reservada", LAS_OCHO)
def test_el_rechazo_ocurre_aunque_sea_el_unico_slot(reservada):
    with pytest.raises(ContratoInvalido):
        ct.validar_slots(pieza(texto={reservada: "x"}), (reservada,))


def test_el_mensaje_lista_todas_las_reservadas_para_que_hf2_sepa_cuales_evitar():
    with pytest.raises(ContratoInvalido) as exc:
        ct.validar_slots(pieza(texto={"fps": "x"}), ("fps",))
    mensaje = str(exc.value)
    for clave in LAS_OCHO:
        assert clave in mensaje


def test_los_nombres_de_slot_legitimos_siguen_pasando():
    for nombre in ("titulo", "subtitulo", "cta", "autor", "fecha", "marca", "tamano"):
        ct.validar_slots(pieza(texto={nombre: "x"}), (nombre,))


def test_sin_el_guard_el_slot_se_perderia_en_silencio():
    """Documenta la DIRECCION real de la colision, medida, no supuesta.

    En el aplanado los slots van primero, asi que gana la clave del sistema: el texto del
    slot se pierde y la plantilla pintaria `30` donde esperaba una frase. No es que el slot
    corrompa el fps; es que el slot desaparece. Igual de silencioso, y por eso se rechaza.
    """
    contaminada = pieza(texto={"titulo": "t", "fps": "pirata"})
    with pytest.raises(ContratoInvalido):
        ct.validar_slots(contaminada, ("titulo", "fps"))
    assert variables_de(contaminada)["fps"] == 30, "gana el sistema, no el slot"
