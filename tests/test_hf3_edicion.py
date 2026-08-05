"""HF-3: el plan de letreros que K corrige a mano.

Se prueba la LOGICA del plan editado, no la interfaz: que un plan invalido no se pueda guardar,
que el sidecar mande sobre el planificador, que descartar devuelva el automatico exacto y que
un sidecar roto no tumbe un render.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import motion_capa
import motion_edicion as me
import motion_plan as mp

CATALOGO = {"hook", "lower_third", "titulo_seccion", "dato_destacado", "cierre"}
DUR = 60000


def _pieza(plantilla="hook", t0=0, texto=None, banda=mp.BANDA_CENTRO):
    return {
        "plantilla": plantilla,
        "t0_ms": t0,
        "t1_ms": t0 + mp.DURACION_MS.get(plantilla, 2000),
        "texto": texto or {"kicker": "", "titulo": "Un titulo"},
        "banda": banda,
    }


def _plan(*piezas):
    return {"version": me.VERSION_SIDECAR, "piezas": list(piezas)}


def _validar(dato, dur=DUR, orientacion="vertical"):
    return me.validar_plan(dato, duracion_ms=dur, orientacion=orientacion, catalogo=CATALOGO)


def _clip(tmp_path: Path) -> Path:
    mp4 = tmp_path / "clip_9x16.mp4"
    mp4.write_bytes(b"no es un mp4 de verdad, aqui solo importa la ruta")
    return mp4


# ── El plan valido pasa ──────────────────────────────────────────────────────


def test_un_plan_valido_se_acepta_y_queda_ordenado():
    r = _validar(_plan(_pieza("cierre", 50000, {"titulo": "T", "cta": "C"}), _pieza("hook", 0)))
    assert r.ok
    assert [p.plantilla for p in r.plan.piezas] == ["hook", "cierre"]


def test_un_plan_vacio_es_valido():
    """Quitar todos los letreros de un clip es una decision legitima."""
    r = _validar(_plan())
    assert r.ok
    assert r.plan.piezas == ()


# ── Lo que NO se puede guardar ───────────────────────────────────────────────


def test_una_pieza_que_cruza_el_final_del_clip_se_rechaza():
    r = _validar(_plan(_pieza("cierre", DUR - 1000)))
    assert not r.ok
    assert "cruzar el final" in " ".join(r.problemas)


def test_dos_piezas_solapadas_se_rechazan_nombrando_las_dos():
    r = _validar(_plan(_pieza("hook", 0), _pieza("lower_third", 2000)))
    assert not r.ok
    problema = " ".join(r.problemas)
    assert "hook" in problema and "lower_third" in problema
    assert "solapan" in problema


def test_la_separacion_minima_tambien_se_exige():
    r = _validar(_plan(_pieza("hook", 0), _pieza("lower_third", 2600)))
    assert not r.ok
    assert str(mp.SEPARACION_MIN_MS) in " ".join(r.problemas)


def test_no_se_puede_estirar_ni_encoger_una_pieza():
    """La duracion la fija la plantilla: una pieza recortada se corta a media animacion."""
    mala = _pieza("hook", 0)
    mala["t1_ms"] = mala["t0_ms"] + 900
    r = _validar(_plan(mala))
    assert not r.ok
    assert "Mueve la pieza, no la estires" in " ".join(r.problemas)


def test_una_plantilla_que_no_esta_en_el_catalogo_se_rechaza():
    r = _validar(_plan(_pieza("inventada", 0)))
    assert not r.ok
    assert "no esta en el catalogo" in " ".join(r.problemas)


def test_un_tiempo_negativo_se_rechaza():
    p = _pieza("hook", 0)
    p["t0_ms"], p["t1_ms"] = -500, 2000
    assert not _validar(_plan(p)).ok


@pytest.mark.parametrize("malo", [{"t0_ms": "0"}, {"t0_ms": 1.5}, {"t0_ms": True}])
def test_un_tiempo_que_no_es_entero_se_rechaza(malo):
    p = {**_pieza("hook", 0), **malo}
    r = _validar(_plan(p))
    assert not r.ok
    assert "milisegundos" in " ".join(r.problemas)


def test_una_banda_desconocida_se_rechaza():
    r = _validar(_plan(_pieza("hook", 0, banda="diagonal")))
    assert not r.ok
    assert "banda" in " ".join(r.problemas)


def test_se_devuelven_TODOS_los_problemas_no_solo_el_primero():
    """El Studio los pinta juntos y K arregla de una pasada."""
    r = _validar(_plan(_pieza("inventada", 0), _pieza("tampoco", 9000)))
    assert len(r.problemas) >= 2


def test_una_version_de_sidecar_desconocida_se_rechaza():
    r = _validar({"version": 99, "piezas": []})
    assert not r.ok
    assert "version" in " ".join(r.problemas)


# ── El sidecar manda sobre el planificador ───────────────────────────────────


def test_guardar_y_cargar_devuelve_el_mismo_plan(tmp_path):
    mp4 = _clip(tmp_path)
    plan = _validar(_plan(_pieza("hook", 0))).plan
    me.guardar(mp4, plan, duracion_ms=DUR)
    cargado = me.cargar(mp4, duracion_ms=DUR, orientacion="vertical", catalogo=CATALOGO)
    assert cargado is not None
    assert [(p.plantilla, p.t0_ms) for p in cargado.piezas] == [("hook", 0)]


def test_el_plan_editado_gana_al_automatico(tmp_path):
    mp4 = _clip(tmp_path)
    textos = mp.TextosMarca(titulo="T", nombre="N", rol="R", cta="C")
    automatico, origen = motion_capa.resolver_plan(
        clip_mp4=mp4,
        duracion_ms=DUR,
        orientacion="horizontal",
        textos=textos,
        tramos=[],
        tray_csv=None,
        catalogo=CATALOGO,
    )
    assert origen == me.ORIGEN_AUTOMATICO
    assert len(automatico.piezas) > 1

    me.guardar(
        mp4, _validar(_plan(_pieza("hook", 0)), orientacion="horizontal").plan, duracion_ms=DUR
    )
    editado, origen = motion_capa.resolver_plan(
        clip_mp4=mp4,
        duracion_ms=DUR,
        orientacion="horizontal",
        textos=textos,
        tramos=[],
        tray_csv=None,
        catalogo=CATALOGO,
    )
    assert origen == me.ORIGEN_EDITADO
    assert [p.plantilla for p in editado.piezas] == ["hook"]


def test_descartar_devuelve_el_plan_automatico_EXACTO(tmp_path):
    mp4 = _clip(tmp_path)
    textos = mp.TextosMarca(titulo="T", nombre="N", rol="R", cta="C")
    antes, _ = motion_capa.resolver_plan(
        clip_mp4=mp4,
        duracion_ms=DUR,
        orientacion="horizontal",
        textos=textos,
        tramos=[],
        tray_csv=None,
        catalogo=CATALOGO,
    )
    me.guardar(
        mp4, _validar(_plan(_pieza("hook", 0)), orientacion="horizontal").plan, duracion_ms=DUR
    )
    assert me.descartar(mp4) is True
    despues, origen = motion_capa.resolver_plan(
        clip_mp4=mp4,
        duracion_ms=DUR,
        orientacion="horizontal",
        textos=textos,
        tramos=[],
        tray_csv=None,
        catalogo=CATALOGO,
    )
    assert origen == me.ORIGEN_AUTOMATICO
    assert antes.a_dict() == despues.a_dict()


def test_descartar_sin_sidecar_no_falla(tmp_path):
    assert me.descartar(_clip(tmp_path)) is False


def test_sin_clip_no_se_busca_sidecar_y_se_planifica(tmp_path):
    """La CLI y los tests pueden llamar sin ruta de clip: eso no puede romper nada."""
    _plan_, origen = motion_capa.resolver_plan(
        clip_mp4=None,
        duracion_ms=DUR,
        orientacion="horizontal",
        textos=mp.TextosMarca(titulo="T", nombre="N", rol="R", cta="C"),
        tramos=[],
        tray_csv=None,
        catalogo=CATALOGO,
    )
    assert origen == me.ORIGEN_AUTOMATICO


# ── Fail-open ────────────────────────────────────────────────────────────────


def test_un_sidecar_corrupto_se_ignora_y_se_replanifica(tmp_path, capsys):
    mp4 = _clip(tmp_path)
    me.ruta_sidecar(mp4).write_text("{no es json", encoding="utf-8")
    assert me.cargar(mp4, duracion_ms=DUR, orientacion="vertical", catalogo=CATALOGO) is None
    assert "se replanifica" in capsys.readouterr().out


def test_un_sidecar_que_ya_no_valida_se_ignora(tmp_path, capsys):
    """El clip cambio de duracion al reencuadrarlo y el plan viejo ya no cabe."""
    mp4 = _clip(tmp_path)
    me.guardar(
        mp4,
        _validar(_plan(_pieza("cierre", 50000, {"titulo": "T", "cta": "C"}))).plan,
        duracion_ms=DUR,
    )
    assert me.cargar(mp4, duracion_ms=20000, orientacion="vertical", catalogo=CATALOGO) is None
    assert "no valido" in capsys.readouterr().out


def test_un_sidecar_de_otra_version_se_ignora(tmp_path):
    mp4 = _clip(tmp_path)
    me.ruta_sidecar(mp4).write_text(json.dumps({"version": 99, "piezas": []}), encoding="utf-8")
    assert me.cargar(mp4, duracion_ms=DUR, orientacion="vertical", catalogo=CATALOGO) is None


def test_el_sidecar_vive_junto_al_clip(tmp_path):
    mp4 = _clip(tmp_path)
    assert me.ruta_sidecar(mp4).parent == mp4.parent
    assert me.ruta_sidecar(mp4).name.startswith(mp4.stem)


# ── La capa apagada no mira nada de esto ─────────────────────────────────────


def test_con_la_capa_apagada_el_sidecar_es_irrelevante(tmp_path):
    mp4 = _clip(tmp_path)
    me.ruta_sidecar(mp4).write_text("{roto", encoding="utf-8")
    r = motion_capa.clips_de_motion(
        opciones=motion_capa.OpcionesMotion(),
        ancho=1080,
        alto=1920,
        fps=30,
        duracion_s=60.0,
        raiz_cache=tmp_path / "cache",
        root=Path(__file__).resolve().parents[1],
        clip_mp4=mp4,
    )
    assert r.clips == ()
    assert r.informe == {"enabled": False}


# ── Re-render incremental (1.7) ──────────────────────────────────────────────


def test_editar_una_pieza_solo_invalida_esa_pieza_en_la_cache():
    """La clave de cache es el hash del CONTRATO, asi que una pieza intacta sigue siendo un hit.

    Es lo que hace barato corregir: K cambia un texto y solo se re-renderiza ese letrero, no
    los cinco. Aqui se comprueba sobre las claves, sin renderizar nada.
    """
    from hyperframes.contrato import calcular_hash

    entorno = {"hyperframes": "0.7.90", "node": "v24", "chromium": "152", "ffmpeg": "8.0"}
    plan = _validar(
        _plan(
            _pieza("hook", 0),
            _pieza("lower_third", 9000, {"nombre": "N", "rol": "R"}),
            _pieza("cierre", 50000, {"titulo": "T", "cta": "C"}),
        )
    ).plan

    def claves(p):
        return {
            pieza.plantilla: calcular_hash(
                motion_capa.contrato_de_pieza(
                    pieza,
                    version="1.0.0",
                    ancho=1080,
                    alto=1920,
                    fps=30,
                    marca=motion_capa.MARCA,
                ),
                entorno,
            )
            for pieza in p.piezas
        }

    antes = claves(plan)
    tocado = mp.PlanMotion(
        plan.orientacion,
        tuple(
            mp.Pieza(p.plantilla, p.t0_ms, p.t1_ms, {**p.texto, "rol": "Otro rol"}, p.banda)
            if p.plantilla == "lower_third"
            else p
            for p in plan.piezas
        ),
    )
    despues = claves(tocado)

    assert despues["lower_third"] != antes["lower_third"], "la pieza editada debe re-renderizarse"
    assert despues["hook"] == antes["hook"], "el hook no se toco: tiene que salir de cache"
    assert despues["cierre"] == antes["cierre"], "el cierre no se toco: tiene que salir de cache"


def test_mover_una_pieza_en_el_tiempo_no_invalida_su_render():
    """El MOV no depende de donde se compone: mover una pieza no la vuelve a renderizar.

    El instante vive en el `ClipOverlay`, no en el contrato, salvo por el `pieza_id`, que no
    entra en lo que se pinta. Es una propiedad util: reordenar el clip es gratis.
    """
    from hyperframes.contrato import calcular_hash

    entorno = {"hyperframes": "0.7.90"}
    original = _validar(_plan(_pieza("hook", 0))).plan.piezas[0]
    movida = mp.Pieza(original.plantilla, 20000, 22500, dict(original.texto), original.banda)

    def clave(pieza):
        dato = motion_capa.contrato_de_pieza(
            pieza, version="1.0.0", ancho=1080, alto=1920, fps=30, marca=motion_capa.MARCA
        )
        dato.pop("pieza_id")  # identificador de archivo, no influye en los pixeles
        return calcular_hash(dato, entorno)

    assert clave(original) == clave(movida)
