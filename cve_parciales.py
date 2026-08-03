"""cve_parciales.py — Gate de enfasis para cues `word_partial` (S39).

## El problema

Desde S38 un cue puede alinearse PARCIALMENTE: los tokens que anclan en una timing word
real conservan su tiempo medido; los huecos los reparte `srt_eventos` con interpolacion, y
un token que no llega al minimo se ABSORBE en el evento anterior. El resultado es un group
normal del motor, con timing por palabra... solo que una parte de ese timing es inventada.

El motor CVE no lo sabia. `srt_render` ya le pasaba los `word_partial` junto con los
`word_aligned`, asi que el punch podia caer sobre una palabra `interpolado` (tiempo
repartido) o `absorbido` (un evento que muestra 3 tokens a la vez). Visualmente eso es un
enfasis fuera de beat: la palabra crece cuando el motor cree, no cuando se dice.

## La regla

En un cue PARCIAL, una keyword automatica solo vale si se apoya en un ancla REAL
(`exact_match` o `substitution_match`) y la palabra tiene carga semantica (lista ampliada de
`stopwords_es`). Si no la hay, el cue se pinta sin enfasis — con texto y timing intactos.

Los cues `word_aligned` NO pasan por aqui: todos sus tokens son anclas reales. Las marcas
MANUALES tampoco: destacar es intencion explicita del usuario y gana a todo (voto #34).

## La auditoria

Cada cue parcial deja registro de si se le puso preset y por que no, con vocabulario
cerrado. `freno_densidad` y `antispam_r7` se distinguen de verdad (via
`cve_keywords.elegir_keywords_detallado`) en vez de agruparse en un "no salio" generico:
D45 se pago caro por un sidecar que reportaba una razon que no era la suya.

Puro: solo stdlib, sin IO, sin mutar los groups.
"""

from __future__ import annotations

import cve_keywords as ck
import stopwords_es

# Un timing MEDIDO. El resto (`interpolado`, `absorbido`) lo calculo `srt_eventos`.
ANCLAS_REALES = frozenset({"exact_match", "substitution_match"})

MODO_PARCIAL = "word_partial"

# Vocabulario cerrado de razones. Se publica tal cual en el sidecar y en el reporte.
RAZON_OK = "con_preset"  # el cue lleva enfasis automatico
RAZON_MANUAL = "manual"  # lleva enfasis por marca explicita del usuario (exento del gate)
RAZON_SIN_CANDIDATO = "sin_candidato"  # ninguna regla propuso una palabra con carga
RAZON_SIN_ANCLA = "sin_ancla_real"  # habia candidata, pero su timing es inventado
RAZON_DENSIDAD = "freno_densidad"  # candidata valida; la corto el tope de D21
RAZON_ANTISPAM = "antispam_r7"  # candidata valida; la corto el anti-spam de repetidas
RAZON_KEYWORDS_OFF = (
    "keywords_off"  # el preset no selecciona keywords (no es una decision del gate)
)

RAZONES = (
    RAZON_OK,
    RAZON_MANUAL,
    RAZON_SIN_CANDIDATO,
    RAZON_SIN_ANCLA,
    RAZON_DENSIDAD,
    RAZON_ANTISPAM,
    RAZON_KEYWORDS_OFF,
)


def es_ancla_real(word: dict) -> bool:
    """True si el timing de esta palabra se MIDIO (no se repartio ni se absorbio).

    Sin campo `kind` -> False: un group que no declara procedencia no puede afirmarla. En la
    practica solo llegan aqui groups de `srt_caption`, que siempre lo traen.
    """
    return str(word.get("kind") or "") in ANCLAS_REALES


class GateParciales:
    """Filtra candidatos automaticos en cues parciales y registra la decision de cada uno.

    Uso (lo cablea `srt_render`, no el llamador):

        gate = GateParciales()
        ... = cve.aplicar_preset(..., gate=gate)
        plan.kw_parciales = gate.resumen()

    Una instancia = un render. No se reutiliza entre renders (el registro se acumularia).
    """

    def __init__(self) -> None:
        # g_idx -> conteos de la fase de filtrado (que se propuso y que sobrevivio)
        self._filtro: dict[int, dict] = {}
        self._registros: list[dict] = []
        self._max_auto: int | None = None
        self._densidad: str | None = None

    # ── Fase 1: filtrado de candidatos ───────────────────────────────────────

    def filtrar_candidatos(
        self,
        groups: list[dict],
        candidatos: list[tuple[int, int, int, str]],
        manual_map: dict[int, list[tuple[int, str]]] | None = None,
    ) -> list[tuple[int, int, int, str]]:
        """Quita los candidatos AUTOMATICOS de cues parciales que no se apoyan en ancla real.

        Conserva el orden original (la seleccion depende de el ante empates) y no toca los
        candidatos de cues completos, de cues fallback ni las marcas manuales.
        """
        manual_map = manual_map or {}
        parciales = {
            g_idx
            for g_idx, g in enumerate(groups)
            if g.get("timing_mode") == MODO_PARCIAL and g_idx not in manual_map
        }
        for g_idx in parciales:
            self._filtro.setdefault(g_idx, {"propuestos": 0, "sin_ancla": 0, "debiles": 0})

        salida: list[tuple[int, int, int, str]] = []
        for cand in candidatos:
            g_idx, w_idx, score, _regla = cand
            if g_idx not in parciales or score >= ck.SCORE_MANUAL:
                salida.append(cand)
                continue
            stats = self._filtro[g_idx]
            stats["propuestos"] += 1
            palabra = self._palabra(groups, g_idx, w_idx)
            if palabra is None or not es_ancla_real(palabra):
                stats["sin_ancla"] += 1
                continue
            if stopwords_es.es_stopword(palabra.get("text", ""), ampliada=True):
                stats["debiles"] += 1
                stats.setdefault("debil_ejemplo", palabra.get("text", ""))
                continue
            salida.append(cand)
        return salida

    # ── Fase 2: registro de lo que la seleccion decidio ──────────────────────

    def registrar_sin_seleccion(self, groups: list[dict]) -> None:
        """Cierra el registro cuando el preset NO selecciona keywords (`keywords: off`).

        Sin esto el resumen quedaria en ceros y un lector lo leeria como "no habia cues
        parciales", que es distinto de "los habia y el preset no destaca nada".
        """
        self._registros = [
            {
                "cue": g.get("id", g_idx),
                "inicio_ms": int(round(float(g.get("start", 0.0)) * 1000)),
                "preset": False,
                "razon": RAZON_KEYWORDS_OFF,
                "palabra": None,
                "regla": None,
            }
            for g_idx, g in enumerate(groups)
            if g.get("timing_mode") == MODO_PARCIAL
        ]

    def anular(self) -> None:
        """Descarta el registro: el render salio SIN marcas (fallback del engine).

        Afirmar un enfasis que no se aplico es peor que no reportar nada.
        """
        self._registros = []

    def registrar_seleccion(
        self,
        groups: list[dict],
        seleccion: ck.SeleccionKeywords,
        manual_map: dict[int, list[tuple[int, str]]] | None = None,
        densidad: str | None = None,
    ) -> None:
        """Cierra el registro: una entrada por cue parcial, con su razon definitiva."""
        manual_map = manual_map or {}
        self._max_auto = seleccion.max_auto
        self._densidad = densidad
        self._registros = []
        for g_idx, g in enumerate(groups):
            if g.get("timing_mode") != MODO_PARCIAL:
                continue
            self._registros.append(self._registro(groups, g_idx, g, seleccion, manual_map))

    def _registro(
        self,
        groups: list[dict],
        g_idx: int,
        g: dict,
        seleccion: ck.SeleccionKeywords,
        manual_map: dict[int, list[tuple[int, str]]],
    ) -> dict:
        base = {
            "cue": g.get("id", g_idx),
            "inicio_ms": int(round(float(g.get("start", 0.0)) * 1000)),
        }
        if g_idx in manual_map:
            palabras = manual_map[g_idx]
            w_idx, regla = palabras[0]
            marcadas = {
                # Un span manual marca VARIAS palabras (#34): el registro dice cuantas para
                # que el sidecar no aparente una sola.
                "n_palabras": len(palabras)
            }
            return {
                **base,
                "preset": True,
                "razon": RAZON_MANUAL,
                **self._detalle(groups, g_idx, w_idx, regla),
                **marcadas,
            }
        for destino, razon in (
            (seleccion.elegidas, RAZON_OK),
            (seleccion.recorte_densidad, RAZON_DENSIDAD),
            (seleccion.recorte_antispam, RAZON_ANTISPAM),
        ):
            if g_idx in destino:
                w_idx, _score, regla = destino[g_idx]
                return {
                    **base,
                    "preset": razon == RAZON_OK,
                    "razon": razon,
                    **self._detalle(groups, g_idx, w_idx, regla),
                }
        stats = self._filtro.get(g_idx, {})
        # Sin candidata viva: distinguir "no habia nada que destacar" de "lo habia, pero su
        # timing es inventado". Una palabra vacia cuenta como lo primero (no es candidata).
        if stats.get("sin_ancla") and not stats.get("debiles"):
            return {
                **base,
                "preset": False,
                "razon": RAZON_SIN_ANCLA,
                "palabra": None,
                "regla": None,
            }
        # Caso mixto (hubo candidata anclada-pero-vacia Y candidata sin ancla): la razon es
        # `sin_candidato` — alguna SI tenia ancla, asi que `sin_ancla_real` seria falso — pero
        # el detalle publica ambos conteos para que la auditoria no pierda informacion.
        detalle = {}
        if stats.get("debiles"):
            detalle = {"detalle": f"debil:{stats.get('debil_ejemplo', '')}"}
            if stats.get("sin_ancla"):
                detalle["detalle"] += f" +{stats['sin_ancla']}_sin_ancla"
        return {
            **base,
            "preset": False,
            "razon": RAZON_SIN_CANDIDATO,
            "palabra": None,
            "regla": None,
            **detalle,
        }

    @staticmethod
    def _palabra(groups: list[dict], g_idx: int, w_idx: int) -> dict | None:
        words = groups[g_idx].get("words", []) if 0 <= g_idx < len(groups) else []
        return words[w_idx] if 0 <= w_idx < len(words) else None

    def _detalle(self, groups: list[dict], g_idx: int, w_idx: int, regla: str) -> dict:
        palabra = self._palabra(groups, g_idx, w_idx)
        return {"palabra": None if palabra is None else palabra.get("text", ""), "regla": regla}

    # ── Salida ───────────────────────────────────────────────────────────────

    def resumen(self) -> dict:
        """Auditoria completa del gate. `None` no es opcion: sin cues parciales -> ceros."""
        totales = dict.fromkeys(RAZONES, 0)
        for r in self._registros:
            totales[r["razon"]] += 1
        return {
            "n_cues_parciales": len(self._registros),
            "con_preset": sum(1 for r in self._registros if r["preset"]),
            "densidad": self._densidad,
            "max_auto": self._max_auto,
            "totales": totales,
            "cues": list(self._registros),
        }


def linea_reporte(resumen: dict | None) -> str | None:
    """Una linea legible con los totales por razon, para consola y REPORTE. None si no aplica."""
    if not resumen or not resumen.get("n_cues_parciales"):
        return None
    t = resumen["totales"]
    detalle = " ".join(f"{razon}={t[razon]}" for razon in RAZONES if t[razon])
    return (
        f"[cve] cues parciales: {resumen['con_preset']}/{resumen['n_cues_parciales']} "
        f"con enfasis | tope automatico {resumen['max_auto']} "
        f"(densidad {resumen['densidad'] or 'historica'}) | {detalle}"
    )


__all__ = [
    "ANCLAS_REALES",
    "RAZONES",
    "RAZON_ANTISPAM",
    "RAZON_DENSIDAD",
    "RAZON_MANUAL",
    "RAZON_OK",
    "RAZON_SIN_ANCLA",
    "RAZON_SIN_CANDIDATO",
    "GateParciales",
    "es_ancla_real",
    "linea_reporte",
]
