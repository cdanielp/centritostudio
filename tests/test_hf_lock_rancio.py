"""Umbral de lock rancio derivado del timeout (HF-1, addendum D50).

Antes eran 900 s constantes contra un timeout de 180 s. El riesgo no era el default sino
el acoplamiento invisible: subir `timeout_s` a 20 minutos dejaba el umbral en 900 s, asi
que una corrida lenta pero VIVA veia su lock reclamado por otra y las dos renderizaban la
misma pieza a la vez. El umbral tiene que crecer con el timeout por construccion.
"""

from __future__ import annotations

import pytest
from hf_dobles import PIEZA_OK, ProcesoFalso, adaptador

from hyperframes import almacen
from hyperframes.catalogo import Catalogo, Plantilla
from hyperframes.invocador import TIMEOUT_DEFAULT_S
from hyperframes.servicio import pedir_pieza

HASH = "b7" + "0" * 62


def test_el_umbral_crece_con_el_timeout():
    assert almacen.rancio_para(600) > almacen.rancio_para(180)


@pytest.mark.parametrize("timeout", [1, 30, 180, 600, 3600])
def test_el_umbral_nunca_es_menor_que_el_timeout(timeout):
    """Invariante que importa: un render vivo jamas puede ser declarado rancio."""
    assert almacen.rancio_para(timeout) > timeout


def test_el_umbral_es_el_triple_del_timeout_cuando_supera_el_piso():
    assert almacen.rancio_para(600) == 1800
    assert almacen.rancio_para(1200) == 3600


def test_hay_un_piso_para_timeouts_muy_cortos():
    """Con timeout de 1 s, 3 s de umbral reclamaria locks de procesos que solo van lentos."""
    assert almacen.rancio_para(1) == almacen.PISO_RANCIO_S
    assert almacen.PISO_RANCIO_S >= 300


def test_el_timeout_default_da_un_umbral_holgado():
    assert almacen.rancio_para(TIMEOUT_DEFAULT_S) == 540


def test_el_lock_usa_el_umbral_derivado_por_defecto(tmp_path):
    """Sin `rancio_s` explicito, el lock deriva del timeout que se le pasa."""
    with almacen.lock(tmp_path, HASH, espera_s=0, timeout_s=1):
        # umbral = PISO_RANCIO_S, muy por encima de la edad real: sigue ocupado
        with almacen.lock(tmp_path, HASH, espera_s=0, timeout_s=1) as segundo:
            assert segundo is False


def test_rancio_explicito_sigue_teniendo_prioridad(tmp_path):
    with almacen.lock(tmp_path, HASH, espera_s=0):
        with almacen.lock(tmp_path, HASH, espera_s=0, rancio_s=-1) as reclamado:
            assert reclamado is True


def test_pedir_pieza_propaga_el_timeout_al_umbral_del_lock(tmp_path, monkeypatch):
    """El timeout del servicio y el umbral del lock no pueden desincronizarse."""
    visto = {}
    original = almacen.lock

    def espia(raiz, hash_, **kw):
        visto.update(kw)
        return original(raiz, hash_, **kw)

    monkeypatch.setattr("hyperframes.servicio.almacen.lock", espia)
    catalogo = Catalogo([Plantilla("hook", "1.0.0", ("titulo", "subtitulo"), "motion/hook")])
    pedir_pieza(
        PIEZA_OK,
        destino=(1920, 1080),
        catalogo=catalogo,
        raiz_cache=tmp_path,
        adaptador=adaptador(ProcesoFalso()),
        timeout_s=600,
    )
    assert visto["timeout_s"] == 600
