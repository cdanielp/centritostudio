"""test_studio_srt.py — Contrato de dominio del administrador SRT de Studio (S36-C1, D37).

Sin red, sin GPU, sin FFmpeg. Cubre confinamiento de video, validacion de nombre,
parseo+validacion contra duracion, almacenamiento privado por hash COMPLETO, integridad
y reparacion del archivo administrado, idempotencia, reemplazo, atomicidad con temporales
unicos (incl. concurrencia) y saneamiento por whitelist del manifiesto. Nunca toca
transcripts/ reales: todo va a tmp_path. El SRT real del usuario NO se usa aqui.
"""

from __future__ import annotations

import hashlib
import json
import threading

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
_SHA_OK = hashlib.sha256(_OK).hexdigest()


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
    data = _srt((1, 0, 1000, "ok"), (2, 2000, 2000, "malo"))
    with pytest.raises(studio_srt.StudioSrtInvalid):
        studio_srt.parse_and_validate(data, source_name="s.srt", video_duration_ms=_DUR)


def test_warnings_no_abortan():
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
def _paths(tmp_path):
    storage = tmp_path / "studio_srt"
    manifests = tmp_path / "transcripts"
    manifests.mkdir(exist_ok=True)
    return storage, manifests


def _store(tmp_path, data=_OK, stem="video_demo"):
    storage, manifests = _paths(tmp_path)
    doc, diags = studio_srt.parse_and_validate(data, source_name="subs.srt", video_duration_ms=_DUR)
    manifest, created, repaired = studio_srt.store_and_associate(
        doc,
        diags,
        video_stem=stem,
        video_filename=f"{stem}.mp4",
        video_duration_ms=_DUR,
        data=data,
        storage_root=storage,
        manifest_dir=manifests,
    )
    return manifest, created, repaired, storage, manifests


def _manifest_file(manifests, stem="video_demo"):
    return manifests / f"{stem}_srt_selection.json"


def _tamper(manifests, mutator, stem="video_demo"):
    p = _manifest_file(manifests, stem)
    d = json.loads(p.read_text(encoding="utf-8"))
    mutator(d)
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def test_almacenamiento_por_hash_completo_y_bytes_preservados(tmp_path):
    manifest, created, repaired, storage, _ = _store(tmp_path)
    assert (created, repaired) == (True, False)
    managed = storage / "video_demo" / f"{_SHA_OK}.srt"
    assert managed.is_file()
    assert managed.read_bytes() == _OK  # bytes originales tal cual
    assert manifest["selection"]["source_sha256"] == _SHA_OK
    assert manifest["selection"]["managed_file"] == f"{_SHA_OK}.srt"  # SHA COMPLETO


def test_managed_file_es_basename_seguro(tmp_path):
    manifest, *_ = _store(tmp_path)
    mf = manifest["selection"]["managed_file"]
    assert "/" not in mf and "\\" not in mf
    assert len(mf) == 64 + len(".srt")


def test_manifest_y_archivo_comparten_sha_completo(tmp_path):
    manifest, _, _, storage, _ = _store(tmp_path)
    managed = storage / "video_demo" / manifest["selection"]["managed_file"]
    assert (
        hashlib.sha256(managed.read_bytes()).hexdigest() == manifest["selection"]["source_sha256"]
    )


def test_contenidos_distintos_nombres_distintos(tmp_path):
    _store(tmp_path)
    otro = _srt((1, 0, 1000, "otro"), (2, 1000, 3000, "texto"))
    m2, *_ = _store(tmp_path, data=otro)
    assert m2["selection"]["managed_file"] != f"{_SHA_OK}.srt"


def test_manifest_version_1_y_summary(tmp_path):
    manifest, *_ = _store(tmp_path)
    assert manifest["version"] == 1
    assert manifest["status"] == "ready"
    assert manifest["summary"]["n_cues"] == 2
    assert manifest["summary"]["n_errors"] == 0
    assert manifest["summary"]["start_ms"] == 0
    assert manifest["summary"]["end_ms"] == 2000
    assert manifest["video"]["duration_ms"] == _DUR


def test_build_manifest_rango_real_no_monotonico():
    """SRT no monotono valido: el summary usa min(start)/max(end), no el primer/ultimo cue.

    Con cue1 1000-2000 y cue2 0-1000 el rango real es 0-2000. Tomar cues[0].start y
    cues[-1].end daria 1000-1000 (degenerado), que luego el saneamiento rechaza.
    """
    import studio_srt_manifest

    no_mono = _srt((1, 1000, 2000, "uno"), (2, 0, 1000, "dos"))
    doc, diags = studio_srt.parse_and_validate(
        no_mono, source_name="subs.srt", video_duration_ms=_DUR
    )
    manifest = studio_srt_manifest.build_manifest(
        video_stem="video_demo",
        video_filename="video_demo.mp4",
        video_duration_ms=_DUR,
        document=doc,
        diagnostics=diags,
        managed_name=f"{hashlib.sha256(no_mono).hexdigest()}.srt",
    )
    assert manifest["summary"]["start_ms"] == 0
    assert manifest["summary"]["end_ms"] == 2000
    assert any(d["code"] == "time_not_monotonic" for d in manifest["diagnostics"])


def test_manifest_no_expone_texto_ni_rutas(tmp_path):
    manifest, *_ = _store(tmp_path)
    blob = str(manifest)
    assert "uno" not in blob and "dos" not in blob
    assert str(tmp_path) not in blob
    assert "managed_path" not in blob
    for d in manifest["diagnostics"]:
        assert set(d.keys()) == {"code", "severity", "cue_position", "cue_index"}


def test_no_quedan_tmp(tmp_path):
    _, _, _, storage, manifests = _store(tmp_path)
    assert not list(storage.rglob("*.tmp"))
    assert not list(manifests.rglob("*.tmp"))


# ─── Idempotencia que verifica el storage (Bloqueante 3) ───────────────────────
def test_idempotencia_archivo_correcto_no_reescribe(tmp_path):
    _store(tmp_path)
    manifest2, created2, repaired2, storage, _ = _store(tmp_path)
    assert (created2, repaired2) == (False, False)
    managed = list((storage / "video_demo").glob("*.srt"))
    assert len(managed) == 1  # no duplica


def test_idempotencia_repara_archivo_faltante(tmp_path):
    _, _, _, storage, _ = _store(tmp_path)
    managed = storage / "video_demo" / f"{_SHA_OK}.srt"
    managed.unlink()  # storage roto: archivo administrado desaparece
    manifest2, created2, repaired2, _, manifests = _store(tmp_path)
    assert (created2, repaired2) == (False, True)  # reconstruido, no idempotencia falsa
    assert managed.is_file() and managed.read_bytes() == _OK
    assert not list(manifests.rglob("*.tmp"))


def test_idempotencia_repara_bytes_corruptos(tmp_path):
    _, _, _, storage, _ = _store(tmp_path)
    managed = storage / "video_demo" / f"{_SHA_OK}.srt"
    managed.write_bytes(b"corrupto")  # hash ya no coincide
    manifest2, created2, repaired2, *_ = _store(tmp_path)
    assert (created2, repaired2) == (False, True)
    assert managed.read_bytes() == _OK  # reparado con los bytes validados


def test_idempotencia_managed_file_inseguro_no_sale_del_root(tmp_path):
    _, _, _, storage, manifests = _store(tmp_path)
    _tamper(manifests, lambda d: d["selection"].update(managed_file="../evil.srt"))
    manifest2, created2, repaired2, *_ = _store(tmp_path)
    assert (created2, repaired2) == (False, True)
    assert manifest2["selection"]["managed_file"] == f"{_SHA_OK}.srt"  # nombre canonico
    assert not (storage / "evil.srt").exists()  # nunca escribe fuera del dir del video
    assert (storage / "video_demo" / f"{_SHA_OK}.srt").is_file()


def test_idempotencia_manifest_truncado_comportamiento_seguro(tmp_path):
    _, _, _, storage, manifests = _store(tmp_path)
    _manifest_file(manifests).write_text("{ truncado", encoding="utf-8")  # JSON roto
    manifest2, created2, repaired2, *_ = _store(tmp_path)
    assert manifest2["version"] == 1 and manifest2["status"] == "ready"
    assert (storage / "video_demo" / f"{_SHA_OK}.srt").is_file()


def test_prefijo_colision_no_reutiliza_bytes_ajenos(tmp_path):
    # Un archivo administrado con hash real distinto al esperado NUNCA se acepta como valido.
    _, _, _, storage, _ = _store(tmp_path)
    managed = storage / "video_demo" / f"{_SHA_OK}.srt"
    assert studio_srt._managed_file_ok(managed.parent, managed.name, _SHA_OK, _OK) is True
    assert studio_srt._managed_file_ok(managed.parent, managed.name, _SHA_OK, b"ajeno") is False


# ─── Reemplazo ─────────────────────────────────────────────────────────────────
def test_nuevo_sha_reemplaza_y_conserva_anterior(tmp_path):
    _store(tmp_path)
    otro = _srt((1, 0, 1000, "otro"), (2, 1000, 3000, "contenido"))
    manifest2, created2, repaired2, storage, _ = _store(tmp_path, data=otro)
    assert (created2, repaired2) == (True, False)
    sha_new = hashlib.sha256(otro).hexdigest()
    assert manifest2["selection"]["source_sha256"] == sha_new
    assert (storage / "video_demo" / f"{_SHA_OK}.srt").is_file()  # anterior conservado
    assert (storage / "video_demo" / f"{sha_new}.srt").is_file()


def test_fallo_antes_del_manifest_conserva_seleccion_previa(tmp_path, monkeypatch):
    manifest1, _, _, storage, manifests = _store(tmp_path)
    manifest_path = _manifest_file(manifests)
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


# ─── Escritura atomica con temporales unicos (Bloqueante 5) ────────────────────
def test_atomic_write_bytes_concurrente_targets_distintos(tmp_path):
    barrier = threading.Barrier(6)

    def worker(i):
        barrier.wait()
        studio_srt._atomic_write_bytes(tmp_path / f"f{i}.bin", f"payload-{i}".encode() * 2000)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for i in range(6):
        assert (tmp_path / f"f{i}.bin").read_bytes() == f"payload-{i}".encode() * 2000
    assert not list(tmp_path.glob("*.tmp"))


def test_atomic_write_bytes_mismo_target_nunca_parcial(tmp_path):
    # Contrato: last-writer-wins con archivo COMPLETO. Bajo contencion extrema un perdedor
    # puede fallar tras reintentos (PermissionError de Windows); jamas queda un `.tmp` ni un
    # payload parcial/mezclado. Recogemos excepciones para no dejar excepcion de hilo suelta.
    target = tmp_path / "shared.bin"
    payloads = [bytes([65 + i]) * (40_000 + i) for i in range(6)]
    barrier = threading.Barrier(6)
    errors: list[BaseException] = []

    def worker(i):
        barrier.wait()
        try:
            studio_srt._atomic_write_bytes(target, payloads[i])
        except OSError as exc:  # last-writer-wins: un perdedor puede fallar limpiamente
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert target.read_bytes() in payloads  # payload completo, nunca mezcla parcial
    assert not list(tmp_path.glob("*.tmp"))  # ningun temporal huerfano
    assert all(isinstance(e, PermissionError) for e in errors)  # solo choque de reemplazo


def test_atomic_write_json_concurrente_sin_tmp(tmp_path):
    barrier = threading.Barrier(6)

    def worker(i):
        barrier.wait()
        studio_srt._atomic_write_json(tmp_path / f"m{i}.json", {"i": i, "pad": "x" * 5000})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for i in range(6):
        assert json.loads((tmp_path / f"m{i}.json").read_text(encoding="utf-8"))["i"] == i
    assert not list(tmp_path.glob("*.tmp"))


def test_atomic_write_bytes_excepcion_no_deja_tmp(tmp_path):
    # Escritura sobre un dir inexistente falla al crear el temporal; no debe quedar `.tmp`.
    target = tmp_path / "sub_inexistente" / "x.bin"
    with pytest.raises(OSError):
        studio_srt._atomic_write_bytes(target, b"data")
    assert not list(tmp_path.rglob("*.tmp"))


# ─── Lectura / desasociacion ───────────────────────────────────────────────────
def test_read_selection_none_cuando_no_hay(tmp_path):
    _, manifests = _paths(tmp_path)
    sel = studio_srt.read_selection("video_demo", manifests)
    assert sel == {
        "version": 1,
        "video": {"name": "video_demo"},
        "selection": {"selected": False},
        "status": "none",
    }


def test_read_selection_devuelve_manifest_saneado(tmp_path):
    _store(tmp_path)
    sel = studio_srt.read_selection("video_demo", tmp_path / "transcripts")
    assert sel["selection"]["selected"] is True
    assert sel["status"] == "ready"
    assert set(sel.keys()) == {"version", "video", "selection", "summary", "diagnostics", "status"}


def test_delete_desasocia_y_es_idempotente(tmp_path):
    _, _, _, storage, manifests = _store(tmp_path)
    r1 = studio_srt.disassociate("video_demo", manifests)
    assert r1 == {
        "video": {"name": "video_demo"},
        "selection": {"selected": False},
        "status": "none",
    }
    assert list((storage / "video_demo").glob("*.srt"))  # no borra administrados
    r2 = studio_srt.disassociate("video_demo", manifests)
    assert r2 == r1  # idempotente
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


# ─── Saneamiento del manifiesto por whitelist ──────────────────────────────────
def test_sanitize_descarta_campo_extra_privado(tmp_path):
    _, _, _, _, manifests = _store(tmp_path)

    def _add_extra(d):
        d["secreto"] = "texto privado del usuario"
        d["selection"]["managed_path"] = "/ruta/absoluta/interna"
        d["cues"] = [{"text": "uno"}]

    _tamper(manifests, _add_extra)
    sel = studio_srt.read_selection("video_demo", manifests)
    blob = json.dumps(sel)
    assert "secreto" not in blob and "texto privado" not in blob
    assert "managed_path" not in blob and "cues" not in sel
    assert set(sel.keys()) == {"version", "video", "selection", "summary", "diagnostics", "status"}


@pytest.mark.parametrize(
    "mutator",
    [
        # basenames / rutas
        lambda d: d["selection"].update(managed_file="../escape.srt"),
        lambda d: d["selection"].update(managed_file="sub/dir.srt"),
        lambda d: d["selection"].update(managed_file="ctrl\x01.srt"),  # caracter de control
        lambda d: d["selection"].update(source_name="a/b.srt"),
        lambda d: d["selection"].update(source_name="ctrl\tname.srt"),  # tab de control
        # identidad del video
        lambda d: d["video"].update(name="otro_video"),
        lambda d: d["video"].update(filename="../evil.mp4"),
        lambda d: d["video"].update(filename="ctrl\x00.mp4"),
        lambda d: d["video"].update(filename=123),
        lambda d: d["video"].update(duration_ms=-5),
        # sha / version / status
        lambda d: d["selection"].update(source_sha256="zz"),
        lambda d: d["selection"].update(source_sha256="abc"),
        lambda d: d["selection"].update(source_sha256="A" * 64),  # mayusculas no hex validas
        lambda d: d.update(version=2),
        lambda d: d.update(status="pending"),
        lambda d: d.pop("status"),
        # encoding allowlist
        lambda d: d["selection"].update(encoding=""),
        lambda d: d["selection"].update(encoding="latin-1"),
        lambda d: d["selection"].update(encoding="utf-16"),
        # numeros semanticos
        lambda d: d["summary"].update(n_cues="dos"),
        lambda d: d["summary"].update(n_cues=0),
        lambda d: d["summary"].update(start_ms=-1),
        lambda d: d["summary"].update(end_ms=d["summary"]["start_ms"] - 1),
        lambda d: d["summary"].update(n_errors=1),
        lambda d: d["summary"].update(n_warnings=-2),
        lambda d: d["summary"].update(n_cues=True),  # bool no es int valido
        # diagnostics
        lambda d: d["diagnostics"].append({"code": "x", "severity": "critico"}),
        lambda d: d["diagnostics"].append({"code": "codigo_inventado", "severity": "warning"}),
        lambda d: d["diagnostics"].append(
            {"code": "overlap", "severity": "warning", "cue_position": -1}
        ),
        lambda d: d["diagnostics"].append(
            {"code": "overlap", "severity": "warning", "cue_index": 0}
        ),
    ],
)
def test_sanitize_rechaza_contrato_violado(tmp_path, mutator):
    _, _, _, _, manifests = _store(tmp_path)
    _tamper(manifests, mutator)
    with pytest.raises(studio_srt.StudioSrtStorageError):
        studio_srt.read_selection("video_demo", manifests)


def test_sanitize_acepta_diagnostico_valido_conocido(tmp_path):
    _, _, _, _, manifests = _store(tmp_path)
    _tamper(
        manifests,
        lambda d: d["diagnostics"].append(
            {"code": "cue_after_video", "severity": "warning", "cue_position": 0, "cue_index": 1}
        ),
    )
    sel = studio_srt.read_selection("video_demo", manifests)
    assert any(x["code"] == "cue_after_video" for x in sel["diagnostics"])


# ─── S36-C1.1: invariantes cerrados del manifiesto ─────────────────────────────
@pytest.mark.parametrize(
    "mutator",
    [
        # video.filename: otro basename, extension falsa, ruta, control C1
        lambda d: d["video"].update(filename="otro.mp4"),
        lambda d: d["video"].update(filename="video_demo.txt"),
        lambda d: d["video"].update(filename="C:\\privado\\video_demo.mp4"),
        lambda d: d["video"].update(filename="../video_demo.mp4"),
        lambda d: d["video"].update(filename="video_demo.mp4\x85"),  # C1 tras basename valido
        # duration_ms: None y 0 no son duraciones reales
        lambda d: d["video"].update(duration_ms=None),
        lambda d: d["video"].update(duration_ms=0),
        # managed_file: cualquier basename seguro distinto del SHA
        lambda d: d["selection"].update(managed_file="benigno.srt"),
        lambda d: d["selection"].update(managed_file=f"{_SHA_OK}.txt"),
        # summary: rango temporal degenerado end==start
        lambda d: d["summary"].update(end_ms=d["summary"]["start_ms"]),
        # control C1 U+0085 (NEL) en un basename
        lambda d: d["selection"].update(source_name="ctrl\x85name.srt"),
    ],
)
def test_sanitize_cierra_invariantes_c11(tmp_path, mutator):
    _, _, _, _, manifests = _store(tmp_path)
    _tamper(manifests, mutator)
    with pytest.raises(studio_srt.StudioSrtStorageError):
        studio_srt.read_selection("video_demo", manifests)


@pytest.mark.parametrize("ext", [".mp4", ".MP4", ".mov", ".MOV"])
def test_sanitize_acepta_extension_video_valida(tmp_path, ext):
    _, _, _, _, manifests = _store(tmp_path)
    _tamper(manifests, lambda d: d["video"].update(filename=f"video_demo{ext}"))
    sel = studio_srt.read_selection("video_demo", manifests)
    assert sel["video"]["filename"] == f"video_demo{ext}"
    assert sel["video"]["duration_ms"] == _DUR


def test_sanitize_acepta_basename_con_acentos_y_espacios(tmp_path):
    _, _, _, _, manifests = _store(tmp_path, stem="mi vídeo")
    sel = studio_srt.read_selection("mi vídeo", manifests)
    assert sel["video"]["name"] == "mi vídeo"
    assert sel["video"]["filename"] == "mi vídeo.mp4"


def test_read_selection_json_corrupto_rechaza(tmp_path):
    _, _, _, _, manifests = _store(tmp_path)
    _manifest_file(manifests).write_text("no es json {", encoding="utf-8")
    with pytest.raises(studio_srt.StudioSrtStorageError):
        studio_srt.read_selection("video_demo", manifests)


# ─── Capacidades ───────────────────────────────────────────────────────────────
def test_capabilities_estatico_y_seguro():
    caps = studio_srt.capabilities()
    assert caps["extensions"] == [".srt"]
    assert caps["association"] == "one_selected_per_video"
    assert caps["batch"] is False
    assert caps["auto_v2"] is False
    assert caps["render"] is False
