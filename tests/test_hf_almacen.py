"""Almacen HF-1: layout de cache, sidecar, integridad, escritura atomica y lock.

El sha256 del MOV se usa como DETECTOR DE INTEGRIDAD de la propia cache (que el archivo no
se corrompio en disco), nunca como asercion de que el render sea visualmente correcto.
"""

from __future__ import annotations

import json

from hf_dobles import ENTORNO, PIEZA_OK

from hyperframes import almacen
from hyperframes.razones import Razon

HASH = "a1b2c3" + "0" * 58


def _guardar(raiz, contenido=b"MOV", hash_=HASH):
    origen = raiz / "origen.mov"
    origen.write_bytes(contenido)
    return almacen.publicar(
        raiz,
        hash_,
        origen,
        contrato=PIEZA_OK,
        entorno=ENTORNO,
        sondeo={"pix_fmt": "yuva444p12le", "duracion_ms": 6000, "fps": 30},
        segundos_render=1.5,
    )


# ─────────────────────────────── layout ──────────────────────────────────


def test_layout_es_dos_primeros_del_hash_mas_hash(tmp_path):
    ruta = almacen.ruta_pieza(tmp_path, HASH)
    assert ruta == tmp_path / HASH[:2] / HASH / "pieza.mov"
    assert almacen.ruta_sidecar(tmp_path, HASH).name == "pieza.json"


def test_publicar_escribe_mov_y_sidecar(tmp_path):
    mov = _guardar(tmp_path)
    assert mov.exists() and mov.read_bytes() == b"MOV"
    side = json.loads(almacen.ruta_sidecar(tmp_path, HASH).read_text(encoding="utf-8"))
    assert side["hash"] == HASH
    assert side["contrato"] == PIEZA_OK
    assert side["entorno"] == ENTORNO
    assert side["duracion_ms"] == 6000 and side["fps"] == 30
    assert side["segundos_render"] == 1.5
    assert side["sha256"] == almacen.sha256_de(mov)
    assert side["fecha"]


def test_publicar_mueve_el_origen_no_deja_temporales(tmp_path):
    _guardar(tmp_path)
    sobrantes = [p for p in (tmp_path / HASH[:2] / HASH).iterdir() if p.suffix == ".tmp"]
    assert sobrantes == []
    assert not (tmp_path / "origen.mov").exists()


# ────────────────────────────── hit y miss ───────────────────────────────


def test_hit_devuelve_la_ruta_y_el_sidecar(tmp_path):
    _guardar(tmp_path)
    hit = almacen.buscar(tmp_path, HASH)
    assert hit.encontrado is True
    assert hit.razon is None
    assert hit.sidecar["hash"] == HASH


def test_miss_cuando_no_existe_nada(tmp_path):
    hit = almacen.buscar(tmp_path, HASH)
    assert hit.encontrado is False
    assert hit.razon is None  # un miss normal no es una incidencia


def test_mov_sin_sidecar_es_miss(tmp_path):
    _guardar(tmp_path)
    almacen.ruta_sidecar(tmp_path, HASH).unlink()
    assert almacen.buscar(tmp_path, HASH).encontrado is False


def test_sidecar_sin_mov_es_miss(tmp_path):
    _guardar(tmp_path)
    almacen.ruta_pieza(tmp_path, HASH).unlink()
    assert almacen.buscar(tmp_path, HASH).encontrado is False


def test_sha256_que_no_cuadra_es_miss_con_razon_cache_corrupta(tmp_path):
    _guardar(tmp_path)
    almacen.ruta_pieza(tmp_path, HASH).write_bytes(b"OTRA-COSA")
    hit = almacen.buscar(tmp_path, HASH)
    assert hit.encontrado is False
    assert hit.razon is Razon.CACHE_CORRUPTA


def test_sidecar_ilegible_es_miss_con_razon_cache_corrupta(tmp_path):
    _guardar(tmp_path)
    almacen.ruta_sidecar(tmp_path, HASH).write_text("{roto", encoding="utf-8")
    hit = almacen.buscar(tmp_path, HASH)
    assert hit.encontrado is False
    assert hit.razon is Razon.CACHE_CORRUPTA


def test_mov_vacio_es_cache_corrupta(tmp_path):
    _guardar(tmp_path)
    almacen.ruta_pieza(tmp_path, HASH).write_bytes(b"")
    assert almacen.buscar(tmp_path, HASH).razon is Razon.CACHE_CORRUPTA


# ─────────────────────────── escritura atomica ───────────────────────────


def test_un_render_que_falla_a_la_mitad_no_deja_entrada_publicada(tmp_path):
    """El temporal vive fuera del directorio final: si el render muere, no hay pieza.mov."""
    with almacen.temporal(tmp_path, HASH) as temp:
        temp.write_bytes(b"a-medias")
        # el bloque termina sin publicar (simula un render abortado)
    assert not almacen.ruta_pieza(tmp_path, HASH).exists()
    assert not temp.exists()


def test_el_temporal_se_borra_aunque_el_bloque_lance(tmp_path):
    try:
        with almacen.temporal(tmp_path, HASH) as temp:
            temp.write_bytes(b"x")
            raise RuntimeError("render reventado")
    except RuntimeError:
        pass
    assert not temp.exists()
    assert not almacen.ruta_pieza(tmp_path, HASH).exists()


def test_el_temporal_termina_en_mov(tmp_path):
    """HyperFrames elige el muxer por la extension: un temporal .mp4 daria otro formato."""
    with almacen.temporal(tmp_path, HASH) as temp:
        assert temp.suffix == ".mov"


def test_dos_temporales_del_mismo_hash_no_colisionan(tmp_path):
    with almacen.temporal(tmp_path, HASH) as a, almacen.temporal(tmp_path, HASH) as b:
        assert a != b


def test_tamano_ocupado_suma_los_archivos(tmp_path):
    _guardar(tmp_path, contenido=b"1234567890")
    assert almacen.tamano_ocupado(tmp_path) > 10


def test_tamano_ocupado_de_raiz_inexistente_es_cero(tmp_path):
    assert almacen.tamano_ocupado(tmp_path / "no-existe") == 0


# ─────────────────────────────── lock ────────────────────────────────────


def test_lock_libre_se_toma_y_se_suelta(tmp_path):
    with almacen.lock(tmp_path, HASH, espera_s=0) as tomado:
        assert tomado is True
    with almacen.lock(tmp_path, HASH, espera_s=0) as otra_vez:
        assert otra_vez is True


def test_lock_ocupado_no_se_toma_dentro_de_la_espera(tmp_path):
    with almacen.lock(tmp_path, HASH, espera_s=0):
        with almacen.lock(tmp_path, HASH, espera_s=0) as segundo:
            assert segundo is False


def test_lock_rancio_se_reclama(tmp_path):
    """Un lock abandonado por un hard-kill no puede bloquear la pieza para siempre."""
    with almacen.lock(tmp_path, HASH, espera_s=0):
        with almacen.lock(tmp_path, HASH, espera_s=0, rancio_s=-1) as reclamado:
            assert reclamado is True


def test_el_lock_se_suelta_aunque_el_bloque_lance(tmp_path):
    try:
        with almacen.lock(tmp_path, HASH, espera_s=0):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    with almacen.lock(tmp_path, HASH, espera_s=0) as tomado:
        assert tomado is True
