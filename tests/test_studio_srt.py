"""test_studio_srt.py — Contrato de dominio del administrador SRT de Studio (S36-C1, D37).

Sin red, sin GPU, sin FFmpeg. Cubre confinamiento de video, validacion de nombre,
parseo+validacion contra duracion, almacenamiento privado por hash, atomicidad,
idempotencia, reemplazo y desasociacion. Nunca toca transcripts/ reales: todo va a
tmp_path. El SRT real del usuario NO se usa aqui.
"""

from __future__ import annotations

import hashlib

import pytest

import studio_srt
from srt_types import WARN_CUE_AFTER_VIDEO


def _ts(ms: int) -> str:
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _srt(*cues: tuple[int, int, int, str]) -> bytes:
    blocks = [f"{i}\n{_ts(s)} --> {_ts(e)}\n{t}\n" for i, s, e, t in cues]
    return "\n".join(blocks).encode("utf-8")


_OK = _srt((1, 0, 1000, "uno"), (2, 1000, 2000, "dos"))
_DUR = 12_000


# ─── Confinamiento del video (resolver) ────────────────────────────────────────
def test_video_inexistente(tmp_path):
    assert studio_srt.resolver_video_input("nope", tmp_path) is None


def test_nombre_vacio(tmp_path):
    assert studio_srt.resolver_video_input("", tmp_path) is None


@pytest.mark.parametrize(
    "name",
    [
        "../secreto",
        "a/b",
        "a\\b",
        "sub/video",
        "..",
        "C:video",
        "C:\\video",
        "\\\\srv\\share\\v",
        "/etc/passwd",
    ],
)
def test_resolver_rechaza_traversal_windows_y_posix(tmp_path, name):
    (tmp_path / "video.mp4").write_bytes(b"x")
    assert studio_srt.resolver_video_input(name, tmp_path) is None


def test_resolver_acepta_basename_mp4_y_mov(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    (tmp_path / "b.MOV").write_bytes(b"x")
    assert studio_srt.resolver_video_input("a", tmp_path).name == "a.mp4"
    assert studio_srt.resolver_video_input("b", tmp_path).name == "b.MOV"


def test_resolver_symlink_fuera_de_input_se_rechaza(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "real.mp4").write_bytes(b"x")
    inp = tmp_path / "input"
    inp.mkdir()
    try:
        (inp / "link.mp4").symlink_to(outside / "real.mp4")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks no disponibles en este entorno")
    # El resolver confina por resolve()+relative_to: un symlink que escapa no resuelve dentro.
    resolved = studio_srt.resolver_video_input("link", inp)
    assert resolved is None or resolved.resolve().parent == inp.resolve()


# ─── Validacion del nombre del SRT ─────────────────────────────────────────────
@pytest.mark.parametrize("name", ["subs.srt", "SUBS.SRT", "Mi Archivo.Srt"])
def test_extension_srt_case_insensitive_valida(name):
    studio_srt.validate_srt_filename(name)  # no lanza


@pytest.mark.parametrize("name", ["", None, "subs.txt", "subs", "a/b.srt", "a\\b.srt", "../x.srt"])
def test_nombre_invalido_rechazado(name):
    with pytest.raises(studio_srt.StudioSrtUnsupported):
        studio_srt.validate_srt_filename(name)


# ─── Parseo + validacion ───────────────────────────────────────────────────────
def test_srt_utf8_valido():
    doc, diags = studio_srt.parse_and_validate(_OK, source_name="s.srt", video_duration_ms=_DUR)
    assert len(doc.cues) == 2
    assert not any(d.severity == "error" for d in diags)


def test_srt_utf8_bom_valido():
    data = b"\xef\xbb\xbf" + _OK
    doc, _ = studio_srt.parse_and_validate(data, source_name="s.srt", video_duration_ms=_DUR)
    assert len(doc.cues) == 2


def test_srt_cp1252_valido():
    data = "1\n00:00:00,000 --> 00:00:01,000\ncafé\n".encode("cp1252")
    doc, _ = studio_srt.parse_and_validate(data, source_name="s.srt", video_duration_ms=_DUR)
    assert doc.cues[0].text == "café"


def test_srt_malformado_rechazado():
    data = b"no soy un srt\nsolo texto suelto\n"
    with pytest.raises(studio_srt.StudioSrtInvalid):
        studio_srt.parse_and_validate(data, source_name="s.srt", video_duration_ms=_DUR)


def test_documento_vacio_rechazado():
    with pytest.raises(studio_srt.StudioSrtInvalid):
        studio_srt.parse_and_validate(b"", source_name="s.srt", video_duration_ms=_DUR)


def test_bloque_con_error_estructural_aborta():
    # segundo bloque con end<=start -> error estructural -> se descarta y aborta por error
    data = _srt((1, 0, 1000, "ok"), (2, 2000, 2000, "malo"))
    with pytest.raises(studio_srt.StudioSrtInvalid):
        studio_srt.parse_and_validate(data, source_name="s.srt", video_duration_ms=_DUR)


def test_warnings_no_abortan():
    # indices no consecutivos -> warning, no aborta
    data = _srt((1, 0, 1000, "uno"), (5, 1000, 2000, "dos"))
    doc, diags = studio_srt.parse_and_validate(data, source_name="s.srt", video_duration_ms=_DUR)
    assert len(doc.cues) == 2
    assert any(d.severity == "warning" for d in diags)


def test_cue_despues_del_video_produce_warning_pero_no_aborta():
    data = _srt((1, 0, 1000, "uno"), (2, 20_000, 21_000, "tarde"))
    doc, diags = studio_srt.parse_and_validate(data, source_name="s.srt", video_duration_ms=_DUR)
    assert len(doc.cues) == 2
    assert any(d.code == WARN_CUE_AFTER_VIDEO for d in diags)


def test_validacion_contra_duracion_none_no_falla():
    doc, _ = studio_srt.parse_and_validate(_OK, source_name="s.srt", video_duration_ms=None)
    assert len(doc.cues) == 2


def test_bytes_sobre_limite_rechazados():
    big = b"x" * (studio_srt.MAX_SRT_BYTES + 1)
    with pytest.raises(studio_srt.StudioSrtTooLarge):
        studio_srt.parse_and_validate(big, source_name="s.srt", video_duration_ms=_DUR)


def test_entrada_no_es_mutada():
    original = bytes(_OK)
    studio_srt.parse_and_validate(_OK, source_name="s.srt", video_duration_ms=_DUR)
    assert _OK == original


# ─── Almacenamiento y asociacion ───────────────────────────────────────────────
def _store(tmp_path, data=_OK, stem="video_demo"):
    storage = tmp_path / "studio_srt"
    manifests = tmp_path / "transcripts"
    manifests.mkdir(exist_ok=True)
    doc, diags = studio_srt.parse_and_validate(data, source_name="subs.srt", video_duration_ms=_DUR)
    manifest, created = studio_srt.store_and_associate(
        doc,
        diags,
        video_stem=stem,
        video_filename=f"{stem}.mp4",
        video_duration_ms=_DUR,
        data=data,
        storage_root=storage,
        manifest_dir=manifests,
    )
    return manifest, created, storage, manifests


def test_almacenamiento_por_hash_y_bytes_preservados(tmp_path):
    manifest, created, storage, _ = _store(tmp_path)
    assert created is True
    sha = hashlib.sha256(_OK).hexdigest()
    managed = storage / "video_demo" / f"{sha[:12]}.srt"
    assert managed.is_file()
    assert managed.read_bytes() == _OK  # bytes originales tal cual
    assert manifest["selection"]["source_sha256"] == sha
    assert manifest["selection"]["managed_file"] == f"{sha[:12]}.srt"


def test_managed_file_es_basename_seguro(tmp_path):
    manifest, *_ = _store(tmp_path)
    mf = manifest["selection"]["managed_file"]
    assert "/" not in mf and "\\" not in mf


def test_manifest_version_1_y_summary(tmp_path):
    manifest, *_ = _store(tmp_path)
    assert manifest["version"] == 1
    assert manifest["status"] == "ready"
    assert manifest["summary"]["n_cues"] == 2
    assert manifest["summary"]["n_errors"] == 0
    assert manifest["summary"]["start_ms"] == 0
    assert manifest["summary"]["end_ms"] == 2000
    assert manifest["video"]["duration_ms"] == _DUR


def test_manifest_no_expone_texto_ni_rutas(tmp_path):
    manifest, _, storage, manifests = _store(tmp_path)
    blob = str(manifest)
    assert "uno" not in blob and "dos" not in blob  # sin texto de cues
    assert str(tmp_path) not in blob  # sin rutas absolutas
    assert "managed_path" not in blob
    for d in manifest["diagnostics"]:
        assert set(d.keys()) == {"code", "severity", "cue_position", "cue_index"}


def test_no_quedan_tmp(tmp_path):
    _, _, storage, manifests = _store(tmp_path)
    assert not list(storage.rglob("*.tmp"))
    assert not list(manifests.rglob("*.tmp"))


def test_idempotencia_mismo_sha(tmp_path):
    _store(tmp_path)
    manifest2, created2, storage, _ = _store(tmp_path)
    assert created2 is False
    managed = list((storage / "video_demo").glob("*.srt"))
    assert len(managed) == 1  # no duplica


def test_nuevo_sha_reemplaza_y_conserva_anterior(tmp_path):
    _store(tmp_path)
    otro = _srt((1, 0, 1000, "otro"), (2, 1000, 3000, "contenido"))
    manifest2, created2, storage, _ = _store(tmp_path, data=otro)
    assert created2 is True
    sha_old = hashlib.sha256(_OK).hexdigest()
    sha_new = hashlib.sha256(otro).hexdigest()
    assert manifest2["selection"]["source_sha256"] == sha_new
    # la seleccion anterior no se borra: su archivo administrado sigue en disco
    assert (storage / "video_demo" / f"{sha_old[:12]}.srt").is_file()
    assert (storage / "video_demo" / f"{sha_new[:12]}.srt").is_file()


def test_fallo_antes_del_manifest_conserva_seleccion_previa(tmp_path, monkeypatch):
    manifest1, _, storage, manifests = _store(tmp_path)
    manifest_path = manifests / "video_demo_srt_selection.json"
    antes = manifest_path.read_bytes()

    def _boom(_path, _obj):
        raise OSError("disco lleno")

    monkeypatch.setattr(studio_srt, "_atomic_write_json", _boom)
    otro = _srt((1, 0, 1000, "reemplazo"), (2, 1000, 2000, "fallido"))
    doc, diags = studio_srt.parse_and_validate(otro, source_name="x.srt", video_duration_ms=_DUR)
    with pytest.raises(studio_srt.StudioSrtStorageError):
        studio_srt.store_and_associate(
            doc,
            diags,
            video_stem="video_demo",
            video_filename="video_demo.mp4",
            video_duration_ms=_DUR,
            data=otro,
            storage_root=storage,
            manifest_dir=manifests,
        )
    assert manifest_path.read_bytes() == antes  # seleccion previa intacta
    assert not list(manifests.rglob("*.tmp"))


def test_read_selection_none_cuando_no_hay(tmp_path):
    manifests = tmp_path / "transcripts"
    manifests.mkdir()
    sel = studio_srt.read_selection("video_demo", manifests)
    assert sel == {
        "version": 1,
        "video": {"name": "video_demo"},
        "selection": {"selected": False},
        "status": "none",
    }


def test_read_selection_devuelve_manifest(tmp_path):
    _store(tmp_path)
    sel = studio_srt.read_selection("video_demo", tmp_path / "transcripts")
    assert sel["selection"]["selected"] is True
    assert sel["status"] == "ready"


def test_delete_desasocia_y_es_idempotente(tmp_path):
    _, _, storage, manifests = _store(tmp_path)
    r1 = studio_srt.disassociate("video_demo", manifests)
    assert r1 == {
        "video": {"name": "video_demo"},
        "selection": {"selected": False},
        "status": "none",
    }
    # no borra archivos administrados
    assert list((storage / "video_demo").glob("*.srt"))
    # idempotente: segunda vez no falla
    r2 = studio_srt.disassociate("video_demo", manifests)
    assert r2 == r1
    assert studio_srt.read_selection("video_demo", manifests)["status"] == "none"


def test_dos_videos_asociaciones_independientes(tmp_path):
    _store(tmp_path, stem="uno")
    otro = _srt((1, 0, 1000, "b"))
    _store(tmp_path, data=otro, stem="dos")
    manifests = tmp_path / "transcripts"
    a = studio_srt.read_selection("uno", manifests)
    b = studio_srt.read_selection("dos", manifests)
    assert a["selection"]["source_sha256"] != b["selection"]["source_sha256"]
    studio_srt.disassociate("uno", manifests)
    assert studio_srt.read_selection("uno", manifests)["status"] == "none"
    assert studio_srt.read_selection("dos", manifests)["status"] == "ready"


# ─── Capacidades ───────────────────────────────────────────────────────────────
def test_capabilities_estatico_y_seguro():
    caps = studio_srt.capabilities()
    assert caps["extensions"] == [".srt"]
    assert caps["association"] == "one_selected_per_video"
    assert caps["batch"] is False
    assert caps["auto_v2"] is False
    assert caps["render"] is False
