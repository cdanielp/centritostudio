"""cve_keywords.py — Deteccion determinista de keywords, marcas manuales y fit de escala.

FUNCIONES PURAS del caption_viral_engine (F6): sin I/O de video, sin red, sin LLM.
Diseno: revision/fase-6/DISENO_CVE.md §4 (reglas R1-R7), §5.3 (fit), §7 (marcas).
Contrato de salida: mismo formato que apply_brain (is_keyword por palabra) + punch_scale.
"""

from __future__ import annotations

import re

# ─────────────────────────────────────────────────────────────────────────────
# Constantes de reglas (§4.1) — scores fijos por regla
# ─────────────────────────────────────────────────────────────────────────────

SCORE_MANUAL = 1000  # [strong]/[big]: la intencion explicita del usuario gana a todo
SCORE_BRAIN = 100  # marcas semanticas del brain.json existente
SCORE_R1_NUMEROS = 90
SCORE_R2_DINERO = 95
SCORE_R3_FECHAS = 70
SCORE_R4_PREGUNTA = 75
SCORE_R5_NEGACION = 85
SCORE_R6_CONTRASTE = 80
SCORE_R7_REPETIDA = 60

DENSIDAD_MAX = 0.40  # fraccion maxima de grupos con keyword (anti-spam)
REPETIDA_MIN_APARICIONES = 3
REPETIDA_MAX_MARCAS = 2  # solo las primeras N apariciones de una repetida
LARGO_MIN_CONTENIDO = 4  # chars minimos para que una palabra sea "de contenido"

# Stopwords: nunca son keyword (lista del prompt del brain + extension conservadora)
STOPWORDS = frozenset(
    "el la los las un una unas unos de en que y o a con por para se me te le les "
    "es son fue era ser estar esta este esto esa ese eso al del lo mi tu su sus "
    "como mas muy ya si no nos hay han ha he va van voy vas todo toda todos todas "
    "pero aunque embargo entonces cuando donde porque".split()
)

NUMERALES = frozenset(
    "uno dos tres cuatro cinco seis siete ocho nueve diez once doce veinte treinta "
    "cuarenta cincuenta sesenta setenta ochenta noventa cien ciento mil millon "
    "millones primero primera segundo segunda tercero tercera doble triple mitad".split()
)

DINERO_PCT = frozenset("pesos peso dolares dolar euros euro dinero gratis".split())

FECHAS = frozenset(
    "enero febrero marzo abril mayo junio julio agosto septiembre octubre "
    "noviembre diciembre hoy manana ahora ayer".split()
)

NEGACIONES = frozenset(
    "nunca jamas nadie ninguno ninguna imposible prohibido error errores peor".split()
)

CONTRASTES = frozenset({"pero", "aunque", "embargo"})  # "sin embargo" -> embargo

# Marcas manuales v1 (§7). Extensible: agregar entrada = agregar marca.
MARCAS_VALIDAS = frozenset({"strong", "big", "center"})
_MARCA_RE = re.compile(r"\[(/?[a-zA-Z_]+)\]")

# Fit de escala (§5.3): estimacion de ancho de texto sin rasterizar
ANCHO_CHAR_FACTOR = 0.65  # ancho promedio de un char vs fontsize (Arial Black aprox)
PICO_REBOTE_FACTOR = 1.12  # el overshoot momentaneo tambien debe caber
FIT_PASO = 10  # reduccion por paso de la cadena "reducir"
KW_SCALE_BASE = 122  # escala actual del keyword del motor (comportamiento previo)


def _normalizar(texto: str) -> str:
    """Palabra en minusculas sin puntuacion ni acentos (para comparar contra sets)."""
    t = texto.lower().strip(".,!?;:¿¡\"'()")
    return t.translate(str.maketrans("áéíóúü", "aeiouu"))


def _es_contenido(palabra: str) -> bool:
    n = _normalizar(palabra)
    return len(n) >= LARGO_MIN_CONTENIDO and n not in STOPWORDS


# ─────────────────────────────────────────────────────────────────────────────
# Reglas R1-R7 (§4.1) — cada una devuelve candidatos (g_idx, w_idx, score, regla)
# ─────────────────────────────────────────────────────────────────────────────


def _regla_por_palabra(norm: str, crudo: str) -> tuple[int, str] | None:
    """Evalua R1/R2/R3/R5 sobre una palabra aislada. Devuelve (score, regla) o None."""
    if "%" in crudo or "$" in crudo or norm in DINERO_PCT:
        return SCORE_R2_DINERO, "R2"
    if any(c.isdigit() for c in norm) or norm in NUMERALES:
        return SCORE_R1_NUMEROS, "R1"
    if norm in NEGACIONES:
        return SCORE_R5_NEGACION, "R5"
    if norm in FECHAS:
        return SCORE_R3_FECHAS, "R3"
    return None


def _candidatos_grupo(g_idx: int, palabras: list[str]) -> list[tuple[int, int, int, str]]:
    """Candidatos por-palabra (R1/R2/R3/R5) + contraste R6 de un grupo."""
    result = []
    for w_idx, crudo in enumerate(palabras):
        norm = _normalizar(crudo)
        if norm in STOPWORDS and norm not in NEGACIONES:
            continue
        hit = _regla_por_palabra(norm, crudo)
        if hit:
            result.append((g_idx, w_idx, hit[0], hit[1]))
    # R6: la palabra de contenido que SIGUE a un conector de contraste
    for w_idx, crudo in enumerate(palabras[:-1]):
        if _normalizar(crudo) in CONTRASTES:
            for j in range(w_idx + 1, len(palabras)):
                if _es_contenido(palabras[j]):
                    result.append((g_idx, j, SCORE_R6_CONTRASTE, "R6"))
                    break
    return result


def _candidatos_pregunta(g_idx: int, grupo: dict) -> list[tuple[int, int, int, str]]:
    """R4: en grupos que terminan en '?', marca la palabra de contenido mas larga."""
    if not grupo.get("text", "").rstrip().endswith("?"):
        return []
    palabras = [w["text"] for w in grupo["words"]]
    contenido = [(len(_normalizar(p)), i) for i, p in enumerate(palabras) if _es_contenido(p)]
    if not contenido:
        return []
    _, idx = max(contenido)
    return [(g_idx, idx, SCORE_R4_PREGUNTA, "R4")]


def _candidatos_repetidas(groups: list[dict]) -> list[tuple[int, int, int, str]]:
    """R7: palabras de contenido con >= REPETIDA_MIN_APARICIONES en todo el transcript."""
    conteo: dict[str, int] = {}
    posiciones: dict[str, list[tuple[int, int]]] = {}
    for g_idx, g in enumerate(groups):
        for w_idx, w in enumerate(g["words"]):
            if not _es_contenido(w["text"]):
                continue
            n = _normalizar(w["text"])
            conteo[n] = conteo.get(n, 0) + 1
            posiciones.setdefault(n, []).append((g_idx, w_idx))
    result = []
    for n, c in conteo.items():
        if c >= REPETIDA_MIN_APARICIONES:
            for g_idx, w_idx in posiciones[n][:REPETIDA_MAX_MARCAS]:
                result.append((g_idx, w_idx, SCORE_R7_REPETIDA, "R7"))
    return result


def detectar_candidatos(groups: list[dict]) -> list[tuple[int, int, int, str]]:
    """Corre R1-R7 sobre los grupos. Devuelve (g_idx, w_idx, score, regla) sin dedup."""
    result: list[tuple[int, int, int, str]] = []
    for g_idx, g in enumerate(groups):
        palabras = [w["text"] for w in g.get("words", [])]
        result.extend(_candidatos_grupo(g_idx, palabras))
        result.extend(_candidatos_pregunta(g_idx, g))
    result.extend(_candidatos_repetidas(groups))
    return result


def candidatos_brain(groups: list[dict], brain_data: dict | None) -> list:
    """Marcas del brain.json como candidatos score 100 (re-ancla por kw_ts, como apply_brain)."""
    if not brain_data or not brain_data.get("groups"):
        return []
    kw_ts = {
        round(float(item["kw_ts"]), 3)
        for item in brain_data["groups"]
        if item.get("kw_ts") is not None
    }
    result = []
    for g_idx, g in enumerate(groups):
        for w_idx, w in enumerate(g.get("words", [])):
            if round(float(w.get("start", -999)), 3) in kw_ts:
                result.append((g_idx, w_idx, SCORE_BRAIN, "brain"))
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Merge y seleccion (§4.2): manual > brain > reglas, 1 por grupo, densidad max
# ─────────────────────────────────────────────────────────────────────────────


def elegir_keywords(
    candidatos: list[tuple[int, int, int, str]], n_groups: int
) -> dict[int, tuple[int, int, str]]:
    """Merge final: 1 keyword por grupo (score mayor; empate no reordena), densidad <=40%.

    Devuelve {g_idx: (w_idx, score, regla)}. Anti-spam R7: no 2 grupos consecutivos por R7.
    """
    por_grupo: dict[int, tuple[int, int, str]] = {}
    for g_idx, w_idx, score, regla in sorted(candidatos, key=lambda c: -c[2]):
        if 0 <= g_idx < n_groups and g_idx not in por_grupo:
            por_grupo[g_idx] = (w_idx, score, regla)

    # Anti-spam: dos consecutivos ambos R7 -> cae el de menor score
    for g_idx in sorted(por_grupo):
        vecino = g_idx + 1
        if vecino in por_grupo and por_grupo[g_idx][2] == por_grupo[vecino][2] == "R7":
            peor = g_idx if por_grupo[g_idx][1] <= por_grupo[vecino][1] else vecino
            por_grupo.pop(peor)

    max_kw = max(int(n_groups * DENSIDAD_MAX), 1)
    if len(por_grupo) > max_kw:
        mejores = sorted(por_grupo.items(), key=lambda kv: -kv[1][1])[:max_kw]
        por_grupo = dict(mejores)
    return por_grupo


# ─────────────────────────────────────────────────────────────────────────────
# Marcado manual v1 (§7): [strong] [big] [center] — parser tolerante
# ─────────────────────────────────────────────────────────────────────────────


def limpiar_token(token: str) -> str:
    """Texto visible de un token: toda marca [x] (valida, invalida o cierre) se elimina.

    Misma regla que parsear_marcas — el ASS jamas muestra corchetes de marca (voto #34).
    """
    return _MARCA_RE.sub("", token)


def parsear_marcas(texto: str) -> tuple[str, dict[int, str], bool]:
    """Extrae marcas v1 del texto de un grupo. Marca invalida = se elimina, jamas rompe.

    Devuelve (texto_limpio, {indice_palabra: marca}, center). La marca aplica a la
    PALABRA SIGUIENTE inmediata; una marca al final del texto (huerfana) se descarta.
    """
    if "[" not in texto:
        return texto, {}, False

    center = False
    marcas: dict[int, str] = {}
    palabras_limpias: list[str] = []
    pendiente: str | None = None

    for token in texto.split():
        resto = token
        while True:
            m = _MARCA_RE.match(resto)
            if not m:
                break
            nombre = m.group(1).lstrip("/").lower()
            if nombre == "center":
                center = True
            elif nombre in MARCAS_VALIDAS and not m.group(1).startswith("/"):
                pendiente = nombre
            resto = resto[m.end() :]  # marca (valida o no) se consume del texto
        resto = _MARCA_RE.sub("", resto)  # marcas incrustadas/de cierre: fuera
        if resto:
            if pendiente:
                marcas[len(palabras_limpias)] = pendiente
                pendiente = None
            palabras_limpias.append(resto)

    return " ".join(palabras_limpias), marcas, center


# ─────────────────────────────────────────────────────────────────────────────
# Fit contra safe zones (§5.3): reducir -> desactivar (mover no aplica a inline)
# ─────────────────────────────────────────────────────────────────────────────


def ajustar_escala_punch(
    palabra: str, fontsize: int, ancho_util_px: int, escala: int
) -> int | None:
    """Cadena REDUCIR: baja la escala en pasos hasta que la palabra quepa.

    Devuelve la escala que cabe (>= KW_SCALE_BASE) o None (DESACTIVAR: la palabra
    pierde el punch y queda como keyword normal — el texto nunca desaparece).
    El pico momentaneo del rebote (PICO_REBOTE_FACTOR) tambien debe caber.
    """
    e = int(escala)
    while e >= KW_SCALE_BASE:
        ancho_est = len(palabra) * fontsize * ANCHO_CHAR_FACTOR * (e / 100) * PICO_REBOTE_FACTOR
        if ancho_est <= ancho_util_px:
            return e
        e -= FIT_PASO
    return None
