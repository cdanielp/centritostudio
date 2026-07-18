"""srt_align.py — Alineacion PURA del texto oficial del SRT con timings reales (S36-B).

El TEXTO del SRT es la fuente oficial (D36B-1): jamas se sustituye, corrige, ni se
normaliza el contenido visible. La normalizacion de este modulo existe SOLO para
comparar tokens; el token original del SRT se preserva siempre para el output.

Los timings salen de `timing_words` (Whisper u otro transcript existente), nunca se
inventan (D36B-2). Solo hay tres tipos de timing por token: `exact_match`,
`substitution_match` (1:1 entre anclas reales) y, a nivel de cue, `cue_fallback`.

Modulo puro: sin disco, sin red, sin FFmpeg, sin render, sin mutacion. Tiempos en
milisegundos enteros (los timing words entran en segundos y se convierten en frontera).

Complejidad: por cue se alinean sus tokens contra las timing words cuyo punto medio
cae dentro de la ventana del cue (particion disjunta), con programacion dinamica tipo
edit-distance O(n_tokens_cue * n_words_ventana). El total queda acotado por el numero de
tokens del SRT y de timing words; no se construye una matriz global gigante.
"""

from __future__ import annotations

import bisect
import unicodedata
from dataclasses import dataclass, field

from srt_types import SrtDocument

ALIGN_VERSION = 1

# Umbral de cobertura por cue para considerarlo word-aligned. Default 1.0: TODOS los
# tokens del cue deben anclar en una timing word real (exact o substitution). Un solo
# token insertado (presente en el SRT, ausente en el audio) degrada el cue a fallback
# honesto en vez de inventarle timing. Ver D36B-2/D36B-3 y PREGUNTAS (threshold final).
DEFAULT_MIN_COVERAGE = 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Resultados tipados (frozen: nunca se mutan)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AlignedWord:
    """Un token del SRT anclado a una timing word real. text SIEMPRE es el original."""

    text: str
    start_ms: int
    end_ms: int
    line_idx: int
    kind: str  # "exact_match" | "substitution_match"


@dataclass(frozen=True)
class AlignedCue:
    """Un cue alineado. En modo cue_fallback words=() y se usa start/end exactos del cue."""

    cue_index: int
    start_ms: int
    end_ms: int
    lines: tuple[str, ...]
    mode: str  # "word_aligned" | "cue_fallback"
    words: tuple[AlignedWord, ...]
    n_tokens: int
    n_matched: int
    coverage: float
    reason: str

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@dataclass(frozen=True)
class AlignmentResult:
    """Resultado agregado + por cue. Serializable, sin rutas, sin secretos."""

    version: int
    cues: tuple[AlignedCue, ...]
    n_cues: int
    word_aligned: int
    cue_fallback: int
    coverage: float
    timing_source: str
    source_sha256: str = ""
    min_coverage: float = DEFAULT_MIN_COVERAGE
    video_duration_ms: int | None = None
    diagnostics: tuple[str, ...] = field(default_factory=tuple)


# ─────────────────────────────────────────────────────────────────────────────
# Normalizacion SOLO para comparar (nunca altera el token de salida)
# ─────────────────────────────────────────────────────────────────────────────


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def normalize_token(token: str) -> str:
    """Forma canonica para COMPARAR: NFKC + casefold + sin acentos + sin puntuacion de borde.

    Numeros y emojis se preservan. Nunca se usa para el texto visible (solo para el match).
    Si al quitar puntuacion queda vacio (token puramente simbolico) se conserva la forma
    plegada completa para no forzar fallbacks por un guion suelto.
    """
    base = _strip_accents(unicodedata.normalize("NFKC", token).casefold())
    stripped = base.strip("¿?¡!.,;:…\"'`()[]{}«»-—–_*~/\\ ")
    return stripped if stripped else base


def _tokenize_cue(lines: tuple[str, ...]) -> list[tuple[str, int]]:
    """(token_original, line_idx) en orden. Divide por espacios, preserva el token tal cual."""
    out: list[tuple[str, int]] = []
    for li, line in enumerate(lines):
        for tok in line.split():
            out.append((tok, li))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Alineacion de secuencias (edit-distance determinista con traceback estable)
# ─────────────────────────────────────────────────────────────────────────────


def _align_ops(src_norm: list[str], tw_norm: list[str]) -> list[tuple[str, int, int]]:
    """Alinea dos secuencias normalizadas. Ops: ('match'|'sub', i, j), ('ins', i, -1),
    ('del', -1, j). i indexa src (tokens SRT); j indexa timing words. Traceback
    determinista: prioriza diagonal, luego consumir timing word (del), luego insercion.
    """
    n, m = len(src_norm), len(tw_norm)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = i
    for j in range(1, m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        si = src_norm[i - 1]
        row, prev = dp[i], dp[i - 1]
        for j in range(1, m + 1):
            sub = prev[j - 1] + (0 if si == tw_norm[j - 1] else 1)
            row[j] = (
                sub
                if sub <= prev[j] + 1 and sub <= row[j - 1] + 1
                else min(prev[j], row[j - 1]) + 1
            )

    ops: list[tuple[str, int, int]] = []
    i, j = n, m
    while i > 0 or j > 0:
        cost = 0 if (i > 0 and j > 0 and src_norm[i - 1] == tw_norm[j - 1]) else 1
        if i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + cost:
            ops.append(("match" if cost == 0 else "sub", i - 1, j - 1))
            i, j = i - 1, j - 1
        elif j > 0 and dp[i][j] == dp[i][j - 1] + 1:
            ops.append(("del", -1, j - 1))
            j -= 1
        else:
            ops.append(("ins", i - 1, -1))
            i -= 1
    ops.reverse()
    return ops


# ─────────────────────────────────────────────────────────────────────────────
# Particion de timing words por ventana de cue (punto medio, disjunta)
# ─────────────────────────────────────────────────────────────────────────────


def _prepare_words(timing_words: list[dict]) -> tuple[list[int], list[dict]]:
    """Ordena las timing words por punto medio (ms). Devuelve (mids_ordenados, words_ms)."""
    prepared: list[dict] = []
    for w in timing_words:
        s_ms = int(round(float(w["s"]) * 1000))
        e_ms = int(round(float(w["e"]) * 1000))
        if e_ms <= s_ms:
            e_ms = s_ms + 1
        prepared.append(
            {
                "w": w["w"],
                "s_ms": s_ms,
                "e_ms": e_ms,
                "mid": (s_ms + e_ms) // 2,
                "norm": normalize_token(w["w"]),
            }
        )
    prepared.sort(key=lambda d: (d["mid"], d["s_ms"]))
    return [d["mid"] for d in prepared], prepared


def _claim_window(
    mids: list[int], words: list[dict], claimed: list[bool], start_ms: int, end_ms: int
) -> list[dict]:
    """Reclama las timing words no usadas con punto medio en [start_ms, end_ms)."""
    lo = bisect.bisect_left(mids, start_ms)
    hi = bisect.bisect_left(mids, end_ms)
    out: list[dict] = []
    for k in range(lo, hi):
        if not claimed[k]:
            claimed[k] = True
            out.append(words[k])
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Alineacion de un cue
# ─────────────────────────────────────────────────────────────────────────────


def _align_cue(cue, window: list[dict], min_coverage: float) -> AlignedCue:
    tokens = _tokenize_cue(cue.lines)
    n_tok = len(tokens)
    if n_tok == 0:  # no deberia ocurrir (validador exige texto), pero fail-open honesto
        return _fallback_cue(cue, 0, 0, "cue sin tokens")

    src_norm = [normalize_token(t) for t, _ in tokens]
    tw_norm = [w["norm"] for w in window]
    ops = _align_ops(src_norm, tw_norm)

    timing_by_src: dict[int, tuple[dict, str]] = {}
    for kind, i, j in ops:
        if kind in ("match", "sub") and i >= 0 and j >= 0:
            timing_by_src[i] = (
                window[j],
                "exact_match" if kind == "match" else "substitution_match",
            )

    n_matched = len(timing_by_src)
    coverage = n_matched / n_tok
    # word_aligned exige anclar TODOS los tokens (sin inserciones) y superar el umbral.
    if n_matched == n_tok and coverage >= min_coverage:
        words = tuple(
            AlignedWord(tokens[i][0], w["s_ms"], w["e_ms"], tokens[i][1], k)
            for i, (w, k) in sorted(timing_by_src.items())
        )
        words = _enforce_monotonic(words)
        return AlignedCue(
            cue.index,
            cue.start_ms,
            cue.end_ms,
            cue.lines,
            "word_aligned",
            words,
            n_tok,
            n_matched,
            round(coverage, 4),
            "todos los tokens anclados",
        )
    reason = f"cobertura {coverage:.2f} < {min_coverage:.2f}" if n_tok else "cue vacio"
    return _fallback_cue(cue, n_tok, n_matched, reason)


def _enforce_monotonic(words: tuple[AlignedWord, ...]) -> tuple[AlignedWord, ...]:
    """Garantiza start<end y no-decreciente. No inventa: solo empuja +1ms un choque exacto."""
    out: list[AlignedWord] = []
    last_end = -1
    for w in words:
        start = max(w.start_ms, last_end)
        end = max(w.end_ms, start + 1)
        out.append(AlignedWord(w.text, start, end, w.line_idx, w.kind))
        last_end = end
    return tuple(out)


def _fallback_cue(cue, n_tok: int, n_matched: int, reason: str) -> AlignedCue:
    cov = round(n_matched / n_tok, 4) if n_tok else 0.0
    return AlignedCue(
        cue.index,
        cue.start_ms,
        cue.end_ms,
        cue.lines,
        "cue_fallback",
        (),
        n_tok,
        n_matched,
        cov,
        reason,
    )


# ─────────────────────────────────────────────────────────────────────────────
# API publica
# ─────────────────────────────────────────────────────────────────────────────


def align_srt_to_words(
    document: SrtDocument,
    timing_words: list[dict],
    *,
    video_duration_ms: int | None = None,
    min_coverage: float = DEFAULT_MIN_COVERAGE,
    timing_source: str = "whisper_words",
) -> AlignmentResult:
    """Alinea el texto oficial del SRT con timings reales. No muta ninguna entrada.

    document: SrtDocument ya cargado/validado (texto = autoridad).
    timing_words: [{"w","s","e",...}] en segundos (Whisper u otro transcript).
    """
    mids, words = _prepare_words(timing_words)
    claimed = [False] * len(words)
    aligned: list[AlignedCue] = []
    for cue in document.cues:
        window = _claim_window(mids, words, claimed, cue.start_ms, cue.end_ms)
        aligned.append(_align_cue(cue, window, min_coverage))

    n_cues = len(aligned)
    n_word = sum(1 for c in aligned if c.mode == "word_aligned")
    total_tok = sum(c.n_tokens for c in aligned)
    total_match = sum(c.n_matched for c in aligned)
    coverage = round(total_match / total_tok, 4) if total_tok else 0.0
    return AlignmentResult(
        version=ALIGN_VERSION,
        cues=tuple(aligned),
        n_cues=n_cues,
        word_aligned=n_word,
        cue_fallback=n_cues - n_word,
        coverage=coverage,
        timing_source=timing_source,
        source_sha256=document.source_sha256,
        min_coverage=min_coverage,
        video_duration_ms=video_duration_ms,
    )


__all__ = [
    "ALIGN_VERSION",
    "DEFAULT_MIN_COVERAGE",
    "AlignedWord",
    "AlignedCue",
    "AlignmentResult",
    "normalize_token",
    "align_srt_to_words",
]
