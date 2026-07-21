"""depurador.py — Depura grabaciones: silencios, muletillas y falsos arranques."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import media_deps
import video_encoder

MULETILLAS = frozenset({"eh", "em", "mmm", "ehh", "este"})
SILENCE_GAP = 0.8  # Silencio mayor a esto se comprime
SILENCE_COMPRESS = 0.25  # Comprimir a este valor
MULETILLA_PAUSE = 0.25  # Pausa minima a ambos lados para cortar muletilla
XFADE_S = 0.03  # Crossfade audio 30ms
DRIFT_THRESHOLD = 0.1  # Umbral de desfase para anotar alerta
DELTA_CLEAN_DB = 6  # Delta voz-a-voz <= este valor: union limpia
DELTA_NOTABLE_DB = 15  # Delta voz-a-voz > este valor: salto notable, considerar normalizacion

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


def _edl_cmd(
    video_path: Path, edl: list[tuple[float, float]], video_args: list[str], target: Path
) -> list[str]:
    """Comando FFmpeg del EDL con los args del ENCODER inyectados. Audio/mapa/filtro intactos."""
    return [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-filter_complex",
        _build_filter(edl),
        "-map",
        "[outv]",
        "-map",
        "[outa]",
        *video_args,
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(target),
    ]


def run_edl(video_path: Path, edl: list[tuple[float, float]], output: Path):
    """Alias publico de _run_edl para uso por clipper (evita importar privados)."""
    return _run_edl(video_path, edl, output)


def _run_edl(video_path: Path, edl: list[tuple[float, float]], output: Path):
    """Ejecuta el EDL re-encodeando con el encoder seleccionado (NVENC/CPU) + crossfade de audio.

    Publica de forma ATOMICA (temp -> verificacion -> os.replace via media_integrity): un fallo
    o un fallback NVENC->CPU nunca deja el nombre final apuntando a un parcial. Devuelve
    (EncoderSelection efectiva, tiempo de encode en s). No expone stderr ni rutas.
    """
    if not edl:
        raise ValueError("EDL vacio: no hay segmentos que conservar")
    media_deps.require_ffmpeg()  # H3: sin ffmpeg -> FFmpegUnavailable accionable (no WinError 2)
    import media_integrity  # noqa: PLC0415

    seleccion = video_encoder.select_encoder(
        video_encoder.active_mode(), video_encoder.EncoderProfile.QUALITY
    )
    holder: dict = {}

    def _quemar(target: Path) -> float:
        outcome = video_encoder.run_ffmpeg_encode(
            seleccion,
            lambda vargs: _edl_cmd(video_path, edl, vargs, target),
            cleanup=lambda: media_integrity._borrar_silencioso(target),
        )
        holder["sel"] = outcome.selection
        return outcome.elapsed

    elapsed = media_integrity.publicar_mp4_atomico(output, _quemar)
    return holder["sel"], elapsed


# ─────────────────────────────────────────────────────────────────────────────
# Auto-evaluacion de fronteras
# ─────────────────────────────────────────────────────────────────────────────


def _volume_at(video_path: Path, start: float, dur: float = 0.3) -> float:
    """Devuelve mean_volume dBFS en el tramo [start, start+dur]."""
    media_deps.require_ffmpeg()  # H3: diagnostico de union; sin ffmpeg -> FFmpegUnavailable
    try:
        r = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                str(max(0, start)),
                "-t",
                str(dur),
                "-i",
                str(video_path),
                "-af",
                "volumedetect",
                "-vn",
                "-f",
                "null",
                "NUL",
            ],
            capture_output=True,
            text=True,
        )
    except OSError:
        raise media_deps.FFmpegUnavailable(media_deps._FFMPEG_MSG) from None
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


def _last_word_end_before(words: list[dict], seg_end: float) -> float | None:
    """Fin de la ultima palabra dentro del segmento (antes del silencio comprimido)."""
    voice_cutoff = seg_end - SILENCE_COMPRESS
    best: float | None = None
    for w in words:
        if w["e"] <= voice_cutoff + 0.01:
            best = w["e"]
    return best


def _eval_joins(
    output: Path, edl: list[tuple[float, float]], voice_refs: list[float | None]
) -> list[dict]:
    """Diagnostica uniones midiendo voz-a-voz. Sin ajuste de cortes. Solo informa."""
    joins = _join_output_times(edl)
    report: list[dict] = []
    for j, j_time in enumerate(joins):
        last_voice_end = voice_refs[j] if j < len(voice_refs) else None
        if last_voice_end is None:
            report.append({"join": j_time, "delta": None, "clase": "sin_referencia"})
            continue
        silence_in_seg = edl[j][1] - last_voice_end
        if silence_in_seg < XFADE_S:
            report.append({"join": j_time, "delta": None, "clase": "silencio_minimo"})
            continue
        pre_start = max(0.0, j_time - silence_in_seg - 0.15)
        vol_pre = _volume_at(output, pre_start, dur=0.15)
        vol_post = _volume_at(output, j_time + 0.02)
        delta = round(abs(vol_pre - vol_post), 1)
        if delta <= DELTA_CLEAN_DB:
            clase = "limpia"
        elif delta <= DELTA_NOTABLE_DB:
            clase = "salto_leve"
        else:
            clase = "salto_notable"
        print(f"[depurar] Union @{j_time:.1f}s: delta={delta:.1f}dB {clase}")
        report.append({"join": round(j_time, 2), "delta": delta, "clase": clase})
    return report


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrador principal
# ─────────────────────────────────────────────────────────────────────────────


def _probe_duration(video_path: Path) -> float:
    """Devuelve duracion en segundos del video.

    H3: ffprobe ausente -> FFprobeUnavailable (no WinError 2 crudo); ffprobe presente pero
    returncode!=0 / stdout vacio / JSON invalido -> MediaProbeError. No publica stderr ni rutas.
    """
    media_deps.require_ffprobe()
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(video_path)],
            capture_output=True,
            text=True,
        )
    except OSError:
        raise media_deps.FFprobeUnavailable(media_deps._FFPROBE_MSG) from None
    if r.returncode != 0 or not (r.stdout or "").strip():
        raise media_deps.MediaProbeError("No se pudo analizar el video para depurarlo.")
    try:
        data = json.loads(r.stdout)
    except ValueError:
        raise media_deps.MediaProbeError("No se pudo analizar el video para depurarlo.") from None
    return float(data.get("format", {}).get("duration", 0))


def depurar(video_path: Path, words: list[dict], mode: str, output_path: Path) -> dict:
    """Depura el video: comprime silencios (seguro) o ademas corta muletillas (agresivo)."""
    dur = _probe_duration(video_path)
    edl = build_edl_agresivo(words, dur) if mode == "agresivo" else build_edl_seguro(words, dur)

    dur_orig = dur
    dur_out = sum(e - s for s, e in edl)
    n_cuts = len(edl) - 1

    if n_cuts == 0:
        shutil.copy2(str(video_path), str(output_path))
        print("[depurar] Sin cortes necesarios.")
        copia = {
            "video_encoder": "copy",
            "encoder_mode": video_encoder.active_mode().value,
            "fallback_used": False,
            "encode_time_s": 0.0,
        }
        return {"cuts": 0, "saved_s": 0.0, "edl": edl, "join_report": [], **copia}

    voice_refs = [_last_word_end_before(words, seg[1]) for seg in edl[:-1]]
    seleccion, encode_s = _run_edl(video_path, edl, output_path)
    join_report = _eval_joins(output_path, edl, voice_refs)

    saved = round(dur_orig - dur_out, 2)
    print(f"[depurar] {n_cuts} cortes | -{saved}s | modo={mode} | encoder={seleccion.encoder}")
    telemetria = video_encoder.selection_telemetry(seleccion, encode_s)
    return {"cuts": n_cuts, "saved_s": saved, "edl": edl, "join_report": join_report, **telemetria}
