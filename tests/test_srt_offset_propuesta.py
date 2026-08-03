"""Propuesta de offset visible desde el Studio (S41).

D45 dejó el estimador construido pero mudo hacia la UI: proponía el offset dentro del sidecar
del render y nadie lo mostraba. Aquí se fija que el view model — lo único que consulta la UI
antes de renderizar — lo publique con su confianza y su número de anclas.

Regla que NO cambia: la propuesta **jamás se auto-aplica** (un offset mal estimado desincroniza
el video entero en silencio). El view model informa; aplicarlo es un parámetro explícito del
render que decide quien mira.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import app as studio_app
import studio_srt


def _ts(ms: int) -> str:
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _srt(*cues: tuple[int, int, int, str]) -> bytes:
    return "\n".join(f"{i}\n{_ts(s)} --> {_ts(e)}\n{t}\n" for i, s, e, t in cues).encode("utf-8")


# El SRT va 2000 ms ADELANTADO respecto del audio: el estimador debe proponer +2000.
_DESFASE_MS = 2000
_TOKENS = [
    "hola", "mundo", "cobra", "kit", "gratis", "carpeta", "marzo", "video",
    "clase", "curso", "precio", "oferta", "prueba", "canal", "grupo", "meta",
    "plan", "reto", "bono", "envio", "pago", "audio", "texto", "imagen", "clip",
]  # fmt: skip
_SRT_OK = _srt(*[(i + 1, i * 1000, i * 1000 + 800, t) for i, t in enumerate(_TOKENS)])
_WORDS = {
    "words": [
        {"w": t, "s": (i * 1000 + _DESFASE_MS) / 1000, "e": (i * 1000 + 800 + _DESFASE_MS) / 1000}
        for i, t in enumerate(_TOKENS)
    ],
    "language": "es",
}


@pytest.fixture
def api(tmp_path, monkeypatch):
    import studio_srt_routes

    inp, trans = tmp_path / "input", tmp_path / "transcripts"
    inp.mkdir()
    trans.mkdir()
    for mod in (studio_app, studio_srt_routes):
        monkeypatch.setattr(mod, "INPUT_DIR", inp)
        monkeypatch.setattr(mod, "TRANSCRIPTS", trans)
    monkeypatch.setattr(studio_srt_routes, "STUDIO_SRT_DIR", trans / "studio_srt")
    (inp / "demo.mp4").write_bytes(b"mp4-bytes")
    return TestClient(studio_app.app), trans, inp


def _asociar(trans, dur=30000):
    doc, diags = studio_srt.parse_and_validate(
        _SRT_OK, source_name="subs.srt", video_duration_ms=dur
    )
    studio_srt.store_and_associate(
        doc, diags, video_stem="demo", video_filename="demo.mp4", video_duration_ms=dur,
        data=_SRT_OK, storage_root=trans / "studio_srt", manifest_dir=trans,
    )  # fmt: skip


def _words(trans, inp, payload=None):
    import transcript_provenance as tp

    arts = tp.resolve_srt_timing_artifacts(
        transcripts_dir=trans, video_stem="demo", video_filename="demo.mp4"
    )
    arts.directory.mkdir(parents=True, exist_ok=True)
    arts.words_path.write_text(
        json.dumps(tp.attach_video_provenance(dict(payload or _WORDS), inp / "demo.mp4")),
        encoding="utf-8",
    )


def _srt_view(client):
    r = client.get("/api/videos/demo/srt/view?caption_source=srt")
    assert r.status_code == 200
    return r.json()["srt"]


# ─── La propuesta ──────────────────────────────────────────────────────────────


def test_el_view_propone_el_offset_con_confianza_y_anclas(api):
    client, trans, inp = api
    _asociar(trans)
    _words(trans, inp)
    prop = _srt_view(client)["offset_propuesto"]
    assert prop is not None
    assert prop["offset_ms"] == pytest.approx(_DESFASE_MS, abs=50)
    assert prop["n_anclas"] >= 20
    assert 0.0 <= prop["confianza"] <= 1.0
    assert isinstance(prop["aplicable"], bool)


def test_la_propuesta_no_se_auto_aplica(api):
    """El view model INFORMA. Nada en el estado del video queda desplazado por consultarlo."""
    client, trans, inp = api
    _asociar(trans)
    _words(trans, inp)
    antes = _srt_view(client)
    assert antes["offset_propuesto"]["offset_ms"] != 0
    # Consultar dos veces da lo mismo: no hay efecto acumulado ni persistido.
    assert _srt_view(client)["offset_propuesto"] == antes["offset_propuesto"]


def test_sin_timings_no_hay_propuesta(api):
    """Fail-open: sin words no se puede estimar, y eso se dice con None, no con un 0 falso."""
    client, trans, _inp = api
    _asociar(trans)
    assert _srt_view(client)["offset_propuesto"] is None


def test_sin_seleccion_no_hay_propuesta(api):
    client, *_ = api
    assert _srt_view(client)["offset_propuesto"] is None


def test_un_srt_ya_alineado_propone_cero(api):
    client, trans, inp = api
    _asociar(trans)
    _words(
        trans,
        inp,
        {"words": [{"w": t, "s": i * 1.0, "e": i * 1.0 + 0.8} for i, t in enumerate(_TOKENS)]},
    )
    assert _srt_view(client)["offset_propuesto"]["offset_ms"] == 0


def test_words_ilegibles_no_tumban_el_view(api):
    """Un transcript roto degrada la propuesta, nunca la respuesta entera."""
    client, trans, inp = api
    _asociar(trans)
    _words(trans, inp)
    import transcript_provenance as tp

    arts = tp.resolve_srt_timing_artifacts(
        transcripts_dir=trans, video_stem="demo", video_filename="demo.mp4"
    )
    arts.words_path.write_text("{ no soy json", encoding="utf-8")
    srt = _srt_view(client)
    assert srt["offset_propuesto"] is None
    assert "timings" in srt  # el resto del view sigue respondiendo


def test_el_estimador_roto_degrada_pero_deja_rastro(api, monkeypatch, capsys):
    """Un fallo del estimador no puede ser mudo: sin log, la UI diria 'sin propuesta' y ya."""
    import srt_offset

    client, trans, inp = api
    _asociar(trans)
    _words(trans, inp)

    def _revienta(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(srt_offset, "estimar_offset", _revienta)
    srt = _srt_view(client)
    assert srt["offset_propuesto"] is None
    assert srt["timings"] == "valid"  # el resto del view no se degrada
    assert "offset no estimado" in capsys.readouterr().out


def test_la_propuesta_no_filtra_texto_ni_rutas(api):
    client, trans, inp = api
    _asociar(trans)
    _words(trans, inp)
    prop = _srt_view(client)["offset_propuesto"]
    # Solo numeros y codigos cerrados: `metodo`/`motivo` son enums del estimador, no texto libre.
    assert set(prop) == {
        "offset_ms",
        "n_anclas",
        "dispersion_ms",
        "confianza",
        "aplicable",
        "metodo",
        "motivo",
    }
    assert prop["motivo"] in ("", "sin_material", "sin_anclas")
    crudo = json.dumps(prop)
    assert "demo.mp4" not in crudo and "hola" not in crudo and "subs.srt" not in crudo
