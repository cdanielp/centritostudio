"""brain.py — Cerebro editorial con provider LLM intercambiable."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

PROVIDER = os.getenv("LLM_PROVIDER", "deepseek")
TRANSCRIPTS = Path(__file__).parent / "transcripts"

_SYSTEM = (
    "Eres editor de video experto en redes sociales en espanol. "
    "Analizas grupos de subtitulos y marcas keywords y emojis. "
    "Responde SOLO con JSON valido, sin texto adicional."
)

_PROMPT = """\
Analiza {n} grupos del video "{ctx}". Por cada grupo devuelve:
- "g": indice 0-based
- "kw": indice de la palabra clave dentro de g["words"] (0-based) o null.
  Solo sustantivos, verbos fuertes, numeros, marcas propias.
  NUNCA articulos ni conectores: el,la,los,las,un,una,de,en,que,y,o,a,con,por,para,se,me,te,le
- "emoji": emoji visual o null. Maximo {max_e} grupos con emoji.

Grupos (indice: palabras):
{txt}

JSON: {{"groups":[{{"g":int,"kw":int|null,"emoji":str|null}},...]}}\
"""


def _call_deepseek(messages: list[dict]) -> tuple[dict, dict]:
    """Llama a DeepSeek via API OpenAI-compatible."""
    from openai import OpenAI

    key = os.getenv("DEEPSEEK_API_KEY", "")
    if not key:
        raise ValueError("DEEPSEEK_API_KEY no configurada en .env")
    client = OpenAI(api_key=key, base_url="https://api.deepseek.com")
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.3,
        timeout=60,
    )
    usage = {
        "prompt": resp.usage.prompt_tokens,
        "completion": resp.usage.completion_tokens,
        "total": resp.usage.total_tokens,
    }
    return json.loads(resp.choices[0].message.content), usage


def _call_mock(messages: list[dict]) -> tuple[dict, dict]:
    """Provider mock — genera datos de prueba sin key. Soporta brain + clipper."""
    content = messages[-1]["content"] if messages else ""
    usage = {"prompt": 0, "completion": 0, "total": 0}
    # Clipper: segmentacion
    if '"segments"' in content or "SEGMENTAR" in content:
        lines = [ln for ln in content.splitlines() if ln.startswith("[f") and ") " in ln]
        if len(lines) >= 2:
            seg = {"f_ini": 0, "f_fin": len(lines) - 1, "tipo": "largo", "tema": "mock completo"}
            return {"segments": [seg]}, usage
        return {"segments": []}, usage
    # Clipper: scoring
    if '"clips"' in content or "hook" in content:
        # Extraer indices globales del prompt
        import re

        indices = [int(m) for m in re.findall(r"^\[(\d+)\]", content, re.MULTILINE)]
        clips = [
            {
                "c": i,
                "hook": 55,
                "autocontenido": 60,
                "densidad": 50,
                "cierre": 45,
                "titulo": f"Clip mock {i}",
                "razon": "Generado por mock",
            }
            for i in indices
        ]
        return {"clips": clips}, usage
    # Brain: analisis de grupos
    n = len([ln for ln in content.splitlines() if ln.startswith("[") and "]:" in ln])
    n = max(1, n)
    groups = [{"g": i, "kw": 0 if i % 3 == 0 else None, "emoji": None} for i in range(n)]
    return {"groups": groups}, usage


def _dispatch(messages: list[dict]) -> tuple[dict, dict]:
    """Despacha al provider correcto."""
    if PROVIDER == "mock":
        return _call_mock(messages)
    return _call_deepseek(messages)


# Alias publico para clipper_brain (evita importar privados)
chat_json = _dispatch


def llm(messages: list[dict], json_schema_hint: dict | None = None) -> dict:
    """Wrapper fail-open al LLM configurado. Devuelve {} si falla."""
    for attempt in range(2):
        try:
            result, _ = _dispatch(messages)
            return result
        except Exception as exc:
            print(f"[brain] LLM intento {attempt + 1} fallo: {type(exc).__name__}")
            if attempt == 0:
                time.sleep(1.5)
    return {}


def _enrich_kw_ts(grupos: list[dict], grp_items: list[dict]) -> None:
    """Añade kw_ts a cada item de brain para que apply_brain sea re-grouping-safe."""
    for item in grp_items:
        g_idx = item.get("g")
        kw_within = item.get("kw")
        if g_idx is not None and g_idx < len(grupos) and kw_within is not None:
            g_words = grupos[g_idx].get("words", [])
            if 0 <= kw_within < len(g_words):
                item["kw_ts"] = round(float(g_words[kw_within]["start"]), 3)


def analizar_grupos(grupos: list[dict], contexto: str = "", video_name: str = "") -> dict:
    """Analiza grupos y persiste brain.json con keywords y emojis sugeridos."""
    if not grupos:
        return {"groups": []}

    max_e = max(1, len(grupos) * 30 // 100)
    txt = "\n".join(f"[{g['id']}]: {' '.join(w['text'] for w in g['words'])}" for g in grupos)
    messages = [
        {"role": "system", "content": _SYSTEM},
        {
            "role": "user",
            "content": _PROMPT.format(
                n=len(grupos),
                ctx=contexto or video_name,
                max_e=max_e,
                txt=txt,
            ),
        },
    ]

    t0 = time.time()
    raw: dict = {}
    usage: dict = {}
    for attempt in range(2):
        try:
            raw, usage = _dispatch(messages)
            break
        except Exception as exc:
            print(f"[brain] LLM intento {attempt + 1} fallo: {type(exc).__name__}")
            if attempt == 0:
                time.sleep(1.5)
    latency = round(time.time() - t0, 2)

    if raw:
        kws = sum(1 for g in raw.get("groups", []) if g.get("kw") is not None)
        n_emoji = sum(1 for g in raw.get("groups", []) if g.get("emoji"))
        tok = usage.get("total", "?")
        print(f"[brain] OK {PROVIDER} | {latency}s | kw={kws} n_emoji={n_emoji} | tok={tok}")
    else:
        raw = {"groups": []}
        print(f"[brain] Fallo ({latency}s) -- render seguira sin enfasis")

    grp_items = raw.get("groups", [])
    _enrich_kw_ts(grupos, grp_items)

    brain_data = {
        "provider": PROVIDER,
        "latency_s": latency,
        "tokens": usage,
        "groups": grp_items,
    }
    if video_name:
        TRANSCRIPTS.mkdir(exist_ok=True)
        path = TRANSCRIPTS / f"{video_name}.brain.json"
        path.write_text(json.dumps(brain_data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[brain] Guardado {path.name}")

    return brain_data
