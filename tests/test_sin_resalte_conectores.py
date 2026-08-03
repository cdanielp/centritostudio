"""Contrato del resalte de conectores (S40).

Regla: una palabra vacía ("que", "un", "de"...) que llega a palabra ACTIVA se pinta con el
estilo base — sin `\\c`, sin `\\kf`, sin pop. Lo que NO cambia:

  * su evento sigue existiendo, con exactamente la misma ventana de tiempo;
  * una `is_keyword` jamás se apaga, esté o no en la lista;
  * el gemelo de glow aplica el MISMO criterio (si no, las dos capas se descuadran);
  * `resaltar_conectores=True` reproduce el render histórico;
  * `cve_keywords.STOPWORDS` no se toca (eso lo fija `test_stopwords_es.py`).
"""

from __future__ import annotations

from dataclasses import replace

import core
import stopwords_es
from styles import get_style


def _grupo(palabras: list[str], keyword: str | None = None) -> dict:
    words = [
        {
            "text": t,
            "start": round(i * 0.4, 3),
            "end": round(i * 0.4 + 0.4, 3),
            "line_idx": 0,
            **({"is_keyword": True} if t == keyword else {}),
        }
        for i, t in enumerate(palabras)
    ]
    return {
        "id": 0,
        "start": 0.0,
        "end": round(len(palabras) * 0.4, 3),
        "text": " ".join(palabras),
        "words": words,
    }


def _dialogues(tmp_path, grupos: list[dict], style_cfg) -> list[str]:
    ass = tmp_path / "out.ass"
    core.build_ass(grupos, 1080, 1920, style_cfg, ass)
    return [ln for ln in ass.read_text(encoding="utf-8").splitlines() if ln.startswith("Dialogue:")]


def _bloque_activo(linea: str) -> str:
    """Tag inline del primer bloque `{...}texto{\\r}` del evento; '' si el evento va plano."""
    if "{\\r}" not in linea:
        return ""
    texto = linea.split(",", 9)[-1]
    ini = texto.find("{")
    return texto[ini : texto.index("}", ini) + 1] if ini >= 0 else ""


def _tiempos(lineas: list[str]) -> list[tuple[str, str]]:
    return [(ln.split(",")[1], ln.split(",")[2]) for ln in lineas]


_PALABRAS = ["cobra", "un", "kit", "de", "contenido"]


# ─────────────────────────────────────────────────────────────────────────────
# La regla
# ─────────────────────────────────────────────────────────────────────────────


def test_el_conector_activo_se_pinta_con_el_estilo_base(tmp_path):
    lineas = _dialogues(tmp_path, [_grupo(_PALABRAS)], get_style("hormozi"))
    # Un evento por palabra; el 2o ("un") y el 4o ("de") son conectores.
    assert len(lineas) == len(_PALABRAS)
    for idx, palabra in enumerate(_PALABRAS):
        tag = _bloque_activo(lineas[idx])
        if stopwords_es.es_conector(palabra):
            assert tag == "", f"'{palabra}' no debia llevar tag de resalte"
        else:
            assert "\\c" in tag, f"'{palabra}' debia seguir resaltandose"


def test_no_se_cuela_ni_color_ni_kf_ni_pop(tmp_path):
    lineas = _dialogues(tmp_path, [_grupo(_PALABRAS)], get_style("hormozi"))
    tag = _bloque_activo(lineas[1])  # "un"
    assert "\\c" not in tag and "\\kf" not in tag and "\\t(" not in tag and "\\fsc" not in tag


def test_el_tiempo_del_conector_no_se_toca(tmp_path):
    """Lo unico que cambia es como se pinta: el evento y su ventana siguen igual."""
    grupos = [_grupo(_PALABRAS)]
    base = get_style("hormozi")
    nuevo = _dialogues(tmp_path, grupos, base)
    historico = _dialogues(tmp_path, grupos, replace(base, resaltar_conectores=True))
    assert len(nuevo) == len(historico) == len(_PALABRAS)
    assert _tiempos(nuevo) == _tiempos(historico)


def test_el_texto_del_conector_sigue_visible(tmp_path):
    lineas = _dialogues(tmp_path, [_grupo(_PALABRAS)], get_style("hormozi"))
    for ln in lineas:
        assert "UN" in ln and "DE" in ln  # hormozi va en mayusculas


def test_una_keyword_jamas_se_apaga_aunque_sea_conector(tmp_path):
    """El enfasis del engine manda sobre la lista: si el CVE la marco, se resalta."""
    grupos = [_grupo(_PALABRAS, keyword="un")]
    lineas = _dialogues(tmp_path, grupos, get_style("hormozi"))
    assert "\\c" in _bloque_activo(lineas[1])


def test_karaoke_el_relleno_del_conector_es_invisible(tmp_path):
    """El conector conserva su `\\kf` pero pintando el "por cantar" IGUAL que el "ya cantado".

    Sin color de resalte y sin escala: visualmente es texto base. Verificado ademas sobre un
    quemado real (ver EVIDENCIA §4), donde el conector deja de teñirse a medio barrido.
    """
    cfg = get_style("karaoke")
    lineas = _dialogues(tmp_path, [_grupo(_PALABRAS)], cfg)
    tag = _bloque_activo(lineas[1])  # "un"
    assert "\\kf" in tag  # conserva el relleno...
    assert "\\c&H" not in tag and "\\fsc" not in tag  # ...pero sin color de resalte ni escala
    assert "\\2c" in tag and "\\2a" in tag  # el "por cantar" se iguala al base, alpha incluido
    assert "\\c" in _bloque_activo(lineas[0])  # "cobra" sigue con su relleno de color


def test_karaoke_conserva_la_sintaxis_de_la_linea(tmp_path):
    """Sin NINGUN `\\kf`, libass deja de tratar la linea como karaoke y repinta las palabras
    FUTURAS con PrimaryColour en vez de SecondaryColour: parpadearia la linea ENTERA, no solo
    el conector. Medido sobre un quemado real: 14664 px de secundario -> 0. Con `\\kf0` pasa lo
    mismo (el cursor no avanza y libass da la linea por cantada). Por eso se conserva el
    relleno con su DURACION REAL y se hace invisible por color.
    """
    lineas = _dialogues(tmp_path, [_grupo(_PALABRAS)], get_style("karaoke"))
    for idx, ln in enumerate(lineas):
        assert "\\kf" in ln, f"evento {idx} perdio la sintaxis de karaoke"
        assert "\\kf0\\" not in ln and not ln.endswith("\\kf0"), f"evento {idx}: relleno nulo"


def test_karaoke_el_relleno_del_conector_dura_lo_mismo_que_antes(tmp_path):
    """La duracion del `\\kf` es la de la palabra: si cambiara, se moveria el cursor de karaoke
    y las palabras futuras cambiarian de color antes o despues de tiempo.
    """
    import re

    grupos = [_grupo(_PALABRAS)]
    cfg = get_style("karaoke")
    nuevo = _dialogues(tmp_path, grupos, cfg)
    historico = _dialogues(tmp_path, grupos, replace(cfg, resaltar_conectores=True))
    dur = lambda ln: re.search(r"\\kf(\d+)", ln).group(1)  # noqa: E731
    assert [dur(ln) for ln in nuevo] == [dur(ln) for ln in historico]


def test_fuera_de_karaoke_el_conector_no_lleva_ningun_tag(tmp_path):
    """El `\\kf0` es una concesion EXCLUSIVA de karaoke; en el resto va texto pelado."""
    for estilo in ("hormozi", "clean", "pms", "bounce"):
        lineas = _dialogues(tmp_path, [_grupo(_PALABRAS)], get_style(estilo))
        assert _bloque_activo(lineas[1]) == "", estilo


def test_las_palabras_con_carga_no_cambian(tmp_path):
    """Contencion: el cambio solo puede tocar conectores, nunca el resto del caption."""
    grupos = [_grupo(_PALABRAS)]
    base = get_style("hormozi")
    nuevo = _dialogues(tmp_path, grupos, base)
    historico = _dialogues(tmp_path, grupos, replace(base, resaltar_conectores=True))
    for idx, palabra in enumerate(_PALABRAS):
        if not stopwords_es.es_conector(palabra):
            assert nuevo[idx] == historico[idx], f"'{palabra}' cambio y no debia"


# ─────────────────────────────────────────────────────────────────────────────
# Escotilla historica
# ─────────────────────────────────────────────────────────────────────────────


def test_resaltar_conectores_reproduce_el_render_historico(tmp_path):
    grupos = [_grupo(_PALABRAS)]
    base = get_style("hormozi")
    historico = _dialogues(tmp_path, grupos, replace(base, resaltar_conectores=True))
    for idx in range(len(_PALABRAS)):
        assert "\\c" in _bloque_activo(historico[idx])  # TODAS resaltan, como antes


def test_el_campo_es_override_valido_de_estilo():
    """Se puede fijar desde styles.json / cve_presets.json (allowlist, sin ejecucion arbitraria)."""
    import styles

    assert styles.filtrar_overrides_validos({"resaltar_conectores": True}) == {
        "resaltar_conectores": True
    }
    assert styles.filtrar_overrides_validos({"resaltar_conectores": "si"}) == {}


# ─────────────────────────────────────────────────────────────────────────────
# El gemelo de glow comparte criterio (si no, se descuadran las dos capas)
# ─────────────────────────────────────────────────────────────────────────────


def test_el_glow_no_escala_un_conector_que_el_texto_dejo_plano():
    import core_ass_fx as fx

    cfg = replace(get_style("hormozi"), kw_glow=True)
    words = _grupo(_PALABRAS, keyword="kit")["words"]
    glow = fx._glow_event_text(words, 1, cfg)  # activa = "un" (conector)
    # El bloque de "un" va invisible y SIN escala: misma metrica que la capa de texto.
    assert "{\\alpha&HFF&}UN{\\r}" in glow
    assert "\\t(" not in glow  # la activa no anima, asi que el glow tampoco


def test_el_glow_si_anima_una_activa_con_carga():
    import core_ass_fx as fx

    cfg = replace(get_style("hormozi"), kw_glow=True)
    words = _grupo(_PALABRAS, keyword="kit")["words"]
    glow = fx._glow_event_text(words, 0, cfg)  # activa = "cobra" (con carga)
    assert "\\t(" in glow


def test_el_predicado_es_la_fuente_unica():
    import core_ass_fx as fx

    cfg = get_style("hormozi")
    assert fx._sin_resalte({"text": "de"}, cfg) is True
    assert fx._sin_resalte({"text": "kit"}, cfg) is False
    assert fx._sin_resalte({"text": "de", "is_keyword": True}, cfg) is False
    assert fx._sin_resalte({"text": "de"}, replace(cfg, resaltar_conectores=True)) is False


# ─────────────────────────────────────────────────────────────────────────────
# La lista es dato
# ─────────────────────────────────────────────────────────────────────────────


def test_sin_resalte_cubre_los_conectores_medidos_por_k():
    for palabra in ("que", "un", "es", "la", "a", "de", "con", "como"):
        assert stopwords_es.es_conector(palabra), palabra


def test_sin_resalte_deja_fuera_lo_que_carga_enfasis():
    """Adverbios y muletillas NO se apagan: "SOLO hoy" tiene que poder golpear."""
    for palabra in ("solo", "siempre", "casi", "gente", "cosa"):
        assert not stopwords_es.es_conector(palabra), palabra


def test_sin_resalte_no_apaga_las_senales_fuertes_del_motor():
    import cve_keywords as ck

    fuertes = ck.NUMERALES | ck.DINERO_PCT | ck.FECHAS | ck.NEGACIONES
    assert (stopwords_es.SIN_RESALTE - stopwords_es.STOPWORDS_BASE) & fuertes == frozenset()


def test_sin_resalte_es_subconjunto_de_la_ampliada():
    assert stopwords_es.SIN_RESALTE < stopwords_es.STOPWORDS_ES
    assert stopwords_es.STOPWORDS_BASE < stopwords_es.SIN_RESALTE


# ─────────────────────────────────────────────────────────────────────────────
# Tilde diacritica: el acento cambia la palabra, no solo la ortografia
# ─────────────────────────────────────────────────────────────────────────────


def test_la_forma_acentuada_si_se_resalta():
    """ "que" conecta, "qué" pregunta. `normalizar` borra acentos: sin este caso especial se
    apagaria justo la version con carga.
    """
    for atono, tonico in (
        ("que", "qué"),
        ("si", "sí"),
        ("mas", "más"),
        ("tu", "tú"),
        ("el", "él"),
        ("como", "cómo"),
        ("cuando", "cuándo"),
        ("donde", "dónde"),
    ):
        assert stopwords_es.es_conector(atono) is True, atono
        assert stopwords_es.es_conector(tonico) is False, tonico


def test_la_tilde_diacritica_sobrevive_a_la_puntuacion():
    assert stopwords_es.es_conector("¿QUÉ?") is False
    assert stopwords_es.es_conector("¿Qué,") is False
    assert stopwords_es.es_conector("¿que?") is True


def test_el_interrogativo_acentuado_se_resalta_en_el_ass(tmp_path):
    lineas = _dialogues(tmp_path, [_grupo(["y", "qué", "sigue"])], get_style("hormozi"))
    assert _bloque_activo(lineas[0]) == ""  # "y" es conector
    assert "\\c" in _bloque_activo(lineas[1])  # "qué" NO lo es


# ─────────────────────────────────────────────────────────────────────────────
# Las dos capas escalan igual en TODOS los modos (bug conocido: sesion 47 de F6)
# ─────────────────────────────────────────────────────────────────────────────


def test_glow_y_texto_comparten_escala_con_conectores_en_todos_los_modos():
    """Si una capa suprime y la otra no, el layout se descuadra por frame.

    Se recorre cada animacion x pop x overshoot y se compara, para CADA posicion activa, si
    las dos capas coinciden en llevar (o no) animacion de escala.
    """
    import core_ass
    import core_ass_fx as fx

    words = _grupo(_PALABRAS, keyword="kit")["words"]
    base = get_style("hormozi")
    for anim in ("highlight", "karaoke", "bounce", "scale"):
        for pop in (1.0, 1.3):
            for overshoot in (False, True):
                cfg = replace(
                    base, animation_type=anim, pop_scale=pop, overshoot=overshoot, kw_glow=True
                )
                for idx, palabra in enumerate(_PALABRAS):
                    texto = core_ass._word_event_text(words, idx, cfg)
                    glow = fx._glow_event_text(words, idx, cfg)
                    suprimida = fx._sin_resalte(words[idx], cfg)
                    caso = f"{anim}/{pop}/{overshoot}/{palabra}"
                    # La escala de la palabra activa aparece (o falta) en las DOS capas.
                    assert ("\\t(" in texto) == ("\\t(" in glow), caso
                    if suprimida:
                        assert "\\t(" not in texto and "\\t(" not in glow, caso
