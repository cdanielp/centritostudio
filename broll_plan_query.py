"""broll_plan_query.py — Texto -> query y clasificacion image/video (S37-A).

Capa PURA y lexica: no traduce, no llama LLM, no consulta Pexels, no usa red ni
aleatoriedad. Todo el matching (stopwords, movimiento) usa una forma normalizada
(casefold + plegado de acentos) pero la SALIDA humana conserva acentos y enie.

La decision image/video es conservadora: image por default, video solo si hay una
senal textual EXPLICITA de movimiento/accion/proceso, y la razon registra que
termino exacto la activo.
"""

from __future__ import annotations

# Pliega acentos y enie SOLO para comparar (la salida conserva la forma original).
_FOLD = str.maketrans("áéíóúüñ", "aeiouun")

# Puntuacion periferica que se recorta de los bordes de un token (no del interior).
_STRIP_CHARS = " \t\r\n.,;:!?¡¿\"'“”‘’()[]{}…—–-*_/\\|`~#@%&+=<>"

# Stopwords para construir queries visuales: articulos, conectores, pronombres debiles.
# Lista local, pequena e inmutable (no se importa cve_keywords para mantener el planner
# autocontenido y sin acoplar contratos historicos). Se compara en forma plegada.
QUERY_STOPWORDS = frozenset(
    "el la los las un una unos unas de del al a en que quien cual cuyo y e o u con "
    "por para se me te le les nos os lo mi tu su sus mis tus nuestro nuestra vuestro "
    "es son fue era eran ser estar esta este esto esa ese eso estos estas esos esas "
    "como mas menos muy ya si no hay han ha he has hemos va van voy vas ir "
    "pero aunque embargo entonces cuando donde porque asi tan tanto cada todo toda "
    "todos todas algo alguien nada nadie aqui alla ahi".split()
)

# Terminos de movimiento/accion/proceso (forma plegada). Conservador y auditable:
# formas base + inflexiones comunes explicitas. Evita stems amplios con falsos positivos
# (p.ej. NO se usa "corr" porque casaria "correo").
# Familias verbales con sus inflexiones comunes en tutoriales (incluye la voz "nosotros"
# -amos/-emos/-imos, muy frecuente en el dominio: "caminamos", "conectamos", "cocinamos").
MOTION_TERMS = frozenset(
    "mover mueve mueven muevo movemos moviendo movio movido movimiento movimientos "
    "caminar camina caminan caminamos caminando "
    "correr corre corren corremos corriendo "
    "saltar salta saltan saltamos saltando salto "
    "girar gira giran giramos girando giro "
    "rotar rota rotan rotamos rotando rotacion "
    "avanzar avanza avanzan avanzamos avanzando avance "
    "retroceder retrocede retroceden retrocedemos retrocediendo "
    "subir sube suben subimos subiendo "
    "bajar baja bajan bajamos bajando "
    "entrar entra entran entramos entrando "
    "salir sale salen salimos saliendo "
    "abrir abre abren abrimos abriendo "
    "cerrar cierra cierran cerramos cerrando "
    "mezclar mezcla mezclan mezclamos mezclando "
    "cortar corta cortan cortamos cortando corte "
    "cocinar cocina cocinan cocinamos cocinando "
    "construir construye construyen construimos construyendo "
    "instalar instala instalan instalamos instalando instalacion "
    "conectar conecta conectan conectamos conectando conexion "
    "montar monta montan montamos montando montaje "
    "transformar transforma transforman transformamos transformando transformacion "
    "convertir convierte convierten convertimos convirtiendo "
    "cambiar cambia cambian cambiamos cambiando cambio "
    "crecer crece crecen crecemos creciendo "
    "caer cae caen caemos cayendo "
    "volar vuela vuelan volamos volando "
    "conducir conduce conducen conducimos conduciendo "
    "manejar maneja manejan manejamos manejando "
    "viajar viaja viajan viajamos viajando viaje "
    "proceso procesos procedimiento".split()
)

# Frases de movimiento que se detectan como subcadena del texto plegado.
MOTION_PHRASES = ("paso a paso", "antes y despues")


def fold(text: str) -> str:
    """Forma normalizada para comparar: casefold + plegado de acentos/enie."""
    return text.casefold().translate(_FOLD)


def clean_token(token: str) -> str:
    """Recorta puntuacion periferica conservando el interior y el Unicode (acentos, enie)."""
    return token.strip(_STRIP_CHARS)


def tokenize(text: str) -> list[str]:
    """Tokeniza por espacios y limpia bordes; descarta vacios. Determinista, sin regex amplia."""
    out: list[str] = []
    for raw in text.split():
        tok = clean_token(raw)
        if tok:
            out.append(tok)
    return out


def detect_motion(keyword: str, group_text: str) -> tuple[str, ...]:
    """Terminos de movimiento presentes en keyword+group_text (forma plegada, orden de aparicion).

    Vacio => la ventana sera image. No-vacio => es CANDIDATA a video (el cupo lo decide el planner).
    """
    found: list[str] = []
    seen: set[str] = set()
    for tok in tokenize(f"{keyword} {group_text}"):
        f = fold(tok)
        if f in MOTION_TERMS and f not in seen:
            seen.add(f)
            found.append(f)
    folded_text = fold(group_text)
    for phrase in MOTION_PHRASES:
        if phrase in folded_text and phrase not in seen:
            seen.add(phrase)
            found.append(phrase)
    return tuple(found)


def build_query(
    keyword: str, group_text: str, max_terms: int
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    """Deriva una query pequena y trazable del texto real del grupo.

    Regla: keyword primero; luego tokens de contexto en orden fuente, sin stopwords ni
    duplicados, hasta max_terms. Devuelve (query, terminos_elegidos, terminos_descartados).
    Preserva acentos/enie en la salida; el matching de stopwords usa forma plegada.
    """
    kw = clean_token(keyword)
    chosen: list[str] = []
    dropped: list[str] = []
    seen: set[str] = set()
    if kw:
        chosen.append(kw)
        seen.add(fold(kw))
    for tok in tokenize(group_text):
        f = fold(tok)
        if f in seen:
            dropped.append(tok)
            continue
        if f in QUERY_STOPWORDS:
            dropped.append(tok)
            continue
        if len(chosen) >= max_terms:
            dropped.append(tok)
            continue
        chosen.append(tok)
        seen.add(f)
    query = " ".join(chosen)
    return query, tuple(chosen), tuple(dropped)


__all__ = [
    "QUERY_STOPWORDS",
    "MOTION_TERMS",
    "MOTION_PHRASES",
    "fold",
    "clean_token",
    "tokenize",
    "detect_motion",
    "build_query",
]
