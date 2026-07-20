"""Tests de alineacion glow/texto en phrase spans (gate visual PR #23).

El gate visual fallo por superposicion/duplicacion ("ESTESTOBIO", "SSIN"): el evento
gemelo de glow (capa 0) usaba escala ESTATICA mientras la palabra activa de la capa de
texto (capa 1) hacia pop -> distinto ancho -> distinto wrap/centrado -> las dos capas se
descuadraban y encimaban. El fix comparte la MISMA envolvente de escala por palabra
(`_active_scale_anim`) entre ambas capas: mismo layout por frame, cero desalineacion.

Invariante que estos tests protegen: para cada palabra de cada evento, la secuencia de
escalas (`\\fscx/\\fscy` y `\\t(...)`) del glow (capa 0) es IDENTICA a la de la capa de
texto (capa 1). Si vuelve a divergir (glow estatico), estos tests se ponen rojos.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import core_ass
import cve
import cve_keywords as ck
from styles import get_style

_SCALE_RE = re.compile(r"\\fsc[xy]\d+")


def _grupo(palabras: list[str], texto: str | None = None, lineas: list[int] | None = None) -> dict:
    words = [
        {
            "text": p,
            "start": i * 0.5,
            "end": i * 0.5 + 0.4,
            "line_idx": (lineas[i] if lineas else 0),
        }
        for i, p in enumerate(palabras)
    ]
    return {
        "id": 0,
        "start": 0.0,
        "end": len(palabras) * 0.5,
        "text": texto if texto is not None else " ".join(palabras),
        "words": words,
    }


def _scale_seq(text: str) -> list[str]:
    """Secuencia ordenada de directivas de escala (fscx/fscy) del texto ASS de un evento."""
    return _SCALE_RE.findall(text)


def _span_glow_cfg():
    """Estilo con glow ON y pop/overshoot (como keyword_punch viral): dispara el gemelo."""
    from dataclasses import replace

    return replace(get_style("hormozi"), kw_glow=True, pop_scale=1.08, overshoot=True)


def _todas_kw(gw: list[dict], punch: int = 145) -> None:
    for w in gw:
        w["is_keyword"] = True
        w["punch_scale"] = punch


# ── Invariante nucleo: glow y texto comparten escala por palabra activa ────────


def test_glow_scale_identica_a_texto_por_idx():
    cfg = _span_glow_cfg()
    gw = _grupo(["esto", "cambio", "todo"])["words"]
    _todas_kw(gw)
    for idx in range(len(gw)):
        glow = core_ass._glow_event_text(gw, idx, cfg)
        texto = core_ass._word_event_text(gw, idx, cfg)
        assert _scale_seq(glow) == _scale_seq(texto), f"desalineacion en idx={idx}"


def test_glow_palabra_activa_no_es_estatica():
    # La palabra activa del glow DEBE llevar la animacion \t (no la escala estatica que
    # causaba la duplicacion). Antes del fix, el glow activo era \fscx145 estatico.
    cfg = _span_glow_cfg()
    gw = _grupo(["esto", "cambio", "todo"])["words"]
    _todas_kw(gw)
    glow0 = core_ass._glow_event_text(gw, 0, cfg)
    # el primer bloque (palabra activa ESTO) contiene \t(...) como en la capa de texto
    activa = glow0.split("{\\r}")[0]
    assert "\\t(" in activa and "\\fscx176" in activa


def test_activa_en_inicio_medio_y_final_alinean():
    cfg = _span_glow_cfg()
    gw = _grupo(["uno", "dos", "tres", "cuatro"])["words"]
    _todas_kw(gw)
    for idx in (0, 1, 3):  # inicio, medio, final
        assert _scale_seq(core_ass._glow_event_text(gw, idx, cfg)) == _scale_seq(
            core_ass._word_event_text(gw, idx, cfg)
        )


def test_frase_dos_lineas_alinea_y_conserva_salto():
    cfg = _span_glow_cfg()
    gw = _grupo(["gana", "mucho", "dinero", "hoy"], lineas=[0, 0, 1, 1])["words"]
    _todas_kw(gw)
    for idx in range(len(gw)):
        glow = core_ass._glow_event_text(gw, idx, cfg)
        texto = core_ass._word_event_text(gw, idx, cfg)
        assert _scale_seq(glow) == _scale_seq(texto)
        assert glow.count("\\N") == texto.count("\\N") == 1  # mismo salto de linea


# ── Build ASS completo: cada gemelo de glow alinea con su evento de texto ──────


def _pares_por_tiempo(ass_path: Path):
    import pysubs2

    subs = pysubs2.load(str(ass_path))
    glow = {ev.start: ev for ev in subs.events if ev.layer == 0}
    texto = {ev.start: ev for ev in subs.events if ev.layer == 1}
    return glow, texto


def _build(gr: dict, cfg, tmp_path: Path) -> Path:
    out = tmp_path / "span.ass"
    core_ass.build_ass([gr], 1080, 1920, cfg, out)
    return out


def test_build_ass_phrase_span_pares_alineados(tmp_path):
    cfg = _span_glow_cfg()
    gr = _grupo(["esto", "cambio", "todo"])
    _todas_kw(gr["words"])
    glow, texto = _pares_por_tiempo(_build(gr, cfg, tmp_path))
    assert set(glow) == set(texto) and len(glow) == 3
    for t in glow:
        assert _scale_seq(glow[t].text) == _scale_seq(texto[t].text)


def test_build_ass_punctuation_span_pares_alineados(tmp_path):
    # Caso demo_phrase_span_punctuation: "[strong]sin costo[/strong]." -> sin costo.
    cfg = _span_glow_cfg()
    limpio, marcas, _c = ck.parsear_marcas("[strong]sin costo[/strong].")
    assert limpio == "sin costo."  # puntuacion unida (no palabra extra)
    gr = _grupo(limpio.split())
    for i in marcas:
        gr["words"][i]["is_keyword"] = True
        gr["words"][i]["punch_scale"] = 145
    glow, texto = _pares_por_tiempo(_build(gr, cfg, tmp_path))
    for t in glow:
        assert _scale_seq(glow[t].text) == _scale_seq(texto[t].text)
    # la puntuacion viaja pegada a la ultima palabra
    assert gr["words"][-1]["text"] == "costo."


def test_cierre_separado_por_espacio_no_crea_palabra(tmp_path):
    limpio, marcas, _c = ck.parsear_marcas("[strong] sin costo [/strong].")
    assert limpio == "sin costo." and marcas == {0: "strong", 1: "strong"}


def test_ninguna_etiqueta_marca_visible_en_ass(tmp_path):
    cfg = _span_glow_cfg()
    limpio, marcas, _c = ck.parsear_marcas("[big]sin costo[/big].")
    gr = _grupo(limpio.split())
    for i in marcas:
        gr["words"][i]["is_keyword"] = True
    ass = _build(gr, cfg, tmp_path)
    contenido = ass.read_text(encoding="utf-8")
    for marca in ("[strong]", "[/strong]", "[big]", "[/big]", "[center]", "[/center]"):
        assert marca not in contenido


# ── Regresion: strong y big desde el engine real ──────────────────────────────


def test_engine_span_strong_y_big_alinean(tmp_path):
    cfg = _span_glow_cfg()
    for texto in ("[strong]esto cambio todo[/strong]", "[big]gana mucho dinero[/big]"):
        gr = _grupo(["esto", "cambio", "todo"], texto=texto)
        out = cve.aplicar_engine([gr], cve.resolve_preset("keyword_punch", "viral"), 1080, 1920)
        assert any(w.get("is_keyword") for w in out[0]["words"])
        glow, txt = _pares_por_tiempo(_build(out[0], cfg, tmp_path))
        for t in glow:
            assert _scale_seq(glow[t].text) == _scale_seq(txt[t].text)


# ── Sin regresion: captions normales sin marcas (sin gemelo mal alineado) ─────


def test_sin_marcas_sin_glow_una_capa(tmp_path):
    # Sin keywords no hay gemelo de glow: un solo evento por palabra (byte-identico historico)
    cfg = _span_glow_cfg()
    gr = _grupo(["hola", "mundo", "claro"])  # ningun is_keyword
    import pysubs2

    out = _build(gr, cfg, tmp_path)
    subs = pysubs2.load(str(out))
    assert len(subs.events) == 3 and all(ev.layer == 0 for ev in subs.events)


def test_word_event_text_byte_identico_historico():
    # El refactor de la escala compartida NO cambia la capa de texto (contrato historico)
    cfg = get_style("hormozi", "off")  # sin pop: escala persistente pura
    gw = _grupo(["gran", "OFERTA", "hoy"])["words"]
    gw[1]["is_keyword"] = True
    gw[1]["punch_scale"] = 145
    txt = core_ass._word_event_text(gw, 1, cfg)  # OFERTA activa
    assert "\\fscx145\\fscy145" in txt and "\\c" in txt
