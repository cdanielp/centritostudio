"""srt_render.py — Helpers de render reutilizables para SRT como texto oficial (S36-B / C2A1).

Extrae de `caption.py` la logica compartida por la CLI (`--srt`) y el worker de Studio
(S36-C2A1): aplicar el preset CVE SOLO a los grupos alineados (los `cue_fallback` quedan
estaticos, D36B-3) y el naming determinista de salidas `_srt` (sin colisionar con los
historicos). Fuente UNICA para que la CLI y el Studio produzcan exactamente los mismos
nombres y el mismo comportamiento de preset.

Sin FFmpeg, sin red, sin jobs. No duplica el motor CVE: delega en `cve.aplicar_preset`.
"""

from __future__ import annotations

from pathlib import Path


def apply_preset_to_srt_groups(
    groups: list,
    plan,
    *,
    brain_path: Path,
    width: int,
    height: int,
    manual_keywords_path: Path | None = None,
) -> tuple[list, object, str | None]:
    """Aplica el preset CVE SOLO a los grupos word_aligned; conserva intactos los fallback.

    Un preset jamas convierte un `cue_fallback` en word-by-word (D36B-3). Reune preservando
    el orden temporal, reasigna IDs deterministas y es fail-open ante un cambio de conteo
    (defensivo: `cve.aplicar_preset` enriquece 1:1, así que no ocurre en la practica).
    Devuelve (groups, plan, aviso); el `aviso` lo imprime el llamador (paridad con la CLI).
    """
    import cve  # noqa: PLC0415

    word_idx = [i for i, g in enumerate(groups) if g.get("timing_mode") != "cue_fallback"]
    word_groups = [groups[i] for i in word_idx]
    processed, plan, aviso = cve.aplicar_preset(
        word_groups, plan, brain_path, width, height, manual_keywords_path
    )
    merged = list(groups)
    if len(processed) == len(word_idx):
        for pos, g in zip(word_idx, processed, strict=True):
            merged[pos] = g
    else:  # defensivo (no ocurre en la practica: cve enriquece 1:1 y conserva el conteo).
        # Se imprime aqui, como la CLI historica, SIN pisar el aviso del engine (que el
        # llamador imprime aparte): ambos mensajes se conservan si algun dia coincidieran.
        print("[cve] AVISO: el preset altero el numero de grupos; se conservan los originales")
    for new_id, g in enumerate(merged):
        g["id"] = new_id
    return merged, plan, aviso


def variante_tag(
    plan, style: str, pop: str | None, rebote: bool | None, intensidad, densidad
) -> str:
    """Sufijo de variante para el nombre de salida SRT (mismo criterio que el flujo clasico)."""
    if plan:
        import cve  # noqa: PLC0415

        return cve.tag_variante(plan.preset, intensidad, densidad)
    pop_tag = f"_{pop}" if pop else ""
    reb_tag = "" if rebote is None else ("_reb" if rebote else "_plano")
    return f"_{style}{pop_tag}{reb_tag}"


def nombre_base_srt(
    stem, variante: str, use_emojis: bool, use_popups: bool, fx_preset: str | None
) -> str:
    """Basename (sin extension) del MP4 SRT: `_srt` + capas activas. No colisiona con historicos."""
    fx_tag = f"_fx-{fx_preset}" if fx_preset else ""
    return (
        f"{stem}{variante}_srt"
        + ("_emojis" if use_emojis else "")
        + ("_popups" if use_popups else "")
        + fx_tag
    )


__all__ = ["apply_preset_to_srt_groups", "variante_tag", "nombre_base_srt"]
