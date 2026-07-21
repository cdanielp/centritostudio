"""test_h2_classic_provenance.py — Procedencia explicita del Auto classic (H2, P2-CLASSIC-REUSE).

`auto_classic_provenance.matches` es fail-closed: mismo video EXACTO (filename+size+mtime) + mismo
lang/model -> reutiliza; distinto tamano/mtime/filename, procedencia ausente/corrupta o lang/model
distintos -> no reutiliza. Fixtures sinteticos en tmp_path, sin FFmpeg ni red.
"""

from __future__ import annotations

import auto_classic_provenance as acp


def _video(tmp_path, name="vid.mp4", data=b"abcdef"):
    v = tmp_path / name
    v.write_bytes(data)
    return v


def test_misma_fuente_reutiliza(tmp_path):
    v = _video(tmp_path)
    prov = acp.build_provenance(v, lang="es", model="auto")
    assert acp.matches(prov, v, lang="es", model="auto") is True


def test_mismo_stem_distinto_tamano_no_reutiliza(tmp_path):
    v = _video(tmp_path, data=b"abcdef")
    prov = acp.build_provenance(v, lang="es", model="auto")
    v.write_bytes(b"abcdefGHIJKL")  # mismo nombre, distinto tamano (y mtime)
    assert acp.matches(prov, v, lang="es", model="auto") is False


def test_mismo_stem_distinto_mtime_no_reutiliza(tmp_path):
    import os

    v = _video(tmp_path)
    prov = acp.build_provenance(v, lang="es", model="auto")
    st = v.stat()
    os.utime(v, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))  # solo cambia mtime
    assert acp.matches(prov, v, lang="es", model="auto") is False


def test_filename_distinto_no_reutiliza(tmp_path):
    v = _video(tmp_path, name="vid.mp4")
    prov = acp.build_provenance(v, lang="es", model="auto")
    otro = _video(tmp_path, name="otro.mp4", data=b"abcdef")
    assert acp.matches(prov, otro, lang="es", model="auto") is False


def test_lang_distinto_no_reutiliza(tmp_path):
    v = _video(tmp_path)
    prov = acp.build_provenance(v, lang="es", model="auto")
    assert acp.matches(prov, v, lang="en", model="auto") is False


def test_model_distinto_no_reutiliza(tmp_path):
    v = _video(tmp_path)
    prov = acp.build_provenance(v, lang="es", model="auto")
    assert acp.matches(prov, v, lang="es", model="medium") is False


def test_procedencia_ausente_fail_closed(tmp_path):
    v = _video(tmp_path)
    assert acp.matches(None, v, lang="es", model="auto") is False
    assert acp.matches({}, v, lang="es", model="auto") is False


def test_pipeline_mode_ajeno_fail_closed(tmp_path):
    v = _video(tmp_path)
    prov = acp.build_provenance(v, lang="es", model="auto")
    prov["pipeline_mode"] = "v2"
    assert acp.matches(prov, v, lang="es", model="auto") is False


def test_schema_version_invalida_fail_closed(tmp_path):
    v = _video(tmp_path)
    prov = acp.build_provenance(v, lang="es", model="auto")
    prov["schema_version"] = 999
    assert acp.matches(prov, v, lang="es", model="auto") is False
    prov["schema_version"] = True  # bool no cuenta como int
    assert acp.matches(prov, v, lang="es", model="auto") is False


def test_video_ausente_fail_closed(tmp_path):
    v = _video(tmp_path)
    prov = acp.build_provenance(v, lang="es", model="auto")
    v.unlink()  # el video esperado ya no existe
    assert acp.matches(prov, v, lang="es", model="auto") is False


def test_valores_no_enteros_fail_closed(tmp_path):
    v = _video(tmp_path)
    prov = acp.build_provenance(v, lang="es", model="auto")
    prov["size_bytes"] = "6"  # str en vez de int
    assert acp.matches(prov, v, lang="es", model="auto") is False
