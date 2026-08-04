"""Servicio HF-1: `pedir_pieza` fail-open, vocabulario cerrado y concurrencia.

`pedir_pieza` es lo unico que HF-3 (Auto v2) llamara. NUNCA lanza por un fallo de render:
un motion graphic que no sale no puede tumbar un paquete de clips (regla de oro 8 del repo,
fail-open del cerebro, aplicada al Motor B).
"""

from __future__ import annotations

import threading

import pytest
from hf_dobles import DESTINO, ENTORNO, PIEZA_OK, ProcesoFalso, adaptador, pieza, sondeo_falso

from hyperframes import pedir_pieza
from hyperframes.catalogo import Catalogo, Plantilla
from hyperframes.razones import RAZONES, Razon

PLANTILLA = Plantilla(
    nombre="hook", version="1.0.0", slots_texto=("titulo", "subtitulo"), proyecto="motion/hook"
)
CATALOGO = Catalogo([PLANTILLA])


def _pedir(tmp_path, dato=None, *, ad=None, **kw):
    return pedir_pieza(
        dato if dato is not None else PIEZA_OK,
        destino=DESTINO,
        catalogo=CATALOGO,
        raiz_cache=tmp_path,
        adaptador=ad or adaptador(),
        **kw,
    )


# ──────────────────────── vocabulario cerrado ────────────────────────────


def test_el_conjunto_de_razones_es_exactamente_el_acordado():
    assert {r.value for r in RAZONES} == {
        "binario_ausente",
        "contrato_invalido",
        "capacidad_no_soportada",
        "plantilla_desconocida",
        "timeout_render",
        "render_fallido",
        "salida_invalida",
        "cache_corrupta",
        "lock_ocupado",
    }


def test_razones_no_tiene_duplicados_ni_sobrantes():
    assert len(RAZONES) == 9
    assert len(set(RAZONES)) == 9


# ───────────────────────────── camino feliz ──────────────────────────────


def test_render_exitoso_devuelve_resultado_completo(tmp_path):
    r = _pedir(tmp_path)
    assert r.razon_fallo is None
    assert r.ruta_mov is not None and r.ruta_mov.exists()
    assert r.desde_cache is False
    assert r.pix_fmt == "yuva444p12le"
    assert r.duracion_ms_real == 6000 and r.fps_real == 30
    assert r.sha256 and len(r.sha256) == 64
    assert r.entorno == ENTORNO
    assert r.hash


def test_consumo_sugerido_trae_los_ajustes_de_hf0(tmp_path):
    """HF-3 no debe redescubrir que fade va en false ni que la ruta encaja con cover."""
    r = _pedir(tmp_path)
    assert r.consumo_sugerido == {"fade": False, "fit": "cover", "mute": True}


def test_segunda_llamada_es_hit_y_no_invoca_el_proceso(tmp_path):
    proceso = ProcesoFalso()
    ad = adaptador(proceso)
    primera = _pedir(tmp_path, ad=ad)
    segunda = _pedir(tmp_path, ad=ad)
    assert proceso.veces == 1
    assert segunda.desde_cache is True
    assert segunda.hash == primera.hash
    assert segunda.ruta_mov == primera.ruta_mov


def test_el_resultado_es_serializable_a_json(tmp_path):
    """HF-3 guardara esto en el paquete: tiene que sobrevivir a json.dumps."""
    import json

    json.dumps(_pedir(tmp_path).a_dict())


# ─────────────────────────────── fail-open ───────────────────────────────


def test_binario_ausente_devuelve_razon_y_no_lanza(tmp_path):
    r = _pedir(tmp_path, ad=adaptador(binario=None))
    assert r.razon_fallo is Razon.BINARIO_AUSENTE
    assert r.ruta_mov is None


def test_contrato_invalido_no_lanza_desde_pedir_pieza(tmp_path):
    r = _pedir(tmp_path, pieza(fps=-1))
    assert r.razon_fallo is Razon.CONTRATO_INVALIDO
    assert r.ruta_mov is None


def test_capacidad_no_soportada_no_lanza(tmp_path):
    r = _pedir(tmp_path, pieza(audio=True))
    assert r.razon_fallo is Razon.CAPACIDAD_NO_SOPORTADA


def test_plantilla_desconocida_no_lanza(tmp_path):
    r = _pedir(tmp_path, pieza(plantilla={"nombre": "no-existe", "version": "9.9.9"}))
    assert r.razon_fallo is Razon.PLANTILLA_DESCONOCIDA


def test_version_de_plantilla_que_no_esta_en_el_catalogo_es_desconocida(tmp_path):
    r = _pedir(tmp_path, pieza(plantilla={"nombre": "hook", "version": "2.0.0"}))
    assert r.razon_fallo is Razon.PLANTILLA_DESCONOCIDA


def test_slot_de_texto_faltante_es_contrato_invalido(tmp_path):
    r = _pedir(tmp_path, pieza(texto={"titulo": "solo uno"}))
    assert r.razon_fallo is Razon.CONTRATO_INVALIDO


def test_slot_de_texto_sobrante_es_contrato_invalido(tmp_path):
    r = _pedir(tmp_path, pieza(texto={"titulo": "a", "subtitulo": "b", "extra": "c"}))
    assert r.razon_fallo is Razon.CONTRATO_INVALIDO


def test_timeout_no_lanza(tmp_path):
    r = _pedir(tmp_path, ad=adaptador(ProcesoFalso(expiro=True)))
    assert r.razon_fallo is Razon.TIMEOUT_RENDER


def test_render_fallido_no_lanza(tmp_path):
    r = _pedir(tmp_path, ad=adaptador(ProcesoFalso(codigo=1, error="explosion")))
    assert r.razon_fallo is Razon.RENDER_FALLIDO


def test_salida_invalida_no_lanza(tmp_path):
    ad = adaptador(ProcesoFalso(), sondeo=sondeo_falso(pix_fmt="yuv420p"))
    r = _pedir(tmp_path, ad=ad)
    assert r.razon_fallo is Razon.SALIDA_INVALIDA


def test_entorno_ilegible_no_lanza(tmp_path):
    def revienta():
        from hyperframes.errores import EntornoIlegible

        raise EntornoIlegible("doctor no respondio")

    ad = adaptador()
    r = _pedir(tmp_path, ad=ad.__class__(**{**ad.__dict__, "leer_entorno": revienta}))
    assert r.razon_fallo is Razon.BINARIO_AUSENTE
    assert r.ruta_mov is None


def test_ninguna_razon_devuelta_queda_fuera_del_vocabulario(tmp_path):
    """Barrido: toda razon que el servicio pueda emitir esta en el conjunto cerrado."""
    casos = [
        (PIEZA_OK, adaptador(binario=None)),
        (pieza(fps=0), adaptador()),
        (pieza(audio=True), adaptador()),
        (pieza(plantilla={"nombre": "x", "version": "1.0.0"}), adaptador()),
        (PIEZA_OK, adaptador(ProcesoFalso(expiro=True))),
        (PIEZA_OK, adaptador(ProcesoFalso(codigo=3))),
        (PIEZA_OK, adaptador(ProcesoFalso(), sondeo=sondeo_falso(fps=1))),
    ]
    for dato, ad in casos:
        r = _pedir(tmp_path, dato, ad=ad)
        assert r.razon_fallo in RAZONES


# ───────────────────── cache corrupta y recuperacion ─────────────────────


def test_cache_corrupta_se_registra_y_se_vuelve_a_renderizar(tmp_path):
    from hyperframes import almacen

    proceso = ProcesoFalso()
    ad = adaptador(proceso)
    primera = _pedir(tmp_path, ad=ad)
    almacen.ruta_pieza(tmp_path, primera.hash).write_bytes(b"corrompido")
    segunda = _pedir(tmp_path, ad=ad)
    assert segunda.razon_fallo is None  # se recupero
    assert segunda.desde_cache is False
    assert Razon.CACHE_CORRUPTA in segunda.incidencias
    assert proceso.veces == 2


def test_cache_corrupta_se_registra_aunque_el_re_render_falle(tmp_path):
    """La incidencia sobrevive al fallo posterior: razon_fallo dice por que no hay MOV y las
    incidencias dicen que ademas habia una entrada podrida que hubo que descartar."""
    from hyperframes import almacen

    primera = _pedir(tmp_path, ad=adaptador(ProcesoFalso()))
    almacen.ruta_pieza(tmp_path, primera.hash).write_bytes(b"corrompido")
    r = _pedir(tmp_path, ad=adaptador(ProcesoFalso(codigo=1, error="boom")))
    assert r.razon_fallo is Razon.RENDER_FALLIDO
    assert Razon.CACHE_CORRUPTA in r.incidencias
    assert r.ruta_mov is None


def test_sin_binario_no_se_llega_a_mirar_la_cache(tmp_path):
    """Hallazgo HF-1: la clave de cache incluye las versiones del entorno, y el entorno se lee
    con el binario. Sin binario no hay hash, asi que `cache_corrupta` es INOBSERVABLE ahi.
    Invertir el orden exigiria inventar un entorno por defecto, que es justo lo prohibido."""
    primera = _pedir(tmp_path, ad=adaptador(ProcesoFalso()))
    from hyperframes import almacen

    almacen.ruta_pieza(tmp_path, primera.hash).write_bytes(b"corrompido")
    r = _pedir(tmp_path, ad=adaptador(binario=None))
    assert r.razon_fallo is Razon.BINARIO_AUSENTE
    assert r.hash is None
    assert r.incidencias == ()


# ─────────────────────────────── concurrencia ────────────────────────────


def test_dos_llamadas_concurrentes_con_el_mismo_hash_renderizan_una_sola_vez(tmp_path):
    arranco = threading.Event()
    suelta = threading.Event()

    def bloquear(_cmd):
        arranco.set()
        suelta.wait(timeout=10)

    proceso = ProcesoFalso(antes=bloquear)
    ad = adaptador(proceso)
    resultados: list = []

    def trabajo():
        resultados.append(_pedir(tmp_path, ad=ad, espera_lock_s=10))

    a = threading.Thread(target=trabajo)
    b = threading.Thread(target=trabajo)
    a.start()
    arranco.wait(timeout=10)  # A ya tiene el lock y esta "renderizando"
    b.start()
    suelta.set()
    a.join(timeout=20)
    b.join(timeout=20)

    assert proceso.veces == 1, "el segundo hilo no debio renderizar de nuevo"
    assert len(resultados) == 2
    assert all(r.razon_fallo is None for r in resultados)
    assert {r.desde_cache for r in resultados} == {False, True}


def test_lock_ocupado_sin_espera_devuelve_lock_ocupado(tmp_path):
    from hyperframes import almacen
    from hyperframes import contrato as ct

    h = ct.calcular_hash(PIEZA_OK, ENTORNO)
    with almacen.lock(tmp_path, h, espera_s=0):
        r = _pedir(tmp_path, espera_lock_s=0)
    assert r.razon_fallo is Razon.LOCK_OCUPADO


# ─────────────────── validacion explicita SI lanza (HF-2) ────────────────


def test_validar_explicito_lanza_para_que_hf2_vea_el_error():
    from hyperframes import validar_contrato
    from hyperframes.errores import ContratoInvalido

    with pytest.raises(ContratoInvalido):
        validar_contrato(
            pieza(marca={"primario": "rojo", "secundario": "#111111", "texto": "#FFF"})
        )
