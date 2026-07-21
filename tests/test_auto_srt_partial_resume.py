"""test_auto_srt_partial_resume.py — Resume de paquetes SRT TERMINADOS PARCIALMENTE (S36-C2C P2).

Un run SRT que termina con done<total escribe `paquete.json` (no es "interrumpido"). La UI
"Reanudar clips fallidos" re-invoca `ejecutar_auto` con el MISMO video/config y NO borra
`paquete.json`. Estos tests demuestran que ese resume real reusa el MISMO paquete/run_id y solo
reprocesa los clips fallidos/faltantes/corruptos, sin re-renderizar los done validos. FFmpeg
mockeado; `srt_caption`/`auto_srt_artifacts`/`studio_srt` corren de verdad. Sin GPU/red/FFmpeg.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import words_con_procedencia

import auto
import studio_srt
import transcript_provenance as tp
from auto_config import AutoConfig


@pytest.fixture(autouse=True)
def _mp4_sintetico_valido(ffprobe_ok):
    """H2 (P1-OUT-3): el resume SRT ahora exige video_reanudable en el clip done; los MP4
    sinteticos no vacios de estos tests cuentan como publicables via el ffprobe stub de conftest.
    Un output FALTANTE sigue fallando (is_file real), como exige test_done_con_output_faltante."""


def _ts(ms):
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _srt(*cues):
    return "\n".join(f"{i}\n{_ts(s)} --> {_ts(e)}\n{t}\n" for i, s, e, t in cues).encode("utf-8")


_SRT = _srt(
    (1, 0, 2000, "Uno dentro"),
    (2, 4000, 6000, "Dos"),
    (3, 9000, 11000, "Tres cruza"),
    (4, 14000, 16000, "Cuatro"),
)
_PARENT_WORDS = {
    "words": [
        {"w": "uno", "s": 0.5, "e": 0.9, "prob": 1.0},
        {"w": "dos", "s": 4.5, "e": 4.9, "prob": 1.0},
        {"w": "tres", "s": 9.5, "e": 9.9, "prob": 1.0},
        {"w": "cuatro", "s": 14.5, "e": 14.9, "prob": 1.0},
    ],
    "language": "es",
}
_CLIPS = [
    {"archivo": "demo_clip1_single.mp4", "start": 0.0, "end": 5.0, "dur_s": 5.0, "titulo": "C1"},
    {"archivo": "demo_clip2_single.mp4", "start": 8.0, "end": 12.0, "dur_s": 4.0, "titulo": "C2"},
    {"archivo": "demo_clip3_single.mp4", "start": 13.0, "end": 17.0, "dur_s": 4.0, "titulo": "C3"},
]


@pytest.fixture
def srt_env(tmp_path, monkeypatch):
    """Entorno SRT con FFmpeg mockeado; expone control de fallo por clip y contador de burns."""
    trans = tmp_path / "transcripts"
    clips = tmp_path / "output" / "clips"
    paquetes = tmp_path / "output" / "paquetes"
    inp = tmp_path / "input"
    for d in (trans, clips, paquetes, inp, tmp_path / "output"):
        d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(auto, "TRANSCRIPTS", trans)
    monkeypatch.setattr(auto, "CLIPS_DIR", clips)
    monkeypatch.setattr(auto, "PAQUETES_DIR", paquetes)
    monkeypatch.setattr(auto, "ROOT", tmp_path)
    video = inp / "demo.mov"
    video.write_bytes(b"parent-video-bytes")
    # H2: procedencia classic para reutilizar el transcript del padre sin retranscribir.
    (trans / "demo_words.json").write_text(
        json.dumps(words_con_procedencia(video, _PARENT_WORDS)), encoding="utf-8"
    )
    doc, diags = studio_srt.parse_and_validate(_SRT, source_name="s.srt", video_duration_ms=20000)
    studio_srt.store_and_associate(
        doc,
        diags,
        video_stem="demo",
        video_filename="demo.mov",
        video_duration_ms=20000,
        data=_SRT,
        storage_root=trans / "studio_srt",
        manifest_dir=trans,
    )
    parts = tp.resolve_srt_timing_artifacts(
        transcripts_dir=trans, video_stem="demo", video_filename="demo.mov"
    )
    parts.directory.mkdir(parents=True, exist_ok=True)
    parts.words_path.write_text(
        json.dumps(tp.attach_video_provenance(dict(_PARENT_WORDS), video)), encoding="utf-8"
    )

    state: dict = {"burns": [], "fail": set()}

    def fake_generar_clips(v, w, n):
        for c in _CLIPS:
            (clips / c["archivo"]).write_bytes(b"clip-" + c["archivo"].encode())
        return {
            "clips": [dict(c) for c in _CLIPS],
            "casi": [],
            "telemetria_resumen": {"costo_usd": 0.0},
        }

    def fake_reframe(clip_path, out_path, **kw):
        Path(out_path).write_bytes(b"9x16-" + Path(out_path).name.encode())
        return {"output": str(out_path), "segmentos": []}

    def fake_build_ass(groups, w, h, style_cfg, ass_path):
        Path(ass_path).write_text("[ass]", encoding="utf-8")

    def fake_burn(inp_mp4, ass, out, overlays, style_cfg):
        state["burns"].append(Path(out).name)
        if any(tok in str(out) for tok in state["fail"]):
            raise RuntimeError("fallo-controlado")
        Path(out).write_bytes(b"final-" + Path(out).name.encode())  # determinista por clip
        return 1.0

    import assets_comfy
    import core
    import reframe

    monkeypatch.setattr(
        auto, "_asegurar_clips", lambda v, w, n: (fake_generar_clips(v, w, "x"), False)
    )
    monkeypatch.setattr(reframe, "reframe_clip", fake_reframe)
    monkeypatch.setattr(
        core, "get_video_info", lambda p: {"width": 1080, "height": 1920, "duration": 4.0}
    )
    monkeypatch.setattr(core, "build_ass", fake_build_ass)
    monkeypatch.setattr(core, "burn_video_with_emojis", fake_burn)
    monkeypatch.setattr(assets_comfy, "resolver_overlays", lambda *a: [])
    return {"video": video, "trans": trans, "paquetes": paquetes, "root": tmp_path, "state": state}


def _run(srt_env):
    return auto.ejecutar_auto(srt_env["video"], "demo", config=AutoConfig(caption_source="srt"))


def _paquete_dir(srt_env, r):
    return srt_env["root"] / r["paquete"]


def _manifiesto(srt_env, r):
    import auto_srt_manifest

    return json.loads(
        (_paquete_dir(srt_env, r) / auto_srt_manifest.manifest_filename()).read_text(
            encoding="utf-8"
        )
    )


def _stat(path: Path):
    st = path.stat()
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest(), st.st_mtime_ns


# ─── Integración: el flujo real de la UI (sin borrar paquete.json) ────────────────────────────
def test_partial_conserva_paquete_json_y_manifiesto(srt_env):
    """1+2: un run parcial CONSERVA paquete.json y su manifiesto refleja done=2/error=1."""
    srt_env["state"]["fail"] = {"clip2"}
    rB = _run(srt_env)
    paquete = _paquete_dir(srt_env, rB)
    assert (paquete / "paquete.json").exists()  # NO es "interrumpido"
    assert _manifiesto(srt_env, rB)["summary"] == {"total": 3, "done": 2, "error": 1}


def test_resume_reusa_mismo_paquete_y_run_id_sin_borrar(srt_env):
    """3+9: re-ejecutar con mismo video/config reutiliza el MISMO directorio y run_id."""
    srt_env["state"]["fail"] = {"clip2"}
    rB = _run(srt_env)
    srt_env["state"]["fail"] = set()  # se repara el burn; NO se toca paquete.json
    rC = _run(srt_env)
    assert _paquete_dir(srt_env, rC) == _paquete_dir(srt_env, rB)
    assert _manifiesto(srt_env, rC)["run_id"] == _manifiesto(srt_env, rB)["run_id"]


def test_resume_solo_reprocesa_el_fallido(srt_env):
    """4+5+7: en el resume solo el clip fallido se re-renderiza (burn counter == 1, clip2)."""
    srt_env["state"]["fail"] = {"clip2"}
    _run(srt_env)
    srt_env["state"]["fail"] = set()
    srt_env["state"]["burns"].clear()
    _run(srt_env)
    burns = srt_env["state"]["burns"]
    assert len(burns) == 1 and "clip2" in burns[0]


def test_resume_no_altera_los_clips_done(srt_env):
    """6: los clips done (1 y 3) quedan byte-idénticos y con mtime intacto tras el resume."""
    srt_env["state"]["fail"] = {"clip2"}
    rB = _run(srt_env)
    paquete = _paquete_dir(srt_env, rB)
    done = {p.name: _stat(p) for p in paquete.glob("*_hormozi.mp4") if "clip2" not in p.name}
    assert len(done) == 2
    srt_env["state"]["fail"] = set()
    _run(srt_env)
    for name, (h, mtime) in done.items():
        h2, mtime2 = _stat(paquete / name)
        assert h2 == h and mtime2 == mtime  # ni rehash ni reescritura


def test_resume_llega_a_done_3(srt_env):
    """8: tras el resume el manifiesto final es done=3/error=0 con 3 outputs válidos."""
    srt_env["state"]["fail"] = {"clip2"}
    _run(srt_env)
    srt_env["state"]["fail"] = set()
    rC = _run(srt_env)
    man = _manifiesto(srt_env, rC)
    assert man["summary"] == {"total": 3, "done": 3, "error": 0}
    assert all(c["output"] for c in man["clips"])


def test_paquete_exitoso_no_se_reanuda(srt_env):
    """10: un run done=3 completo NO se reabre; el siguiente run crea un paquete nuevo."""
    r1 = _run(srt_env)  # done=3
    assert _manifiesto(srt_env, r1)["summary"]["done"] == 3
    r2 = _run(srt_env)
    assert _paquete_dir(srt_env, r2) != _paquete_dir(srt_env, r1)


def test_respuesta_publica_no_expone_rutas(srt_env):
    """18: ni el resultado ni el manifiesto exponen rutas absolutas ni texto privado."""
    srt_env["state"]["fail"] = {"clip2"}
    rB = _run(srt_env)
    srt_env["state"]["fail"] = set()
    rC = _run(srt_env)
    blob = json.dumps(_manifiesto(srt_env, rC))
    assert "/" not in blob.replace("://", "") and "\\\\" not in blob and "titulo" not in blob
    assert str(srt_env["root"]) not in json.dumps(rB["clips"])


# ─── Unitarios: selección segura del paquete (_paquete_dir_v2 / _paquete_v2_reanudable) ────────
def _final_name(clip_archivo: str) -> str:
    return f"{clip_archivo.replace('.mp4', '')}_9x16_{auto.STYLE_AUTO}.mp4"


def _mk_v2_pkg(paquetes: Path, name: str, fp: str, dirname: str, states: list[str], *, marker=True):
    """Crea un paquete v2 sintético con marker + paquete.json + clips done/error."""
    d = paquetes / dirname
    d.mkdir(parents=True, exist_ok=True)
    if marker is True:
        (d / "auto_v2.json").write_text(
            json.dumps({"config_fingerprint": fp, "pipeline_mode": "v2"}), encoding="utf-8"
        )
    elif isinstance(marker, str):
        (d / "auto_v2.json").write_text(marker, encoding="utf-8")  # marker corrupto
    clips_info = []
    for i, st in enumerate(states, 1):
        final = _final_name(f"c{i}.mp4")
        if st == "done":
            (d / final).write_bytes(b"final-" + final.encode())
            (d / (Path(final).stem + ".info.json")).write_text(
                json.dumps({"archivo": final, "clip_id": f"c{i}"}), encoding="utf-8"
            )
            clips_info.append({"archivo": final, "clip_id": f"c{i}", "caption_source": "srt"})
        else:
            clips_info.append(
                {"archivo": final, "clip_id": f"c{i}", "caption_source": "srt", "status": "error"}
            )
    (d / "paquete.json").write_text(json.dumps({"clips": clips_info, "meta": {}}), encoding="utf-8")
    return d


@pytest.fixture
def paq(tmp_path, monkeypatch):
    p = tmp_path / "paquetes"
    p.mkdir()
    monkeypatch.setattr(auto, "PAQUETES_DIR", p)
    return p


def test_fingerprint_distinto_no_reutiliza(paq):
    """11: un paquete parcial con otro fingerprint NO se reutiliza -> paquete nuevo."""
    _mk_v2_pkg(paq, "demo", "fp-A", "demo_v2_20260720-1200", ["done", "error", "done"])
    d, reanudado = auto._paquete_dir_v2("demo", "fp-B", allow_completed_partial_resume=True)
    assert reanudado is False and d.name != "demo_v2_20260720-1200"


def test_video_distinto_no_reutiliza(paq):
    """12: un paquete de otro video lógico (otro name) NO se reutiliza."""
    _mk_v2_pkg(paq, "otro", "fp-A", "otro_v2_20260720-1200", ["done", "error", "done"])
    d, reanudado = auto._paquete_dir_v2("demo", "fp-A", allow_completed_partial_resume=True)
    assert reanudado is False and d.name.startswith("demo_v2_")


def test_classic_no_se_reutiliza_como_srt(paq):
    """13: un paquete clásico ({name}_{fecha}, sin _v2_) jamás se reutiliza como SRT/v2."""
    (paq / "demo_20260720-1200").mkdir()
    (paq / "demo_20260720-1200" / "paquete.json").write_text(
        json.dumps({"clips": [{"archivo": "x", "status": "error"}], "meta": {}}), encoding="utf-8"
    )
    d, reanudado = auto._paquete_dir_v2("demo", "fp-A", allow_completed_partial_resume=True)
    assert reanudado is False and d.name.startswith("demo_v2_")


def test_v2_transcript_conserva_comportamiento_historico(paq):
    """14: sin allow_completed_partial (v2 transcript) un paquete completado NO se reabre."""
    _mk_v2_pkg(paq, "demo", "fp-A", "demo_v2_20260720-1200", ["done", "error", "done"])
    d, reanudado = auto._paquete_dir_v2("demo", "fp-A")  # default: allow=False
    assert reanudado is False and d.name != "demo_v2_20260720-1200"


def test_marker_corrupto_no_se_reutiliza(paq):
    """15: un paquete con auto_v2.json corrupto no se reutiliza ni provoca crash."""
    _mk_v2_pkg(
        paq,
        "demo",
        "fp-A",
        "demo_v2_20260720-1200",
        ["done", "error", "done"],
        marker="{marker roto no json",
    )
    d, reanudado = auto._paquete_dir_v2("demo", "fp-A", allow_completed_partial_resume=True)
    assert reanudado is False and d.name != "demo_v2_20260720-1200"


def test_paquete_json_corrupto_no_se_reutiliza(paq):
    """16: paquete.json corrupto -> no se reutiliza como parcial completado (fail-closed)."""
    d0 = _mk_v2_pkg(paq, "demo", "fp-A", "demo_v2_20260720-1200", ["done", "error", "done"])
    (d0 / "paquete.json").write_text("{clips roto no json", encoding="utf-8")
    d, reanudado = auto._paquete_dir_v2("demo", "fp-A", allow_completed_partial_resume=True)
    assert reanudado is False and d.name != "demo_v2_20260720-1200"


def test_entre_dos_parciales_elige_el_mas_reciente(paq):
    """17: con dos paquetes parciales compatibles se reanuda el MÁS RECIENTE."""
    _mk_v2_pkg(paq, "demo", "fp-A", "demo_v2_20260720-1200", ["done", "error", "done"])
    _mk_v2_pkg(paq, "demo", "fp-A", "demo_v2_20260720-1300", ["error", "done", "done"])
    d, reanudado = auto._paquete_dir_v2("demo", "fp-A", allow_completed_partial_resume=True)
    assert reanudado is True and d.name == "demo_v2_20260720-1300"


def test_paquete_completamente_exitoso_no_es_parcial(paq):
    """10-bis (unit): un paquete done=3/error=0 no se trata como parcial reanudable."""
    _mk_v2_pkg(paq, "demo", "fp-A", "demo_v2_20260720-1200", ["done", "done", "done"])
    d, reanudado = auto._paquete_dir_v2("demo", "fp-A", allow_completed_partial_resume=True)
    assert reanudado is False and d.name != "demo_v2_20260720-1200"


def test_done_con_output_faltante_es_reanudable(paq):
    """6-bis (unit): un clip 'done' con MP4 borrado marca el paquete como parcial reanudable."""
    d0 = _mk_v2_pkg(paq, "demo", "fp-A", "demo_v2_20260720-1200", ["done", "done", "done"])
    next(d0.glob("*_hormozi.mp4")).unlink()  # output faltante
    d, reanudado = auto._paquete_dir_v2("demo", "fp-A", allow_completed_partial_resume=True)
    assert reanudado is True and d == d0


# ─── Contrato UI: el botón "Reanudar clips fallidos" reusa el MISMO flujo Auto ────────────────
def test_contrato_ui_resume_reusa_paquete_con_config_del_backend(srt_env):
    """El flujo REAL del botón (construir_auto_config del backend, mismo video/config) reutiliza el
    paquete parcial y su run_id SIN borrar paquete.json ni crear otro package_id."""
    import studio_auto

    def _cfg():  # exactamente lo que arma /api/videos/{name}/auto con caption_source=srt
        return studio_auto.construir_auto_config(
            mode="classic",
            broll_enabled=True,
            fx_enabled=True,
            fx_preset="express",
            caption_source="srt",
        )

    srt_env["state"]["fail"] = {"clip2"}
    rB = auto.ejecutar_auto(srt_env["video"], "demo", config=_cfg())
    paquete = _paquete_dir(srt_env, rB)
    assert (paquete / "paquete.json").exists()  # el backend NO borra paquete.json para reanudar
    srt_env["state"]["fail"] = set()
    srt_env["state"]["burns"].clear()
    rC = auto.ejecutar_auto(
        srt_env["video"], "demo", config=_cfg()
    )  # el botón re-invoca el mismo flujo
    assert _paquete_dir(srt_env, rC) == paquete  # mismo package_id
    assert _manifiesto(srt_env, rC)["run_id"] == _manifiesto(srt_env, rB)["run_id"]
    assert _manifiesto(srt_env, rC)["summary"] == {"total": 3, "done": 3, "error": 0}
    assert len(srt_env["state"]["burns"]) == 1  # solo el fallido se reprocesó


def test_contrato_ui_boton_reanudar_no_usa_endpoint_dedicado():
    """El botón 'Reanudar clips fallidos' llama startAuto() (mismo flujo); no hay endpoint retry
    dedicado ni borrado de paquete.json en el cliente."""
    html = (Path(auto.__file__).parent / "static" / "index.html").read_text(encoding="utf-8")
    # El botón dispara startAuto() (mismo flujo Auto), no un endpoint/handler dedicado de retry.
    assert 'onclick="startAuto()">Reanudar clips fallidos' in html
    assert "/retry" not in html  # sin endpoint dedicado de retry en v1
    assert "paquete.json" not in html  # el cliente nunca manipula/borra el paquete.json
