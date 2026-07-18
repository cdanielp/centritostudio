"""test_srt_import.py — Contrato completo del importador SRT (S36-A, DECISIONES D33).

Sin red, sin GPU, sin FFmpeg. Cubre timestamps, decodificacion, parser, validacion,
serializacion, contrato JSON, CLI y propiedades. El SRT real del usuario NO se usa aqui:
el CI pasa aunque ese archivo no exista.
"""

from __future__ import annotations

import json

import pytest

import srt_tool
from srt_import import (
    SrtCue,
    SrtDecodeError,
    SrtDocument,
    SrtError,
    SrtLimitError,
    SrtParseError,
    format_timestamp,
    load_srt,
    parse_srt_bytes,
    parse_srt_text,
    parse_timestamp,
    serialize_srt,
    srt_to_contract,
    validate_srt,
    write_srt_contract,
)
from srt_types import (
    ERR_DOCUMENT_EMPTY,
    ERR_EMPTY_CUE_TEXT,
    ERR_END_LE_START,
    ERR_INDEX_NON_POSITIVE,
    ERR_INDEX_NOT_INTEGER,
    ERR_MISSING_TIMESTAMP,
    ERR_NEGATIVE_START,
    ERR_NUL_CHARACTER,
    ERR_TIMESTAMP_UNREADABLE,
    ERR_TRUNCATED_BLOCK,
    MAX_CHARS_PER_LINE,
    MAX_LINES_PER_CUE,
    WARN_CONTROL_CHARACTERS,
    WARN_CP1252_FALLBACK,
    WARN_CUE_AFTER_VIDEO,
    WARN_CUE_PARTIALLY_OUT,
    WARN_DECIMAL_DOT,
    WARN_INDEX_DUPLICATE,
    WARN_INDEX_NOT_CONSECUTIVE,
    WARN_OVERLAP,
    WARN_TIME_NOT_MONOTONIC,
    WARN_TOO_MANY_LINES,
)


def _doc(*cues, encoding="utf-8", sha="0" * 64, diagnostics=(), name="x.srt"):
    return SrtDocument(tuple(cues), encoding, sha, tuple(diagnostics), name)


def _cue(index, start, end, lines, pos=0):
    return SrtCue(index, start, end, tuple(lines), pos)


def _codes(diags):
    return [d.code for d in diags]


# ============================== TIMESTAMPS ==============================


def test_timestamp_cero():
    assert parse_timestamp("00:00:00,000") == 0


def test_timestamp_normal():
    assert parse_timestamp("01:02:03,456") == ((1 * 60 + 2) * 60 + 3) * 1000 + 456


def test_timestamp_horas_grandes():
    assert parse_timestamp("100:00:00,000") == 100 * 3600 * 1000


def test_timestamp_coma():
    assert parse_timestamp("00:00:01,250") == 1250


def test_timestamp_punto_tolerado():
    assert parse_timestamp("00:00:01.250") == 1250


@pytest.mark.parametrize("bad", ["00:60:00,000", "00:99:00,000"])
def test_timestamp_minutos_invalidos(bad):
    with pytest.raises(SrtParseError):
        parse_timestamp(bad)


@pytest.mark.parametrize("bad", ["00:00:60,000", "00:00:75,000"])
def test_timestamp_segundos_invalidos(bad):
    with pytest.raises(SrtParseError):
        parse_timestamp(bad)


@pytest.mark.parametrize("bad", ["00:00:01,25", "00:00:01,5", "00:00:01,"])
def test_timestamp_milisegundos_incompletos(bad):
    with pytest.raises(SrtParseError):
        parse_timestamp(bad)


def test_timestamp_negativo():
    with pytest.raises(SrtParseError):
        parse_timestamp("-00:00:01,000")


@pytest.mark.parametrize("bad", ["00:00:01,000 extra", "abc", "1:2:3", "00:00:01"])
def test_timestamp_basura(bad):
    with pytest.raises(SrtParseError):
        parse_timestamp(bad)


@pytest.mark.parametrize(
    "ms", [0, 1, 999, 1000, 59_999, 3_600_000, 2_473_300, 2_474_600, 359_999_999]
)
def test_timestamp_roundtrip(ms):
    assert parse_timestamp(format_timestamp(ms)) == ms


def test_timestamp_grandes_sin_float_drift():
    # 100 h + 1 ms: sin flotantes no hay perdida de precision.
    ms = 100 * 3600 * 1000 + 1
    assert parse_timestamp(format_timestamp(ms)) == ms


def test_format_timestamp_negativo_rechazado():
    with pytest.raises(SrtParseError):
        format_timestamp(-1)


# ============================== DECODIFICACION ==============================

_MINIMO = "1\n00:00:00,000 --> 00:00:01,000\ntexto\n"


def test_decode_utf8():
    doc = parse_srt_bytes("1\n00:00:00,000 --> 00:00:01,000\ncafé ñ\n".encode())
    assert doc.encoding == "utf-8"
    assert doc.cues[0].text == "café ñ"


def test_decode_utf8_bom():
    data = b"\xef\xbb\xbf" + _MINIMO.encode()
    doc = parse_srt_bytes(data)
    assert doc.encoding == "utf-8"
    assert doc.cues[0].lines[0] == "texto"


def test_decode_crlf():
    doc = parse_srt_bytes(_MINIMO.replace("\n", "\r\n").encode())
    assert len(doc.cues) == 1
    assert doc.cues[0].text == "texto"


def test_decode_lf():
    doc = parse_srt_bytes(_MINIMO.encode())
    assert len(doc.cues) == 1


def test_decode_cp1252_fallback():
    data = "1\n00:00:00,000 --> 00:00:01,000\ncafé\n".encode("cp1252")
    doc = parse_srt_bytes(data)
    assert doc.encoding == "windows-1252"
    assert doc.cues[0].text == "café"
    assert WARN_CP1252_FALLBACK in _codes(doc.diagnostics)


def test_decode_bytes_imposibles():
    with pytest.raises(SrtDecodeError):
        parse_srt_bytes(b"\x81\x8d\x8f")


def test_decode_encoding_explicito_utf8_falla():
    with pytest.raises(SrtDecodeError):
        parse_srt_bytes("café".encode("cp1252"), encoding="utf-8")


def test_nul_detectado():
    doc = parse_srt_text("1\n00:00:00,000 --> 00:00:01,000\nab\x00cd\n")
    assert doc.cues == ()
    assert ERR_NUL_CHARACTER in _codes(doc.diagnostics)


def test_extension_srt_mayuscula_valida(tmp_path):
    p = tmp_path / "SUB.SRT"
    p.write_bytes(_MINIMO.encode())
    assert len(load_srt(p).cues) == 1


def test_extension_incorrecta_rechazada(tmp_path):
    p = tmp_path / "sub.txt"
    p.write_bytes(_MINIMO.encode())
    with pytest.raises(SrtError):
        load_srt(p)


def test_archivo_sobre_limite_rechazado(tmp_path):
    p = tmp_path / "big.srt"
    p.write_bytes(_MINIMO.encode())
    with pytest.raises(SrtLimitError):
        load_srt(p, max_bytes=10)


def test_directorio_rechazado(tmp_path):
    with pytest.raises(SrtError):
        load_srt(tmp_path)


def test_archivo_inexistente_rechazado(tmp_path):
    with pytest.raises(SrtError):
        load_srt(tmp_path / "no_existe.srt")


# ============================== PARSER ==============================


def test_cue_minimo():
    doc = parse_srt_text(_MINIMO)
    assert len(doc.cues) == 1
    c = doc.cues[0]
    assert (c.index, c.start_ms, c.end_ms, c.text, c.source_position) == (1, 0, 1000, "texto", 0)


def test_multiples_cues():
    txt = _MINIMO + "\n2\n00:00:01,000 --> 00:00:02,000\ndos\n"
    doc = parse_srt_text(txt)
    assert [c.index for c in doc.cues] == [1, 2]


def test_multilinea():
    doc = parse_srt_text("1\n00:00:00,000 --> 00:00:02,000\nlinea uno\nlinea dos\n")
    assert doc.cues[0].lines == ("linea uno", "linea dos")


def test_sin_newline_final():
    doc = parse_srt_text("1\n00:00:00,000 --> 00:00:01,000\nsin salto final")
    assert doc.cues[0].text == "sin salto final"


def test_varias_lineas_vacias_entre_cues():
    txt = "1\n00:00:00,000 --> 00:00:01,000\nuno\n\n\n\n2\n00:00:01,000 --> 00:00:02,000\ndos\n"
    doc = parse_srt_text(txt)
    assert [c.index for c in doc.cues] == [1, 2]


def test_espacios_antes_del_primer_bloque():
    doc = parse_srt_text("\n\n  \n1\n00:00:00,000 --> 00:00:01,000\nuno\n")
    assert doc.cues[0].source_position == 0


def test_texto_con_numeros():
    doc = parse_srt_text("1\n00:00:00,000 --> 00:00:01,000\n1234 y 5678\n")
    assert doc.cues[0].text == "1234 y 5678"


def test_texto_con_flecha_como_contenido():
    doc = parse_srt_text("1\n00:00:00,000 --> 00:00:01,000\nusa --> para apuntar\n")
    assert doc.cues[0].text == "usa --> para apuntar"


def test_texto_script_preservado():
    doc = parse_srt_text("1\n00:00:00,000 --> 00:00:01,000\n<script>alert(1)</script>\n")
    assert doc.cues[0].text == "<script>alert(1)</script>"


def test_texto_italica_preservado():
    doc = parse_srt_text("1\n00:00:00,000 --> 00:00:01,000\n<i>hola</i>\n")
    assert doc.cues[0].text == "<i>hola</i>"


def test_acentos_y_enie_preservados():
    doc = parse_srt_text("1\n00:00:00,000 --> 00:00:01,000\nEspañol: acción, niño\n")
    assert doc.cues[0].text == "Español: acción, niño"


def test_emoji_preservado():
    doc = parse_srt_text("1\n00:00:00,000 --> 00:00:01,000\nhola \U0001f600 mundo\n")
    assert doc.cues[0].text == "hola \U0001f600 mundo"


def test_espacios_internos_no_normalizados():
    doc = parse_srt_text("1\n00:00:00,000 --> 00:00:01,000\n  dos   espacios  \n")
    assert doc.cues[0].lines[0] == "  dos   espacios  "


def test_indice_duplicado_warning():
    txt = "1\n00:00:00,000 --> 00:00:01,000\nuno\n\n1\n00:00:01,000 --> 00:00:02,000\ndos\n"
    diags = validate_srt(parse_srt_text(txt))
    assert WARN_INDEX_DUPLICATE in _codes(diags)


def test_indice_no_consecutivo_warning():
    txt = "1\n00:00:00,000 --> 00:00:01,000\nuno\n\n5\n00:00:01,000 --> 00:00:02,000\ndos\n"
    diags = validate_srt(parse_srt_text(txt))
    assert WARN_INDEX_NOT_CONSECUTIVE in _codes(diags)


def test_indice_no_entero_error():
    doc = parse_srt_text("uno\n00:00:00,000 --> 00:00:01,000\ntexto\n")
    assert doc.cues == ()
    assert ERR_INDEX_NOT_INTEGER in _codes(doc.diagnostics)


def test_falta_timestamp_error():
    doc = parse_srt_text("1\nesto no es tiempo\ntexto\n")
    assert doc.cues == ()
    assert ERR_MISSING_TIMESTAMP in _codes(doc.diagnostics)


def test_timestamp_invalido_error():
    doc = parse_srt_text("1\n00:00:0X,000 --> 00:00:01,000\ntexto\n")
    assert doc.cues == ()
    assert ERR_TIMESTAMP_UNREADABLE in _codes(doc.diagnostics)


def test_end_igual_start_error():
    doc = parse_srt_text("1\n00:00:01,000 --> 00:00:01,000\ntexto\n")
    assert doc.cues == ()
    assert ERR_END_LE_START in _codes(doc.diagnostics)


def test_end_menor_start_error():
    doc = parse_srt_text("1\n00:00:02,000 --> 00:00:01,000\ntexto\n")
    assert doc.cues == ()
    assert ERR_END_LE_START in _codes(doc.diagnostics)


def test_cue_vacio_error():
    doc = parse_srt_text(
        "1\n00:00:00,000 --> 00:00:01,000\n\n2\n00:00:01,000 --> 00:00:02,000\nok\n"
    )
    # el bloque 1 no tiene texto (linea en blanco = separador) -> se convierte en truncado
    assert [c.index for c in doc.cues] == [2]
    assert any(c in _codes(doc.diagnostics) for c in (ERR_EMPTY_CUE_TEXT, ERR_TRUNCATED_BLOCK))


def test_bloque_truncado_diagnosticado():
    doc = parse_srt_text("1\n\n2\n00:00:01,000 --> 00:00:02,000\nok\n")
    assert ERR_TRUNCATED_BLOCK in _codes(doc.diagnostics)


def test_basura_entre_bloques_diagnosticada():
    txt = (
        "1\n00:00:00,000 --> 00:00:01,000\nuno\n\n"
        "BASURA SIN FORMATO\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\ndos\n"
    )
    doc = parse_srt_text(txt)
    assert [c.index for c in doc.cues] == [1, 2]
    assert ERR_INDEX_NOT_INTEGER in _codes(doc.diagnostics)


def test_tolerante_recupera_cues_posteriores():
    txt = "1\n00:00:0X,000 --> 00:00:01,000\nmalo\n\n2\n00:00:01,000 --> 00:00:02,000\nbueno\n"
    doc = parse_srt_text(txt)
    assert [c.index for c in doc.cues] == [2]


def test_estricto_aborta():
    txt = "1\n00:00:0X,000 --> 00:00:01,000\nmalo\n"
    with pytest.raises(SrtParseError):
        parse_srt_text(txt, strict=True)


def test_estricto_warnings_no_abortan():
    txt = "1\n00:00:00,000 --> 00:00:01.000\ntexto\n"  # punto = warning, no error
    doc = parse_srt_text(txt, strict=True)
    assert len(doc.cues) == 1
    assert WARN_DECIMAL_DOT in _codes(doc.diagnostics)


def test_orden_fuente_preservado():
    txt = "3\n00:00:00,000 --> 00:00:01,000\na\n\n7\n00:00:01,000 --> 00:00:02,000\nb\n"
    doc = parse_srt_text(txt)
    assert [c.index for c in doc.cues] == [3, 7]
    assert [c.source_position for c in doc.cues] == [0, 1]


def test_no_reordena_por_timestamp():
    txt = "1\n00:00:05,000 --> 00:00:06,000\ntarde\n\n2\n00:00:00,000 --> 00:00:01,000\ntemprano\n"
    doc = parse_srt_text(txt)
    assert [c.start_ms for c in doc.cues] == [5000, 0]


def test_input_string_no_mutado():
    txt = "1\n00:00:00,000 --> 00:00:01,000\ntexto\n"
    original = str(txt)
    parse_srt_text(txt)
    assert txt == original


def test_archivo_vacio():
    doc = parse_srt_text("")
    assert doc.cues == ()


def test_punto_decimal_serializa_con_coma():
    doc = parse_srt_text("1\n00:00:00,000 --> 00:00:01.500\ntexto\n")
    assert doc.cues[0].end_ms == 1500
    assert WARN_DECIMAL_DOT in _codes(doc.diagnostics)
    assert "," in serialize_srt(doc) and "1.500" not in serialize_srt(doc)


# ============================== VALIDACION ==============================


def test_overlap_warning():
    a = _cue(1, 0, 2000, ["a"], 0)
    b = _cue(2, 1500, 3000, ["b"], 1)
    assert WARN_OVERLAP in _codes(validate_srt(_doc(a, b)))


def test_no_overlap():
    a = _cue(1, 0, 1000, ["a"], 0)
    b = _cue(2, 1000, 2000, ["b"], 1)
    assert WARN_OVERLAP not in _codes(validate_srt(_doc(a, b)))


def test_orden_temporal_no_monotono():
    a = _cue(1, 5000, 6000, ["a"], 0)
    b = _cue(2, 1000, 2000, ["b"], 1)
    assert WARN_TIME_NOT_MONOTONIC in _codes(validate_srt(_doc(a, b)))


def test_cue_fuera_de_duracion_video():
    c = _cue(1, 10_000, 11_000, ["a"], 0)
    assert WARN_CUE_AFTER_VIDEO in _codes(validate_srt(_doc(c), video_duration_ms=5000))


def test_cue_parcialmente_fuera():
    c = _cue(1, 4000, 6000, ["a"], 0)
    assert WARN_CUE_PARTIALLY_OUT in _codes(validate_srt(_doc(c), video_duration_ms=5000))


def test_indice_no_positivo_error():
    c = _cue(0, 0, 1000, ["a"], 0)
    assert ERR_INDEX_NON_POSITIVE in _codes(validate_srt(_doc(c)))


def test_negative_start_error():
    c = _cue(1, -100, 1000, ["a"], 0)
    assert ERR_NEGATIVE_START in _codes(validate_srt(_doc(c)))


def test_documento_vacio_error():
    assert _codes(validate_srt(_doc())) == [ERR_DOCUMENT_EMPTY]


def test_control_chars_warning():
    c = _cue(1, 0, 1000, ["hola\x07mundo"], 0)
    assert WARN_CONTROL_CHARACTERS in _codes(validate_srt(_doc(c)))


def test_tab_preservado_no_es_peligroso():
    c = _cue(1, 0, 1000, ["hola\tmundo"], 0)
    codes = _codes(validate_srt(_doc(c)))
    assert WARN_CONTROL_CHARACTERS not in codes


def test_demasiadas_lineas_warning():
    c = _cue(1, 0, 1000, [f"l{i}" for i in range(MAX_LINES_PER_CUE + 1)], 0)
    assert WARN_TOO_MANY_LINES in _codes(validate_srt(_doc(c)))


def test_linea_muy_larga_warning():
    c = _cue(1, 0, 1000, ["x" * (MAX_CHARS_PER_LINE + 1)], 0)
    diags = validate_srt(_doc(c))
    assert "line_too_long" in _codes(diags)


def test_diagnosticos_deterministas():
    a = _cue(1, 0, 2000, ["a"], 0)
    b = _cue(2, 1500, 3000, ["b"], 1)
    d = _doc(a, b)
    assert validate_srt(d) == validate_srt(d)


def test_diagnosticos_ordenados_por_cue():
    a = _cue(1, 0, 2000, ["a"], 0)
    b = _cue(5, 1500, 3000, ["b"], 1)  # no consecutivo + overlap en el mismo cue
    positions = [x.cue_position for x in validate_srt(_doc(a, b))]
    assert positions == sorted(positions)


def test_dos_diagnosticos_mismo_cue_se_conservan():
    a = _cue(1, 0, 2000, ["a"], 0)
    b = _cue(5, 1500, 3000, ["b"], 1)
    codes = _codes(validate_srt(_doc(a, b)))
    assert WARN_INDEX_NOT_CONSECUTIVE in codes and WARN_OVERLAP in codes


# ============================== SERIALIZACION ==============================


def _rich_doc():
    txt = (
        "1\n00:00:00,000 --> 00:00:01,500\nHola ñ\nsegunda\n\n"
        "2\n00:00:01,500 --> 00:00:03,000\n<i>x</i> 😀\n"
    )
    return parse_srt_text(txt, source_name="demo.srt")


def _semantic_key(doc):
    return [(c.index, c.start_ms, c.end_ms, c.lines) for c in doc.cues]


def test_roundtrip_semantico():
    doc = _rich_doc()
    assert _semantic_key(parse_srt_text(serialize_srt(doc))) == _semantic_key(doc)


def test_serialize_mantiene_indices():
    txt = "3\n00:00:00,000 --> 00:00:01,000\na\n\n9\n00:00:01,000 --> 00:00:02,000\nb\n"
    doc = parse_srt_text(txt)
    assert [c.index for c in parse_srt_text(serialize_srt(doc)).cues] == [3, 9]


def test_serialize_reindex():
    txt = "3\n00:00:00,000 --> 00:00:01,000\na\n\n9\n00:00:01,000 --> 00:00:02,000\nb\n"
    doc = parse_srt_text(txt)
    assert [c.index for c in parse_srt_text(serialize_srt(doc, reindex=True)).cues] == [1, 2]


def test_serialize_mantiene_lineas():
    doc = _rich_doc()
    assert _semantic_key(parse_srt_text(serialize_srt(doc)))[0][3] == ("Hola ñ", "segunda")


def test_serialize_usa_coma():
    assert " --> " in serialize_srt(_rich_doc())
    assert "," in serialize_srt(_rich_doc())


def test_serialize_newline_lf():
    out = serialize_srt(_rich_doc(), newline="\n")
    assert "\r" not in out


def test_serialize_newline_crlf():
    out = serialize_srt(_rich_doc(), newline="\r\n")
    assert "\r\n" in out and parse_srt_bytes(out.encode()).cues


def test_serialize_no_agrega_texto():
    doc = _rich_doc()
    total_in = sum(len("".join(c.lines)) for c in doc.cues)
    total_out = sum(len("".join(c.lines)) for c in parse_srt_text(serialize_srt(doc)).cues)
    assert total_in == total_out


def test_serialize_no_elimina_unicode():
    assert "😀" in serialize_srt(_rich_doc()) and "ñ" in serialize_srt(_rich_doc())


def test_serialize_original_no_modificado():
    doc = _rich_doc()
    before = _semantic_key(doc)
    serialize_srt(doc, reindex=True)
    assert _semantic_key(doc) == before


def test_serialize_doble_estable():
    doc = _rich_doc()
    assert serialize_srt(doc) == serialize_srt(doc)


# ============================== CONTRATO JSON ==============================


def test_contract_json_serializable():
    payload = srt_to_contract(_rich_doc())
    assert json.loads(json.dumps(payload, ensure_ascii=False))["version"] == 1


def test_contract_version_1():
    assert srt_to_contract(_rich_doc())["version"] == 1


def test_contract_tiempos_int():
    payload = srt_to_contract(_rich_doc())
    for c in payload["cues"]:
        assert isinstance(c["start_ms"], int) and isinstance(c["end_ms"], int)
    for k in ("start_ms", "end_ms", "duration_ms"):
        assert isinstance(payload["summary"][k], int)


def test_contract_basename_sin_ruta():
    doc = parse_srt_text(_MINIMO, source_name="C:\\ruta\\privada\\sub.srt")
    assert srt_to_contract(doc)["source"]["name"] == "sub.srt"


def test_contract_sha256_estable():
    a = srt_to_contract(parse_srt_text(_MINIMO))["source"]["sha256"]
    b = srt_to_contract(parse_srt_text(_MINIMO))["source"]["sha256"]
    assert a == b and len(a) == 64


def test_contract_summary_correcto():
    doc = _rich_doc()
    s = srt_to_contract(doc)["summary"]
    assert s["n_cues"] == 2 and s["start_ms"] == 0 and s["end_ms"] == 3000
    assert s["duration_ms"] == 3000


def test_contract_diagnostics_estructura():
    txt = "1\n00:00:00,000 --> 00:00:01.500\ntexto\n"
    diags = srt_to_contract(parse_srt_text(txt))["diagnostics"]
    assert diags and set(diags[0]) == {"code", "severity", "message", "cue_position", "cue_index"}


def test_contract_ensure_ascii_false():
    payload = srt_to_contract(_rich_doc())
    dumped = json.dumps(payload, ensure_ascii=False)
    assert "ñ" in dumped


def test_contract_no_muta_document():
    doc = _rich_doc()
    before = _semantic_key(doc)
    srt_to_contract(doc)
    assert _semantic_key(doc) == before


def test_write_contract_atomico(tmp_path):
    dest = tmp_path / "out.json"
    write_srt_contract(_rich_doc(), dest)
    assert json.loads(dest.read_text(encoding="utf-8"))["version"] == 1
    assert not (tmp_path / "out.json.tmp").exists()


def test_write_contract_destino_explicito_no_sobreescribe(tmp_path):
    dest = tmp_path / "out.json"
    write_srt_contract(_rich_doc(), dest)
    with pytest.raises(SrtError):
        write_srt_contract(_rich_doc(), dest)


# ============================== CLI ==============================

_FIX = "revision/s36-srt-import/fixtures"


def test_cli_validate_valido_exit0(capsys):
    assert srt_tool.main(["validate", f"{_FIX}/valido_minimo.srt"]) == 0


def test_cli_validate_invalido_exit1():
    assert srt_tool.main(["validate", f"{_FIX}/invalido_timestamp.srt"]) == 1


def test_cli_validate_overlap_reporta(capsys):
    srt_tool.main(["validate", f"{_FIX}/overlap_warning.srt"])
    assert "overlap" in capsys.readouterr().out


def test_cli_no_imprime_texto_completo(tmp_path, capsys):
    p = tmp_path / "x.srt"
    p.write_bytes(b"1\n00:00:00,000 --> 00:00:01,000\nFRASE_PRIVADA_SECRETA\n")
    srt_tool.main(["validate", str(p)])
    assert "FRASE_PRIVADA_SECRETA" not in capsys.readouterr().out


def test_cli_no_imprime_ruta_absoluta(tmp_path, capsys):
    p = tmp_path / "x.srt"
    p.write_bytes(_MINIMO.encode())
    srt_tool.main(["validate", str(p)])
    assert str(tmp_path) not in capsys.readouterr().out


def test_cli_normalize_no_sobreescribe_input(tmp_path):
    p = tmp_path / "x.srt"
    p.write_bytes(_MINIMO.encode())
    # La CLI captura SrtError y devuelve exit 1; el input no debe tocarse.
    assert srt_tool.main(["normalize", str(p), "--output", str(p)]) == 1
    assert p.read_bytes() == _MINIMO.encode()


def test_cli_normalize_roundtrip(tmp_path):
    src = tmp_path / "x.srt"
    src.write_bytes(_rich_doc_bytes())
    dest = tmp_path / "norm.srt"
    assert srt_tool.main(["normalize", str(src), "--output", str(dest)]) == 0
    assert _semantic_key(load_srt(dest)) == _semantic_key(load_srt(src))


def test_cli_contract_json_valido(tmp_path):
    src = tmp_path / "x.srt"
    src.write_bytes(_MINIMO.encode())
    dest = tmp_path / "c.json"
    assert srt_tool.main(["contract", str(src), "--output", str(dest)]) == 0
    assert json.loads(dest.read_text(encoding="utf-8"))["summary"]["n_cues"] == 1


def test_cli_inspect_exit0(tmp_path):
    src = tmp_path / "x.srt"
    src.write_bytes(_MINIMO.encode())
    assert srt_tool.main(["inspect", str(src)]) == 0


def test_cli_error_sin_traceback(tmp_path, capsys):
    assert srt_tool.main(["validate", str(tmp_path / "no.srt")]) == 1
    assert "Traceback" not in capsys.readouterr().err


def _rich_doc_bytes():
    return (
        "1\n00:00:00,000 --> 00:00:01,500\nHola ñ\nsegunda\n\n"
        "2\n00:00:01,500 --> 00:00:03,000\n<i>x</i> 😀\n"
    ).encode()


# ============================== PROPIEDADES ==============================


@pytest.mark.parametrize(
    "ms", [0, 1, 7, 60_000, 61_001, 3_599_999, 3_600_000, 2_474_600, 359_999_999]
)
def test_prop_parse_format_identidad(ms):
    assert parse_timestamp(format_timestamp(ms)) == ms


@pytest.mark.parametrize("reindex", [False, True])
def test_prop_serialize_parse_conserva_semantica(reindex):
    doc = _rich_doc()
    out = parse_srt_text(serialize_srt(doc, reindex=reindex))
    assert [(c.start_ms, c.end_ms, c.lines) for c in out.cues] == [
        (c.start_ms, c.end_ms, c.lines) for c in doc.cues
    ]


def test_prop_validate_doble_igual():
    a = _cue(1, 0, 2000, ["a"], 0)
    b = _cue(3, 1500, 3000, ["b"], 1)
    d = _doc(a, b)
    assert validate_srt(d, video_duration_ms=1000) == validate_srt(d, video_duration_ms=1000)


def test_prop_srt_to_contract_no_muta():
    doc = _rich_doc()
    snapshot = json.dumps(srt_to_contract(doc), ensure_ascii=False)
    srt_to_contract(doc)
    assert json.dumps(srt_to_contract(doc), ensure_ascii=False) == snapshot
