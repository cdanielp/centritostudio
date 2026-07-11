"""caption_qa.py — QA de transcripcion: detecta palabras mal transcritas ANTES del burn.

Capa opcional (regla 15: default off, no altera ninguna capa existente) que corre
sobre los words ya transcritos, antes del agrupado. Detectores puros en
caption_qa_detect.py (glosario, guion, heuristica); aqui vive la orquestacion,
la carga fail-open de glosario/guion, el auditor DeepSeek (opt-in, jamas reescribe
el transcript completo) y la aplicacion de correcciones.

Modos: "alertas" (solo escribe {stem}_caption_alerts.json, words intactos) y
"auto_seguro" (aplica SOLO confianza alta, en memoria). El words.json de disco NUNCA
se modifica: la edicion/marcado manual futuro siempre gana sobre el QA. Fail-open
total (regla de oro #8 extendida): si el QA falla, el render sale con la
transcripcion original — el consumidor (caption.py / auto.py) envuelve la llamada.
"""

from __future__ import annotations

import json
from pathlib import Path

from caption_qa_detect import PUNT, contexto_palabra, generar_alertas, normalizar

ROOT = Path(__file__).parent
TRANSCRIPTS = ROOT / "transcripts"
GLOSARIO_PATH = ROOT / "assets" / "glosario.json"

MODOS = ("alertas", "auto_seguro")

# Builtins minimos si assets/glosario.json falta o esta roto (fail-open).
TERMINOS_BUILTIN = [
    "ComfyUI",
    "Flux",
    "LoRA",
    "checkpoint",
    "workflow",
    "canvas",
    "custom nodes",
    "VAE",
    "CLIP",
    "GGUF",
    "safetensors",
    "Prompt Models",
    "DeepSeek",
]
VARIANTES_BUILTIN = {"confeti ui": "ComfyUI", "config ui": "ComfyUI", "kansas": "canvas"}


# ─────────────────────────────────────────────────────────────────────────────
# Carga de glosario y guion (fail-open)
# ─────────────────────────────────────────────────────────────────────────────


def cargar_glosario(path: str | Path | None = None) -> dict:
    """Glosario editable -> {terminos, normas, variantes}. Roto/ausente = builtins."""
    p = Path(path) if path else GLOSARIO_PATH
    terminos, variantes = TERMINOS_BUILTIN, VARIANTES_BUILTIN
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
        if isinstance(data.get("terminos"), list):
            terminos = [str(t).strip() for t in data["terminos"] if str(t).strip()]
        if isinstance(data.get("variantes"), dict):
            variantes = {str(k): str(v) for k, v in data["variantes"].items()}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        print(f"[caption-qa] glosario no legible ({p.name}) - se usan terminos builtin")
    return {
        "terminos": terminos,
        "normas": {normalizar(t): t for t in terminos},
        "variantes": {normalizar(k): v for k, v in variantes.items()},
    }


def cargar_guion(stem: str, path: str | Path | None = None) -> str | None:
    """Guion opcional: ruta explicita (--guion) o transcripts/{stem}_guion.txt.

    Acepta texto completo, resumen, temario o lista de terminos — todo se trata
    igual (vocabulario + contexto). Ausente o ilegible -> None (QA sigue sin guion).
    """
    candidato = Path(path) if path else TRANSCRIPTS / f"{stem}_guion.txt"
    try:
        if candidato.exists():
            return candidato.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        print(
            f"[caption-qa] guion no legible ({candidato.name}: {type(exc).__name__}) "
            "- QA sigue sin guion"
        )
        return None
    if path:
        print(f"[caption-qa] guion no encontrado: {path} - QA sigue sin guion")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Auditor DeepSeek (opt-in, fail-open) — audita alertas, jamas reescribe todo
# ─────────────────────────────────────────────────────────────────────────────

_PROMPT_AUDITOR = """\
Eres corrector de transcripciones de video en espanol sobre IA generativa.
Vocabulario tecnico esperado: {terminos}.
{guion}Frases sospechosas (la palabra dudosa va entre <<...>>):
{items}

Por cada item devuelve: "i" (indice), "correccion" (la palabra correcta, o null si
la transcripcion original ya es correcta) y "seguro" (true solo si no hay duda).
NO corrijas palabras comunes correctas; solo errores evidentes de transcripcion.
JSON: {{"veredictos":[{{"i":int,"correccion":str|null,"seguro":bool}},...]}}\
"""


def _aplicar_veredicto(alerta: dict, veredicto: dict) -> None:
    """Ajusta una alerta segun el veredicto del auditor (muta la alerta)."""
    corr = veredicto.get("correccion")
    if corr and str(corr).strip():
        alerta["sugerencia"] = str(corr).strip()
        alerta["fuente"] = "deepseek"
        if veredicto.get("seguro") is True:
            alerta["confianza"], alerta["aplicar_auto"] = "alta", True
        else:
            alerta["confianza"] = "media"
        alerta["motivo"] += " | confirmada por DeepSeek"
    elif veredicto.get("seguro") is True:
        alerta["confianza"], alerta["aplicar_auto"] = "baja", False
        alerta["motivo"] += " | DeepSeek: transcripcion correcta"


def auditar_con_llm(
    alertas: list[dict], words: list[dict], glosario: dict, guion_texto: str | None = None
) -> list[dict]:
    """DeepSeek como AUDITOR de las alertas no-altas. Fail-open: alertas intactas."""
    dudosas = [a for a in alertas if a["confianza"] != "alta"]
    if not dudosas:
        return alertas
    try:
        import brain  # noqa: PLC0415

        items = "\n".join(
            f"[{i}] {contexto_palabra(words, round(float(a['timestamp']), 3))} "
            f"(sugerencia actual: {a['sugerencia'] or 'ninguna'})"
            for i, a in enumerate(dudosas)
        )
        guion = f"Guion de referencia:\n{guion_texto[:1500]}\n\n" if guion_texto else ""
        prompt = _PROMPT_AUDITOR.format(
            terminos=", ".join(glosario["terminos"]), guion=guion, items=items
        )
        raw, _usage = brain.chat_json([{"role": "user", "content": prompt}])
        for v in raw.get("veredictos", []):
            i = v.get("i")
            if isinstance(i, int) and 0 <= i < len(dudosas):
                _aplicar_veredicto(dudosas[i], v)
    except Exception as exc:
        print(
            f"[caption-qa] auditor LLM fallo ({type(exc).__name__}) "
            "- alertas deterministas intactas"
        )
    return alertas


# ─────────────────────────────────────────────────────────────────────────────
# Aplicacion (auto_seguro) y sidecar
# ─────────────────────────────────────────────────────────────────────────────


def _sufijo_puntuacion(token: str) -> str:
    """Puntuacion final de un token ('archivo,' -> ',') para conservarla al corregir."""
    i = len(token)
    while i > 0 and token[i - 1] in PUNT:
        i -= 1
    return token[i:]


def aplicar_correcciones(words: list[dict], alertas: list[dict]) -> tuple[list[dict], int]:
    """Aplica SOLO alertas de confianza alta con aplicar_auto y sugerencia.

    Conserva timestamps: el span corregido ocupa [s del primer token, e del ultimo];
    los demas words no se tocan. No muta la lista de entrada ni escribe a disco.
    """
    aplicables = {
        round(float(a["timestamp"]), 3): a
        for a in alertas
        if a["confianza"] == "alta" and a["aplicar_auto"] and a["sugerencia"]
    }
    if not aplicables:
        return list(words), 0
    resultado: list[dict] = []
    aplicadas, i = 0, 0
    while i < len(words):
        a = aplicables.get(round(float(words[i]["s"]), 3))
        n = int(a.get("n_palabras", 1)) if a else 1
        if a and i + n <= len(words):
            ultimo = words[i + n - 1]
            resultado.append(
                {
                    "w": a["sugerencia"] + _sufijo_puntuacion(ultimo["w"]),
                    "s": words[i]["s"],
                    "e": ultimo["e"],
                    "prob": min(w.get("prob", 1.0) for w in words[i : i + n]),
                }
            )
            a["aplicada"] = True
            aplicadas += 1
            i += n
        else:
            resultado.append(dict(words[i]))
            i += 1
    return resultado, aplicadas


def escribir_alertas(
    stem: str, modo: str, alertas: list[dict], aplicadas: int, out_dir: Path | None = None
) -> Path | None:
    """Sidecar {stem}_caption_alerts.json. Fail-open: su fallo jamas tumba el render."""
    d = Path(out_dir) if out_dir else TRANSCRIPTS
    try:
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{stem}_caption_alerts.json"
        data = {
            "stem": stem,
            "modo": modo,
            "n_alertas": len(alertas),
            "aplicadas": aplicadas,
            "pendientes": len(alertas) - aplicadas,
            "alertas": alertas,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
    except OSError as exc:
        print(f"[caption-qa] no se pudo escribir alertas ({exc}) - render sigue")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Puntos de entrada
# ─────────────────────────────────────────────────────────────────────────────


def ejecutar_qa(
    words: list[dict],
    stem: str,
    modo: str = "alertas",
    guion_path: str | Path | None = None,
    glosario_path: str | Path | None = None,
    usar_llm: bool = False,
    out_dir: Path | None = None,
) -> tuple[list[dict], dict]:
    """Punto de entrada del Caption QA. Devuelve (words_qa, resumen).

    modo="alertas": los words de salida son LA MISMA lista de entrada (cero cambios).
    modo="auto_seguro": aplica solo confianza alta; el resto queda como pendiente.
    El words.json de disco nunca se modifica desde aqui (manual futuro gana).
    """
    if modo not in MODOS:
        raise ValueError(f"modo '{modo}' invalido; opciones: {MODOS}")
    glosario = cargar_glosario(glosario_path)
    guion_texto = cargar_guion(stem, guion_path)
    alertas = generar_alertas(words, glosario, guion_texto)
    if usar_llm and alertas:
        alertas = auditar_con_llm(alertas, words, glosario, guion_texto)
    if modo == "auto_seguro":
        words_qa, aplicadas = aplicar_correcciones(words, alertas)
    else:
        words_qa, aplicadas = words, 0
    path = escribir_alertas(stem, modo, alertas, aplicadas, out_dir)
    resumen = {
        "n_alertas": len(alertas),
        "aplicadas": aplicadas,
        "pendientes": len(alertas) - aplicadas,
        "con_guion": guion_texto is not None,
        "alerts_file": path.name if path else None,
    }
    return words_qa, resumen


def qa_para_reporte(stem: str, words_path: Path | None = None) -> dict | None:
    """Resumen solo-lectura para el REPORTE.md del Modo Automatico. Fail-open total.

    Corre en modo "alertas" (jamas modifica nada); devuelve el resumen o None.
    """
    try:
        p = words_path or TRANSCRIPTS / f"{stem}_words.json"
        if not p.exists():
            return None
        words = json.loads(p.read_text(encoding="utf-8")).get("words", [])
        if not words:
            return None
        _words, resumen = ejecutar_qa(words, stem, modo="alertas")
        return resumen
    except Exception as exc:
        print(f"[caption-qa] reporte fail-open: {type(exc).__name__}")
        return None
