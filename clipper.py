"""clipper.py — Clipper viral: segmenta, puntua, selecciona y corta clips SIN captions.

Diseño completo en revision/fase-4/DISENO_CLIPPER.md. En esta sesion solo se
implementa el scoring determinista (duracion + total ponderado); la orquestacion
son stubs (F4 impl). Orden recomendado del pipeline: depurar ANTES del clipper.
"""

from __future__ import annotations

from pathlib import Path

CLIPS_DIR = Path(__file__).parent / "output" / "clips"

# Duraciones por tipo en segundos (decision del arquitecto; obj largo = punto medio 60-90)
DUR = {
    "corto": {"min": 20.0, "obj": 30.0, "max": 40.0},
    "largo": {"min": 55.0, "obj": 75.0, "max": 100.0},
}

# Pesos de la rubrica (suman 1.0). "duracion" la calcula score_duracion, NUNCA el LLM.
PESOS = {"hook": 0.30, "autocontenido": 0.25, "densidad": 0.20, "cierre": 0.15, "duracion": 0.10}

SCORE_MIN = 60  # umbral de entrega (calibrar con clase real en implementacion)
MAX_CLIPS = 3
SOLAPE_MAX = 0.30  # solape maximo permitido entre clips entregados
SEPARACION_MIN_S = 15.0  # separacion minima entre clips entregados

# Chunking de segmentacion (densidad medida en videos reales: ~2.66 palabras/s)
CHUNK_WORDS = 2500  # ~15.6 min de voz por chunk
OVERLAP_WORDS = 300  # ~113 s > clip largo maximo (100 s): nada queda partido
IOU_DUP = 0.6  # rangos de palabra con IoU mayor = candidatos duplicados

# Construccion de frases (unidad atomica de la segmentacion)
FRASE_PAUSA_S = 0.7  # pausa que cierra frase (ademas de . ! ? ...)
FRASE_MAX_WORDS = 30  # cierre forzado cuando Whisper no puntua

# Aire en los cortes, acotado por la palabra vecina real (ver DISENO §2)
PAD_INI_S = 0.15
PAD_FIN_S = 0.35


# ── Scoring determinista (implementado: es contrato, los tests lo fijan) ────


def score_duracion(dur_s: float, tipo: str) -> int:
    """Ajuste de duracion 0-100: 100 en el objetivo, 50 en los bordes, 0 fuera de rango."""
    d = DUR[tipo]
    if dur_s < d["min"] or dur_s > d["max"]:
        return 0
    if dur_s <= d["obj"]:
        frac = (d["obj"] - dur_s) / (d["obj"] - d["min"])
    else:
        frac = (dur_s - d["obj"]) / (d["max"] - d["obj"])
    return round(100 - 50 * frac)


def calcular_score_total(subscores: dict, dur_s: float, tipo: str) -> int:
    """Score final 0-100: suma ponderada en Python. El LLM jamas calcula totales."""
    total = sum(subscores[k] * PESOS[k] for k in ("hook", "autocontenido", "densidad", "cierre"))
    total += score_duracion(dur_s, tipo) * PESOS["duracion"]
    return round(total)


# ── Orquestacion (stubs — sesion de implementacion F4) ──────────────────────


def build_frases(words: list[dict]) -> list[dict]:
    """Divide words en frases: [{"idx","wi","wf","s","e","text"}] con indices GLOBALES.

    Corta por puntuacion final (. ! ? ...), pausa > FRASE_PAUSA_S o FRASE_MAX_WORDS.
    """
    raise NotImplementedError("F4: se implementa en la sesion de implementacion")


def chunk_frases(frases: list[dict]) -> list[list[dict]]:
    """Parte frases en ventanas de ~CHUNK_WORDS palabras con solape OVERLAP_WORDS."""
    raise NotImplementedError("F4: se implementa en la sesion de implementacion")


def dedup_segmentos(segmentos: list[dict]) -> list[dict]:
    """Fusiona duplicados del solape entre chunks (IoU de rango de palabras > IOU_DUP)."""
    raise NotImplementedError("F4: se implementa en la sesion de implementacion")


def seleccionar_clips(candidatos: list[dict]) -> tuple[list[dict], list[dict]]:
    """Aplica SCORE_MIN, solape <= SOLAPE_MAX, separacion y MAX_CLIPS.

    Devuelve (elegidos, descartados_con_motivo).
    """
    raise NotImplementedError("F4: se implementa en la sesion de implementacion")


def cortar_clip(video_path: Path, start: float, end: float, output: Path) -> None:
    """Corta [start, end] re-encodeando via depurador.run_edl con EDL de 1 segmento."""
    raise NotImplementedError("F4: se implementa en la sesion de implementacion")


def exportar_transcript_clip(words: list[dict], wi: int, wf: int, clip_stem: str) -> None:
    """Escribe {clip_stem}_words.json y _groups.json re-basados a t=0 (regla de oro #4)."""
    raise NotImplementedError("F4: se implementa en la sesion de implementacion")


def generar_clips(video_path: Path, words: list[dict], tipos: str = "ambos") -> dict:
    """Pipeline completo del clipper. Devuelve el dict de clips.json.

    {"clips": [...], "descartados": [...], "telemetria": [...], "error": str|None}
    Nunca crashea por el LLM y nunca inventa clips: sin candidatos validos devuelve
    clips=[] con mensaje accionable (DISENO_CLIPPER.md §4.4).
    """
    raise NotImplementedError("F4: se implementa en la sesion de implementacion")
