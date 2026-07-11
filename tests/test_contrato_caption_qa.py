"""Tests de contrato del Caption QA (S33): caption_qa + caption_qa_detect.

Contratos verificados (spec B8 de la sesion 33):
- El glosario detecta terminos mal escritos (variante conocida + similitud).
- El guion opcional sugiere correcciones (contexto de bigrama precedente).
- Los stopwords NUNCA se corrigen ni generan alertas sin razon.
- Los timestamps se conservan al aplicar correcciones (span = [s primero, e ultimo]).
- Modo "alertas" NO modifica el transcript (misma lista, cero cambios).
- Modo "auto_seguro" aplica SOLO confianza alta.
- El auditor DeepSeek es fail-open (si revienta, las alertas quedan intactas).
- El sidecar {stem}_caption_alerts.json se genera con el esquema completo.
- El render no falla si el QA falla (wrapper fail-open de caption.py).
- Glosario roto/ausente cae a builtins (fail-open del loader).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import caption_qa as cq
import caption_qa_detect as cqd


def _w(texto: str, s: float, prob: float = 0.95) -> dict:
    return {"w": texto, "s": s, "e": round(s + 0.3, 3), "prob": prob}


def _words_confeti() -> list[dict]:
    """Transcript con el dolor real: 'confeti UI' en vez de 'ComfyUI'."""
    return [
        _w("hoy", 0.0),
        _w("abrimos", 0.5),
        _w("confeti", 1.0),
        _w("UI,", 1.4),
        _w("para", 1.8),
        _w("editar", 2.2),
    ]


def _glosario_builtin() -> dict:
    return cq.cargar_glosario(Path("no_existe_glosario.json"))


# ── glosario: variantes conocidas y similitud ────────────────────────────────


def test_variante_conocida_multitoken():
    alertas = cqd.generar_alertas(_words_confeti(), _glosario_builtin())
    assert len(alertas) == 1
    a = alertas[0]
    assert a["texto_detectado"] == "confeti UI,"
    assert a["sugerencia"] == "ComfyUI"
    assert a["confianza"] == "alta" and a["aplicar_auto"] is True
    assert a["fuente"] == "glosario" and a["n_palabras"] == 2
    assert a["timestamp"] == 1.0


def test_similitud_detecta_termino_mal_escrito():
    words = [_w("cargamos", 0.0), _w("el", 0.5), _w("checpoint", 1.0), _w("base", 1.5)]
    alertas = cqd.generar_alertas(words, _glosario_builtin())
    assert len(alertas) == 1
    a = alertas[0]
    assert a["sugerencia"] == "checkpoint"
    assert a["confianza"] == "alta", "similitud 0.947 >= FUZZY_ALTA"
    assert a["fuente"] == "glosario"


def test_kansas_via_variante_no_similitud():
    """'Kansas' vs 'canvas' (0.667) NO pasa el umbral fuzzy: lo caza la variante curada."""
    words = [_w("dibujamos", 0.0), _w("en", 0.5), _w("el", 0.8), _w("Kansas", 1.1)]
    alertas = cqd.generar_alertas(words, _glosario_builtin())
    assert len(alertas) == 1
    assert alertas[0]["sugerencia"] == "canvas"
    assert alertas[0]["confianza"] == "alta"


# ── guion opcional ───────────────────────────────────────────────────────────


def test_guion_sugiere_correccion_por_contexto():
    guion = "vamos a abrir el archivo del proyecto"
    words = [_w("vamos", 0.0), _w("a", 0.4), _w("abrir", 0.8), _w("el", 1.2), _w("aflicjo", 1.6)]
    alertas = cqd.detectar_guion(words, guion, _glosario_builtin())
    assert len(alertas) == 1
    a = alertas[0]
    assert a["texto_detectado"] == "aflicjo"
    assert a["sugerencia"] == "archivo"
    assert a["fuente"] == "guion"
    assert a["confianza"] == "media", "guion sugiere, no auto-aplica"
    assert a["aplicar_auto"] is False


def test_guion_no_alerta_palabras_correctas():
    guion = "vamos a abrir el archivo del proyecto"
    words = [_w("vamos", 0.0), _w("a", 0.4), _w("abrir", 0.8), _w("el", 1.2), _w("archivo", 1.6)]
    assert cqd.detectar_guion(words, guion, _glosario_builtin()) == []


# ── stopwords protegidos ─────────────────────────────────────────────────────


def test_stopwords_no_se_corrigen_sin_razon():
    """Stopwords y tokens cortos jamas generan alertas, ni con prob baja."""
    words = [_w("en", 0.0, prob=0.2), _w("un", 0.5, prob=0.2), _w("con", 1.0, prob=0.1)]
    assert cqd.generar_alertas(words, _glosario_builtin()) == []


# ── modos ────────────────────────────────────────────────────────────────────


def test_modo_alertas_no_modifica_transcript(tmp_path):
    words = _words_confeti()
    respaldo = copy.deepcopy(words)
    words_qa, resumen = cq.ejecutar_qa(words, "demo", modo="alertas", out_dir=tmp_path)
    assert words_qa is words, "modo alertas devuelve LA MISMA lista"
    assert words == respaldo, "cero mutacion"
    assert resumen["n_alertas"] == 1 and resumen["aplicadas"] == 0


def test_auto_seguro_aplica_solo_alta(tmp_path):
    guion = tmp_path / "g.txt"
    guion.write_text("vamos a abrir el archivo del proyecto", encoding="utf-8")
    words = _words_confeti() + [
        _w("abrir", 3.0),
        _w("el", 3.4),
        _w("aflicjo", 3.8),
    ]
    words_qa, resumen = cq.ejecutar_qa(
        words, "demo", modo="auto_seguro", guion_path=guion, out_dir=tmp_path
    )
    textos = [w["w"] for w in words_qa]
    assert "ComfyUI," in textos, "alta aplicada (conserva la coma original)"
    assert "aflicjo" in textos, "media NO aplicada (queda pendiente)"
    assert resumen["aplicadas"] == 1
    assert resumen["pendientes"] == resumen["n_alertas"] - 1


def test_timestamps_se_conservan(tmp_path):
    words = _words_confeti()
    words_qa, _ = cq.ejecutar_qa(words, "demo", modo="auto_seguro", out_dir=tmp_path)
    assert len(words_qa) == len(words) - 1, "el span de 2 tokens se fusiona en 1"
    corregida = next(w for w in words_qa if w["w"] == "ComfyUI,")
    assert corregida["s"] == 1.0, "start del primer token del span"
    assert corregida["e"] == words[3]["e"], "end del ultimo token del span"
    for original, nueva in zip(words[:2], words_qa[:2], strict=False):
        assert original == nueva, "vecinos intactos"
    assert words_qa[-2:] == words[-2:], "resto del transcript intacto"


def test_modo_invalido_lanza_error(tmp_path):
    try:
        cq.ejecutar_qa([], "demo", modo="turbo", out_dir=tmp_path)
        raise AssertionError("debio lanzar ValueError")
    except ValueError:
        pass


# ── auditor DeepSeek (fail-open) ─────────────────────────────────────────────


def test_deepseek_fail_open(tmp_path, monkeypatch):
    import brain

    def _boom(_messages):
        raise RuntimeError("API caida")

    monkeypatch.setattr(brain, "chat_json", _boom)
    guion = tmp_path / "g.txt"
    guion.write_text("vamos a abrir el archivo del proyecto", encoding="utf-8")
    words = [_w("abrir", 0.8), _w("el", 1.2), _w("aflicjo", 1.6)]
    # No debe lanzar: las alertas deterministas quedan intactas
    words_qa, resumen = cq.ejecutar_qa(
        words, "demo", modo="alertas", guion_path=guion, usar_llm=True, out_dir=tmp_path
    )
    assert words_qa is words
    assert resumen["n_alertas"] == 1


def test_deepseek_confirma_sube_confianza(tmp_path, monkeypatch):
    import brain

    def _fake(_messages):
        return {"veredictos": [{"i": 0, "correccion": "archivo", "seguro": True}]}, {}

    monkeypatch.setattr(brain, "chat_json", _fake)
    guion = tmp_path / "g.txt"
    guion.write_text("vamos a abrir el archivo del proyecto", encoding="utf-8")
    words = [_w("abrir", 0.8), _w("el", 1.2), _w("aflicjo", 1.6)]
    words_qa, resumen = cq.ejecutar_qa(
        words, "demo", modo="auto_seguro", guion_path=guion, usar_llm=True, out_dir=tmp_path
    )
    assert resumen["aplicadas"] == 1, "confirmada por DeepSeek -> alta -> aplicada"
    assert any(w["w"] == "archivo" for w in words_qa)


# ── sidecar ──────────────────────────────────────────────────────────────────


def test_caption_alerts_json_se_genera(tmp_path):
    _, resumen = cq.ejecutar_qa(_words_confeti(), "demo", modo="alertas", out_dir=tmp_path)
    path = tmp_path / "demo_caption_alerts.json"
    assert path.exists()
    assert resumen["alerts_file"] == path.name
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["n_alertas"] == 1 and data["modo"] == "alertas"
    campos = set(data["alertas"][0])
    assert {
        "timestamp",
        "texto_detectado",
        "sugerencia",
        "confianza",
        "motivo",
        "fuente",
        "aplicar_auto",
        "aplicada",
    } <= campos


# ── fail-open: glosario y render ─────────────────────────────────────────────


def test_glosario_roto_cae_a_builtins(tmp_path):
    roto = tmp_path / "glosario.json"
    roto.write_text("{esto no es json", encoding="utf-8")
    glosario = cq.cargar_glosario(roto)
    assert "ComfyUI" in glosario["terminos"]
    assert glosario["variantes"]["confeti ui"] == "ComfyUI"


def test_glosario_custom_del_usuario(tmp_path):
    custom = tmp_path / "glosario.json"
    custom.write_text(
        json.dumps({"terminos": ["HyperFrames"], "variantes": {"hiper freims": "HyperFrames"}}),
        encoding="utf-8",
    )
    glosario = cq.cargar_glosario(custom)
    assert glosario["terminos"] == ["HyperFrames"]
    words = [_w("uso", 0.0), _w("hiper", 0.5), _w("freims", 1.0)]
    alertas = cqd.detectar_variantes(words, glosario)
    assert len(alertas) == 1 and alertas[0]["sugerencia"] == "HyperFrames"


def test_render_no_falla_si_qa_falla(monkeypatch):
    """El wrapper de caption.py devuelve la transcripcion original si el QA revienta."""
    import caption
    import caption_qa

    def _boom(*_args, **_kwargs):
        raise RuntimeError("QA roto")

    monkeypatch.setattr(caption_qa, "ejecutar_qa", _boom)
    transcript = {"words": _words_confeti(), "language": "es"}
    resultado = caption._aplicar_caption_qa(transcript, "demo", {"modo": "auto_seguro"})
    assert resultado is transcript, "fail-open: transcripcion original intacta"


def test_qa_para_reporte_fail_open(tmp_path, monkeypatch):
    monkeypatch.setattr(cq, "TRANSCRIPTS", tmp_path)
    assert cq.qa_para_reporte("no_existe") is None
    words_path = tmp_path / "demo_words.json"
    words_path.write_text(
        json.dumps({"words": _words_confeti(), "language": "es"}), encoding="utf-8"
    )
    resumen = cq.qa_para_reporte("demo")
    assert resumen is not None and resumen["n_alertas"] == 1
    assert resumen["aplicadas"] == 0, "reporte es solo-lectura (modo alertas)"


def test_reporte_md_incluye_caption_qa():
    import auto

    clips_info = [
        {
            "archivo": "clip1.mp4",
            "titulo": "Demo",
            "score": 80,
            "dur_s": 30.0,
            "avisos": [],
            "qa": {
                "n_alertas": 2,
                "aplicadas": 0,
                "pendientes": 2,
                "alerts_file": "clip1_caption_alerts.json",
            },
        }
    ]
    md = auto.generar_reporte_md("demo", clips_info, {"fecha": "hoy"})
    assert "Caption QA: 2 deteccion(es)" in md
    assert "2 pendientes de revision" in md
    assert "clip1_caption_alerts.json" in md
