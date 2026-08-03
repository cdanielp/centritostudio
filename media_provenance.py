"""media_provenance.py — Liga un `{stem}_words.json` al video del que salio (P1).

**Por que existe.** El depurador produce `output/{stem}_limpio.mp4` quitando silencios
REPARTIDOS por todo el video, y su transcript vive como `{stem}_limpio_words.json`. Esos
timings pertenecen a un timeline distinto al del original `input/{stem}.mp4`: el desfase no es
constante, CRECE (0 -> 122 s en el material real del proyecto). Quemar unos sobre el otro
produce captions desincronizados que ningun test detecta y que solo se ven comparando el audio
con la imagen. Costo tres rondas de revision visual antes de encontrarse.

**Contrato.**

  * Al transcribir, el words json registra su fuente en `source_media`: ruta relativa, sha256,
    duracion en ms y fps. Campo ADITIVO: no toca `words`, `language` ni `source_video`.
  * Los words json existentes SIN el campo siguen siendo validos, como procedencia DESCONOCIDA.
  * Con procedencia y sha256 distinto -> `ProcedenciaError`, se detiene.
  * Sin procedencia -> se compara la duracion del video contra el ultimo `word.end`; mas de
    `TOLERANCIA_S` de diferencia -> `ProcedenciaError` diciendo cuantos segundos difieren y cual
    seria el archivo esperado.

Nunca un aviso silencioso: si no se puede afirmar que los timings son de ese video, se para.

Complementa (no reemplaza) a `transcript_provenance.source_video`, que fija filename+size+mtime
para el binding TOCTOU del namespace SRT de Studio. Aqui interesa la IDENTIDAD del contenido
(sha256) y la COHERENCIA temporal (duracion), que es lo que fallaba.

Puro salvo por leer el archivo para hashearlo: sin red, sin FFmpeg (la duracion y los fps los
aporta el llamador, que ya los tiene de `core.get_video_info`).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

FINGERPRINT_VERSION = 1

# Holgura entre el ultimo `word.end` y la duracion del video. El transcript termina con la
# ultima palabra, asi que un video real siempre dura un poco mas (silencio de cola). 2 s cubre
# esa cola sin dejar pasar un cambio de timeline (el caso real difiere en 122 s).
TOLERANCIA_S = 2.0

_EXT_VIDEO = (".mp4", ".mov")
# Donde buscar el archivo que el llamador probablemente queria (por convencion de naming).
_DIRS_CANDIDATOS = ("output", "input", "clips")

_CHUNK = 1 << 20


class ProcedenciaError(Exception):
    """Los timings no se pueden atribuir con seguridad al video con el que se van a usar.

    Error de CONTRATO, no bug: el llamador lo traduce a un mensaje accionable. Nunca lleva
    rutas absolutas ni contenido del transcript.
    """


def sha256_archivo(path: Path) -> str:
    """sha256 en streaming (los videos no caben comodos en memoria)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for bloque in iter(lambda: f.read(_CHUNK), b""):
            h.update(bloque)
    return h.hexdigest()


def _relpath(video_path: Path, root: Path | None) -> str:
    """Ruta relativa a la raiz en POSIX; el basename si cae fuera. Nunca absoluta."""
    video_path = Path(video_path)
    if root is not None:
        try:
            return video_path.resolve().relative_to(Path(root).resolve()).as_posix()
        except ValueError:
            pass
    return video_path.name


def build_media_fingerprint(
    video_path: Path, *, duration_s: float, fps: float, root: Path | None = None
) -> dict:
    """Bloque `source_media` v1 del video EXACTO: relpath + sha256 + duracion + fps."""
    video_path = Path(video_path)
    return {
        "version": FINGERPRINT_VERSION,
        "relpath": _relpath(video_path, root),
        "sha256": sha256_archivo(video_path),
        "duration_ms": int(round(float(duration_s) * 1000)),
        "fps": float(fps),
    }


def attach_media_fingerprint(
    transcript: dict, video_path: Path, *, duration_s: float, fps: float, root: Path | None = None
) -> dict:
    """Copia del transcript con `source_media` del video exacto (no muta el original)."""
    return {
        **transcript,
        "source_media": build_media_fingerprint(
            video_path, duration_s=duration_s, fps=fps, root=root
        ),
    }


def _ultimo_end_s(transcript: object) -> float | None:
    """Fin de la ultima palabra con timing utilizable, o None si el transcript no sirve."""
    if not isinstance(transcript, dict):
        return None
    words = transcript.get("words")
    if not isinstance(words, list) or not words:
        return None
    fines = [w["e"] for w in words if isinstance(w, dict) and isinstance(w.get("e"), (int, float))]
    return max(fines) if fines else None


def archivo_esperado(words_path: Path | None, root: Path | None) -> str | None:
    """Ruta relativa del video que el nombre del words json sugiere, si existe en disco.

    `{stem}_words.json` -> `{stem}.mp4|.mov` buscado en output/, input/ y clips/. Es
    exactamente el hilo que faltaba en el fallo real: el words se llamaba `..._limpio_words`
    y el video correcto era `output/..._limpio.mp4`.
    """
    if words_path is None or root is None:
        return None
    nombre = Path(words_path).name
    if not nombre.endswith("_words.json"):
        return None
    stem = nombre[: -len("_words.json")]
    for d in _DIRS_CANDIDATOS:
        for ext in _EXT_VIDEO:
            cand = Path(root) / d / f"{stem}{ext}"
            if cand.is_file():
                return f"{d}/{stem}{ext}"
    return None


def _validar_fingerprint(fp: object) -> dict:
    """Estructura minima del bloque. Un fingerprint roto NO se ignora: se rechaza."""
    if not isinstance(fp, dict):
        raise ProcedenciaError("procedencia de video invalida en el transcript")
    if fp.get("version") != FINGERPRINT_VERSION:
        raise ProcedenciaError("version de procedencia de video no soportada")
    sha = fp.get("sha256")
    if not isinstance(sha, str) or len(sha) != 64:
        raise ProcedenciaError("procedencia de video sin sha256 utilizable")
    return fp


def verificar_transcript_contra_video(
    transcript: object,
    video_path: Path,
    *,
    video_duration_s: float,
    words_path: Path | None = None,
    root: Path | None = None,
    tolerancia_s: float = TOLERANCIA_S,
) -> None:
    """Falla si los timings no se pueden atribuir a `video_path`. No devuelve nada.

    Con `source_media`: manda el sha256. Sin el: manda la coherencia de duracion.
    """
    video_path = Path(video_path)
    fin = _ultimo_end_s(transcript)
    if fin is None:
        raise ProcedenciaError("el transcript no tiene palabras con timing utilizable")

    fp = transcript.get("source_media") if isinstance(transcript, dict) else None
    if fp is not None:
        fp = _validar_fingerprint(fp)
        real = sha256_archivo(video_path)
        if real != fp["sha256"]:
            declarado = fp.get("relpath") or "(desconocido)"
            raise ProcedenciaError(
                f"los timings son de '{declarado}' y se estan usando contra "
                f"'{video_path.name}': son videos distintos (sha256 no coincide). "
                "Usa el video del que salio el transcript, o vuelve a transcribir."
            )
        return

    # Procedencia desconocida (words legacy): unico control posible, la coherencia temporal.
    if float(video_duration_s) <= 0:
        raise ProcedenciaError(
            f"no se pudo leer la duracion de '{video_path.name}' y el transcript no declara "
            "procedencia: no hay forma de confirmar que los timings sean de este video."
        )
    delta = abs(float(video_duration_s) - fin)
    if delta <= tolerancia_s:
        return
    esperado = archivo_esperado(words_path, root)
    pista = (
        f" El archivo esperado seria '{esperado}'."
        if esperado
        else " Verifica de que video salio ese transcript."
    )
    raise ProcedenciaError(
        f"los timings terminan en {fin:.1f} s y '{video_path.name}' dura "
        f"{float(video_duration_s):.1f} s: difieren {delta:.1f} s. "
        "El transcript no declara procedencia, asi que no se puede confirmar que sean del "
        "mismo video (el depurador reescribe el timeline y el desfase crece)." + pista
    )


__all__ = [
    "FINGERPRINT_VERSION",
    "TOLERANCIA_S",
    "ProcedenciaError",
    "sha256_archivo",
    "build_media_fingerprint",
    "attach_media_fingerprint",
    "archivo_esperado",
    "verificar_transcript_contra_video",
]
