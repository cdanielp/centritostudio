"""clipper_brain.py — Etapas LLM del clipper: segmentacion semantica y scoring.

Diseño completo en revision/fase-4/DISENO_CLIPPER.md.
Reutiliza brain.chat_json (alias publico de _dispatch) — sin importar privados.
"""

from __future__ import annotations

import math
import time

TIPOS_CLIP = ("corto", "largo")
MAX_SEG_POR_CHUNK = 8  # candidatos maximos que pide el prompt de segmentacion
SCORING_BATCH = 12  # candidatos por llamada de scoring

# Precios deepseek-chat USD por millon de tokens (cache-miss). Verificar vigentes.
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

_TIPOS_CORTO = '- "corto": punchline o gancho rapido que se consume en ~20-40 segundos.'
_TIPOS_LARGO = '- "largo": explicacion completa de UNA idea en ~55-100 segundos.'

_PROMPT_SEG = """\
Recibes la transcripcion de "{ctx}" dividida en frases numeradas.
Tu tarea es SEGMENTAR: encontrar tramos que sean unidades de idea completa
(planteamiento -> desarrollo -> remate) y clasificarlos.

Tipos:
{tipos}

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
    if not math.isfinite(v):
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


# ── Llamadas LLM ─────────────────────────────────────────────────────────────
# Reusan brain.chat_json (alias publico de _dispatch).
# Retry: tecnico (transporte, backoff 1.5s) + semantico (validacion vacia).
# Ver DISENO_CLIPPER.md §4.4.


def _tipos_block(tipos: str) -> str:
    """Construye el bloque de tipos para el prompt segun el filtro solicitado."""
    lines = []
    if tipos in ("ambos", "cortos"):
        lines.append(_TIPOS_CORTO)
    if tipos in ("ambos", "largos"):
        lines.append(_TIPOS_LARGO)
    return "\n".join(lines)


def _call_llm_with_retry(
    messages: list[dict],
    validate_fn,
    validate_args: tuple,
    etapa: str,
    chunk_idx: int | None,
) -> tuple[list[dict], list[dict]]:
    """Llama al LLM con retry tecnico + semantico. Devuelve (validos, tels)."""
    import brain  # noqa: PLC0415

    tels: list[dict] = []
    validos: list[dict] = []

    for attempt in range(2):
        t0 = time.time()
        try:
            raw, usage = brain.chat_json(messages)
            lat = round(time.time() - t0, 2)
            tels.append(telemetria(etapa, usage, lat, provider=brain.PROVIDER, chunk=chunk_idx))
            validos = validate_fn(raw, *validate_args)
            if validos:
                return validos, tels
            # Retry semantico
            if attempt == 0:
                motivo = f"{etapa}: respuesta vacia o todos los items invalidos"
                print(f"[clipper_brain] retry semantico {etapa} chunk={chunk_idx}: {motivo}")
                retry_note = (
                    f"Tu respuesta anterior fue invalida ({motivo}). "
                    "Responde SOLO el JSON del esquema."
                )
                messages = [
                    *messages,
                    {"role": "assistant", "content": str(raw)},
                    {"role": "user", "content": retry_note},
                ]
        except Exception as exc:
            lat = round(time.time() - t0, 2)
            print(
                f"[clipper_brain] {etapa} chunk={chunk_idx} intento {attempt + 1} "
                f"error: {type(exc).__name__}: {exc}"
            )
            if attempt == 0:
                time.sleep(1.5)

    return validos, tels


def segmentar_transcript(
    frases: list[dict], contexto: str = "", tipos: str = "ambos"
) -> tuple[list[dict], list[dict]]:
    """Etapa A: chunking + LLM + validacion. Devuelve (segmentos_validos, telemetrias)."""
    from clipper import chunk_frases  # noqa: PLC0415 lazy — evita circular

    if not frases:
        return [], []

    chunks = chunk_frases(frases)

    tipos_txt = _tipos_block(tipos)
    n_frases = len(frases)
    all_segs: list[dict] = []
    all_tels: list[dict] = []

    for chunk_idx, chunk in enumerate(chunks):
        lines = []
        for f in chunk:
            mm = int(f["s"] // 60)
            ss = int(f["s"] % 60)
            dur = round(f["e"] - f["s"], 1)
            lines.append(f"[f{f['idx']:03d}] ({mm:02d}:{ss:02d}, {dur}s) {f['text']}")
        frases_txt = "\n".join(lines)

        messages = [
            {"role": "system", "content": _SYSTEM_SEG},
            {
                "role": "user",
                "content": _PROMPT_SEG.format(
                    ctx=contexto or "video",
                    tipos=tipos_txt,
                    max_seg=MAX_SEG_POR_CHUNK,
                    frases=frases_txt,
                ),
            },
        ]

        validos, tels = _call_llm_with_retry(
            messages,
            validar_segmentacion,
            (n_frases,),
            "segmentacion",
            chunk_idx,
        )
        all_tels.extend(tels)
        if validos:
            all_segs.extend(validos)
            print(f"[clipper_brain] seg chunk {chunk_idx}: {len(validos)} candidatos")
        else:
            print(f"[clipper_brain] seg chunk {chunk_idx}: sin candidatos validos")

    return all_segs, all_tels


def puntuar_candidatos(candidatos: list[dict]) -> tuple[list[dict], list[dict]]:
    """Etapa B: scoring por lotes + validacion. Devuelve (scores_validos, telemetrias)."""
    if not candidatos:
        return [], []

    n_total = len(candidatos)
    all_scores: list[dict] = []
    all_tels: list[dict] = []

    for batch_start in range(0, n_total, SCORING_BATCH):
        batch = candidatos[batch_start : batch_start + SCORING_BATCH]
        batch_size = len(batch)
        batch_idx = batch_start // SCORING_BATCH

        lines = []
        for local_i, cand in enumerate(batch):
            global_i = batch_start + local_i
            dur = cand["dur_s"]
            texto = cand.get("texto", "(sin texto)")
            lines.append(f"[{global_i}] {cand['tipo']} | {dur:.1f}s | {texto}")
        cands_txt = "\n\n".join(lines)

        messages = [
            {"role": "system", "content": _SYSTEM_SCORE},
            {
                "role": "user",
                "content": _PROMPT_SCORE.format(candidatos=cands_txt),
            },
        ]

        validos, tels = _call_llm_with_retry(
            messages,
            validar_scoring,
            (n_total,),
            "scoring",
            batch_idx,
        )
        all_tels.extend(tels)

        # Filtrar a indices del batch actual (el LLM usa indices globales)
        batch_range = set(range(batch_start, batch_start + batch_size))
        validos_batch = [v for v in validos if v["c"] in batch_range]
        if validos_batch:
            all_scores.extend(validos_batch)
            print(
                f"[clipper_brain] score batch {batch_idx}: "
                f"{len(validos_batch)}/{batch_size} candidatos"
            )
        else:
            print(f"[clipper_brain] score batch {batch_idx}: sin scores validos")

    return all_scores, all_tels
