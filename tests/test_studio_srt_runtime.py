"""test_studio_srt_runtime.py — Runtime privado de la seleccion SRT para render (S36-C2A1, D38).

Sin red, sin GPU, sin FFmpeg, sin Auto. Cubre resolucion de la seleccion activa, integridad
en tiempo de uso (no confia solo en el manifiesto), carga de timings, preparacion de groups
reutilizando S36-B, sidecar, resumen publico saneado y no-mutacion. Todo en tmp_path; jamas
usa el SRT privado del usuario.
"""

from __future__ import annotations

import hashlib
import json

import pytest

import studio_srt
import studio_srt_runtime as rt


def _ts(ms: int) -> str:
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _srt(*cues: tuple[int, int, int, str]) -> bytes:
    blocks = [f"{i}\n{_ts(s)} --> {_ts(e)}\n{t}\n" for i, s, e, t in cues]
    return "\n".join(blocks).encode("utf-8")


# SRT con 1 cue word_aligned ("Hola mundo") + 1 cue sin audio -> cue_fallback.
_SRT_MIX = _srt((1, 0, 2000, "Hola mundo"), (2, 3000, 5000, "Texto sin audio"))
_DUR = 6000


def _words(*triples) -> dict:
    return {
        "words": [{"w": w, "s": s, "e": e, "prob": 1.0} for (w, s, e) in triples],
        "language": "es",
    }


_WORDS_MIX = _words(("hola", 0.0, 0.5), ("mundo", 0.6, 1.0))


def _paths(tmp_path):
    storage = tmp_path / "studio_srt"
    manifests = tmp_path / "transcripts"
    manifests.mkdir(exist_ok=True)
    return storage, manifests


def _associate(tmp_path, data=_SRT_MIX, stem="demo", dur=_DUR):
    """Asocia un SRT usando el backend real de C1. Devuelve (storage, manifests)."""
    storage, manifests = _paths(tmp_path)
    doc, diags = studio_srt.parse_and_validate(data, source_name="subs.srt", video_duration_ms=dur)
    studio_srt.store_and_associate(
        doc,
        diags,
        video_stem=stem,
        video_filename=f"{stem}.mp4",
        video_duration_ms=dur,
        data=data,
        storage_root=storage,
        manifest_dir=manifests,
    )
    return storage, manifests


def _write_words(manifests, words=_WORDS_MIX, stem="demo"):
    (manifests / f"{stem}_words.json").write_text(json.dumps(words), encoding="utf-8")


def _manifest_file(manifests, stem="demo"):
    return manifests / f"{stem}_srt_selection.json"


def _tamper(manifests, mutator, stem="demo"):
    p = _manifest_file(manifests, stem)
    d = json.loads(p.read_text(encoding="utf-8"))
    mutator(d)
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def _resolve(storage, manifests, stem="demo"):
    return rt.resolve_selected_srt(stem, storage_root=storage, manifest_dir=manifests)


# ─── Resolucion e integridad ───────────────────────────────────────────────────
def test_seleccion_none_sin_manifiesto(tmp_path):
    storage, manifests = _paths(tmp_path)
    assert _resolve(storage, manifests) is None


def test_seleccion_valida(tmp_path):
    storage, manifests = _associate(tmp_path)
    sel = _resolve(storage, manifests)
    assert sel is not None
    assert sel.video_stem == "demo"
    assert sel.source_sha256 == hashlib.sha256(_SRT_MIX).hexdigest()
    assert sel.managed_file == f"{sel.source_sha256}.srt"
    assert sel.managed_path.is_file()


def test_hash_real_coincide(tmp_path):
    storage, manifests = _associate(tmp_path)
    sel = _resolve(storage, manifests)
    assert hashlib.sha256(sel.managed_path.read_bytes()).hexdigest() == sel.source_sha256


def test_archivo_administrado_faltante(tmp_path):
    storage, manifests = _associate(tmp_path)
    sha = hashlib.sha256(_SRT_MIX).hexdigest()
    (storage / "demo" / f"{sha}.srt").unlink()
    with pytest.raises(rt.StudioSrtIntegrityError):
        _resolve(storage, manifests)


def test_archivo_administrado_corrupto(tmp_path):
    storage, manifests = _associate(tmp_path)
    sha = hashlib.sha256(_SRT_MIX).hexdigest()
    (storage / "demo" / f"{sha}.srt").write_bytes(b"otro contenido distinto")
    with pytest.raises(rt.StudioSrtIntegrityError):
        _resolve(storage, manifests)


def test_managed_file_basename_inseguro(tmp_path):
    # managed_file que viola el contrato C1 lo rechaza el saneamiento del manifiesto
    # (read_selection) con StudioSrtStorageError, antes de tocar el storage. Nunca se sirve.
    storage, manifests = _associate(tmp_path)
    _tamper(manifests, lambda d: d["selection"].update(managed_file="../fuera.srt"))
    with pytest.raises(studio_srt.StudioSrtStorageError):
        _resolve(storage, manifests)


def test_manifiesto_sha_distinto_al_managed(tmp_path):
    storage, manifests = _associate(tmp_path)
    # managed_file debe ser exactamente {source_sha256}.srt; un sha256 valido pero distinto rompe.
    otro = "a" * 64
    _tamper(
        manifests,
        lambda d: d["selection"].update(source_sha256=otro, managed_file=f"{otro}.srt"),
    )
    with pytest.raises(rt.StudioSrtIntegrityError):
        _resolve(storage, manifests)


def test_manifiesto_corrupto_propaga_storage_error(tmp_path):
    storage, manifests = _associate(tmp_path)
    _tamper(manifests, lambda d: d["summary"].update(end_ms=d["summary"]["start_ms"]))
    with pytest.raises(studio_srt.StudioSrtStorageError):
        _resolve(storage, manifests)


def test_confinamiento_rechaza_escape_del_root(tmp_path):
    # Defensa en profundidad: aunque managed_file ya se valida como basename seguro, el
    # confinamiento por resolve()+relative_to() rechaza cualquier ruta que escape del storage.
    with pytest.raises(rt.StudioSrtIntegrityError):
        rt._managed_path_confinada(tmp_path / "studio_srt", "demo", "../../escape.srt")


def test_verify_runtime_integrity_detecta_borrado(tmp_path):
    storage, manifests = _associate(tmp_path)
    sel = _resolve(storage, manifests)
    rt.verify_runtime_integrity(sel)  # ok
    sel.managed_path.unlink()
    with pytest.raises(rt.StudioSrtIntegrityError):
        rt.verify_runtime_integrity(sel)


# ─── Timings (words.json) ──────────────────────────────────────────────────────
def _prepare(tmp_path, words=_WORDS_MIX, srt=_SRT_MIX, dur=_DUR):
    storage, manifests = _associate(tmp_path, data=srt, dur=dur)
    if words is not None:
        (manifests / "demo_words.json").write_text(json.dumps(words), encoding="utf-8")
    sel = _resolve(storage, manifests)
    return (
        sel,
        rt.prepare_selected_srt_groups(
            sel,
            words_path=manifests / "demo_words.json",
            video_duration_ms=dur,
            alignment_sidecar_path=manifests / "demo_srt_alignment.json",
        ),
        manifests,
    )


def test_words_inexistentes(tmp_path):
    storage, manifests = _associate(tmp_path)
    sel = _resolve(storage, manifests)
    with pytest.raises(rt.StudioSrtTimingMissing):
        rt.prepare_selected_srt_groups(
            sel,
            words_path=manifests / "demo_words.json",
            video_duration_ms=_DUR,
            alignment_sidecar_path=manifests / "demo_srt_alignment.json",
        )


@pytest.mark.parametrize(
    "content",
    [
        "{no es json",
        json.dumps(["no", "dict"]),
        json.dumps({"words": "no-lista"}),
        json.dumps({"words": []}),
    ],
)
def test_words_invalidas_o_vacias(tmp_path, content):
    storage, manifests = _associate(tmp_path)
    sel = _resolve(storage, manifests)
    (manifests / "demo_words.json").write_text(content, encoding="utf-8")
    with pytest.raises(rt.StudioSrtTimingMissing):
        rt.prepare_selected_srt_groups(
            sel,
            words_path=manifests / "demo_words.json",
            video_duration_ms=_DUR,
            alignment_sidecar_path=manifests / "demo_srt_alignment.json",
        )


# ─── Preparacion de groups ─────────────────────────────────────────────────────
def test_srt_valido_word_aligned_y_fallback(tmp_path):
    _sel, prepared, _m = _prepare(tmp_path)
    assert prepared.result.word_aligned == 1
    assert prepared.result.cue_fallback == 1
    modes = [g["timing_mode"] for g in prepared.groups]
    assert modes == ["word_aligned", "cue_fallback"]


def test_srt_con_warnings_no_aborta(tmp_path):
    # Cue despues del video -> warning (no error); el render sigue y n_warnings>=1.
    srt = _srt((1, 0, 2000, "Hola mundo"), (2, 20_000, 21_000, "Tarde"))
    _sel, prepared, _m = _prepare(tmp_path, srt=srt, dur=6000)
    assert prepared.summary["n_warnings"] >= 1


def test_error_estructural_se_traduce_a_runtime_error(tmp_path, monkeypatch):
    storage, manifests = _associate(tmp_path)
    _write_words(manifests)
    sel = _resolve(storage, manifests)
    import srt_caption
    from srt_import import SrtError

    def _boom(*_a, **_k):
        raise SrtError("estructural")

    monkeypatch.setattr(srt_caption, "preparar_desde_srt", _boom)
    with pytest.raises(rt.StudioSrtRuntimeError):
        rt.prepare_selected_srt_groups(
            sel,
            words_path=manifests / "demo_words.json",
            video_duration_ms=_DUR,
            alignment_sidecar_path=manifests / "demo_srt_alignment.json",
        )


def test_summary_consistente_y_saneado(tmp_path):
    sel, prepared, _m = _prepare(tmp_path)
    s = prepared.summary
    assert s["word_aligned"] + s["cue_fallback"] == s["n_cues"]
    assert s["source"] == "srt"
    assert s["source_sha256"] == sel.source_sha256
    assert s["alignment_sidecar"] == "demo_srt_alignment.json"
    # Sin cues, sin texto, sin rutas.
    assert "cues" not in s
    blob = json.dumps(s)
    assert "Hola" not in blob and "audio" not in blob
    assert str(tmp_path) not in blob


def test_sidecar_escrito_y_sin_rutas(tmp_path):
    _sel, _prepared, manifests = _prepare(tmp_path)
    sidecar = manifests / "demo_srt_alignment.json"
    assert sidecar.is_file()
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert data["summary"]["n_cues"] == 2
    # El sidecar es privado (transcripts/) pero no debe llevar rutas absolutas.
    assert str(tmp_path) not in sidecar.read_text(encoding="utf-8")


def test_groups_llevan_texto_oficial(tmp_path):
    _sel, prepared, _m = _prepare(tmp_path)
    assert prepared.groups[0]["text"] == "Hola mundo"  # texto del SRT, no del transcript


def test_no_muta_words_ni_srt(tmp_path):
    words = _words(("hola", 0.0, 0.5), ("mundo", 0.6, 1.0))
    snapshot = json.dumps(words)
    storage, manifests = _associate(tmp_path)
    (manifests / "demo_words.json").write_text(json.dumps(words), encoding="utf-8")
    sha_antes = hashlib.sha256(
        (storage / "demo" / f"{hashlib.sha256(_SRT_MIX).hexdigest()}.srt").read_bytes()
    ).hexdigest()
    sel = _resolve(storage, manifests)
    rt.prepare_selected_srt_groups(
        sel,
        words_path=manifests / "demo_words.json",
        video_duration_ms=_DUR,
        alignment_sidecar_path=manifests / "demo_srt_alignment.json",
    )
    # words en disco intactas; SRT administrado intacto (hash preservado).
    assert json.loads((manifests / "demo_words.json").read_text(encoding="utf-8")) == json.loads(
        snapshot
    )
    sha_despues = hashlib.sha256(
        (storage / "demo" / f"{hashlib.sha256(_SRT_MIX).hexdigest()}.srt").read_bytes()
    ).hexdigest()
    assert sha_antes == sha_despues == sel.source_sha256
