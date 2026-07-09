"""clipper_brain.py — Etapas LLM del clipper: segmentacion semantica y scoring.

Diseño completo en revision/fase-4/DISENO_CLIPPER.md. En esta sesion solo se
implementa el contrato de validacion JSON; las llamadas LLM son stubs (F4 impl).
"""

from __future__ import annotations

import math

TIPOS_CLIP = ("corto", "largo")
MAX_SEG_POR_CHUNK = 8  # candidatos maximos que pide el prompt de segmentacion
SCORING_BATCH = 12  # candidatos por llamada de scoring

# Precios deepseek-chat USD por millon de tokens (cache-miss).
# VERIFICAR precios vigentes en la sesion de implementacion.
PRECIO_INPUT_USD_M = 0.27
PRECIO_OUTPUT_USD_M = 1.10

# ── Esquemas de respuesta (contrato con el LLM; validar_* los hace cumplir) ──
SCHEMA_SEGMENTACION = {
    "segments": [{"f_ini": "int", "f_fin": "int", "tipo": "corto|largo", "tema": "str 5 palabras"}]
}
SCHEMA_SCORING = {
    "clips": [
        {
            "c": "int",
            "hook": "int 0-100",
            "autocontenido": "int 0-100",
            "densidad": "int 0-100",
            "cierre": "int 0-100",
            "titulo": "str",
            "razon": "str",
        }
    ]
}

_SUBSCORES = ("hook", "autocontenido", "densidad", "cierre")

_SYSTEM_SEG = (
    "Eres editor senior de clips virales en espanol. "
    "Respondes SOLO con JSON valido, sin texto adicional."
)

_PROMPT_SEG = """\
Recibes la transcripcion de "{ctx}" dividida en frases numeradas.
Tu tarea es SEGMENTAR: encontrar tramos que sean unidades de idea completa
(planteamiento -> desarrollo -> remate) y clasificarlos.

Tipos:
- "corto": punchline o gancho rapido que se consume en ~20-40 segundos.
- "largo": explicacion completa de UNA idea en ~55-100 segundos.

Reglas:
- Un segmento empieza donde ARRANCA la idea, nunca a mitad de otra idea.
- Un segmento debe entenderse sin ver el resto de la clase.
- Un "corto" puede vivir dentro de un "largo" (solape permitido entre candidatos).
- Usa la duracion de cada frase para acercarte al rango del tipo.
- Maximo {max_seg} segmentos. Si ningun tramo es digno, devuelve lista vacia.
- Usa SOLO los indices de frase dados. No inventes indices.

Frases (indice | inicio mm:ss | dur s | texto):
{frases}

JSON: {{"segments":[{{"f_ini":int,"f_fin":int,"tipo":"corto"|"largo",\
"tema":"resumen 5 palabras"}},...]}}\
"""

_SYSTEM_SCORE = (
    "Eres jurado experto de clips virales en espanol. "
    "Respondes SOLO con JSON valido, sin texto adicional."
)

_PROMPT_SCORE = """\
Recibes candidatos a clip extraidos de una clase. Puntua CADA candidato
en 4 criterios independientes, 0-100 cada uno:

- "hook": las primeras ~10 palabras generan tension, pregunta o promesa POR SI SOLAS.
  90+ = imposible dejar de ver. 50 = neutro. <30 = arranque plano o administrativo.
- "autocontenido": se entiende sin contexto externo. Penaliza fuerte "como vimos antes",
  "esto que mencione", pronombres sin antecedente, referencias a material no visible.
- "densidad": ensena o revela algo concreto (dato, tecnica, numero, contraste, error comun).
- "cierre": termina en punchline, dato o llamada clara. Penaliza si se desvanece
  o corta a mitad de argumento.

Ademas por candidato:
- "titulo": 4-8 palabras estilo redes, sin comillas ni emojis.
- "razon": UNA linea (<120 caracteres): por que funciona (o por que no).

NO calcules promedios ni score total: eso lo hace el sistema.
Se estricto: en una clase normal la mayoria de los candidatos merece <60 en hook.

Candidatos (indice | tipo | duracion | texto completo):
{candidatos}

JSON: {{"clips":[{{"c":int,"hook":int,"autocontenido":int,"densidad":int,"cierre":int,\
"titulo":str,"razon":str}},...]}}\
"""


# ── Validacion (contrato: nunca lanza, descarta lo invalido) ─────────────────


def _indice(v: object, n: int) -> int | None:
    """Devuelve v como indice entero exacto en [0, n); None si no lo es."""
    if isinstance(v, bool):
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if not isinstance(v, int):
        return None
    return v if 0 <= v < n else None


def _subscore(v: object) -> int | None:
    """Devuelve v como subscore 0-100 (float se redondea); None si no es numerico valido."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if not math.isfinite(v):  # json.loads acepta NaN/Infinity: no deben tumbar la validacion
        return None
    n = round(v)
    return n if 0 <= n <= 100 else None


def _texto(v: object, default: str, tope: int) -> str:
    """Campo cosmetico: str limpio truncado a tope, o default si falta/es invalido."""
    if isinstance(v, str) and v.strip():
        return v.strip()[:tope]
    return default


def validar_segmentacion(raw: dict, n_frases: int) -> list[dict]:
    """Valida la respuesta de segmentacion; descarta items malformados, nunca lanza."""
    if not isinstance(raw, dict) or not isinstance(raw.get("segments"), list):
        return []
    validos: list[dict] = []
    for item in raw["segments"]:
        if not isinstance(item, dict):
            continue
        f_ini = _indice(item.get("f_ini"), n_frases)
        f_fin = _indice(item.get("f_fin"), n_frases)
        if f_ini is None or f_fin is None or f_ini > f_fin:
            continue
        if item.get("tipo") not in TIPOS_CLIP:
            continue
        validos.append(
            {
                "f_ini": f_ini,
                "f_fin": f_fin,
                "tipo": item["tipo"],
                "tema": _texto(item.get("tema"), "(sin tema)", 80),
            }
        )
    return validos


def validar_scoring(raw: dict, n_candidatos: int) -> list[dict]:
    """Valida la respuesta de scoring; descarta items malformados y 'c' duplicados."""
    if not isinstance(raw, dict) or not isinstance(raw.get("clips"), list):
        return []
    validos: list[dict] = []
    vistos: set[int] = set()
    for item in raw["clips"]:
        if not isinstance(item, dict):
            continue
        c = _indice(item.get("c"), n_candidatos)
        if c is None or c in vistos:
            continue
        subs = {k: _subscore(item.get(k)) for k in _SUBSCORES}
        if any(v is None for v in subs.values()):
            continue
        vistos.add(c)
        validos.append(
            {
                "c": c,
                **subs,
                "titulo": _texto(item.get("titulo"), "Clip sin titulo", 80),
                "razon": _texto(item.get("razon"), "(sin razon)", 160),
            }
        )
    return validos


# ── Telemetria ────────────────────────────────────────────────────────────────


def telemetria(
    etapa: str, usage: dict, latency_s: float, provider: str = "", chunk: int | None = None
) -> dict:
    """Registro de una llamada LLM con costo estimado en USD."""
    costo = (
        usage.get("prompt", 0) / 1e6 * PRECIO_INPUT_USD_M
        + usage.get("completion", 0) / 1e6 * PRECIO_OUTPUT_USD_M
    )
    return {
        "provider": provider,
        "etapa": etapa,
        "chunk": chunk,
        "tokens": usage,
        "latency_s": round(latency_s, 2),
        "costo_usd": round(costo, 5),
    }


# ── Llamadas LLM (stubs — sesion de implementacion F4) ──────────────────────
# Reusan brain.chat_json (alias publico de _dispatch, se promueve al implementar):
# retry tecnico (transporte, backoff 1.5s) + retry semantico (validacion vacia
# reenvia el prompt con el motivo). Ver DISENO_CLIPPER.md §4.4.


def segmentar_transcript(
    frases: list[dict], contexto: str = "", tipos: str = "ambos"
) -> tuple[list[dict], list[dict]]:
    """Etapa A: chunking + LLM + validacion. Devuelve (segmentos_validos, telemetrias)."""
    raise NotImplementedError("F4: se implementa en la sesion de implementacion")


def puntuar_candidatos(candidatos: list[dict]) -> tuple[list[dict], list[dict]]:
    """Etapa B: scoring por lotes + validacion. Devuelve (scores_validos, telemetrias)."""
    raise NotImplementedError("F4: se implementa en la sesion de implementacion")
