"""Exposición del modo parcial y del offset en la CLI (S41).

D45/D47/D48 viven detrás de `modo_parcial`, y hasta S41 ese parámetro solo existía en la API:
desde la CLI era inalcanzable y todo render con `--srt` salía con el comportamiento viejo.

Contrato que se fija aquí:

  * `--srt-parcial` activa el alineado parcial; `--srt-offset` aplica un desplazamiento
    EXPLÍCITO. Ambos exigen `--srt` (pedirlos sin él es un error del usuario, no algo que se
    ignore en silencio).
  * Sin esos flags, la ruta `--srt` se comporta EXACTAMENTE como antes (modo_parcial=False,
    offset_ms=0).
  * El offset propuesto se imprime SIEMPRE, pero jamás se auto-aplica (D45).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import caption
from caption_args import build_parser

# ─── Parser ────────────────────────────────────────────────────────────────────


def test_parser_expone_srt_parcial_y_offset():
    args = build_parser().parse_args(
        ["input/x.mp4", "--srt", "sub.srt", "--srt-parcial", "--srt-offset", "5284"]
    )
    assert args.srt_parcial is True
    assert args.srt_offset == 5284


def test_defaults_reproducen_el_comportamiento_historico():
    args = build_parser().parse_args(["input/x.mp4", "--srt", "sub.srt"])
    assert args.srt_parcial is False
    assert args.srt_offset == 0


def test_offset_acepta_negativo():
    args = build_parser().parse_args(["input/x.mp4", "--srt", "s.srt", "--srt-offset", "-1200"])
    assert args.srt_offset == -1200


# ─── Guardas de usuario ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "extra",
    (
        ["--srt-parcial"],
        ["--srt-offset", "500"],
        ["--srt-parcial", "--srt-offset", "500"],
        # 0.0 es un valor PEDIDO, no un vacio: la guarda no puede usar truthiness.
        ["--srt-min-coverage", "0.0"],
    ),
)
def test_los_flags_srt_exigen_srt(monkeypatch, capsys, extra):
    """Pedir modo parcial sin `--srt` es un error, no un flag que se traga el vacio."""
    monkeypatch.setattr("sys.argv", ["caption.py", "input/x.mp4", *extra])
    with pytest.raises(SystemExit) as exc:
        caption.main()
    assert exc.value.code != 0
    assert "--srt" in capsys.readouterr().out


def test_min_coverage_sin_modo_parcial_es_error(monkeypatch, capsys):
    """Sin modo parcial el umbral no cambia una sola salida: aceptarlo callado seria mentir."""
    monkeypatch.setattr(
        "sys.argv", ["caption.py", "input/x.mp4", "--srt", "s.srt", "--srt-min-coverage", "0.5"]
    )
    with pytest.raises(SystemExit) as exc:
        caption.main()
    assert exc.value.code != 0
    assert "--srt-parcial" in capsys.readouterr().out


def test_ningun_mensaje_de_la_ruta_srt_sale_del_ascii():
    """La consola de Windows no siempre es cp1252: un guion largo la revienta a media corrida."""
    fuente = Path(caption.__file__).read_text(encoding="utf-8")
    prints = [ln for ln in fuente.splitlines() if "[srt]" in ln or "[ERROR] --srt" in ln]
    assert prints
    for linea in prints:
        assert linea.isascii(), linea


def test_offset_fuera_de_rango_es_error(monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.argv", ["caption.py", "input/x.mp4", "--srt", "s.srt", "--srt-offset", "99999999"]
    )
    with pytest.raises(SystemExit) as exc:
        caption.main()
    assert exc.value.code != 0
    assert "offset" in capsys.readouterr().out.lower()


# ─── Cableado hasta el alineador ───────────────────────────────────────────────


def _espiar_preparar(monkeypatch) -> dict:
    """Sustituye `srt_caption.preparar_desde_srt` y captura sus kwargs. Corta antes del render."""
    import srt_caption

    visto: dict = {}

    def _spy(srt_path, timing_words, **kw):
        visto.update(kw)
        raise _Corte()

    monkeypatch.setattr(srt_caption, "preparar_desde_srt", _spy)
    return visto


class _Corte(Exception):
    """Corta el proceso justo después de la llamada bajo prueba (no se renderiza nada)."""


def _correr(monkeypatch, tmp_path, **kw):
    """Llama a `process_video` con la ruta SRT mockeada hasta `preparar_desde_srt`."""
    monkeypatch.setattr(caption.core, "detect_device", lambda: ("cpu", "int8"))
    monkeypatch.setattr(caption.core, "resolve_model", lambda m: ("p", "small"))
    monkeypatch.setattr(
        caption.core, "get_video_info", lambda p: {"width": 1080, "height": 1920, "duration": 10.0}
    )
    monkeypatch.setattr(
        caption, "_load_or_transcribe", lambda *a, **k: {"words": [], "language": "es"}
    )
    visto = _espiar_preparar(monkeypatch)
    with pytest.raises(_Corte):
        caption.process_video(
            Path("v.mp4"), "clean", "es", tmp_path, "auto", srt_path=tmp_path / "s.srt", **kw
        )
    return visto


def test_sin_flags_el_alineador_recibe_el_comportamiento_historico(monkeypatch, tmp_path):
    visto = _correr(monkeypatch, tmp_path)
    assert visto.get("modo_parcial", False) is False
    assert visto.get("offset_ms", 0) == 0


def test_srt_parcial_llega_al_alineador(monkeypatch, tmp_path):
    visto = _correr(monkeypatch, tmp_path, srt_parcial=True)
    assert visto["modo_parcial"] is True


def test_srt_offset_llega_al_alineador(monkeypatch, tmp_path):
    visto = _correr(monkeypatch, tmp_path, srt_offset_ms=-1200)
    assert visto["offset_ms"] == -1200


def test_min_coverage_es_configurable(monkeypatch, tmp_path):
    visto = _correr(monkeypatch, tmp_path, srt_parcial=True, srt_min_coverage=0.75)
    assert visto["min_coverage"] == 0.75


# ─── El modo parcial no puede ser un no-op ─────────────────────────────────────


_SRT_PARCIAL = (
    "1\n00:00:00,000 --> 00:00:04,000\nuno dos tres cuatro\n"  # solo anclan 2 de 4 tokens
)
_WORDS_PARCIAL = [
    {"w": "uno", "s": 0.0, "e": 0.5, "prob": 1.0},
    {"w": "cuatro", "s": 3.0, "e": 3.5, "prob": 1.0},
]


def _preparar(tmp_path, **kw):
    """Ruta REAL: mide el umbral que acabo usando el alineador, no el que se pidio."""
    import srt_caption

    p = tmp_path / "s.srt"
    p.write_text(_SRT_PARCIAL, encoding="utf-8")
    _g, result, _payload = srt_caption.preparar_desde_srt(p, _WORDS_PARCIAL, **kw)
    return result


def test_el_modo_parcial_baja_el_umbral_por_si_solo(tmp_path):
    """Activar el modo parcial y dejar el umbral en 1.0 NO produce ni un cue parcial.

    Con umbral 1.0 el porton exige anclar TODOS los tokens, que es justo la ruta historica: el
    control quedaria encendido sin hacer nada. Sin umbral explicito se usa el mismo con el que
    se rindio y aprobo la evidencia de D45/D47/D48.
    """
    import srt_align

    r = _preparar(tmp_path, modo_parcial=True)
    assert r.min_coverage == srt_align.MIN_COVERAGE_PARCIAL < srt_align.DEFAULT_MIN_COVERAGE
    assert r.word_partial == 1  # y de verdad anima el cue


def test_el_umbral_explicito_gana(tmp_path):
    r = _preparar(tmp_path, modo_parcial=True, min_coverage=1.0)
    assert r.min_coverage == 1.0
    assert r.word_partial == 0  # el llamador pidio el porton estricto y se respeta


def test_sin_modo_parcial_el_umbral_sigue_siendo_el_historico(tmp_path):
    import srt_align

    r = _preparar(tmp_path)
    assert r.min_coverage == srt_align.DEFAULT_MIN_COVERAGE == 1.0
    assert r.word_partial == 0 and r.cue_fallback == 1
