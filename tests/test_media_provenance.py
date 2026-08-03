"""Procedencia video <-> words json (P1, tras tres rondas de revision visual perdidas).

El agujero real: `{stem}_limpio_words.json` son los timings del video DEPURADO
(`output/{stem}_limpio.mp4`), pero se quemaron sobre el video ORIGINAL (`input/{stem}.mp4`).
Son dos timelines: el depurador quita silencios repartidos, asi que el desfase CRECE (0 -> 122 s
en el material real). Nada aviso, y el error solo se ve comparando el audio con los captions.

Contrato:
  * al transcribir, el words json registra su fuente (ruta relativa, sha256, duracion, fps);
  * los words json existentes SIN ese campo siguen validos como procedencia desconocida;
  * con procedencia y sha256 distinto -> ERROR, se detiene;
  * sin procedencia -> se compara la duracion del video contra el ultimo `word.end`; mas de 2 s
    de diferencia -> ERROR indicando cuantos segundos difieren y cual seria el archivo esperado.

Nunca un aviso silencioso.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import media_provenance as mp

ROOT = Path(__file__).resolve().parents[1]


# ── Fixtures sinteticos ──────────────────────────────────────────────────────


def _video(tmp_path: Path, nombre: str, contenido: bytes = b"video-sintetico") -> Path:
    p = tmp_path / nombre
    p.write_bytes(contenido)
    return p


def _words(fin_s: float, fingerprint: dict | None = None) -> dict:
    d = {
        "words": [
            {"w": "hola", "s": 0.0, "e": 0.5, "prob": 1.0},
            {"w": "final", "s": fin_s - 0.4, "e": fin_s, "prob": 1.0},
        ],
        "language": "es",
    }
    if fingerprint is not None:
        d["source_media"] = fingerprint
    return d


# ── Productor ────────────────────────────────────────────────────────────────


def test_fingerprint_registra_los_cuatro_datos(tmp_path):
    v = _video(tmp_path, "demo.mp4")
    fp = mp.build_media_fingerprint(v, duration_s=12.5, fps=30.0, root=tmp_path)
    assert fp["version"] == mp.FINGERPRINT_VERSION
    assert fp["relpath"] == "demo.mp4"
    assert fp["duration_ms"] == 12500
    assert fp["fps"] == 30.0
    assert len(fp["sha256"]) == 64


def test_relpath_es_relativa_a_la_raiz(tmp_path):
    (tmp_path / "input").mkdir()
    v = _video(tmp_path / "input", "demo.mp4")
    fp = mp.build_media_fingerprint(v, duration_s=1.0, fps=24.0, root=tmp_path)
    assert fp["relpath"] == "input/demo.mp4", "siempre POSIX, nunca ruta absoluta"


def test_attach_no_muta_el_transcript(tmp_path):
    v = _video(tmp_path, "demo.mp4")
    original = _words(10.0)
    copia = json.loads(json.dumps(original))
    nuevo = mp.attach_media_fingerprint(original, v, duration_s=10.0, fps=24.0, root=tmp_path)
    assert original == copia
    assert "source_media" in nuevo and "source_media" not in original


# ── Validador: con procedencia ───────────────────────────────────────────────


def test_sha_coincide_pasa(tmp_path):
    v = _video(tmp_path, "demo.mp4")
    fp = mp.build_media_fingerprint(v, duration_s=10.0, fps=24.0, root=tmp_path)
    mp.verificar_transcript_contra_video(_words(10.0, fp), v, video_duration_s=10.0)


def test_sha_distinto_es_error_y_se_detiene(tmp_path):
    v1 = _video(tmp_path, "uno.mp4", b"contenido-A")
    v2 = _video(tmp_path, "dos.mp4", b"contenido-B-distinto")
    fp = mp.build_media_fingerprint(v1, duration_s=10.0, fps=24.0, root=tmp_path)
    with pytest.raises(mp.ProcedenciaError) as e:
        mp.verificar_transcript_contra_video(_words(10.0, fp), v2, video_duration_s=10.0)
    assert "uno.mp4" in str(e.value), "el error dice de que video SON los timings"
    assert "dos.mp4" in str(e.value), "y contra cual se estaba usando"


def test_fingerprint_corrupto_no_se_ignora_en_silencio(tmp_path):
    v = _video(tmp_path, "demo.mp4")
    for roto in ({"version": 1}, {"version": 99, "sha256": "x" * 64}, "no-es-dict"):
        with pytest.raises(mp.ProcedenciaError):
            mp.verificar_transcript_contra_video(_words(10.0, roto), v, video_duration_s=10.0)


# ── Validador: sin procedencia (words legacy) ────────────────────────────────


def test_sin_procedencia_con_duracion_coherente_pasa(tmp_path):
    """Los words json existentes siguen validos: procedencia desconocida, no invalida."""
    v = _video(tmp_path, "demo.mp4")
    mp.verificar_transcript_contra_video(_words(100.0), v, video_duration_s=101.5)


def test_sin_procedencia_dentro_de_la_tolerancia_pasa(tmp_path):
    v = _video(tmp_path, "demo.mp4")
    mp.verificar_transcript_contra_video(_words(100.0), v, video_duration_s=102.0)


def test_sin_procedencia_fuera_de_tolerancia_es_error(tmp_path):
    v = _video(tmp_path, "demo.mp4")
    with pytest.raises(mp.ProcedenciaError) as e:
        mp.verificar_transcript_contra_video(_words(100.0), v, video_duration_s=222.0)
    msg = str(e.value)
    assert "122" in msg, f"debe decir cuantos segundos difieren: {msg}"


def test_tolerancia_configurable(tmp_path):
    v = _video(tmp_path, "demo.mp4")
    mp.verificar_transcript_contra_video(
        _words(100.0), v, video_duration_s=110.0, tolerancia_s=15.0
    )
    with pytest.raises(mp.ProcedenciaError):
        mp.verificar_transcript_contra_video(
            _words(100.0), v, video_duration_s=110.0, tolerancia_s=5.0
        )


def test_el_error_propone_el_archivo_esperado(tmp_path):
    """El caso real: los words son del depurado y el video esperado esta en output/."""
    (tmp_path / "input").mkdir()
    (tmp_path / "output").mkdir()
    original = _video(tmp_path / "input", "clase.mp4")
    _video(tmp_path / "output", "clase_limpio.mp4")
    words_path = tmp_path / "transcripts" / "clase_limpio_words.json"
    words_path.parent.mkdir()
    words_path.write_text(json.dumps(_words(100.0)), encoding="utf-8")

    with pytest.raises(mp.ProcedenciaError) as e:
        mp.verificar_transcript_contra_video(
            _words(100.0), original, video_duration_s=222.0, words_path=words_path, root=tmp_path
        )
    msg = str(e.value)
    assert "clase_limpio.mp4" in msg, f"debe nombrar el archivo esperado: {msg}"
    assert "output/" in msg, f"y donde esta: {msg}"


def test_sin_candidato_el_error_sigue_siendo_claro(tmp_path):
    v = _video(tmp_path, "demo.mp4")
    with pytest.raises(mp.ProcedenciaError) as e:
        mp.verificar_transcript_contra_video(_words(10.0), v, video_duration_s=99.0)
    assert "89" in str(e.value)


def test_transcript_vacio_no_revienta(tmp_path):
    v = _video(tmp_path, "demo.mp4")
    with pytest.raises(mp.ProcedenciaError):
        mp.verificar_transcript_contra_video({"words": []}, v, video_duration_s=10.0)


# ── El caso REAL, sobre el material del repo (se salta si no esta) ───────────


def _par_real():
    """Cualquier `{stem}_limpio_words.json` cuyo video ORIGINAL exista en input/.

    Se descubre en disco en vez de escribir el nombre: el gate de privacidad prohibe
    versionar rutas de material del usuario, y ademas asi el test no se ata a un archivo.
    """
    trans = ROOT / "transcripts"
    if not trans.is_dir():
        return None, None
    for wp in sorted(trans.glob("*_limpio_words.json")):
        base = wp.name[: -len("_limpio_words.json")]
        for ext in (".mp4", ".mov"):
            vid = ROOT / "input" / f"{base}{ext}"
            if vid.is_file():
                return wp, vid
    return None, None


_WP, _VID = _par_real()


@pytest.mark.skipif(_WP is None, reason="material real no disponible (CI / repo limpio)")
def test_caso_real_words_del_depurado_contra_el_video_original():
    """Reproduce el fallo que costo tres rondas: debe ERROR, no aviso."""
    import core

    transcript = json.loads(_WP.read_text(encoding="utf-8"))
    dur = core.get_video_info(_VID)["duration"]
    with pytest.raises(mp.ProcedenciaError) as e:
        mp.verificar_transcript_contra_video(
            transcript, _VID, video_duration_s=dur, words_path=_WP, root=ROOT
        )
    msg = str(e.value)
    assert "difieren" in msg
    assert "_limpio" in msg, f"debe proponer el depurado como archivo esperado: {msg}"


# ── El guard cableado en el worker de render ─────────────────────────────────


def test_worker_de_render_corta_con_timings_ajenos(tmp_path, monkeypatch):
    """El render debe quedar en `error`, no producir un MP4 desincronizado."""
    import core
    import jobs_registry
    import jobs_render

    trans = tmp_path / "transcripts"
    out = tmp_path / "output"
    trans.mkdir()
    out.mkdir()
    monkeypatch.setattr(jobs_render, "TRANSCRIPTS", trans)
    monkeypatch.setattr(jobs_render, "OUTPUT_DIR", out)
    monkeypatch.setattr(jobs_render, "ROOT", tmp_path)
    (trans / "demo_groups.json").write_text(
        json.dumps([{"id": 0, "start": 0.0, "end": 1.0, "words": [], "text": ""}]), encoding="utf-8"
    )
    # Timings que acaban en 10 s contra un video de 300 s: otro timeline.
    (trans / "demo_words.json").write_text(json.dumps(_words(10.0)), encoding="utf-8")
    monkeypatch.setattr(
        core, "get_video_info", lambda _p: {"width": 1080, "height": 1920, "duration": 300.0}
    )
    monkeypatch.setattr(core, "build_ass", lambda *a, **k: None)
    monkeypatch.setattr(core, "burn_video", lambda *a, **k: pytest.fail("no debe quemar"))

    jid = jobs_registry.new_job("render demo")
    jobs_render.run_render(
        jid, out / "demo.mp4", trans / "demo_groups.json", "demo", "hormozi", None
    )
    job = jobs_registry.get_job(jid)
    assert job["status"] == "error"
    assert "difieren" in job["message"], f"el motivo debe ser explicito: {job['message']}"


def test_worker_de_render_pasa_con_timings_coherentes(tmp_path, monkeypatch):
    import core
    import jobs_registry
    import jobs_render

    trans = tmp_path / "transcripts"
    out = tmp_path / "output"
    trans.mkdir()
    out.mkdir()
    monkeypatch.setattr(jobs_render, "TRANSCRIPTS", trans)
    monkeypatch.setattr(jobs_render, "OUTPUT_DIR", out)
    monkeypatch.setattr(jobs_render, "ROOT", tmp_path)
    (trans / "demo_groups.json").write_text(
        json.dumps([{"id": 0, "start": 0.0, "end": 1.0, "words": [], "text": ""}]), encoding="utf-8"
    )
    (trans / "demo_words.json").write_text(json.dumps(_words(299.0)), encoding="utf-8")
    monkeypatch.setattr(
        core, "get_video_info", lambda _p: {"width": 1080, "height": 1920, "duration": 300.0}
    )
    monkeypatch.setattr(core, "build_ass", lambda *a, **k: None)
    monkeypatch.setattr(core, "burn_video", lambda *a, **k: 1.0)

    jid = jobs_registry.new_job("render demo")
    jobs_render.run_render(
        jid, out / "demo.mp4", trans / "demo_groups.json", "demo", "hormozi", None
    )
    assert jobs_registry.get_job(jid)["status"] == "done"
