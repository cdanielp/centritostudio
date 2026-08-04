"""HF-3 punto 5.3: el gate que caza una plantilla editada sin subir su version.

La clave de cache de una pieza es CIEGA al contenido de `motion/`: hashea el contrato y el
entorno, no el HTML. Editar una propiedad de CSS produce un MOV distinto y deja la clave
identica, asi que un hit de cache devolveria la pieza vieja. La regla D51.1 dice que la
version de la plantilla es lo que invalida; este test convierte esa regla en algo que falla
solo, en vez de depender de que nadie se olvide.

Corre en el CI: no renderiza, no necesita npx, solo lee archivos.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import motion_sello as ms

RAIZ = Path(__file__).resolve().parents[1]
MOTION = RAIZ / "motion"
LOCK = MOTION / ms.NOMBRE_LOCK


def test_el_lock_existe_y_cubre_todo_el_catalogo():
    lock = ms.leer_lock(LOCK)
    catalogo = {d["nombre"] for d in ms.leer_catalogo(MOTION / "catalogo.json")}
    assert lock, f"falta {LOCK.name}: corre revision/hf-3/sellar_versiones.py"
    assert set(lock) == catalogo


def test_el_contenido_de_motion_cuadra_con_las_versiones_declaradas():
    """EL gate. Si truena, el mensaje dice exactamente que hacer."""
    catalogo = ms.leer_catalogo(MOTION / "catalogo.json")
    problemas = ms.comparar(ms.sellar(MOTION, catalogo), ms.leer_lock(LOCK))
    assert not problemas, "\n".join(problemas)


def test_la_version_del_lock_es_la_del_catalogo_y_la_del_ejemplo():
    """Tres sitios declaran la version; si divergen, la pieza se pide con una que no existe."""
    lock = ms.leer_lock(LOCK)
    for d in ms.leer_catalogo(MOTION / "catalogo.json"):
        nombre, version = d["nombre"], d["version"]
        assert lock[nombre]["version"] == version, nombre
        ejemplo = json.loads((MOTION / "ejemplos" / f"{nombre}.json").read_text(encoding="utf-8"))
        assert ejemplo["plantilla"]["version"] == version, nombre


# ── El detector, probado contra casos fabricados ─────────────────────────────


def _plantilla_falsa(tmp_path: Path, nombre: str, cuerpo: str) -> Path:
    carpeta = tmp_path / nombre
    (carpeta / "horizontal").mkdir(parents=True)
    (carpeta / "index.html").write_text(cuerpo, encoding="utf-8")
    (carpeta / "horizontal" / "index.html").write_text(cuerpo, encoding="utf-8")
    return carpeta


def test_detecta_contenido_cambiado_con_la_misma_version(tmp_path):
    catalogo = [{"nombre": "p", "version": "1.0.0"}]
    _plantilla_falsa(tmp_path, "p", "antes")
    lock = ms.sellar(tmp_path, catalogo)
    (tmp_path / "p" / "index.html").write_text("despues", encoding="utf-8")

    problemas = ms.comparar(ms.sellar(tmp_path, catalogo), lock)
    assert len(problemas) == 1
    assert "el CONTENIDO de motion/p/ cambio" in problemas[0]
    assert "1.0.0" in problemas[0]


def test_un_cambio_en_el_gemelo_horizontal_tambien_cuenta(tmp_path):
    """El gemelo se renderiza igual que el primario: si cambia, la cache tambien miente."""
    catalogo = [{"nombre": "p", "version": "1.0.0"}]
    _plantilla_falsa(tmp_path, "p", "antes")
    lock = ms.sellar(tmp_path, catalogo)
    (tmp_path / "p" / "horizontal" / "index.html").write_text("otro", encoding="utf-8")

    assert ms.comparar(ms.sellar(tmp_path, catalogo), lock)


def test_contenido_cambiado_CON_version_nueva_no_es_un_problema_de_cache(tmp_path):
    """Subir la version es exactamente lo que hay que hacer; solo pide volver a sellar."""
    _plantilla_falsa(tmp_path, "p", "antes")
    lock = ms.sellar(tmp_path, [{"nombre": "p", "version": "1.0.0"}])
    (tmp_path / "p" / "index.html").write_text("despues", encoding="utf-8")

    problemas = ms.comparar(ms.sellar(tmp_path, [{"nombre": "p", "version": "1.0.1"}]), lock)
    assert len(problemas) == 1
    assert "vuelve a sellar" in problemas[0].lower()
    assert "CONTENIDO" not in problemas[0]


def test_sin_cambios_no_hay_problemas(tmp_path):
    catalogo = [{"nombre": "p", "version": "1.0.0"}]
    _plantilla_falsa(tmp_path, "p", "igual")
    lock = ms.sellar(tmp_path, catalogo)
    assert ms.comparar(ms.sellar(tmp_path, catalogo), lock) == []


def test_plantilla_nueva_sin_sellar_se_avisa(tmp_path):
    _plantilla_falsa(tmp_path, "p", "x")
    _plantilla_falsa(tmp_path, "q", "y")
    lock = ms.sellar(tmp_path, [{"nombre": "p", "version": "1.0.0"}])
    problemas = ms.comparar(
        ms.sellar(
            tmp_path, [{"nombre": "p", "version": "1.0.0"}, {"nombre": "q", "version": "1.0.0"}]
        ),
        lock,
    )
    assert len(problemas) == 1
    assert "sin sellar" in problemas[0]


def test_el_sello_cambia_si_se_renombra_un_archivo(tmp_path):
    """La ruta entra al hash: renombrar cambia lo que HyperFrames renderiza."""
    carpeta = _plantilla_falsa(tmp_path, "p", "x")
    antes = ms.sello_de_carpeta(carpeta)
    (carpeta / "index.html").rename(carpeta / "otro.html")
    assert ms.sello_de_carpeta(carpeta) != antes


def test_el_sello_es_estable_entre_llamadas(tmp_path):
    carpeta = _plantilla_falsa(tmp_path, "p", "x")
    assert ms.sello_de_carpeta(carpeta) == ms.sello_de_carpeta(carpeta)


@pytest.mark.parametrize("basura", ["__pycache__", ".DS_Store"])
def test_los_artefactos_ignorados_no_mueven_el_sello(tmp_path, basura):
    carpeta = _plantilla_falsa(tmp_path, "p", "x")
    antes = ms.sello_de_carpeta(carpeta)
    destino = carpeta / basura
    if basura == "__pycache__":
        destino.mkdir()
        (destino / "algo.pyc").write_bytes(b"\x00\x01")
    else:
        destino.write_text("ruido", encoding="utf-8")
    assert ms.sello_de_carpeta(carpeta) == antes
