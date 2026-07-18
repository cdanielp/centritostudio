"""test_caption_srt.py — Contrato de la CLI/adaptador de captions con --srt (S36-B).

El TEXTO del SRT es la autoridad; Whisper solo aporta timings. Sin GPU, sin FFmpeg real
(se mockean transcribe/build_ass/burn). Solo texto SINTETICO.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import caption
import core
import srt_caption
from caption_args import build_parser
from srt_import import SrtError


def _write_srt(tmp_path: Path, text: str, name: str = "corregido.srt") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


_SRT_OK = (
    "1\n00:00:00,000 --> 00:00:02,000\nHola mundo\n\n"
    "2\n00:00:03,000 --> 00:00:05,000\nTexto sin audio\n"
)


def _tw(*triples):
    return [{"w": w, "s": s, "e": e, "prob": 1.0} for (w, s, e) in triples]


# ============================== PARSER ==============================


def test_parser_expone_srt():
    args = build_parser().parse_args(["input/x.mp4", "--srt", "sub.srt"])
    assert args.srt == "sub.srt"


def test_sin_srt_default_none():
    args = build_parser().parse_args(["input/x.mp4"])
    assert args.srt is None
    # defaults historicos intactos
    assert args.style == "hormozi" and args.lang == "es"


# ============================== ADAPTADOR: preparar_desde_srt ==============================


def test_preparar_word_aligned_y_fallback(tmp_path):
    srt = _write_srt(tmp_path, _SRT_OK)
    groups, result, payload = srt_caption.preparar_desde_srt(
        srt, _tw(("hola", 0.0, 0.5), ("mundo", 0.6, 1.0)), video_duration_ms=5000
    )
    assert result.word_aligned == 1 and result.cue_fallback == 1
    modes = [g["timing_mode"] for g in groups]
    assert modes == ["word_aligned", "cue_fallback"]
    assert payload["summary"]["n_cues"] == 2


def test_texto_srt_es_autoridad(tmp_path):
    srt = _write_srt(tmp_path, "1\n00:00:00,000 --> 00:00:02,000\nHola MUNDO\n")
    # Whisper transcribio distinto; el texto visible debe seguir siendo el del SRT
    groups, _r, _p = srt_caption.preparar_desde_srt(
        srt, _tw(("ola", 0.0, 0.5), ("mundo", 0.6, 1.0))
    )
    assert groups[0]["text"] == "Hola MUNDO"


def test_whisper_solo_aporta_timings(tmp_path):
    srt = _write_srt(tmp_path, "1\n00:00:00,000 --> 00:00:03,000\nuno dos\n")
    groups, _r, _p = srt_caption.preparar_desde_srt(srt, _tw(("uno", 0.5, 0.9), ("dos", 1.5, 1.9)))
    w = groups[0]["words"]
    assert w[0]["start"] == 0.5 and w[1]["start"] == 1.5  # timings reales de Whisper


def test_srt_inexistente_lanza(tmp_path):
    with pytest.raises(SrtError):
        srt_caption.preparar_desde_srt(tmp_path / "no.srt", _tw())


def test_extension_incorrecta_lanza(tmp_path):
    p = tmp_path / "sub.txt"
    p.write_text(_SRT_OK, encoding="utf-8")
    with pytest.raises(SrtError):
        srt_caption.preparar_desde_srt(p, _tw())


def test_srt_malformado_lanza(tmp_path):
    p = _write_srt(tmp_path, "no soy un srt\nni de lejos\n")
    with pytest.raises(SrtError):
        srt_caption.preparar_desde_srt(p, _tw())


def test_srt_con_error_estructural_aborta(tmp_path):
    # end <= start: error estructural -> el bloque no produce cue -> sin cues -> aborta
    p = _write_srt(tmp_path, "1\n00:00:02,000 --> 00:00:01,000\ntexto\n")
    with pytest.raises(SrtError):
        srt_caption.preparar_desde_srt(p, _tw())


def test_validacion_contra_duracion_warning_no_aborta(tmp_path):
    # cue despues del fin del video: solo warning, el render continua
    srt = _write_srt(tmp_path, "1\n00:00:10,000 --> 00:00:12,000\ntarde\n")
    groups, _r, payload = srt_caption.preparar_desde_srt(
        srt, _tw(("tarde", 10.0, 11.0)), video_duration_ms=5000
    )
    assert len(groups) == 1
    assert payload["summary"]["n_warnings"] >= 1


# ============================== GROUPS + build_ass ==============================


def test_construir_groups_fallback_shape(tmp_path):
    srt = _write_srt(tmp_path, "1\n00:00:00,000 --> 00:00:02,000\nlinea uno\nlinea dos\n")
    groups, _r, _p = srt_caption.preparar_desde_srt(srt, _tw())  # sin timings -> fallback
    g = groups[0]
    assert g["timing_mode"] == "cue_fallback"
    assert [w["line_idx"] for w in g["words"]] == [0, 1]


def _dialogue_lines(ass_path: Path):
    return [
        ln for ln in ass_path.read_text(encoding="utf-8").splitlines() if ln.startswith("Dialogue:")
    ]


def test_build_ass_fallback_es_estatico(tmp_path):
    from styles import get_style

    srt = _write_srt(tmp_path, "1\n00:00:00,000 --> 00:00:02,000\ncafe listo\n")
    groups, _r, _p = srt_caption.preparar_desde_srt(srt, _tw())  # fallback
    ass = tmp_path / "out.ass"
    core.build_ass(groups, 1080, 1920, get_style("clean"), ass)
    lines = _dialogue_lines(ass)
    assert len(lines) == 1  # UN evento estatico por cue
    assert "\\kf" not in lines[0] and "\\t(" not in lines[0]  # sin karaoke/animacion falsa
    assert "cafe listo" in lines[0]


def test_build_ass_word_aligned_un_evento_por_palabra(tmp_path):
    from styles import get_style

    srt = _write_srt(tmp_path, "1\n00:00:00,000 --> 00:00:02,000\nuno dos tres\n")
    groups, _r, _p = srt_caption.preparar_desde_srt(
        srt, _tw(("uno", 0.0, 0.4), ("dos", 0.5, 0.9), ("tres", 1.0, 1.4))
    )
    ass = tmp_path / "out.ass"
    core.build_ass(groups, 1080, 1920, get_style("clean"), ass)
    assert len(_dialogue_lines(ass)) == 3


def test_build_ass_fallback_multilinea_preservada(tmp_path):
    from styles import get_style

    srt = _write_srt(tmp_path, "1\n00:00:00,000 --> 00:00:02,000\nlinea uno\nlinea dos\n")
    groups, _r, _p = srt_caption.preparar_desde_srt(srt, _tw())  # fallback
    ass = tmp_path / "out.ass"
    core.build_ass(groups, 1080, 1920, get_style("clean"), ass)
    lines = _dialogue_lines(ass)
    assert len(lines) == 1 and "\\N" in lines[0]  # un evento, salto de linea preservado


def test_build_ass_grupo_historico_sin_timing_mode_intacto(tmp_path):
    from styles import get_style

    # grupo como el de core.group_words (SIN timing_mode) -> ruta historica word-by-word
    groups = [
        {
            "id": 0,
            "start": 0.0,
            "end": 1.0,
            "text": "uno dos",
            "words": [
                {"text": "uno", "start": 0.0, "end": 0.4, "line_idx": 0},
                {"text": "dos", "start": 0.5, "end": 0.9, "line_idx": 0},
            ],
        }
    ]
    ass = tmp_path / "out.ass"
    core.build_ass(groups, 1080, 1920, get_style("clean"), ass)
    assert len(_dialogue_lines(ass)) == 2  # dos palabras -> dos eventos (sin cambios)


# ============================== SIDECAR ==============================


def test_sidecar_contrato_y_basenames(tmp_path):
    srt = _write_srt(tmp_path, _SRT_OK, name="C_privada.srt")
    _g, _r, payload = srt_caption.preparar_desde_srt(
        srt, _tw(("hola", 0.0, 0.5), ("mundo", 0.6, 1.0)), words_file="video_words.json"
    )
    assert set(payload) == {"version", "source", "timing_source", "summary", "cues"}
    assert payload["source"]["name"] == "C_privada.srt"
    assert "/" not in (payload["source"]["name"] or "")
    assert payload["timing_source"]["words_file"] == "video_words.json"
    dumped = json.dumps(payload, ensure_ascii=False)
    assert json.loads(dumped)["version"] == 1


def test_sidecar_escritura_atomica(tmp_path):
    srt = _write_srt(tmp_path, _SRT_OK)
    _g, _r, payload = srt_caption.preparar_desde_srt(srt, _tw(("hola", 0.0, 0.5)))
    dest = tmp_path / "align.json"
    srt_caption.escribir_sidecar(payload, dest)
    assert json.loads(dest.read_text(encoding="utf-8"))["version"] == 1
    assert not (tmp_path / "align.json.tmp").exists()


# ============================== INTEGRACION _process_srt (mocks) ==============================


def _mock_engine(monkeypatch, tmp_path, words):
    monkeypatch.setattr(caption.core, "detect_device", lambda: ("cpu", "int8"))
    monkeypatch.setattr(caption.core, "resolve_model", lambda m: ("small", "small"))
    monkeypatch.setattr(
        caption.core,
        "get_video_info",
        lambda v: {"width": 1080, "height": 1920, "duration": 6.0, "fps": 30.0, "has_audio": True},
    )
    monkeypatch.setattr(
        caption, "_load_or_transcribe", lambda *a, **k: {"words": words, "language": "es"}
    )
    monkeypatch.setattr(caption.core, "build_ass", lambda *a, **k: Path(a[4]).write_text("x"))
    burned = {}

    def _burn(inp, ass, out):
        Path(out).write_text("mp4")
        burned["out"] = Path(out)
        return 0.1

    monkeypatch.setattr(caption.core, "burn_video", _burn)
    monkeypatch.setattr(caption, "_TRANSCRIPTS_DIR", tmp_path)
    return burned


def test_process_srt_naming_y_sidecar(tmp_path, monkeypatch):
    burned = _mock_engine(monkeypatch, tmp_path, _tw(("hola", 0.0, 0.5), ("mundo", 0.6, 1.0)))
    srt = _write_srt(tmp_path, _SRT_OK)
    out_dir = tmp_path / "out"
    total, transcript = caption.process_video(
        Path("input/video.mp4"), "clean", "es", out_dir, "auto", srt_path=srt
    )
    assert burned["out"].name == "video_clean_srt.mp4"  # sufijo _srt (D36B-6)
    assert (tmp_path / "video_srt_alignment.json").exists()  # sidecar de auditoria
    assert transcript["language"] == "es"


def test_process_srt_no_toca_srt_fuente(tmp_path, monkeypatch):
    _mock_engine(monkeypatch, tmp_path, _tw(("hola", 0.0, 0.5), ("mundo", 0.6, 1.0)))
    srt = _write_srt(tmp_path, _SRT_OK)
    antes = srt.read_bytes()
    caption.process_video(Path("input/v.mp4"), "clean", "es", tmp_path / "o", "auto", srt_path=srt)
    assert srt.read_bytes() == antes  # la fuente jamas se modifica


# ============================== main(): guardas ==============================


def _run_main(monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["caption.py", *argv])
    with pytest.raises(SystemExit) as exc:
        caption.main()
    return exc.value.code


def test_main_rechaza_directorio_con_srt(tmp_path, monkeypatch):
    (tmp_path / "vids").mkdir()
    srt = _write_srt(tmp_path, _SRT_OK)
    code = _run_main(monkeypatch, [str(tmp_path / "vids"), "--srt", str(srt)])
    assert code == 1


def test_main_rechaza_auto_seguro_con_srt(tmp_path, monkeypatch):
    srt = _write_srt(tmp_path, _SRT_OK)
    code = _run_main(
        monkeypatch,
        [
            str(tmp_path / "v.mp4"),
            "--srt",
            str(srt),
            "--caption-qa",
            "--caption-qa-mode",
            "auto_seguro",
        ],
    )
    assert code == 1


def test_llamada_historica_compatible():
    # process_video conserva srt_path como keyword-only con default None
    import inspect

    sig = inspect.signature(caption.process_video)
    p = sig.parameters["srt_path"]
    assert p.kind == inspect.Parameter.KEYWORD_ONLY and p.default is None


# ============ S36-B ENDURECIMIENTO: flags no ignorados, SrtError, QA, naming ============


def _mock_engine_full(monkeypatch, tmp_path, words):
    """Mock del motor que captura QUE funcion de quemado se uso y con que capas."""
    monkeypatch.setattr(caption.core, "detect_device", lambda: ("cpu", "int8"))
    monkeypatch.setattr(caption.core, "resolve_model", lambda m: ("small", "small"))
    monkeypatch.setattr(
        caption.core,
        "get_video_info",
        lambda v: {"width": 1080, "height": 1920, "duration": 6.0, "fps": 30.0, "has_audio": True},
    )
    monkeypatch.setattr(
        caption, "_load_or_transcribe", lambda *a, **k: {"words": words, "language": "es"}
    )
    monkeypatch.setattr(caption.core, "build_ass", lambda *a, **k: Path(a[4]).write_text("x"))
    cap: dict = {}

    def _burn(inp, ass, out):
        Path(out).write_text("mp4")
        cap["burn"] = "plain"
        cap["out"] = Path(out)
        return 0.1

    def _burn_ov(inp, ass, out, overlays, style_cfg, popups, fx_plan, clips=None):
        Path(out).write_text("mp4")
        cap.update(burn="overlays", out=Path(out), overlays=overlays, popups=popups, fx=fx_plan)
        return 0.1

    monkeypatch.setattr(caption.core, "burn_video", _burn)
    monkeypatch.setattr(caption.core, "burn_video_with_emojis", _burn_ov)
    monkeypatch.setattr(caption, "_TRANSCRIPTS_DIR", tmp_path)
    return cap


def test_process_srt_error_es_srterror_no_systemexit(tmp_path, monkeypatch):
    _mock_engine_full(monkeypatch, tmp_path, _tw(("x", 0.0, 0.5)))
    bad = _write_srt(tmp_path, "no soy un srt\n")
    with pytest.raises(SrtError):  # funcion de libreria: excepcion tipada, jamas SystemExit
        caption.process_video(Path("v.mp4"), "clean", "es", tmp_path / "o", "auto", srt_path=bad)


def test_process_srt_qa_opts_rechazado_como_srterror(tmp_path, monkeypatch):
    _mock_engine_full(monkeypatch, tmp_path, _tw(("hola", 0.0, 0.5)))
    srt = _write_srt(tmp_path, _SRT_OK)
    with pytest.raises(SrtError):
        caption.process_video(
            Path("v.mp4"),
            "clean",
            "es",
            tmp_path / "o",
            "auto",
            qa_opts={"modo": "alertas"},
            srt_path=srt,
        )


def test_main_traduce_srt_invalido_a_exit_no_cero(tmp_path, monkeypatch):
    _mock_engine_full(monkeypatch, tmp_path, _tw(("x", 0.0, 0.5)))
    vid = tmp_path / "v.mp4"
    vid.write_text("fake")
    bad = _write_srt(tmp_path, "no soy un srt\n")
    assert _run_main(monkeypatch, [str(vid), "--srt", str(bad)]) == 1


@pytest.mark.parametrize("modo", ["alertas", "auto_seguro"])
def test_main_rechaza_caption_qa_con_srt(tmp_path, monkeypatch, modo):
    srt = _write_srt(tmp_path, _SRT_OK)
    code = _run_main(
        monkeypatch,
        [str(tmp_path / "v.mp4"), "--srt", str(srt), "--caption-qa", "--caption-qa-mode", modo],
    )
    assert code == 1


def test_emojis_srt_ejecuta_ruta_emojis(tmp_path, monkeypatch):
    import assets_comfy

    cap = _mock_engine_full(monkeypatch, tmp_path, _tw(("hola", 0.0, 0.5), ("mundo", 0.6, 1.0)))
    called = {}
    monkeypatch.setattr(
        assets_comfy, "resolver_overlays", lambda *a, **k: called.update(ov=True) or []
    )
    srt = _write_srt(tmp_path, _SRT_OK)
    caption.process_video(
        Path("v.mp4"), "clean", "es", tmp_path / "o", "auto", use_emojis=True, srt_path=srt
    )
    assert called.get("ov") and cap["burn"] == "overlays"
    assert cap["out"].name.endswith("_srt_emojis.mp4")


def test_popups_srt_llama_resolvers(tmp_path, monkeypatch):
    import cve_clips
    import cve_popups

    _mock_engine_full(monkeypatch, tmp_path, _tw(("hola", 0.0, 0.5), ("mundo", 0.6, 1.0)))
    seen = {}
    monkeypatch.setattr(cve_popups, "resolver_popups", lambda *a, **k: seen.update(pop=True) or [])
    monkeypatch.setattr(cve_clips, "resolver_clips", lambda *a, **k: seen.update(clip=True) or [])
    srt = _write_srt(tmp_path, _SRT_OK)
    caption.process_video(
        Path("v.mp4"), "clean", "es", tmp_path / "o", "auto", use_popups=True, srt_path=srt
    )
    assert seen.get("pop") and seen.get("clip")


def test_fx_srt_genera_y_pasa_fxplan(tmp_path, monkeypatch):
    cap = _mock_engine_full(monkeypatch, tmp_path, _tw(("hola", 0.0, 0.5), ("mundo", 0.6, 1.0)))
    sentinel = object()
    monkeypatch.setattr(caption, "_resolver_plan_fx", lambda *a, **k: sentinel)
    srt = _write_srt(tmp_path, _SRT_OK)
    caption.process_video(
        Path("v.mp4"), "clean", "es", tmp_path / "o", "auto", fx_preset="express", srt_path=srt
    )
    assert cap["burn"] == "overlays" and cap["fx"] is sentinel
    assert cap["out"].name.endswith("_srt_fx-express.mp4")


def test_preset_srt_llama_aplicar_preset_solo_word_aligned(tmp_path, monkeypatch):
    import cve

    _mock_engine_full(monkeypatch, tmp_path, _tw(("hola", 0.0, 0.5), ("mundo", 0.6, 1.0)))
    recibido = {}

    def _spy(groups, plan, brain, w, h, kw):
        recibido["groups"] = groups
        return groups, plan, None

    monkeypatch.setattr(cve, "aplicar_preset", _spy)
    srt = _write_srt(tmp_path, _SRT_OK)  # cue1 word_aligned + cue2 fallback
    caption.process_video(
        Path("v.mp4"),
        "clean",
        "es",
        tmp_path / "o",
        "auto",
        preset="keyword_punch",
        srt_path=srt,
    )
    modes = [g["timing_mode"] for g in recibido["groups"]]
    assert modes == ["word_aligned"]  # el cue_fallback NUNCA se pasa al preset


def test_aplicar_preset_srt_conserva_fallback_estatico(monkeypatch):
    import cve

    groups = [
        {"id": 0, "timing_mode": "word_aligned", "words": [{"text": "a"}], "text": "a"},
        {
            "id": 1,
            "timing_mode": "cue_fallback",
            "words": [{"text": "x", "line_idx": 0}],
            "text": "x",
        },
    ]

    def _spy(word_groups, plan, *a):
        for g in word_groups:
            g["marcado"] = True
        return word_groups, plan, None

    monkeypatch.setattr(cve, "aplicar_preset", _spy)
    merged, _plan = caption._aplicar_preset_srt(groups, object(), "stem", 1080, 1920)
    fb = merged[1]
    assert fb["timing_mode"] == "cue_fallback" and "marcado" not in fb  # intacto
    assert merged[0].get("marcado") is True  # el word_aligned si paso por el motor
    assert [g["id"] for g in merged] == [0, 1]  # ids deterministas


def test_resolver_plan_fx_fail_open_devuelve_none():
    # preset FX no reconocido -> fail-open honesto (None), la ruta cae a burn_video
    assert caption._resolver_plan_fx("preset_inexistente_xyz", "stem", 6.0) is None


def test_nombre_srt_no_colisiona():
    combos = {
        caption._nombre_srt("v", "_clean", False, False, None),
        caption._nombre_srt("v", "_clean", True, False, None),
        caption._nombre_srt("v", "_clean", False, True, None),
        caption._nombre_srt("v", "_clean", False, False, "express"),
        caption._nombre_srt("v", "_clean", True, True, "pro"),
    }
    assert len(combos) == 5  # todas las combinaciones producen nombres distintos
    assert all("_srt" in n for n in combos)


def test_sin_srt_usa_burn_plain(tmp_path, monkeypatch):
    # sanity: sin capas ni SRT, la ruta clasica sigue quemando con burn_video
    cap = _mock_engine_full(monkeypatch, tmp_path, _tw(("hola", 0.0, 0.5)))
    monkeypatch.setattr(
        caption.core,
        "group_words",
        lambda w, **k: [
            {
                "id": 0,
                "start": 0.0,
                "end": 0.5,
                "text": "hola",
                "words": [{"text": "hola", "start": 0.0, "end": 0.5, "line_idx": 0}],
            }
        ],
    )
    caption.process_video(Path("v.mp4"), "clean", "es", tmp_path / "o", "auto")
    assert cap["burn"] == "plain"
