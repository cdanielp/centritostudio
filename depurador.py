"""depurador.py — Depura grabaciones: silencios, muletillas y falsos arranques."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

MULETILLAS = frozenset({"eh", "em", "mmm", "ehh", "este"})
SILENCE_GAP = 0.8         # Silencio mayor a esto se comprime
SILENCE_COMPRESS = 0.25   # Comprimir a este valor
MULETILLA_PAUSE = 0.25    # Pausa minima a ambos lados para cortar muletilla
XFADE_S = 0.03            # Crossfade audio 30ms
MAX_ITERS = 3             # Iteraciones de auto-evaluacion
DRIFT_THRESHOLD = 0.1     # Umbral de desfase para anotar alerta

# ─────────────────────────────────────────────────────────────────────────────
# Construccion del EDL (lista de segmentos a conservar)
# ─────────────────────────────────────────────────────────────────────────────


def build_edl_seguro(words: list[dict], video_duration: float) -> list[tuple[float, float]]:
    """EDL modo seguro: comprime silencios >0.8s a 0.25s."""
    if not words:
        return [(0.0, video_duration)]
    segs: list[tuple[float, float]] = []
    cur_start = 0.0
    for i in range(len(words) - 1):
        gap_s, gap_e = words[i]["e"], words[i + 1]["s"]
        if gap_e - gap_s > SILENCE_GAP:
            segs.append((cur_start, gap_s + SILENCE_COMPRESS))
            cur_start = gap_e
    segs.append((cur_start, video_duration))
    return segs


def detectar_muletillas(words: list[dict]) -> list[int]:
    """Devuelve indices de words que son muletillas aisladas con pausas >= 0.25s."""
    indices: list[int] = []
    for i, w in enumerate(words):
        if w["w"].lower() not in MULETILLAS:
            continue
        pb = (w["s"] - words[i - 1]["e"]) if i > 0 else MULETILLA_PAUSE
        pa = (words[i + 1]["s"] - w["e"]) if i < len(words) - 1 else MULETILLA_PAUSE
        if pb >= MULETILLA_PAUSE and pa >= MULETILLA_PAUSE:
            indices.append(i)
    return indices


def detectar_falsos_arranques(words: list[dict]) -> list[int]:
    """Devuelve indices de words que son la primera instancia de un bigrama repetido."""
    indices: list[int] = []
    for i in range(len(words) - 1):
        if words[i]["w"].lower() != words[i + 1]["w"].lower():
            continue
        pause_antes = (words[i]["s"] - words[i - 1]["e"]) if i > 0 else 0.5
        if pause_antes >= 0.4:
            indices.append(i)
    return indices


def _cortar_segmento(
    edl: list[tuple[float, float]], cut_s: float, cut_e: float
) -> list[tuple[float, float]]:
    """Elimina el rango [cut_s, cut_e] del EDL."""
    result: list[tuple[float, float]] = []
    for s, e in edl:
        if cut_e <= s or cut_s >= e:
            result.append((s, e))
        elif cut_s <= s and cut_e >= e:
            pass  # Segmento completamente cortado
        else:
            if s < cut_s:
                result.append((s, cut_s))
            if cut_e < e:
                result.append((cut_e, e))
    return result


def build_edl_agresivo(words: list[dict], video_duration: float) -> list[tuple[float, float]]:
    """EDL modo agresivo: silencios + muletillas aisladas + falsos arranques."""
    edl = build_edl_seguro(words, video_duration)
    cortes = set(detectar_muletillas(words)) | set(detectar_falsos_arranques(words))
    for idx in sorted(cortes):
        w = words[idx]
        edl = _cortar_segmento(edl, w["s"], w["e"])
    return edl


# ─────────────────────────────────────────────────────────────────────────────
# Re-calculo de words.json tras los cortes
# ─────────────────────────────────────────────────────────────────────────────


def _map_time(t: float, edl: list[tuple[float, float]]) -> float | None:
    """Mapea tiempo original al tiempo de salida; None si el tiempo fue cortado."""
    acc = 0.0
    for s, e in edl:
        if t < s - 0.001:
            return None
        if t <= e + 0.001:
            return acc + (t - s)
        acc += e - s
    return None


def recalcular_words(words: list[dict], edl: list[tuple[float, float]]) -> tuple[list[dict], float]:
    """Ajusta words.json segun EDL. Devuelve (new_words, max_drift_s)."""
    result: list[dict] = []
    max_drift = 0.0
    for w in words:
        new_s = _map_time(w["s"], edl)
        new_e = _map_time(w["e"], edl)
        if new_s is not None and new_e is not None:
            drift = abs((new_e - new_s) - (w["e"] - w["s"]))
            max_drift = max(max_drift, drift)
            result.append({**w, "s": round(new_s, 3), "e": round(new_e, 3)})
    return result, round(max_drift, 3)


# ─────────────────────────────────────────────────────────────────────────────
# Corte FFmpeg con crossfade de audio
# ─────────────────────────────────────────────────────────────────────────────


def _build_filter(edl: list[tuple[float, float]]) -> str:
    """Construye filter_complex FFmpeg con crossfades de audio de 30ms."""
    n = len(edl)
    parts_v: list[str] = []
    parts_a: list[str] = []
    for i, (s, e) in enumerate(edl):
        dur = round(e - s, 4)
        parts_v.append(f"[0:v]trim=start={s}:end={e},setpts=PTS-STARTPTS[v{i}]")
        af = f"[0:a]atrim=start={s}:end={e},asetpts=PTS-STARTPTS"
        if i > 0:
            af += f",afade=t=in:st=0:d={XFADE_S}"
        if i < n - 1:
            af += f",afade=t=out:st={max(0, dur - XFADE_S):.3f}:d={XFADE_S}"
        af += f"[a{i}]"
        parts_a.append(af)
    # concat espera streams intercalados: [v0][a0][v1][a1]...
    interleaved = "".join(f"[v{i}][a{i}]" for i in range(n))
    concat = f"{interleaved}concat=n={n}:v=1:a=1[outv][outa]"
    return ";".join(parts_v + parts_a + [concat])


def _run_edl(video_path: Path, edl: list[tuple[float, float]], output: Path) -> None:
    """Ejecuta el EDL en FFmpeg re-encoding con crossfade de audio."""
    if not edl:
        raise ValueError("EDL vacio: no hay segmentos que conservar")
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-filter_complex", _build_filter(edl),
        "-map", "[outv]", "-map", "[outa]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "128k", str(output),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"FFmpeg depurar error:\n{r.stderr[-1500:]}")


# ─────────────────────────────────────────────────────────────────────────────
# Auto-evaluacion de fronteras
# ─────────────────────────────────────────────────────────────────────────────


def _volume_at(video_path: Path, start: float, dur: float = 0.3) -> float:
    """Devuelve mean_volume dBFS en el tramo [start, start+dur]."""
    r = subprocess.run(
        ["ffmpeg", "-y", "-ss", str(max(0, start)), "-t", str(dur),
         "-i", str(video_path), "-af", "volumedetect", "-vn", "-f", "null", "NUL"],
        capture_output=True, text=True,
    )
    for line in r.stderr.splitlines():
        if "mean_volume:" in line:
            try:
                return float(line.split("mean_volume:")[1].split("dB")[0].strip())
            except ValueError:
                pass
    return -99.0


def _join_output_times(edl: list[tuple[float, float]]) -> list[float]:
    """Tiempos de union en el video de salida (uno por cada transicion entre segmentos)."""
    times: list[float] = []
    acc = 0.0
    for i, (s, e) in enumerate(edl):
        acc += e - s
        if i < len(edl) - 1:
            times.append(round(acc, 3))
    return times


def _eval_and_adjust(
    output: Path, edl: list[tuple[float, float]]
) -> tuple[list[tuple[float, float]], bool]:
    """Verifica TODAS las fronteras; ajusta ±80ms donde delta > 6dB. Devuelve (edl, hubo_ajuste)."""
    joins = _join_output_times(edl)
    hubo_ajuste = False
    for j, j_time in enumerate(joins):
        vol_pre = _volume_at(output, j_time - 0.3)
        vol_post = _volume_at(output, j_time + 0.02)
        if abs(vol_pre - vol_post) > 6:
            print(f"[depurar] Union @{j_time:.1f}s: delta={abs(vol_pre-vol_post):.1f}dB, ajustando")
            s, e = edl[j]
            edl[j] = (s, max(s + XFADE_S * 2, e - 0.08))
            hubo_ajuste = True
    return edl, hubo_ajuste


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrador principal
# ─────────────────────────────────────────────────────────────────────────────


def _probe_duration(video_path: Path) -> float:
    """Devuelve duracion en segundos del video."""
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(video_path)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe error:\n{r.stderr[-1000:]}")
    return float(json.loads(r.stdout).get("format", {}).get("duration", 0))


def depurar(
    video_path: Path, words: list[dict], mode: str, output_path: Path
) -> dict:
    """Depura el video: comprime silencios (seguro) o ademas corta muletillas (agresivo)."""
    dur = _probe_duration(video_path)
    edl = build_edl_agresivo(words, dur) if mode == "agresivo" else build_edl_seguro(words, dur)

    dur_orig = dur
    dur_out = sum(e - s for s, e in edl)
    n_cuts = len(edl) - 1

    if n_cuts == 0:
        shutil.copy2(str(video_path), str(output_path))
        print("[depurar] Sin cortes necesarios.")
        return {"cuts": 0, "saved_s": 0.0, "iterations": 0, "edl": edl}

    iterations = 0
    for _ in range(MAX_ITERS):
        iterations += 1
        _run_edl(video_path, edl, output_path)
        edl, ajustado = _eval_and_adjust(output_path, edl)
        if not ajustado:
            break

    saved = round(dur_orig - dur_out, 2)
    print(f"[depurar] {n_cuts} cortes | -{saved}s | modo={mode} | iters={iterations}")
    return {"cuts": n_cuts, "saved_s": saved, "iterations": iterations, "edl": edl}
