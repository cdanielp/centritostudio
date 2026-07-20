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

DENSIDAD_MAX = 0.40  # fraccion maxima de grupos con keyword (anti-spam, ruta historica)

# Densidades calibradas (D21, s31): DOBLE FRENO tope absoluto Y porcentaje.
# En clips cortos manda el %, en largos el tope absoluto — es intencional, no
# simplificar a solo %. baja usa el techo del rango 10-15% votado (el tope
# absoluto ya frena los clips largos). Default de keyword_punch: "baja".
DENSIDADES: dict[str, tuple[int, float]] = {
    "baja": (5, 0.15),
    "media": (10, 0.20),
    "alta": (15, 0.30),
}
DENSIDAD_DEFAULT = "baja"
REPETIDA_MIN_APARICIONES = 3
REPETIDA_MAX_MARCAS = 2  # solo las primeras N apariciones de una repetida
LARGO_MIN_CONTENIDO = 4  # chars minimos para que una palabra sea "de contenido" (R7)
# Filtro anti-debil (D22): mas conservador que LARGO_MIN_CONTENIDO — solo corta
# fragmentos de 1-2 chars. Palabras cortas CON valor ("kit", "PNG") sobreviven; los
# stopwords ya se cazan por lista sin importar longitud. Evita falsos positivos.
LARGO_MIN_KEYWORD_DEBIL = 3

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
_SPAN_MARKS = frozenset({"strong", "big"})  # spans de enfasis; center es posicional
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


def es_keyword_debil(palabra: str, crudo: str | None = None) -> bool:
    """True si la palabra NO debe entrar como keyword AUTOMATICA (stopword/corta).

    Filtro anti-basura del brain (D22, BLOQUE 2): el brain reancla por timestamp y
    puede elegir palabras debiles ("en", "un", "de"). Se descarta si es stopword o
    demasiado corta, EXCEPTO si dispara una senal fuerte (dinero/numeros/negaciones/
    fechas via _regla_por_palabra) — esas nunca son debiles.

    Las reglas R1-R7 ya saltan stopwords; esto cubre la ruta del brain. Las marcas
    MANUALES jamas pasan por aqui (voto #34: manual siempre gana).
    """
    n = _normalizar(palabra)
    if _regla_por_palabra(n, crudo if crudo is not None else palabra) is not None:
        return False  # senal fuerte: dinero, numero, negacion o fecha
    return n in STOPWORDS or len(n) < LARGO_MIN_KEYWORD_DEBIL


def razon_debil(palabra: str) -> str:
    """Razon legible del descarte (para el sidecar de transparencia D21/D22)."""
    n = _normalizar(palabra)
    return "stopword" if n in STOPWORDS else "corta"


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


def candidatos_brain(
    groups: list[dict], brain_data: dict | None, descartadas: list | None = None
) -> list:
    """Marcas del brain.json como candidatos score 100 (re-ancla por kw_ts, como apply_brain).

    Filtro D22 (BLOQUE 2): una palabra del brain que sea debil (stopword/corta sin
    senal fuerte) NO entra como candidato. Si se pasa `descartadas`, se le anexa un
    registro {palabra, timestamp, grupo, razon, fuente} de cada rechazo (transparencia).
    """
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
            if round(float(w.get("start", -999)), 3) not in kw_ts:
                continue
            palabra = w.get("text", "")
            if es_keyword_debil(palabra):
                if descartadas is not None:
                    descartadas.append(
                        {
                            "palabra": palabra,
                            "timestamp": w.get("start"),
                            "grupo": g_idx,
                            "razon": razon_debil(palabra),
                            "fuente": "brain",
                        }
                    )
                continue
            result.append((g_idx, w_idx, SCORE_BRAIN, "brain"))
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Merge y seleccion (§4.2): manual > brain > reglas, 1 por grupo, densidad max
# ─────────────────────────────────────────────────────────────────────────────


def max_keywords_auto(n_groups: int, densidad: str | None) -> int:
    """Doble freno de D21: min(tope absoluto, porcentaje). None = ruta historica (40%)."""
    if densidad in DENSIDADES:
        tope, pct = DENSIDADES[densidad]
        return min(tope, max(int(n_groups * pct), 1))
    return max(int(n_groups * DENSIDAD_MAX), 1)


def elegir_keywords(
    candidatos: list[tuple[int, int, int, str]],
    n_groups: int,
    densidad: str | None = None,
) -> dict[int, tuple[int, int, str]]:
    """Merge final: 1 keyword por grupo (score mayor; empate no reordena) + freno densidad.

    Devuelve {g_idx: (w_idx, score, regla)}. Anti-spam R7: no 2 grupos consecutivos por R7.
    El freno de densidad (D21) recorta solo las AUTOMATICAS (peor score primero); las
    marcas manuales quedan exentas (voto #34: saturar es decision del usuario).
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

    max_kw = max_keywords_auto(n_groups, densidad)
    autos = {g: v for g, v in por_grupo.items() if v[1] < SCORE_MANUAL}
    if len(autos) > max_kw:
        sobran = sorted(autos.items(), key=lambda kv: -kv[1][1])[max_kw:]
        for g_idx, _v in sobran:
            por_grupo.pop(g_idx)
    return por_grupo


def elegir_manuales(
    candidatos: list[tuple[int, int, int, str]],
) -> dict[int, list[tuple[int, str]]]:
    """Todas las palabras manuales (SCORE_MANUAL) por grupo, deduplicadas y ordenadas.

    Los spans/frases manuales estan EXENTOS de 1-por-grupo y de densidad (#34): cada
    palabra marcada sobrevive. Dedup por (grupo, palabra); en conflicto de regla gana
    'manual_big' (mas fuerte). Determinista: indices ascendentes. Devuelve
    {g_idx: [(w_idx, regla), ...]}.
    """
    por_grupo: dict[int, dict[int, str]] = {}
    for g_idx, w_idx, score, regla in candidatos:
        if score < SCORE_MANUAL:
            continue
        reglas = por_grupo.setdefault(g_idx, {})
        if w_idx not in reglas or regla == "manual_big":
            reglas[w_idx] = regla
    return {g: sorted(r.items()) for g, r in por_grupo.items()}


# ─────────────────────────────────────────────────────────────────────────────
# Marcado manual v1 por sidecar (§7, D22 BLOQUE 3): {stem}_keywords.json
# ─────────────────────────────────────────────────────────────────────────────

# Intensidades de una entrada manual -> regla (big amplifica escala como manual_big)
_INTENSIDAD_A_REGLA = {"big": "manual_big", "grande": "manual_big"}


def _regla_manual(entry: dict) -> str:
    """Regla de una entrada manual: 'manual' o 'manual_big' segun intensidad/perfil."""
    inten = str(entry.get("intensidad") or entry.get("perfil") or "").lower()
    return _INTENSIDAD_A_REGLA.get(inten, "manual")


def _entry_apunta_al_grupo(entry: dict, g_idx: int, words: list[dict]) -> bool:
    """Filtro opcional de una entrada por grupo o timestamp (si los trae)."""
    if entry.get("grupo") is not None and int(entry["grupo"]) != g_idx:
        return False
    ts = entry.get("timestamp")
    if ts is not None:
        return any(abs(float(w.get("start", -999)) - float(ts)) < 0.05 for w in words)
    return True


def candidatos_manuales(groups: list[dict], entries: list[dict] | None) -> list:
    """Candidatos manuales (SCORE_MANUAL) desde el sidecar {stem}_keywords.json.

    Cada entrada destaca una `palabra` exacta o una `frase` corta (secuencia de
    palabras). Opcional: `grupo`/`timestamp` para acotar, `intensidad`/`perfil` para
    amplificar (big -> manual_big). Prioridad total sobre reglas y brain; NUNCA se
    filtra por stopwords (voto #34: manual siempre gana). Marca TODAS las apariciones
    que casen (elegir_keywords deja 1 por grupo; manual esta exento de densidad).

    Fail-open a nivel entrada: una entrada malformada se ignora con log, no rompe.
    """
    if not entries:
        return []
    result: list[tuple[int, int, int, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            palabra = entry.get("palabra")
            frase = entry.get("frase")
            secuencia = (
                [_normalizar(t) for t in str(frase).split()]
                if frase
                else ([_normalizar(str(palabra))] if palabra else [])
            )
            secuencia = [s for s in secuencia if s]
            if not secuencia:
                continue
            regla = _regla_manual(entry)
            for g_idx, g in enumerate(groups):
                words = g.get("words", [])
                if not _entry_apunta_al_grupo(entry, g_idx, words):
                    continue
                norms = [_normalizar(w.get("text", "")) for w in words]
                for i in range(len(norms) - len(secuencia) + 1):
                    if norms[i : i + len(secuencia)] == secuencia:
                        # Span #34: la frase marca CADA palabra (no solo el ancla);
                        # una `palabra` (secuencia de 1) sigue marcando esa sola palabra.
                        for off in range(len(secuencia)):
                            result.append((g_idx, i + off, SCORE_MANUAL, regla))
        except (ValueError, TypeError, KeyError) as e:
            print(f"[cve] entrada manual ignorada ({e}) - render no afectado")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Marcado manual v1 inline (§7): [strong] [big] [center] — parser tolerante
# ─────────────────────────────────────────────────────────────────────────────


def limpiar_token(token: str) -> str:
    """Texto visible de un token: toda marca [x] (valida, invalida o cierre) se elimina.

    Misma regla que parsear_marcas — el ASS jamas muestra corchetes de marca (voto #34).
    """
    return _MARCA_RE.sub("", token)


def _tokenizar_marcas(token: str) -> list[tuple[str, str]]:
    """Descompone un token en eventos ordenados: ('open'|'close', nombre) | ('word', texto).

    Reconoce marcas al inicio, al final o incrustadas ('todo[/strong]', '[big]diez')
    para que un span cierre aunque el tag venga pegado a la ultima palabra del cue.
    """
    eventos: list[tuple[str, str]] = []
    pos = 0
    for m in _MARCA_RE.finditer(token):
        if m.start() > pos:
            eventos.append(("word", token[pos : m.start()]))
        crudo = m.group(1)
        eventos.append(("close" if crudo.startswith("/") else "open", crudo.lstrip("/").lower()))
        pos = m.end()
    if pos < len(token):
        eventos.append(("word", token[pos:]))
    return eventos


def _cerrar_span(
    abiertos: list[tuple[str, int]], nombre: str, fin: int, spans: list[tuple[str, int, int]]
) -> None:
    """Empareja el span abierto mas reciente con ese nombre (LIFO). Sin apertura -> se ignora."""
    for k in range(len(abiertos) - 1, -1, -1):
        if abiertos[k][0] == nombre:
            _n, ini = abiertos.pop(k)
            spans.append((nombre, ini, fin))
            return


def _marcas_por_palabra(spans: list[tuple[str, int, int]], n: int) -> dict[int, str]:
    """Resuelve la marca de cada palabra: gana el span mas corto/interno; empate -> big."""
    marcas: dict[int, str] = {}
    for idx in range(n):
        cubren = [sp for sp in spans if sp[1] <= idx < sp[2]]
        if cubren:
            marcas[idx] = min(cubren, key=lambda sp: (sp[2] - sp[1], 0 if sp[0] == "big" else 1))[0]
    return marcas


def _es_solo_puntuacion(s: str) -> bool:
    """True si s no tiene ningun caracter alfanumerico (coma, punto, comillas, ¿¡?!…)."""
    return bool(s) and not any(c.isalnum() for c in s)


def _procesar_token(
    eventos: list[tuple[str, str]],
    palabras: list[str],
    abiertos: list[tuple[str, int]],
    spans: list[tuple[str, int, int]],
) -> bool:
    """Procesa un token (= una palabra visible como maximo) y aplica sus marcas.

    Los segmentos de texto del token se CONCATENAN en una sola palabra: la puntuacion
    pegada a un cierre (`costo[/strong].`) queda DENTRO de la palabra (`costo.`), no como
    token extra — asi el indice y el conteo de palabras cuadran con las words del grupo.
    Si la marca viene separada por espacio (`[/strong] .` o `[/big] ,`) el token queda como
    SOLO puntuacion: se adjunta a la palabra previa (no crea palabra extra ni desalinea el
    conteo con group["words"]). Devuelve True si vio una apertura [center]. Muta in-place.
    """
    palabra = "".join(v for t, v in eventos if t == "word")
    # Puntuacion suelta tras un cierre/apertura separado por espacio -> a la palabra previa.
    if palabra and _es_solo_puntuacion(palabra) and palabras:
        palabras[-1] += palabra
        palabra = ""  # se trata como token de solo-marcas para el indexado
    idx = len(palabras)
    if palabra:
        palabras.append(palabra)
    # Palabra presente: apertura desde esta palabra, cierre inclusivo de esta palabra.
    # Token solo-marcas: apertura a la palabra SIGUIENTE, cierre hasta la ultima (compat v1).
    ini = idx
    fin = idx + 1 if palabra else idx
    center = False
    for tipo, val in eventos:
        if tipo == "open" and val == "center":
            center = True
        elif tipo == "open" and val in _SPAN_MARKS:
            abiertos.append((val, ini))
        elif tipo == "close" and val in _SPAN_MARKS:
            _cerrar_span(abiertos, val, fin, spans)
    return center


def parsear_marcas(texto: str) -> tuple[str, dict[int, str], bool]:
    """Extrae marcas v1/spans del texto de un grupo. Marca invalida = se elimina, jamas rompe.

    Devuelve (texto_limpio, {indice_palabra: marca}, center). Un span cerrado
    `[strong]a b c[/strong]` marca CADA palabra (#34); una apertura sin cierre marca solo
    la palabra siguiente (compat v1). La puntuacion pegada se conserva en la palabra y NO
    cuenta como palabra extra. Solapamientos: gana el span mas corto/interno (empate ->
    big). `[center]` es flag de grupo (posicional); su cierre se ignora.
    """
    if "[" not in texto:
        return texto, {}, False

    center = False
    palabras: list[str] = []
    abiertos: list[tuple[str, int]] = []  # (nombre, indice de la palabra inicial)
    spans: list[tuple[str, int, int]] = []  # (nombre, inicio, fin exclusivo)

    for token in texto.split():
        if _procesar_token(_tokenizar_marcas(token), palabras, abiertos, spans):
            center = True

    n = len(palabras)
    for nombre, ini in abiertos:  # apertura sin cierre -> next-word (compat v1)
        if ini < n:
            spans.append((nombre, ini, ini + 1))
    return " ".join(palabras), _marcas_por_palabra(spans, n), center


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
