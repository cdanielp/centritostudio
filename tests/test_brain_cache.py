"""Cache del sidecar del brain: una transcripcion identica no vuelve a llamar al LLM.

Antes, `analizar_grupos` llamaba al proveedor en TODA corrida y escribia
`transcripts/{stem}.brain.json` que nadie volvia a leer. Eso costaba una llamada por
re-render y, como un LLM no devuelve lo mismo dos veces, hacia que el mismo clip saliera
distinto en cada pasada.

Ninguna prueba de aqui toca la red: el proveedor se sustituye por un doble que cuenta llamadas.
"""

from __future__ import annotations

import json

import pytest

import brain

GRUPOS = [
    {"id": 0, "words": [{"text": "la", "start": 0.0}, {"text": "desercion", "start": 0.4}]},
    {"id": 1, "words": [{"text": "subio", "start": 1.0}, {"text": "mucho", "start": 1.5}]},
]
RESPUESTA = {"groups": [{"g": 0, "kw": 1, "emoji": None}]}


@pytest.fixture
def llm(monkeypatch, tmp_path):
    """Doble del proveedor que cuenta llamadas, y `transcripts/` redirigido al tmp."""
    llamadas = []

    def _dispatch(messages):
        llamadas.append(messages)
        return json.loads(json.dumps(RESPUESTA)), {"total": 100}

    monkeypatch.setattr(brain, "_dispatch", _dispatch)
    monkeypatch.setattr(brain, "TRANSCRIPTS", tmp_path)
    return llamadas


def test_la_primera_corrida_llama_y_escribe_el_sidecar(llm, tmp_path):
    datos = brain.analizar_grupos(GRUPOS, video_name="clip")
    assert len(llm) == 1
    sidecar = tmp_path / "clip.brain.json"
    assert sidecar.is_file()
    guardado = json.loads(sidecar.read_text(encoding="utf-8"))
    assert guardado["grupos_hash"] == brain.hash_de_grupos(GRUPOS)
    assert datos["groups"]


def test_la_segunda_corrida_no_llama_al_llm(llm):
    brain.analizar_grupos(GRUPOS, video_name="clip")
    brain.analizar_grupos(GRUPOS, video_name="clip")
    assert len(llm) == 1, "la segunda corrida volvio a llamar al proveedor"


def test_la_segunda_corrida_devuelve_lo_mismo(llm):
    uno = brain.analizar_grupos(GRUPOS, video_name="clip")
    otro = brain.analizar_grupos(GRUPOS, video_name="clip")
    assert uno["groups"] == otro["groups"]


def test_un_texto_distinto_invalida_la_cache(llm):
    brain.analizar_grupos(GRUPOS, video_name="clip")
    otros = [
        {"id": 0, "words": [{"text": "otra", "start": 0.0}, {"text": "cosa", "start": 0.4}]},
    ]
    brain.analizar_grupos(otros, video_name="clip")
    assert len(llm) == 2


def test_un_cambio_solo_de_TIEMPOS_no_invalida_la_cache(llm):
    """El LLM solo ve el texto: un desplazamiento de milisegundos no puede cambiar su respuesta."""
    brain.analizar_grupos(GRUPOS, video_name="clip")
    movidos = [
        {
            "id": g["id"],
            "words": [{"text": w["text"], "start": w["start"] + 10.0} for w in g["words"]],
        }
        for g in GRUPOS
    ]
    datos = brain.analizar_grupos(movidos, video_name="clip")
    assert len(llm) == 1
    # ...pero el timestamp de la keyword SI se recalcula contra los grupos de ahora.
    assert datos["groups"][0]["kw_ts"] == pytest.approx(10.4)


def test_forzar_salta_la_cache(llm):
    brain.analizar_grupos(GRUPOS, video_name="clip")
    brain.analizar_grupos(GRUPOS, video_name="clip", forzar=True)
    assert len(llm) == 2


def test_el_default_es_usar_la_cache():
    import inspect

    firma = inspect.signature(brain.analizar_grupos)
    assert firma.parameters["forzar"].default is False


def test_un_sidecar_sin_huella_no_se_reutiliza(llm, tmp_path):
    """Los sidecars escritos antes de esta cache no traen `grupos_hash`: fail-closed."""
    (tmp_path / "clip.brain.json").write_text(
        json.dumps({"provider": "x", "groups": [{"g": 0, "kw": 0}]}), encoding="utf-8"
    )
    brain.analizar_grupos(GRUPOS, video_name="clip")
    assert len(llm) == 1


def test_un_sidecar_corrupto_no_tumba_nada(llm, tmp_path):
    (tmp_path / "clip.brain.json").write_text("{no es json", encoding="utf-8")
    datos = brain.analizar_grupos(GRUPOS, video_name="clip")
    assert len(llm) == 1
    assert datos["groups"]


def test_sin_video_name_no_hay_cache_posible(llm):
    """Sin nombre no hay sidecar donde guardar ni de donde leer: se llama siempre."""
    brain.analizar_grupos(GRUPOS)
    brain.analizar_grupos(GRUPOS)
    assert len(llm) == 2


def test_la_huella_solo_mira_el_texto_y_el_id():
    movidos = [
        {
            "id": g["id"],
            "words": [{"text": w["text"], "start": w["start"] + 5.0} for w in g["words"]],
        }
        for g in GRUPOS
    ]
    assert brain.hash_de_grupos(GRUPOS) == brain.hash_de_grupos(movidos)
    distinto = [{"id": 0, "words": [{"text": "otra", "start": 0.0}]}]
    assert brain.hash_de_grupos(GRUPOS) != brain.hash_de_grupos(distinto)


def test_auto_pasa_el_flag_al_brain(monkeypatch):
    """`_brain_fail_open` es la fuente unica que usan la ruta classic y Auto v2."""
    import auto

    vistos = {}

    def _falso(grupos, video_name="", forzar=False):
        vistos["forzar"] = forzar
        return {"groups": [{"g": 0}]}

    monkeypatch.setattr(brain, "analizar_grupos", _falso)
    auto._brain_fail_open(GRUPOS, "clip")
    assert vistos["forzar"] is False
    auto._brain_fail_open(GRUPOS, "clip", forzar=True)
    assert vistos["forzar"] is True
