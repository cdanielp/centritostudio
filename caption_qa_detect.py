"""caption_qa_detect.py — Detectores PUROS del Caption QA (sin I/O, sin red, sin LLM).

Tres detectores deterministas sobre los words transcritos:
1. VARIANTES: errores de transcripcion conocidos del glosario (confianza alta).
2. SIMILITUD: difflib contra terminos tecnicos largos (checpoint -> checkpoint).
3. GUION: vocabulario esperado + contexto de bigrama precedente
   ("abrir el aflicjo" cuando el guion dice "abrir el archivo").
4. HEURISTICA: probabilidad Whisper baja (alerta sin sugerencia).

La orquestacion, carga de archivos y el auditor LLM viven en caption_qa.py.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from cve_keywords import STOPWORDS

# Umbrales calibrados en s33 con pares reales: checpoint/checkpoint 0.947,
# workflou/workflow 0.875 (verdaderos) vs flujo/flux 0.667, archivo/activo 0.769
# (falsos). Los casos foneticos (confeti ui, kansas) NO se cazan por similitud:
# van como variantes curadas del glosario (ruta premium, consistente con D23).
FUZZY_ALTA = 0.87  # >= : error ortografico casi seguro -> aplicar_auto
FUZZY_MEDIA = 0.78  # >= : sospecha razonable -> alerta sin auto-aplicar
FUZZY_GUION = 0.85  # similitud minima contra el vocabulario del guion
FUZZY_PISO_CONTEXTO = 0.30  # el reemplazo por contexto no puede ser palabra ajena total
LARGO_MIN_TOKEN = 4  # tokens mas cortos no se evaluan por similitud (FP-prone)
LARGO_MIN_TERMINO = 6  # terminos cortos (Flux, VAE, CLIP) solo entran via variantes
PROB_SOSPECHOSA = 0.40  # umbral de la heuristica de probabilidad Whisper
MAX_NGRAM = 3  # variantes de hasta 3 tokens ("deep sik" -> DeepSeek)
PUNT = ".,!?;:…\"')("

_PRIORIDAD_CONF = {"alta": 3, "media": 2, "baja": 1}


def normalizar(texto: str) -> str:
    """Token en minusculas sin puntuacion de borde ni acentos."""
    t = texto.lower().strip(PUNT + "¿¡")
    return t.translate(str.maketrans("áéíóúü", "aeiouu"))


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _alerta(
    word: dict,
    detectado: str,
    sugerencia: str | None,
    confianza: str,
    motivo: str,
    fuente: str,
    aplicar_auto: bool,
    n_palabras: int = 1,
) -> dict:
    """Registro de alerta con el esquema del sidecar caption_alerts.json."""
    return {
        "timestamp": word["s"],
        "texto_detectado": detectado,
        "sugerencia": sugerencia,
        "confianza": confianza,
        "motivo": motivo,
        "fuente": fuente,
        "aplicar_auto": aplicar_auto,
        "aplicada": False,
        "n_palabras": n_palabras,
    }


def detectar_variantes(words: list[dict], glosario: dict) -> list[dict]:
    """Variantes CONOCIDAS del glosario sobre n-gramas de 1-3 tokens (alta)."""
    variantes = glosario["variantes"]
    normas = [normalizar(w["w"]) for w in words]
    alertas: list[dict] = []
    i = 0
    while i < len(words):
        hit = None
        for n in range(min(MAX_NGRAM, len(words) - i), 0, -1):
            frase = " ".join(normas[i : i + n])
            if frase and frase in variantes:
                hit = (n, variantes[frase])
                break
        if hit is None:
            i += 1
            continue
        n, sugerencia = hit
        if normalizar(sugerencia) != " ".join(normas[i : i + n]):
            detectado = " ".join(w["w"] for w in words[i : i + n])
            motivo = "variante conocida del glosario"
            alertas.append(
                _alerta(words[i], detectado, sugerencia, "alta", motivo, "glosario", True, n)
            )
        i += n
    return alertas


def detectar_similitud_glosario(words: list[dict], glosario: dict) -> list[dict]:
    """Similitud difflib contra terminos tecnicos largos (checpoint -> checkpoint)."""
    objetivos = [(t, orig) for t, orig in glosario["normas"].items() if len(t) >= LARGO_MIN_TERMINO]
    if not objetivos:
        return []
    alertas = []
    for w in words:
        n = normalizar(w["w"])
        if len(n) < LARGO_MIN_TOKEN or n in STOPWORDS or n in glosario["normas"]:
            continue
        score, orig = max((_ratio(n, t), orig) for t, orig in objetivos)
        if score >= FUZZY_MEDIA:
            conf = "alta" if score >= FUZZY_ALTA else "media"
            motivo = f"similitud {score:.2f} con termino del glosario"
            alertas.append(_alerta(w, w["w"], orig, conf, motivo, "glosario", conf == "alta"))
    return alertas


def _tokens_guion(texto: str) -> list[str]:
    return [t for t in texto.split() if normalizar(t)]


def vocabulario_guion(texto: str) -> dict[str, str]:
    """{norma: forma_original} de las palabras de contenido del guion."""
    vocab: dict[str, str] = {}
    for t in _tokens_guion(texto):
        n = normalizar(t)
        if len(n) >= LARGO_MIN_TOKEN and n not in STOPWORDS:
            vocab.setdefault(n, t.strip(PUNT + "¿¡"))
    return vocab


def contexto_guion(texto: str) -> dict[tuple[str, str], str]:
    """{(prev2, prev1): palabra esperada} — bigrama precedente; claves ambiguas fuera."""
    tokens = _tokens_guion(texto)
    normas = [normalizar(t) for t in tokens]
    index: dict[tuple[str, str], str] = {}
    ambiguas: set[tuple[str, str]] = set()
    for i in range(2, len(tokens)):
        if len(normas[i]) < LARGO_MIN_TOKEN or normas[i] in STOPWORDS:
            continue
        clave = (normas[i - 2], normas[i - 1])
        if clave in index and normalizar(index[clave]) != normas[i]:
            ambiguas.add(clave)
        else:
            index[clave] = tokens[i].strip(PUNT + "¿¡")
    for clave in ambiguas:
        index.pop(clave, None)
    return index


def _alerta_por_contexto(
    words: list[dict], i: int, normas: list[str], contexto: dict
) -> dict | None:
    """Alerta si el bigrama precedente del transcript sale en el guion con otra palabra."""
    if i < 2:
        return None
    esperado = contexto.get((normas[i - 2], normas[i - 1]))
    if not esperado or normalizar(esperado) == normas[i]:
        return None
    if _ratio(normas[i], normalizar(esperado)) < FUZZY_PISO_CONTEXTO:
        return None
    motivo = f"el guion dice '{esperado}' tras '... {words[i - 2]['w']} {words[i - 1]['w']}'"
    return _alerta(words[i], words[i]["w"], esperado, "media", motivo, "guion", False)


def detectar_guion(words: list[dict], guion_texto: str, glosario: dict) -> list[dict]:
    """Palabras que el guion esperaba distintas: contexto de bigrama + similitud."""
    vocab = vocabulario_guion(guion_texto)
    contexto = contexto_guion(guion_texto)
    normas = [normalizar(w["w"]) for w in words]
    alertas = []
    for i, w in enumerate(words):
        n = normas[i]
        if len(n) < LARGO_MIN_TOKEN or n in STOPWORDS or n in vocab or n in glosario["normas"]:
            continue
        por_contexto = _alerta_por_contexto(words, i, normas, contexto)
        if por_contexto:
            alertas.append(por_contexto)
            continue
        if vocab:
            score, orig = max((_ratio(n, v), orig) for v, orig in vocab.items())
            if score >= FUZZY_GUION:
                motivo = f"similitud {score:.2f} con palabra del guion"
                alertas.append(_alerta(w, w["w"], orig, "media", motivo, "guion", False))
    return alertas


def detectar_heuristica(words: list[dict]) -> list[dict]:
    """Palabras con probabilidad Whisper baja: alerta sin sugerencia (revision humana)."""
    alertas = []
    for w in words:
        n = normalizar(w["w"])
        prob = w.get("prob", 1.0)
        if len(n) >= LARGO_MIN_TOKEN and n not in STOPWORDS and prob < PROB_SOSPECHOSA:
            motivo = f"probabilidad Whisper baja ({prob})"
            alertas.append(_alerta(w, w["w"], None, "baja", motivo, "heuristica", False))
    return alertas


def _dedup(alertas: list[dict]) -> list[dict]:
    """1 alerta por timestamp: gana la de mayor confianza; orden cronologico."""
    por_ts: dict[float, dict] = {}
    for a in alertas:
        ts = round(float(a["timestamp"]), 3)
        actual = por_ts.get(ts)
        if actual is None or _PRIORIDAD_CONF[a["confianza"]] > _PRIORIDAD_CONF[actual["confianza"]]:
            por_ts[ts] = a
    return [por_ts[ts] for ts in sorted(por_ts)]


def generar_alertas(
    words: list[dict], glosario: dict, guion_texto: str | None = None
) -> list[dict]:
    """Corre los detectores deterministas y consolida 1 alerta por timestamp."""
    alertas = detectar_variantes(words, glosario)
    alertas += detectar_similitud_glosario(words, glosario)
    if guion_texto:
        alertas += detectar_guion(words, guion_texto, glosario)
    alertas += detectar_heuristica(words)
    return _dedup(alertas)


def contexto_palabra(words: list[dict], ts: float, radio: int = 4) -> str:
    """Frase de +-radio palabras con la sospechosa entre <<...>> (para el auditor)."""
    idx = next((i for i, w in enumerate(words) if abs(float(w["s"]) - ts) < 0.005), None)
    if idx is None:
        return ""
    ini, fin = max(0, idx - radio), min(len(words), idx + radio + 1)
    return " ".join(
        f"<<{w['w']}>>" if i == idx else w["w"] for i, w in enumerate(words[ini:fin], ini)
    )
