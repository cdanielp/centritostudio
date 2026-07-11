"""cve_popups.py — image_popups v1: biblioteca del usuario + disparos manual/keyword (F6 S31).

Capa de RESOLUCION fail-open (DISENO_CVE.md §3.2): produce la lista de Popup que
core_ass.burn_video_with_emojis compone via core_overlays. Cualquier fallo (biblioteca
vacia, JSON invalido, imagen faltante) degrada a lista vacia o entrada omitida con
log accionable (regla #16) — el render JAMAS se cae por un popup. ComfyUI no se
requiere: la cascada v1 es manual ({stem}_popups.json) -> biblioteca por keyword.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

from core_overlays import ANCLAS, POPUP_FADE_S, Popup

ROOT = Path(__file__).parent
BIBLIOTECA_DIR = ROOT / "assets" / "biblioteca"
TRANSCRIPTS_DIR = ROOT / "transcripts"

EXTENSIONES_VALIDAS = (".png", ".webp")  # imagenes con transparencia (alpha)
POPUP_DURATION_S = 1.2  # duracion default (la misma probada de la capa de emojis)
POSICIONES_VALIDAS = ANCLAS | {"auto_safe"}
_ID_RE = re.compile(r"[^a-z0-9_-]")


def sanitizar_id(nombre: str) -> str:
    """Id canonico desde un filename o palabra: minusculas, sin acentos, [a-z0-9_-]."""
    n = nombre.lower().translate(str.maketrans("áéíóúüñ", "aeiouun"))
    return _ID_RE.sub("", n)


def indexar_biblioteca(directorio: Path | None = None) -> dict[str, Path]:
    """Mapa id -> ruta desde assets/biblioteca. Vacia o ausente -> {} (fail-open)."""
    d = directorio or BIBLIOTECA_DIR
    if not d.is_dir():
        return {}
    index: dict[str, Path] = {}
    for f in sorted(d.iterdir()):
        if f.suffix.lower() not in EXTENSIONES_VALIDAS:
            continue
        iid = sanitizar_id(f.stem)
        if not iid:
            print(f"[popups] archivo sin id valido, ignorado: {f.name}")
            continue
        if iid in index:
            print(f"[popups] id duplicado '{iid}': gana {index[iid].name}, se ignora {f.name}")
            continue
        index[iid] = f
    return index


def _resolver_png_manual(entrada: dict, biblioteca: dict[str, Path]) -> Path | None:
    """Ruta del PNG de una entrada manual: id de biblioteca ('imagen') o ruta 'png'
    relativa a assets/. None si no resuelve."""
    iid = sanitizar_id(str(entrada.get("imagen", "") or ""))
    if iid and iid in biblioteca:
        return biblioteca[iid]
    png = str(entrada.get("png", "") or "")
    if png:
        rel = Path(png)
        if not rel.is_absolute() and ".." not in rel.parts:
            candidato = ROOT / "assets" / rel
            if candidato.exists():
                return candidato
    return None


def _entrada_manual(i: int, entrada: object, biblioteca: dict[str, Path]) -> Popup | None:
    """Valida una entrada de popups.json. Invalida -> None con log accionable."""
    if not isinstance(entrada, dict):
        print(f"[popups] entrada #{i} no es un objeto JSON, omitida")
        return None
    try:
        t0 = float(entrada["t"])
        dur = float(entrada.get("dur", POPUP_DURATION_S))
        if t0 < 0 or dur <= 0:
            raise ValueError("t/dur fuera de rango")
    except (KeyError, TypeError, ValueError):
        print(f"[popups] entrada #{i} sin 't'/'dur' validos, omitida")
        return None
    png = _resolver_png_manual(entrada, biblioteca)
    if png is None:
        print(f"[popups] entrada #{i}: imagen no encontrada ('imagen' id o 'png' ruta), omitida")
        print("  -> Accion: agrega el PNG/WebP a assets/biblioteca/ o corrige la ruta")
        return None
    pos = str(entrada.get("pos", "auto_safe"))
    if pos not in POSICIONES_VALIDAS:
        print(f"[popups] entrada #{i}: pos '{pos}' invalida, se usa auto_safe")
        pos = "auto_safe"
    behind = bool(entrada.get("behind_text", False))
    return Popup(png=png, t0=t0, t1=t0 + dur, pos=pos, behind_text=behind)


def cargar_popups_manual(path: Path, biblioteca: dict[str, Path]) -> list[Popup]:
    """Lee {stem}_popups.json. JSON invalido o no-lista -> [] con log, jamas rompe."""
    if not path.exists():
        return []
    try:
        # utf-8-sig: tolera el BOM que Notepad agrega al guardar "UTF-8 con BOM"
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError) as e:
        print(f"[popups] {path.name} invalido ({e}) - popups manuales omitidos")
        return []
    if not isinstance(data, list):
        print(f"[popups] {path.name} debe ser una lista JSON - popups manuales omitidos")
        return []
    result: list[Popup] = []
    for i, entrada in enumerate(data):
        p = _entrada_manual(i, entrada, biblioteca)
        if p:
            result.append(p)
    return result


def popups_por_keyword(groups: list[dict], biblioteca: dict[str, Path]) -> list[Popup]:
    """Dispara un popup cuando una palabra del transcript coincide con un id de biblioteca.

    v1: primera aparicion por id (el freno de solape lo aplica resolver_popups).
    """
    vistos: set[str] = set()
    result: list[Popup] = []
    for g in groups:
        for w in g.get("words", []):
            iid = sanitizar_id(str(w.get("text", "")))
            if not iid or iid not in biblioteca or iid in vistos:
                continue
            try:
                t0 = float(w["start"])
            except (KeyError, TypeError, ValueError):
                continue
            vistos.add(iid)
            result.append(Popup(png=biblioteca[iid], t0=t0, t1=t0 + POPUP_DURATION_S))
    return result


def _se_solapan(a: Popup, b: Popup) -> bool:
    return a.t0 < b.t1 and b.t0 < a.t1


def _filtrar_simultaneos(manuales: list[Popup], autos: list[Popup]) -> list[Popup]:
    """Maximo 1 overlay simultaneo (default v1): manual gana a keyword; primero gana."""
    elegidos: list[Popup] = []
    orden = sorted(manuales, key=lambda p: p.t0) + sorted(autos, key=lambda p: p.t0)
    for p in orden:
        choque = next((q for q in elegidos if _se_solapan(p, q)), None)
        if choque:
            print(
                f"[popups] '{p.png.name}' @{p.t0:.1f}s desactivado "
                f"(solapa con '{choque.png.name}', max 1 simultaneo)"
            )
            continue
        elegidos.append(p)
    return sorted(elegidos, key=lambda p: p.t0)


def _simplificar_si_corto(p: Popup) -> Popup:
    """Paso SIMPLIFICAR (§5.3): duracion menor a 2 fades -> aparece sin fade."""
    if p.fade and (p.t1 - p.t0) < 2 * POPUP_FADE_S:
        print(f"[popups] '{p.png.name}' muy corto para fade: aparece sin animacion")
        return replace(p, fade=False)
    return p


def resolver_popups(
    groups: list[dict],
    stem: str,
    transcripts_dir: Path | None = None,
    biblioteca_dir: Path | None = None,
) -> list[Popup]:
    """Cascada v1 (§3.2): manual ({stem}_popups.json) + biblioteca por keyword.

    Fail-open total: cualquier excepcion devuelve [] con log; el render sigue.
    """
    try:
        biblioteca = indexar_biblioteca(biblioteca_dir)
        manual_path = (transcripts_dir or TRANSCRIPTS_DIR) / f"{stem}_popups.json"
        manuales = cargar_popups_manual(manual_path, biblioteca)
        autos = popups_por_keyword(groups, biblioteca) if biblioteca else []
        popups = [_simplificar_si_corto(p) for p in _filtrar_simultaneos(manuales, autos)]
        if popups:
            resumen = ", ".join(f"{p.png.name}@{p.t0:.1f}s" for p in popups)
            print(f"[popups] {len(popups)} popup(s): {resumen}")
        elif not biblioteca and not manuales:
            print("[popups] biblioteca vacia y sin popups.json - capa omitida")
            print(f"  -> Accion: agrega PNG/WebP a assets/biblioteca/ o crea {manual_path.name}")
        return popups
    except Exception as e:
        print(f"[popups] resolucion fallo ({e}) - capa de popups omitida")
        return []
