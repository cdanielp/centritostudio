"""Tests de CONTRATO para core.py — son el Definition of Done ejecutable de la Fase 1.

Se saltan automaticamente mientras core.py no exista. En cuanto exista, DEBEN pasar.
El contrato exacto (firmas y forma del transcript) vive en:
.claude/skills/centrito-dev/SKILL.md — seccion "Contrato de core.py".
"""

import pytest

core = pytest.importorskip("core", reason="core.py aun no existe (se crea en Fase 1)")
import core_ass  # noqa: E402
import styles  # noqa: E402

# ── Fixture de brain data con kw_ts para test regroup-safe ──────────────────
_WORDS_PLANOS = [
    {"w": "Los", "s": 0.00, "e": 0.30, "prob": 0.99},
    {"w": "tacos", "s": 0.40, "e": 0.80, "prob": 0.99},  # keyword (ts=0.40)
    {"w": "son", "s": 0.90, "e": 1.10, "prob": 0.99},
    {"w": "buenos", "s": 1.20, "e": 1.60, "prob": 0.99},
]
_BRAIN_CON_KW_TS = {"groups": [{"g": 0, "kw": 1, "kw_ts": 0.40, "emoji": "🌮"}]}


def _palabras_de(grupos):
    """Aplana lista de grupos a lista de textos de palabras."""
    return [w["text"] for g in grupos for w in g["words"]]


def test_agrupa_y_no_pierde_palabras(transcript_falso):
    grupos = core.group_words(transcript_falso, max_chars=18, max_lines=2)
    assert len(grupos) >= 2
    assert len(_palabras_de(grupos)) == 7  # ninguna palabra se pierde


def test_corta_por_pausa_larga(transcript_falso):
    """Gap de 1.0s entre 'rapido.' (2.10) y 'Ahora' (3.10) > 0.4s => bloques distintos."""
    grupos = core.group_words(transcript_falso, max_chars=80, max_lines=2)
    for g in grupos:
        palabras = [w["text"] for w in g["words"]]
        assert not ("rápido." in palabras and "Ahora" in palabras), (
            "La pausa de 1.0s debe cortar el grupo aunque quepan los caracteres"
        )


def test_corta_por_puntuacion(transcript_falso):
    """'rapido.' termina en punto => nada del segmento siguiente en su mismo bloque."""
    grupos = core.group_words(transcript_falso, max_chars=200, max_lines=2)
    for g in grupos:
        palabras = [w["text"] for w in g["words"]]
        if any(p.endswith(".") for p in palabras):
            assert palabras[-1].endswith("."), "Tras puntuacion final debe cerrarse el bloque"


def test_max_words_se_respeta(transcript_falso):
    grupos = core.group_words(transcript_falso, max_chars=80, max_lines=2, max_words=2)
    for g in grupos:
        assert len(g["words"]) <= 2


def test_sin_palabra_huerfana(transcript_falso):
    """El ultimo bloque no puede ser 1 palabra si cabia en el anterior."""
    grupos = core.group_words(transcript_falso, max_chars=30, max_lines=2)
    if len(grupos) >= 2 and len(grupos[-1]["words"]) == 1:
        chars_prev = sum(len(w["text"]) + 1 for w in grupos[-2]["words"])
        chars_huerfana = len(grupos[-1]["words"][0]["text"])
        assert chars_prev + chars_huerfana > 30, "Palabra huerfana que cabia en el bloque anterior"


def test_build_ass_utf8_y_playres(transcript_falso, tmp_path):
    cfg = styles.get_style("karaoke")  # karaoke no fuerza mayusculas
    salida = tmp_path / "utf8.ass"
    grupos = core.group_words(transcript_falso, max_chars=80, max_lines=2)
    core.build_ass(grupos, 1080, 1920, cfg, salida)
    contenido = salida.read_text(encoding="utf-8-sig")
    assert "PlayResY: 1920" in contenido
    assert ("niño" in contenido) or ("NIÑO" in contenido), "La enie debe sobrevivir al .ass"
    assert ("rápido" in contenido) or ("RÁPIDO" in contenido), "El acento debe sobrevivir"


def test_consistencia_entre_resoluciones(transcript_falso, tmp_path):
    """1056x1920 y 1080x1920 deben producir el MISMO tamano visual (misma altura)."""
    cfg = styles.get_style("hormozi")
    grupos = core.group_words(transcript_falso)
    a, b = tmp_path / "a.ass", tmp_path / "b.ass"
    core.build_ass(grupos, 1056, 1920, cfg, a)
    core.build_ass(grupos, 1080, 1920, cfg, b)

    def fontsize(p):
        for linea in p.read_text(encoding="utf-8-sig").splitlines():
            if linea.startswith("Style:"):
                return float(linea.split(",")[2])
        raise AssertionError(f"Sin linea Style en {p}")

    fa, fb = fontsize(a), fontsize(b)
    assert abs(fa - fb) / fb < 0.02, f"Fontsize difiere entre resoluciones: {fa} vs {fb}"


def _kw_words(grupos):
    """Devuelve lista de words con is_keyword=True de todos los grupos."""
    return [w for g in grupos for w in g["words"] if w.get("is_keyword")]


def test_apply_brain_agrupacion_auto():
    """La keyword debe detectarse via kw_ts en agrupacion automatica."""
    grupos = core.group_words(_WORDS_PLANOS, max_chars=40)
    enriq = core_ass.apply_brain(grupos, _BRAIN_CON_KW_TS)
    kws = _kw_words(enriq)
    assert len(kws) == 1, f"Esperaba 1 keyword, obtuvo {len(kws)}"
    assert kws[0]["text"] == "tacos"


def test_apply_brain_regroup_max_words_2():
    """La keyword debe ser la MISMA palabra aunque se reagrupe con max_words=2."""
    grupos_2w = core.group_words(_WORDS_PLANOS, max_chars=40, max_words=2)
    enriq_2w = core_ass.apply_brain(grupos_2w, _BRAIN_CON_KW_TS)
    kws_2w = _kw_words(enriq_2w)
    assert len(kws_2w) == 1, f"Esperaba 1 keyword en reagrupacion, obtuvo {len(kws_2w)}"
    assert kws_2w[0]["text"] == "tacos"
    # El emoji sigue al keyword sin importar el grupo
    grupo_con_kw = next(g for g in enriq_2w for w in g["words"] if w.get("is_keyword"))
    assert grupo_con_kw.get("brain_emoji") == "🌮"
