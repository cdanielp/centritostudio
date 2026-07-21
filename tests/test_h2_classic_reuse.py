"""test_h2_classic_reuse.py — Reuso classic de transcript/clips en Auto (H2 + fixes de Codex).

Cubre:
  - `_transcript_reutilizable`: reutiliza tanto la procedencia `auto_classic_provenance` como el
    `source_video` que escribe el transcriptor de UI (`jobs.run_transcribe`), sin retranscribir el
    flujo comun Transcribir->Auto; fail-closed si es de otro video o sin procedencia.
  - `_asegurar_clips`: en ERROR del clipper NO sella procedencia (no reutiliza un clips.json stale
    de otro video con el mismo stem); en EXITO deja clips.json + sidecar CONSISTENTES y reutiliza.
Fixtures sinteticos en tmp_path, sin FFmpeg ni red.
"""

from __future__ import annotations

import auto
import transcript_provenance as tp


def _video(tmp_path, name="vid.mp4", data=b"abcdef"):
    v = tmp_path / name
    v.write_bytes(data)
    return v


# ── _transcript_reutilizable ──────────────────────────────────────────────────
def test_reutiliza_procedencia_classic(tmp_path):
    import auto_classic_provenance as acp

    v = _video(tmp_path)
    raw = {
        "words": [{"w": "h"}],
        "language": "es",
        "auto_classic_provenance": acp.build_provenance(v, lang="es", model="auto"),
    }
    assert auto._transcript_reutilizable(raw, v, "es") is True


def test_reutiliza_source_video_del_transcriptor_ui(tmp_path):
    # Flujo Transcribir(Studio)->Auto: jobs.run_transcribe escribe `source_video`, no la classic.
    v = _video(tmp_path)
    raw = tp.attach_video_provenance({"words": [{"w": "h"}], "language": "es"}, v)
    assert "source_video" in raw and "auto_classic_provenance" not in raw
    assert auto._transcript_reutilizable(raw, v, "es") is True


def test_source_video_de_otro_video_no_se_reutiliza(tmp_path):
    v = _video(tmp_path)
    raw = tp.attach_video_provenance({"words": [], "language": "es"}, v)
    v.write_bytes(b"abcdef-DISTINTO")  # cambia size/mtime -> ya no corresponde
    assert auto._transcript_reutilizable(raw, v, "es") is False


def test_sin_procedencia_no_se_reutiliza(tmp_path):
    v = _video(tmp_path)
    assert auto._transcript_reutilizable({"words": [], "language": "es"}, v, "es") is False


# ── _asegurar_clips (fix Codex: sellar solo tras exito) ───────────────────────
def test_clips_error_no_sella_procedencia(tmp_path, monkeypatch):
    import clipper

    monkeypatch.setattr(auto, "CLIPS_DIR", tmp_path)
    v = _video(tmp_path)
    monkeypatch.setattr(clipper, "generar_clips", lambda *a, **k: {"error": "sin API key"})
    resultado, reutilizado = auto._asegurar_clips(v, [], "vid")
    assert resultado.get("error") and reutilizado is False
    # En error NO se sella procedencia -> un clips.json stale no se reutilizaria despues.
    assert not (tmp_path / "vid_clips.provenance.json").exists()


def test_clips_exito_sella_y_luego_reutiliza(tmp_path, monkeypatch):
    import clipper

    monkeypatch.setattr(auto, "CLIPS_DIR", tmp_path)
    v = _video(tmp_path)
    llamadas = []

    def _fake(*_a, **_k):
        llamadas.append(1)
        return {"clips": [{"archivo": "vid_c1.mp4"}], "casi": []}

    monkeypatch.setattr(clipper, "generar_clips", _fake)
    _r1, reuse1 = auto._asegurar_clips(v, [], "vid")
    assert reuse1 is False
    assert (tmp_path / "vid_clips.json").exists() and (
        tmp_path / "vid_clips.provenance.json"
    ).exists()
    # Segunda corrida del MISMO video: reutiliza (no vuelve a llamar al clipper).
    _r2, reuse2 = auto._asegurar_clips(v, [], "vid")
    assert reuse2 is True and len(llamadas) == 1


def test_clips_video_distinto_mismo_stem_no_reutiliza(tmp_path, monkeypatch):
    import clipper

    monkeypatch.setattr(auto, "CLIPS_DIR", tmp_path)
    v = _video(tmp_path)
    monkeypatch.setattr(clipper, "generar_clips", lambda *a, **k: {"clips": [], "casi": []})
    auto._asegurar_clips(v, [], "vid")
    v.write_bytes(b"OTRO-VIDEO-MISMO-STEM")  # cambia size/mtime
    _r, reuse = auto._asegurar_clips(v, [], "vid")
    assert reuse is False  # procedencia no coincide -> re-ejecuta el clipper
