"""Lectura de versiones del entorno HF-1.

Las cuatro versiones se leen en TIEMPO DE EJECUCION desde `hyperframes doctor --json`.
Si no se pueden leer es fallo con razon, nunca un default inventado (si se inventara, la
cache serviria un MOV renderizado con otro Chrome como si fuera valido).
"""

from __future__ import annotations

import json

import pytest
from hyperframes import entorno as en
from hyperframes.errores import EntornoIlegible

DOCTOR_OK = {
    "ok": False,  # global false por Docker/whisper opcionales: NO se gatea aqui
    "checks": [
        {"name": "Version", "ok": True, "detail": "0.7.90 (latest)"},
        {"name": "Node.js", "ok": True, "detail": "v24.18.0 (win32 x64)"},
        {
            "name": "FFmpeg",
            "ok": True,
            "detail": "ffmpeg 8.0-essentials_build-www.gyan.dev at C:\\bin\\ffmpeg.exe",
        },
        {
            "name": "Chrome",
            "ok": True,
            "detail": "cache: $HOME\\.cache\\hyperframes\\chrome\\chrome-headless-shell\\"
            "win64-152.0.7928.2\\chrome-headless-shell-win64\\chrome-headless-shell.exe",
        },
    ],
}


def test_extrae_las_cuatro_versiones_del_payload_real():
    v = en.parsear_doctor(json.dumps(DOCTOR_OK))
    assert v == {
        "hyperframes": "0.7.90",
        "node": "v24.18.0",
        "chromium": "152.0.7928.2",
        "ffmpeg": "8.0-essentials_build-www.gyan.dev",
    }


def test_ok_global_false_no_impide_leer_el_entorno():
    """Hallazgo HF-1: doctor devuelve ok=false por Docker/whisper ausentes, que no importan
    para renderizar. Gatear en `ok` global seria un falso negativo permanente en esta maquina."""
    payload = json.loads(json.dumps(DOCTOR_OK))
    payload["ok"] = False
    en.parsear_doctor(json.dumps(payload))


@pytest.mark.parametrize("nombre", ["Version", "Node.js", "FFmpeg", "Chrome"])
def test_falta_un_check_obligatorio_es_entorno_ilegible(nombre):
    payload = json.loads(json.dumps(DOCTOR_OK))
    payload["checks"] = [c for c in payload["checks"] if c["name"] != nombre]
    with pytest.raises(EntornoIlegible) as exc:
        en.parsear_doctor(json.dumps(payload))
    assert nombre in str(exc.value)


@pytest.mark.parametrize("nombre", ["Version", "Node.js", "FFmpeg", "Chrome"])
def test_check_en_false_es_entorno_ilegible(nombre):
    payload = json.loads(json.dumps(DOCTOR_OK))
    for c in payload["checks"]:
        if c["name"] == nombre:
            c["ok"] = False
    with pytest.raises(EntornoIlegible):
        en.parsear_doctor(json.dumps(payload))


def test_chrome_sin_version_reconocible_es_ilegible_no_default():
    payload = json.loads(json.dumps(DOCTOR_OK))
    for c in payload["checks"]:
        if c["name"] == "Chrome":
            c["detail"] = "cache: C:\\sin\\numero\\de\\version"
    with pytest.raises(EntornoIlegible) as exc:
        en.parsear_doctor(json.dumps(payload))
    assert "Chrome" in str(exc.value)


def test_json_invalido_es_entorno_ilegible():
    with pytest.raises(EntornoIlegible):
        en.parsear_doctor("no soy json")


def test_salida_con_ruido_antes_del_json_se_tolera():
    """La CLI imprime avisos antes del JSON; el parser toma el primer objeto valido."""
    ruido = "Hyperframes collects anonymous usage data.\n" + json.dumps(DOCTOR_OK)
    assert en.parsear_doctor(ruido)["hyperframes"] == "0.7.90"


def test_versiones_no_vacias_en_ninguna_clave():
    payload = json.loads(json.dumps(DOCTOR_OK))
    for c in payload["checks"]:
        if c["name"] == "Version":
            c["detail"] = "   "
    with pytest.raises(EntornoIlegible):
        en.parsear_doctor(json.dumps(payload))
