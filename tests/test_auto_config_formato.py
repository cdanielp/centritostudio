"""HF-4 Formato dual: el campo `formato` de AutoConfig y su contrato de fingerprint.

Mismo patron que la capa de letreros (test_hf3_motion_capa.py): un campo nuevo en `to_dict()`
invalidaria de golpe todos los paquetes v2 ya existentes si no se omite en el caso default.
`formato="9:16"` es esa ruta historica: tiene que fingerprintear exactamente igual que antes
de que este campo existiera.
"""

from __future__ import annotations

import pytest

from auto_config import FORMATOS, AutoConfig, AutoConfigError


def test_el_default_es_9x16():
    assert AutoConfig().formato == "9:16"


def test_formato_9x16_no_entra_al_to_dict():
    assert "formato" not in AutoConfig().to_dict()
    assert "formato" not in AutoConfig(formato="9:16").to_dict()


def test_formato_9x16_el_fingerprint_es_el_historico():
    """Pasar formato="9:16" explicito, o no pasarlo, tiene que dar el MISMO fingerprint: si no,
    este campo invalidaria todos los checkpoints v2 ya existentes sin cambiar un solo byte de
    salida."""
    historico = AutoConfig(mode="v2")
    assert historico.fingerprint() == AutoConfig(mode="v2", formato="9:16").fingerprint()


def test_formato_16x9_y_ambos_cambian_el_fingerprint():
    base = AutoConfig(mode="v2").fingerprint()
    assert AutoConfig(mode="v2", formato="16:9").fingerprint() != base
    assert AutoConfig(mode="v2", formato="ambos").fingerprint() != base
    assert (
        AutoConfig(mode="v2", formato="16:9").fingerprint()
        != AutoConfig(mode="v2", formato="ambos").fingerprint()
    )


def test_formato_16x9_entra_al_to_dict():
    assert AutoConfig(formato="16:9").to_dict()["formato"] == "16:9"
    assert AutoConfig(formato="ambos").to_dict()["formato"] == "ambos"


def test_formato_invalido_es_error_de_contrato():
    with pytest.raises(AutoConfigError, match="formato invalido"):
        AutoConfig(formato="4:3")


@pytest.mark.parametrize("formato", sorted(FORMATOS))
def test_formatos_validos_no_exigen_v2(formato):
    """A diferencia de motion_enabled, formato no exige mode='v2': classic tambien puede pedir
    16:9/ambos (solo que sin broll ni letreros, que ya exigian v2 por su cuenta)."""
    AutoConfig(mode="classic", formato=formato)  # no debe levantar
