"""Tests de depurador.py — corren sin GPU ni videos reales."""

from unittest.mock import patch

import depurador

# ── Fixture de words sinteticas ───────────────────────────────────────────────

WORDS = [
    {"w": "hola", "s": 0.0, "e": 0.4, "prob": 0.99},
    {"w": "buenas", "s": 0.5, "e": 1.0, "prob": 0.99},
    # Silencio de 1.5s (1.0 → 2.5) — debe comprimirse
    {"w": "eh", "s": 2.5, "e": 2.7, "prob": 0.99},  # muletilla aislada
    # Pausa de 0.5s (2.7 → 3.2) — ok
    {"w": "esto", "s": 3.2, "e": 3.8, "prob": 0.99},
    {"w": "es", "s": 3.9, "e": 4.2, "prob": 0.99},
    # Falso arranque: "es" repetido con pausa antes de "esto" mayor a 0.4s (1.2s → ok)
    {"w": "es", "s": 4.3, "e": 4.6, "prob": 0.99},
    {"w": "bueno", "s": 4.7, "e": 5.0, "prob": 0.99},
]
DUR = 5.5


# ── Tests seguro ──────────────────────────────────────────────────────────────


def test_edl_seguro_comprime_silencio():
    edl = depurador.build_edl_seguro(WORDS, DUR)
    # Gap de 1.5s entre buenas(1.0) y eh(2.5): debe cortar [1.25, 2.5]
    assert len(edl) == 2
    # Primer segmento termina en 1.0 + 0.25 = 1.25
    assert abs(edl[0][0] - 0.0) < 0.01
    assert abs(edl[0][1] - 1.25) < 0.01
    # Segundo segmento arranca en 2.5
    assert abs(edl[1][0] - 2.5) < 0.01
    assert abs(edl[1][1] - DUR) < 0.01


def test_edl_seguro_respeta_pausas_cortas():
    words_sin_gap = [
        {"w": "a", "s": 0.0, "e": 0.5},
        {"w": "b", "s": 0.7, "e": 1.2},  # gap 0.2s < 0.8s — no cortar
    ]
    edl = depurador.build_edl_seguro(words_sin_gap, 1.5)
    assert len(edl) == 1
    assert abs(edl[0][0]) < 0.01
    assert abs(edl[0][1] - 1.5) < 0.01


# ── Tests muletillas ──────────────────────────────────────────────────────────


def test_detectar_muletilla_aislada():
    # "eh" en WORDS[2] tiene pausa_antes=1.5s y pausa_despues=0.5s — ambas >= 0.25s
    indices = depurador.detectar_muletillas(WORDS)
    assert 2 in indices, f"'eh' aislado debe detectarse; got {indices}"


def test_no_cortar_este_sin_pausas():
    words_sin_pausa = [
        {"w": "quiero", "s": 0.0, "e": 0.5},
        {"w": "este", "s": 0.6, "e": 0.8},  # pausa_antes=0.1s < 0.25s
        {"w": "libro", "s": 0.9, "e": 1.2},  # pausa_despues=0.1s < 0.25s
    ]
    indices = depurador.detectar_muletillas(words_sin_pausa)
    assert 1 not in indices, "'este' sin pausas NO debe cortarse"


# ── Tests falsos arranques ────────────────────────────────────────────────────


def test_detectar_falso_arranque():
    words_fa = [
        {"w": "hola", "s": 0.0, "e": 0.3},
        # Silencio 1.2s
        {"w": "es", "s": 1.5, "e": 1.8},  # inicio de segmento nuevo (pausa 1.2s)
        {"w": "es", "s": 1.9, "e": 2.2},  # bigrama repetido
        {"w": "bueno", "s": 2.3, "e": 2.6},
    ]
    indices = depurador.detectar_falsos_arranques(words_fa)
    assert 1 in indices, f"'es es' debe detectarse como falso arranque; got {indices}"


# ── Tests recalcular_words ────────────────────────────────────────────────────


def test_recalcular_words_elimina_cortados():
    edl = [(0.0, 1.25), (2.5, 5.5)]
    # word "eh" de 2.5-2.7 esta en el segundo segmento (inicio)
    new_words, drift = depurador.recalcular_words(WORDS, edl)
    textos = [w["w"] for w in new_words]
    assert "hola" in textos
    assert "eh" in textos  # "eh" esta dentro del segmento conservado (2.5-5.5)


def test_recalcular_words_timestamps():
    words_simple = [
        {"w": "a", "s": 0.0, "e": 0.5, "prob": 0.99},
        {"w": "b", "s": 2.0, "e": 2.5, "prob": 0.99},  # despues de un corte
    ]
    edl = [(0.0, 0.75), (2.0, 3.0)]  # Corte en [0.75, 2.0]
    new_words, _ = depurador.recalcular_words(words_simple, edl)
    assert len(new_words) == 2
    # "a" no cambia (esta en primer segmento, sin offset)
    assert abs(new_words[0]["s"] - 0.0) < 0.01
    assert abs(new_words[0]["e"] - 0.5) < 0.01
    # "b" empieza en 2.0 original → 0.75 en output (acc del segmento 0 = 0.75)
    assert abs(new_words[1]["s"] - 0.75) < 0.01


def test_edl_agresivo_mas_cortes_que_seguro():
    edl_seg = depurador.build_edl_seguro(WORDS, DUR)
    edl_agr = depurador.build_edl_agresivo(WORDS, DUR)
    # Agresivo deberia tener al menos tantos o mas segmentos que seguro
    dur_seg = sum(e - s for s, e in edl_seg)
    dur_agr = sum(e - s for s, e in edl_agr)
    assert dur_agr <= dur_seg + 0.01, "Agresivo no puede ser mas largo que seguro"


# ── Tests _eval_joins (diagnostico voz-a-voz) ────────────────────────────────

_WORDS_VOZ = [
    {"w": "hola", "s": 0.0, "e": 1.0, "prob": 0.99},
    {"w": "mundo", "s": 2.5, "e": 3.0, "prob": 0.99},
]
# EDL: silencio original 1.5s (1.0->2.5) comprimido a 0.25s -> seg[0] = (0, 1.25)
_EDL_BASE = [(0.0, 1.25), (2.5, 4.0)]
# voice_refs: "hola" termina en 1.0 <= 1.25-0.25+0.01=1.01
_VOICE_REFS = [depurador._last_word_end_before(_WORDS_VOZ, e) for _, e in _EDL_BASE[:-1]]


def test_voice_refs_apunta_a_ultima_palabra():
    """_last_word_end_before devuelve el fin de la ultima palabra antes del silencio."""
    assert _VOICE_REFS == [1.0], f"Esperado [1.0], obtenido {_VOICE_REFS}"


def test_eval_joins_clasifica_union_limpia(tmp_path):
    """Delta voz-voz <= 6dB: clasifica como 'limpia' y no modifica el EDL."""
    fake = tmp_path / "v.mp4"
    fake.write_bytes(b"")
    with patch.object(depurador, "_volume_at", side_effect=[-15.0, -17.0]):
        report = depurador._eval_joins(fake, list(_EDL_BASE), _VOICE_REFS)
    assert len(report) == 1
    assert report[0]["clase"] == "limpia"
    assert report[0]["delta"] == 2.0


def test_eval_joins_clasifica_salto_leve(tmp_path):
    """Delta voz-voz 6-15dB: clasifica como 'salto_leve'."""
    fake = tmp_path / "v.mp4"
    fake.write_bytes(b"")
    with patch.object(depurador, "_volume_at", side_effect=[-15.0, -25.0]):
        report = depurador._eval_joins(fake, list(_EDL_BASE), _VOICE_REFS)
    assert len(report) == 1
    assert report[0]["clase"] == "salto_leve"
    assert report[0]["delta"] == 10.0


def test_eval_joins_clasifica_salto_notable(tmp_path):
    """Delta voz-voz > 15dB: clasifica como 'salto_notable'; EDL permanece intacto."""
    fake = tmp_path / "v.mp4"
    fake.write_bytes(b"")
    with patch.object(depurador, "_volume_at", side_effect=[-15.0, -35.0]):
        report = depurador._eval_joins(fake, list(_EDL_BASE), _VOICE_REFS)
    assert len(report) == 1
    assert report[0]["clase"] == "salto_notable"
    assert report[0]["delta"] == 20.0
