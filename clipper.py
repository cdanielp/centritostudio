"""clipper.py — Clipper viral: segmenta, puntua, selecciona y corta clips SIN captions.

Diseño completo en revision/fase-4/DISENO_CLIPPER.md.
Orden recomendado del pipeline: depurar ANTES del clipper.
"""

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

CLIPS_DIR = Path(__file__).parent / "output" / "clips"
TRANSCRIPTS_DIR = Path(__file__).parent / "transcripts"

# Duraciones por tipo en segundos (decision del arquitecto; obj largo = punto medio 60-90)
DUR = {
    "corto": {"min": 20.0, "obj": 30.0, "max": 40.0},
    "largo": {"min": 55.0, "obj": 75.0, "max": 100.0},
}

# Pesos de la rubrica (suman 1.0). "duracion" la calcula score_duracion, NUNCA el LLM.
PESOS = {"hook": 0.30, "autocontenido": 0.25, "densidad": 0.20, "cierre": 0.15, "duracion": 0.10}

SCORE_MIN = 60  # umbral de entrega (calibrar con clase real)
MAX_CLIPS = 3
SOLAPE_MAX = 0.30  # solape maximo permitido entre clips entregados (fraccion del mas corto)
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

_PUNCT_FRASE = frozenset({".", "!", "?", "…"})


# ── Scoring determinista (contrato: los tests lo fijan) ──────────────────────


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


# ── Construccion de frases ────────────────────────────────────────────────────


def build_frases(words: list[dict]) -> list[dict]:
    """Divide words en frases: [{"idx","wi","wf","s","e","text"}] con indices GLOBALES.

    Corta por puntuacion final (. ! ? ...), pausa > FRASE_PAUSA_S o FRASE_MAX_WORDS.
    """
    if not words:
        return []

    frases: list[dict] = []
    buf: list[int] = []  # indices globales de words en la frase actual

    def flush() -> None:
        if not buf:
            return
        wi, wf = buf[0], buf[-1]
        text = " ".join(words[i]["w"] for i in buf)
        frases.append(
            {
                "idx": len(frases),
                "wi": wi,
                "wf": wf,
                "s": words[wi]["s"],
                "e": words[wf]["e"],
                "text": text,
            }
        )
        buf.clear()

    for i, w in enumerate(words):
        buf.append(i)
        ends_sentence = bool(w["w"]) and w["w"][-1] in _PUNCT_FRASE
        pause_after = (words[i + 1]["s"] - w["e"]) if i + 1 < len(words) else 0.0
        if ends_sentence or pause_after > FRASE_PAUSA_S or len(buf) >= FRASE_MAX_WORDS:
            flush()

    flush()
    return frases


# ── Chunking con solape ───────────────────────────────────────────────────────


def chunk_frases(frases: list[dict]) -> list[list[dict]]:
    """Parte frases en ventanas de ~CHUNK_WORDS palabras con solape OVERLAP_WORDS."""
    if not frases:
        return []

    chunks: list[list[dict]] = []
    start_idx = 0

    while start_idx < len(frases):
        chunk: list[dict] = []
        word_count = 0
        i = start_idx

        while i < len(frases):
            n = frases[i]["wf"] - frases[i]["wi"] + 1
            if word_count + n > CHUNK_WORDS and chunk:
                break
            chunk.append(frases[i])
            word_count += n
            i += 1

        chunks.append(chunk)

        if i >= len(frases):
            break

        # Encontrar inicio del proximo chunk con solape OVERLAP_WORDS
        overlap = 0
        next_start = i  # default: sin solape
        for k in range(i - 1, start_idx, -1):
            n = frases[k]["wf"] - frases[k]["wi"] + 1
            overlap += n
            if overlap >= OVERLAP_WORDS:
                next_start = k
                break

        start_idx = next_start if next_start > start_idx else i

    return chunks


# ── Dedup de candidatos tras union de chunks ──────────────────────────────────


def dedup_segmentos(segmentos: list[dict]) -> list[dict]:
    """Fusiona duplicados del solape entre chunks (IoU de rango de palabras > IOU_DUP)."""
    kept: list[dict] = []
    for seg in segmentos:
        wi_a, wf_a = seg["wi"], seg["wf"]
        is_dup = False
        for k in kept:
            wi_b, wf_b = k["wi"], k["wf"]
            inter_s = max(wi_a, wi_b)
            inter_e = min(wf_a, wf_b)
            if inter_e < inter_s:
                continue
            inter = inter_e - inter_s + 1
            union = (wf_a - wi_a + 1) + (wf_b - wi_b + 1) - inter
            if union > 0 and inter / union > IOU_DUP:
                is_dup = True
                break
        if not is_dup:
            kept.append(seg)
    return kept


# ── Seleccion final ───────────────────────────────────────────────────────────


def seleccionar_clips(candidatos: list[dict]) -> tuple[list[dict], list[dict]]:
    """Aplica SCORE_MIN, solape <= SOLAPE_MAX, separacion y MAX_CLIPS.

    Devuelve (elegidos, descartados_con_motivo). Ranking unico puro por score.
    """
    sorted_cands = sorted(candidatos, key=lambda c: c["score"], reverse=True)
    elegidos: list[dict] = []
    descartados: list[dict] = []

    for cand in sorted_cands:
        if len(elegidos) >= MAX_CLIPS:
            descartados.append({**cand, "motivo": "max_clips"})
            continue

        if cand["score"] < SCORE_MIN:
            descartados.append({**cand, "motivo": "score_bajo"})
            continue

        motivo = None
        for e in elegidos:
            # Solape: fraccion del clip mas corto
            wi_a, wf_a = cand["wi"], cand["wf"]
            wi_b, wf_b = e["wi"], e["wf"]
            inter_s = max(wi_a, wi_b)
            inter_e = min(wf_a, wf_b)
            if inter_e >= inter_s:
                inter = inter_e - inter_s + 1
                min_len = min(wf_a - wi_a + 1, wf_b - wi_b + 1)
                if min_len > 0 and inter / min_len > SOLAPE_MAX:
                    motivo = "solape"
                    break

            # Separacion minima
            gap = max(cand["start"] - e["end"], e["start"] - cand["end"])
            if gap < SEPARACION_MIN_S:
                motivo = "separacion"
                break

        if motivo:
            descartados.append({**cand, "motivo": motivo})
        else:
            elegidos.append(cand)

    return elegidos, descartados


# ── Corte y exportacion de transcripts ───────────────────────────────────────


def cortar_clip(video_path: Path, start: float, end: float, output: Path) -> None:
    """Corta [start, end] re-encodeando via depurador.run_edl con EDL de 1 segmento."""
    import depurador as dep  # noqa: PLC0415

    dep.run_edl(video_path, [(start, end)], output)


def exportar_transcript_clip(words: list[dict], wi: int, wf: int, clip_stem: str) -> None:
    """Escribe {clip_stem}_words.json y _groups.json re-basados a t=0 (regla de oro #4)."""
    import core  # noqa: PLC0415

    clip_words = words[wi : wf + 1]
    t0 = clip_words[0]["s"] if clip_words else 0.0
    rebased = [{**w, "s": round(w["s"] - t0, 3), "e": round(w["e"] - t0, 3)} for w in clip_words]

    TRANSCRIPTS_DIR.mkdir(exist_ok=True)
    words_data = {"words": rebased, "language": "es"}
    words_path = TRANSCRIPTS_DIR / f"{clip_stem}_words.json"
    words_path.write_text(json.dumps(words_data, ensure_ascii=False, indent=2), encoding="utf-8")

    groups = core.group_words(rebased)
    groups_path = TRANSCRIPTS_DIR / f"{clip_stem}_groups.json"
    groups_path.write_text(json.dumps(groups, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[clipper] transcript clip: {len(rebased)} palabras, {len(groups)} grupos")


def _atomic_write_text(path: Path, text: str) -> None:
    """Escritura atomica (tmp + os.replace); no deja `.tmp` medio escrito visible."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="")
    os.replace(tmp, path)


def exportar_srt_clip(srt_document, start_s: float, end_s: float, clip_stem: str) -> dict | None:
    """Recorta/rebasa el SRT fuente al intervalo REAL del clip [start, end) (D36B-8/9).

    Rebase contra `clip.start` real (con padding), no contra la primera palabra: asi video,
    audio y SRT comparten el mismo cero. Nunca modifica la fuente. Devuelve metadata saneada
    (solo basenames) o None si el clip no tiene cues. ms enteros con `round(seconds*1000)`.
    """
    from srt_import import serialize_srt, srt_to_contract  # noqa: PLC0415
    from srt_slice import slice_srt  # noqa: PLC0415

    start_ms = round(start_s * 1000)
    end_ms = round(end_s * 1000)
    derived = slice_srt(srt_document, start_ms, end_ms, rebase=True, reindex=True)

    TRANSCRIPTS_DIR.mkdir(exist_ok=True)
    srt_file = f"{clip_stem}.srt"
    contract_file = f"{clip_stem}_srt.json"
    if not derived.cues:  # clip sin cues: metadata honesta n_cues=0, sin archivo (D36B-8)
        return {
            "file": None,
            "contract_file": None,
            "n_cues": 0,
            "source_sha256": srt_document.source_sha256,
            "start_ms_source": start_ms,
            "end_ms_source": end_ms,
            "rebased": True,
        }
    _atomic_write_text(TRANSCRIPTS_DIR / srt_file, serialize_srt(derived))
    _atomic_write_text(
        TRANSCRIPTS_DIR / contract_file,
        json.dumps(srt_to_contract(derived), ensure_ascii=False, indent=2),
    )
    return {
        "file": srt_file,
        "contract_file": contract_file,
        "n_cues": len(derived.cues),
        "source_sha256": srt_document.source_sha256,
        "start_ms_source": start_ms,
        "end_ms_source": end_ms,
        "rebased": True,
    }


# ── Pipeline principal ────────────────────────────────────────────────────────


def generar_clips(  # noqa: C901
    video_path: Path, words: list[dict], tipos: str = "ambos", *, srt_document=None
) -> dict:
    """Pipeline completo del clipper. Devuelve el dict de clips.json.

    {"clips": [...], "descartados": [...], "telemetria": [...], "error": str|None}
    Nunca crashea por el LLM y nunca inventa clips: sin candidatos validos devuelve
    clips=[] con mensaje accionable (DISENO_CLIPPER.md §4.4).

    Con `srt_document` (SrtDocument ya cargado) genera ademas, por clip, un SRT rebasado
    al intervalo real del clip (D36B-8). Sin el, comportamiento historico exacto: no lee
    ni genera SRT alguno.
    """
    import clipper_brain as cb  # noqa: PLC0415 lazy — evita circular

    result: dict = {
        "clips": [],
        "descartados": [],
        "telemetria": [],
        "casi": [],
        "error": None,
    }

    # Verificar API key antes de leer el video
    if os.getenv("LLM_PROVIDER", "deepseek") != "mock":
        if not os.getenv("DEEPSEEK_API_KEY", ""):
            result["error"] = "DEEPSEEK_API_KEY no configurada en .env"
            print(f"[clipper] ERROR: {result['error']}")
            return result

    if not words:
        result["error"] = "Lista de palabras vacia"
        return result

    stem = video_path.stem
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    t_total = time.time()
    print(f"[clipper] Inicio -- {len(words)} palabras | tipos={tipos} | {stem}")

    # 1. Construir frases
    frases = build_frases(words)
    print(f"[clipper] {len(frases)} frases construidas")
    if not frases:
        result["error"] = "No se construyeron frases del transcript"
        _write_clips_json(stem, result)
        return result

    # 2. Etapa A: segmentacion semantica
    try:
        raw_segs, tels_seg = cb.segmentar_transcript(frases, contexto=stem, tipos=tipos)
    except Exception as exc:
        result["error"] = f"Error en segmentacion: {exc}"
        _write_clips_json(stem, result)
        return result

    result["telemetria"].extend(tels_seg)

    if not raw_segs:
        result["error"] = "El LLM no devolvio candidatos validos tras 2 intentos en segmentacion"
        _write_clips_json(stem, result)
        return result

    print(f"[clipper] {len(raw_segs)} candidatos de segmentacion")

    # 3. Mapear frases -> palabras -> timestamps + dedup
    segs_with_words = []
    for seg in raw_segs:
        f_s = frases[seg["f_ini"]]
        f_e = frases[seg["f_fin"]]
        segs_with_words.append({**seg, "wi": f_s["wi"], "wf": f_e["wf"]})

    segs_deduped = dedup_segmentos(segs_with_words)
    print(f"[clipper] {len(segs_deduped)} tras dedup (eran {len(segs_with_words)})")

    # 4. Calcular timestamps con padding + filtro de duracion
    candidatos: list[dict] = []
    for seg in segs_deduped:
        wi, wf = seg["wi"], seg["wf"]

        # Timestamps con padding acotado por palabras vecinas
        if wi > 0:
            pad_start = max(words[wi - 1]["e"] + 0.05, words[wi]["s"] - PAD_INI_S)
        else:
            pad_start = words[wi]["s"] - PAD_INI_S
        start = max(0.0, pad_start)

        if wf + 1 < len(words):
            pad_end = min(words[wf + 1]["s"] - 0.05, words[wf]["e"] + PAD_FIN_S)
        else:
            pad_end = words[wf]["e"] + PAD_FIN_S
        end = pad_end

        dur = end - start
        tipo = seg["tipo"]

        # Filtro de duracion con reclasificacion
        d = DUR[tipo]
        if not (d["min"] <= dur <= d["max"]):
            otro = "largo" if tipo == "corto" else "corto"
            d_otro = DUR[otro]
            if d_otro["min"] <= dur <= d_otro["max"]:
                tipo = otro
                print(
                    f"[clipper] Reclasificado f{seg['f_ini']}-f{seg['f_fin']}: {tipo} ({dur:.1f}s)"
                )
            else:
                result["descartados"].append(
                    {
                        **seg,
                        "start": round(start, 3),
                        "end": round(end, 3),
                        "dur_s": round(dur, 2),
                        "motivo": "duracion",
                    }
                )
                continue

        # Filtro de tipo solicitado
        if tipos != "ambos" and tipo != tipos.rstrip("s"):
            result["descartados"].append(
                {
                    **seg,
                    "tipo": tipo,
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "dur_s": round(dur, 2),
                    "motivo": "tipo_no_solicitado",
                }
            )
            continue

        texto = " ".join(words[j]["w"] for j in range(wi, wf + 1))
        candidatos.append(
            {
                **seg,
                "tipo": tipo,
                "wi": wi,
                "wf": wf,
                "start": round(start, 3),
                "end": round(end, 3),
                "dur_s": round(dur, 2),
                "texto": texto,
            }
        )

    if not candidatos:
        result["error"] = "Todos los candidatos fueron descartados por duracion"
        _write_clips_json(stem, result)
        return result

    print(f"[clipper] {len(candidatos)} candidatos tras filtro de duracion")

    # 5. Etapa B: scoring
    try:
        scores, tels_score = cb.puntuar_candidatos(candidatos)
    except Exception as exc:
        result["error"] = f"Error en scoring: {exc}"
        _write_clips_json(stem, result)
        return result

    result["telemetria"].extend(tels_score)

    scores_by_c = {s["c"]: s for s in scores}
    scored: list[dict] = []
    for idx, cand in enumerate(candidatos):
        if idx not in scores_by_c:
            result["descartados"].append({**cand, "motivo": "llm_omitido"})
            continue
        sc = scores_by_c[idx]
        subs = {k: sc[k] for k in ("hook", "autocontenido", "densidad", "cierre")}
        sc_dur = score_duracion(cand["dur_s"], cand["tipo"])
        score_total = calcular_score_total(subs, cand["dur_s"], cand["tipo"])
        scored.append(
            {
                **cand,
                "subscores": subs,
                "score_duracion": sc_dur,
                "score": score_total,
                "titulo": sc.get("titulo", "Clip sin titulo"),
                "razon": sc.get("razon", "(sin razon)"),
            }
        )

    if not scored:
        result["error"] = "El LLM no devolvio scores validos tras 2 intentos"
        _write_clips_json(stem, result)
        return result

    # 6. Seleccion final
    elegidos, descartados_sel = seleccionar_clips(scored)
    result["descartados"].extend(descartados_sel)

    # Casi (50-59): visibles en UI para calibracion
    result["casi"] = [
        d
        for d in result["descartados"]
        if d.get("motivo") == "score_bajo" and 50 <= d.get("score", 0) < SCORE_MIN
    ]

    # 7. Cortar clips y exportar transcripts
    clips_out: list[dict] = []
    for n, clip in enumerate(elegidos, 1):
        out_name = f"{stem}_clip{n}_{clip['tipo']}"
        out_path = CLIPS_DIR / f"{out_name}.mp4"
        try:
            print(
                f"[clipper] Cortando clip {n}/{len(elegidos)}: {out_path.name} "
                f"({clip['start']:.1f}-{clip['end']:.1f}s, score={clip['score']})"
            )
            cortar_clip(video_path, clip["start"], clip["end"], out_path)
            exportar_transcript_clip(words, clip["wi"], clip["wf"], out_name)
            clip_info = {
                "archivo": out_path.name,
                "tipo": clip["tipo"],
                "start": clip["start"],
                "end": clip["end"],
                "dur_s": clip["dur_s"],
                "wi": clip["wi"],
                "wf": clip["wf"],
                "score": clip["score"],
                "subscores": clip["subscores"],
                "score_duracion": clip["score_duracion"],
                "titulo": clip["titulo"],
                "razon": clip["razon"],
                "tema": clip.get("tema", "(sin tema)"),
            }
            if srt_document is not None:
                # El MP4 ya esta cortado: un fallo del SRT derivado NO tumba el clip (D36B-8).
                try:
                    srt_meta = exportar_srt_clip(srt_document, clip["start"], clip["end"], out_name)
                    if srt_meta is not None:
                        clip_info["srt"] = srt_meta
                        print(f"[clipper] SRT clip {n}: {srt_meta['n_cues']} cues rebasados")
                except Exception as exc:  # noqa: BLE001
                    print(f"[clipper] AVISO: SRT del clip {n} no generado ({type(exc).__name__})")
            clips_out.append(clip_info)
        except Exception as exc:
            print(f"[clipper] Error cortando clip {n}: {exc}")
            result["descartados"].append({**clip, "motivo": f"error_corte: {exc}"})

    # 8. Telemetria agregada
    tels = result["telemetria"]
    total_tok = sum(t.get("tokens", {}).get("total", 0) for t in tels)
    total_costo = sum(t.get("costo_usd", 0) for t in tels)
    total_lat = sum(t.get("latency_s", 0) for t in tels)
    n_seg = sum(1 for t in tels if t.get("etapa") == "segmentacion")
    n_sc = sum(1 for t in tels if t.get("etapa") == "scoring")
    provider = tels[0]["provider"] if tels else "?"

    result["clips"] = clips_out
    result["telemetria_resumen"] = {
        "provider": provider,
        "calls_seg": n_seg,
        "calls_score": n_sc,
        "tokens_total": total_tok,
        "costo_usd": round(total_costo, 5),
        "latencia_total_s": round(total_lat, 2),
        "wall_s": round(time.time() - t_total, 1),
    }

    print(
        f"[clipper] OK {provider} | seg {n_seg} llamadas | score {n_sc} llamadas | "
        f"{total_tok} tok | ${total_costo:.4f} | {total_lat:.1f}s LLM"
    )
    print(f"[clipper] {len(clips_out)} clips generados / {len(result['descartados'])} descartados")

    _write_clips_json(stem, result)
    return result


def _write_clips_json(stem: str, result: dict) -> None:
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    path = CLIPS_DIR / f"{stem}_clips.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[clipper] {path.name} escrito")
