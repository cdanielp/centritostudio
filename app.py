"""
app.py — API FastAPI para Centrito Studio.
Levanta en puerto 8787. Sirve static/index.html como UI.
Workers de background en jobs.py.
"""

from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import json

from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

import core
import jobs
import path_safety
import studio_auto
import studio_keywords
import studio_packages
import studio_srt
import studio_srt_routes
from styles import STYLES

# ─── Directorios ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
INPUT_DIR = ROOT / "input"
TRANSCRIPTS = ROOT / "transcripts"
OUTPUT_DIR = ROOT / "output"
THUMBS_DIR = ROOT / "thumbs"
STATIC_DIR = ROOT / "static"

for d in [INPUT_DIR, TRANSCRIPTS, OUTPUT_DIR, THUMBS_DIR, STATIC_DIR]:
    d.mkdir(exist_ok=True)

# ─── FastAPI ──────────────────────────────────────────────────────────────────
app = FastAPI(title="Centrito Studio")

CLIPS_DIR = ROOT / "output" / "clips"
CLIPS_DIR.mkdir(exist_ok=True)


class _AllowlistStatic(StaticFiles):
    """Mount que solo sirve archivos con extension en una ALLOWLIST y confinados al directorio.

    H1 (P0-3/P0-4): un mount estatico abierto exponia texto/JSON privado y cualquier binario
    a la LAN. Esta base sirve UNICAMENTE los tipos declarados por la subclase y ademas resuelve
    la ruta real y exige que caiga dentro del directorio (bloquea traversal y symlinks que
    apunten fuera). Cualquier otra cosa -> 404 generico. Sin extra en el constructor: se puede
    reconstruir con `type(mount)(directory=...)`.
    """

    ALLOWED_EXT: frozenset[str] = frozenset()

    def _confinado_y_permitido(self, path: str) -> bool:
        norm = path.replace("\\", "/").strip("/")
        if not norm:
            return False
        base = norm.rsplit("/", 1)[-1]
        if Path(base).suffix.lower() not in self.ALLOWED_EXT:
            return False
        try:
            root = Path(self.directory).resolve()
            target = (root / norm).resolve()
            target.relative_to(root)  # escape por traversal o symlink -> ValueError
        except (ValueError, OSError):
            return False
        return True

    async def get_response(self, path, scope):
        if not self._confinado_y_permitido(path):
            return PlainTextResponse("Not Found", status_code=404)
        return await super().get_response(path, scope)


class _OutputMedia(_AllowlistStatic):
    """/output: SOLO renders .mp4 publicos. Bloquea .ass/.json/.srt/sidecars y el subarbol
    paquetes/ (servido unicamente por el router validado studio_packages). Cierra P0-3."""

    ALLOWED_EXT = frozenset({".mp4"})

    async def get_response(self, path, scope):
        # El primer segmento, normalizado como lo hace el FS de Windows (case-insensitive,
        # sin puntos/espacios finales): asi /output/Paquetes o /output/paquetes./ tampoco
        # escapan el confinamiento (bypass real detectado en revision).
        primer = path.replace("\\", "/").strip("/").split("/", 1)[0].rstrip(". ").lower()
        if primer == "paquetes":
            return PlainTextResponse("Not Found", status_code=404)
        return await super().get_response(path, scope)


class _ThumbsMedia(_AllowlistStatic):
    """/thumbs: solo miniaturas de imagen."""

    ALLOWED_EXT = frozenset({".jpg", ".jpeg", ".png", ".webp"})


class _ClipsMedia(_AllowlistStatic):
    """/clips: solo el binario .mp4 del clip para preview/descarga (no JSON/checkpoints)."""

    ALLOWED_EXT = frozenset({".mp4"})


# P0-4: el mount publico /input queda ELIMINADO. El binario fuente se sirve por el endpoint
# validado /api/videos/{name}/source (basename seguro + confinado). Los demas mounts pasan a
# allowlist estricta por tipo. El servidor ademas bindea solo loopback (ver LISTEN_HOST).
app.mount("/output", _OutputMedia(directory=str(OUTPUT_DIR)), name="output")
app.mount("/clips", _ClipsMedia(directory=str(CLIPS_DIR)), name="clips")
app.mount("/thumbs", _ThumbsMedia(directory=str(THUMBS_DIR)), name="thumbs")


@app.get("/")
def root():
    # charset explicito: el navegador nunca debe interpretar la UI en Latin-1
    # (evita mojibake en acentos/emojis aunque falte el <meta charset>).
    return FileResponse(str(STATIC_DIR / "index.html"), media_type="text/html; charset=utf-8")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ─── Guard compartido de identificadores en rutas (H1, P0-1) ──────────────────
def _validar_name(name: str) -> None:
    """Rechaza cualquier identificador que no sea un basename PURO antes de tocar el FS.

    Fuente unica: path_safety.is_safe_basename. 404 saneado (no refleja `name`, que puede
    traer traversal/control), sin abrir ni escribir archivos y sin lanzar jobs. Se llama al
    INICIO de cada endpoint {name}/{stem} antes de construir cualquier Path (P0-1).
    """
    if not path_safety.is_safe_basename(name):
        raise HTTPException(404, "Recurso no encontrado.")


# ─── Videos ───────────────────────────────────────────────────────────────────
@app.get("/api/videos")
def list_videos():
    result = []
    fuentes = sorted(
        [*INPUT_DIR.glob("*.mp4"), *INPUT_DIR.glob("*.mov")], key=lambda p: p.name.lower()
    )
    for mp4 in fuentes:
        if mp4.stem.startswith("test_"):
            continue
        info_file = TRANSCRIPTS / f"{mp4.stem}_info.json"
        groups_file = TRANSCRIPTS / f"{mp4.stem}_groups.json"
        outputs = list(OUTPUT_DIR.glob(f"{mp4.stem}_*.mp4"))

        if outputs:
            status = "renderizado"
        elif groups_file.exists():
            status = "transcrito"
        else:
            status = "sin_transcribir"

        # Pipeline stages — fuente de verdad: artefactos en disco
        stages: dict = {
            "transcrito": groups_file.exists(),
            "depurado": (OUTPUT_DIR / f"{mp4.stem}_limpio.mp4").exists(),
            "clips_n": 0,
            "reencuadrado": False,
        }
        clips_json = CLIPS_DIR / f"{mp4.stem}_clips.json"
        if clips_json.exists():
            try:
                clips_data = json.loads(clips_json.read_text(encoding="utf-8"))
                stages["clips_n"] = len(clips_data.get("clips", []))
            except Exception:
                pass
        stages["reencuadrado"] = bool(list(CLIPS_DIR.glob(f"{mp4.stem}_*_9x16.mp4")))

        if info_file.exists():
            info = json.loads(info_file.read_text(encoding="utf-8"))
        else:
            info = core.get_video_info(mp4)
            info_file.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")

        thumb = THUMBS_DIR / f"{mp4.stem}.jpg"
        if not thumb.exists():
            core.extract_thumb(mp4, thumb)

        result.append(
            {
                "name": mp4.stem,
                "filename": mp4.name,
                "status": status,
                "stages": stages,
                "duration": round(info.get("duration", 0), 2),
                "width": info.get("width", 0),
                "height": info.get("height", 0),
                "mean_volume": info.get("mean_volume", -99),
                "has_audio": info.get("has_audio", False),
                "thumb": f"/thumbs/{mp4.stem}.jpg" if thumb.exists() else None,
                "outputs": [o.name for o in outputs],
            }
        )
    return result


@app.get("/api/videos/{name}/source")
def get_video_source(name: str):
    """Sirve el binario fuente (input/) por un endpoint VALIDADO en vez del mount abierto (P0-4).

    Confina el basename, resuelve solo dentro de INPUT_DIR (.mp4/.mov, archivo real, sin escapar
    por symlink) y devuelve un FileResponse (soporta Range para reproduccion/seek). 404 generico.
    """
    _validar_name(name)
    video = _resolver_video_input(name)
    if video is None:
        raise HTTPException(404, "Video no encontrado.")
    media = "video/mp4" if video.suffix.lower() == ".mp4" else "video/quicktime"
    return FileResponse(str(video), media_type=media)


# ─── Upload seguro (H1, P0-2) ─────────────────────────────────────────────────
_DEFAULT_MAX_VIDEO_BYTES = 20 * 1024**3  # 20 GiB
_ALLOWED_UPLOAD_EXT = frozenset({".mp4", ".mov"})
_UPLOAD_CHUNK = 1 << 20  # 1 MiB por lectura; nunca se lee el cuerpo completo de una vez


def _max_video_bytes() -> int:
    """Limite de carga en bytes: CENTRITO_MAX_VIDEO_BYTES o el default seguro (20 GiB).

    Un valor invalido/no-positivo cae al default con un warning y NUNCA tumba la app.
    """
    raw = os.environ.get("CENTRITO_MAX_VIDEO_BYTES")
    if raw is None:
        return _DEFAULT_MAX_VIDEO_BYTES
    try:
        val = int(raw)
    except (TypeError, ValueError):
        val = 0
    if val <= 0:
        print(f"[studio] CENTRITO_MAX_VIDEO_BYTES invalido ({raw!r}); uso el default de 20 GiB")
        return _DEFAULT_MAX_VIDEO_BYTES
    return val


def _borrar_tmp(p: Path) -> None:
    try:
        p.unlink()
    except OSError:
        pass


async def _stream_a_temporal(file: UploadFile, tmp: Path, max_bytes: int) -> int:
    """Copia el upload por chunks al temporal con tope DURO de bytes. Devuelve el total.

    NO confia en Content-Length: aunque falte o mienta, aborta con 413 al superar max_bytes.
    """
    total = 0
    with open(tmp, "wb") as f:
        while True:
            chunk = await file.read(_UPLOAD_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise HTTPException(413, "El archivo excede el limite permitido.")
            f.write(chunk)
    return total


@app.post("/api/videos/upload")
async def upload_video(request: Request, file: UploadFile = File(...)):
    """Carga un video confinada a input/: basename seguro + .mp4/.mov + tope de bytes +
    temporal validado por ffprobe + `os.replace` atomico. Nunca escribe al destino final
    durante la carga ni borra un final anterior si la nueva carga falla (P0-2, P1-OUT)."""
    filename = file.filename
    if not filename:
        raise HTTPException(400, "Falta el nombre del archivo.")
    if not path_safety.is_safe_basename(filename):
        raise HTTPException(400, "Nombre de archivo invalido.")
    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_UPLOAD_EXT:
        raise HTTPException(400, "Extension no permitida (solo .mp4/.mov).")

    max_bytes = _max_video_bytes()
    # Rechazo temprano por Content-Length si esta disponible y ya supera el limite.
    clen = request.headers.get("content-length")
    if clen is not None:
        try:
            if int(clen) > max_bytes:
                raise HTTPException(413, "El archivo excede el limite permitido.")
        except ValueError:
            pass  # header mentiroso: el tope por chunks lo cubre igual

    dest = INPUT_DIR / filename
    tmp_dir = INPUT_DIR / ".uploads"  # subdir oculto: no lo lista el glob input/*.mp4
    tmp_dir.mkdir(exist_ok=True)
    tmp = tmp_dir / f"{uuid.uuid4().hex}{ext}"  # preserva la extension final para ffprobe
    try:
        total = await _stream_a_temporal(file, tmp, max_bytes)
        if total == 0:
            raise HTTPException(422, "El archivo esta vacio.")
        import media_integrity  # noqa: PLC0415

        try:
            media_integrity.verificar_video(tmp)
        except media_integrity.MediaIntegrityError:
            raise HTTPException(422, "El archivo no es un video valido.") from None
        os.replace(tmp, dest)  # publicacion atomica SOLO tras validar
    except HTTPException:
        _borrar_tmp(tmp)
        raise
    except Exception:
        _borrar_tmp(tmp)
        raise HTTPException(500, "No se pudo procesar la carga.") from None

    # Post-proceso (info + thumb). Fail-open: no invalida una carga ya publicada.
    info: dict = {}
    try:
        info = core.get_video_info(dest)
        (TRANSCRIPTS / f"{dest.stem}_info.json").write_text(
            json.dumps(info, ensure_ascii=False), encoding="utf-8"
        )
        core.extract_thumb(dest, THUMBS_DIR / f"{dest.stem}.jpg")
    except Exception:
        print(f"[studio] post-proceso de carga fallo para {dest.name} (carga ya publicada)")
    return {"name": dest.stem, "filename": dest.name, **info}


# ─── Transcripcion ────────────────────────────────────────────────────────────
@app.post("/api/videos/{name}/transcribe")
def start_transcribe(
    name: str, lang: str = "es", model: str = "auto", caption_source: str = "transcript"
):
    _validar_name(name)
    if caption_source not in ("transcript", "srt"):
        raise HTTPException(400, "caption_source debe ser 'transcript' o 'srt'.")
    if caption_source == "srt":
        return _start_transcribe_srt(name, lang, model)
    mp4 = INPUT_DIR / f"{name}.mp4"
    if not mp4.exists():
        raise HTTPException(404, f"Video {name}.mp4 no encontrado")
    info_file = TRANSCRIPTS / f"{name}_info.json"
    if info_file.exists():
        info = json.loads(info_file.read_text(encoding="utf-8"))
        if info.get("mean_volume", 0) < -40:
            raise HTTPException(400, "El video no tiene voz detectable (mean_volume < -40 dB)")
    jid = jobs.new_job(f"Transcribiendo {name}...")
    threading.Thread(
        target=jobs.run_transcribe, args=(jid, mp4, lang, model, name), daemon=True
    ).start()
    return {"job_id": jid}


def _start_transcribe_srt(name: str, lang: str, model: str):
    """Transcribe el video EXACTO asociado al SRT (por `manifest.video.filename`), de modo que
    `{name}_words.json` quede ligado a ese video (procedencia). Sin selección -> 400; video
    exacto ausente -> 409; storage corrupto -> 500. La ruta transcript histórica no cambia.
    """
    import studio_srt_manifest  # noqa: PLC0415
    import studio_srt_runtime  # noqa: PLC0415
    import transcript_provenance  # noqa: PLC0415

    if not studio_srt_manifest.is_safe_basename(name):
        raise HTTPException(404, "Video no encontrado en input/.")
    try:
        selection = studio_srt_runtime.resolve_selected_srt(
            name, storage_root=TRANSCRIPTS / "studio_srt", manifest_dir=TRANSCRIPTS
        )
    except studio_srt.StudioSrtError:
        raise HTTPException(500, "No se pudo leer la seleccion SRT.") from None
    if selection is None:
        raise HTTPException(400, "No hay un SRT seleccionado para este video.")
    try:
        binding = studio_srt_runtime.bind_selected_video(selection, input_dir=INPUT_DIR)
    except studio_srt_runtime.StudioSrtSelectedVideoMissing:
        raise HTTPException(409, "El video asociado al SRT ya no esta disponible.") from None
    except studio_srt.StudioSrtError:
        raise HTTPException(500, "No se pudo leer la seleccion SRT.") from None
    # Los timings SRT viven en un namespace privado por filename (NO pisan {stem}_words/groups).
    key = transcript_provenance.srt_artifact_key(selection.video_filename)
    jid = jobs.new_job(f"Transcribiendo {name} (SRT)...")
    threading.Thread(
        target=jobs.run_transcribe,
        args=(jid, binding.path, lang, model, name),
        kwargs={"srt_artifact_key": key, "selected_video_binding": binding},
        daemon=True,
    ).start()
    return {"job_id": jid}


# ─── Transcript ───────────────────────────────────────────────────────────────
@app.get("/api/videos/{name}/transcript")
def get_transcript(name: str):
    _validar_name(name)
    grp_path = TRANSCRIPTS / f"{name}_groups.json"
    if not grp_path.exists():
        raise HTTPException(404, "Transcript no encontrado — transcribe primero")
    return json.loads(grp_path.read_text(encoding="utf-8"))


@app.put("/api/videos/{name}/transcript")
def save_transcript(name: str, body: list = Body(...)):
    _validar_name(name)
    grp_path = TRANSCRIPTS / f"{name}_groups.json"
    rebalanced = [core.rebalance_timestamps(g) if g.get("edited") else g for g in body]
    for i, g in enumerate(rebalanced):
        g["id"] = i
    grp_path.write_text(json.dumps(rebalanced, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"saved": len(rebalanced)}


# ─── Analisis IA ──────────────────────────────────────────────────────────────
@app.post("/api/videos/{name}/analyze")
def start_analyze(name: str):
    _validar_name(name)
    grp_path = TRANSCRIPTS / f"{name}_groups.json"
    if not grp_path.exists():
        raise HTTPException(400, "Transcribe el video antes de analizar")
    jid = jobs.new_job(f"Analizando {name} con IA...")
    threading.Thread(target=jobs.run_analyze, args=(jid, grp_path, name), daemon=True).start()
    return {"job_id": jid}


# ─── Brain ────────────────────────────────────────────────────────────────────
@app.get("/api/videos/{name}/brain")
def get_brain(name: str):
    _validar_name(name)
    path = TRANSCRIPTS / f"{name}.brain.json"
    if not path.exists():
        return {"groups": []}
    return json.loads(path.read_text(encoding="utf-8"))


@app.put("/api/videos/{name}/brain")
def save_brain(name: str, body: list = Body(...)):
    _validar_name(name)
    path = TRANSCRIPTS / f"{name}.brain.json"
    grp_path = TRANSCRIPTS / f"{name}_groups.json"
    if grp_path.exists():
        grupos = json.loads(grp_path.read_text(encoding="utf-8"))
        for item in body:
            g_idx = item.get("g")
            kw_within = item.get("kw")
            if g_idx is not None and g_idx < len(grupos) and kw_within is not None:
                g_words = grupos[g_idx].get("words", [])
                if 0 <= kw_within < len(g_words):
                    item["kw_ts"] = round(float(g_words[kw_within]["start"]), 3)
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    existing["groups"] = body
    path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"saved": len(body)}


@app.get("/api/videos/{name}/keywords")
def get_keywords(name: str):
    """Marcado manual guardado (spans/keywords) para prellenar la UI. Saneado, sin rutas."""
    import studio_srt_manifest  # noqa: PLC0415

    if not studio_srt_manifest.is_safe_basename(name):
        raise HTTPException(400, "Nombre de video invalido")
    entradas = studio_keywords.read_entries(TRANSCRIPTS / f"{name}_keywords.json")
    return {"keywords": entradas}


@app.post("/api/videos/{name}/keywords")
def save_keywords(name: str, body: dict = Body(...)):
    """Guarda el sidecar {stem}_keywords.json desde la UI (validado/saneado, IO atomico)."""
    import studio_srt_manifest  # noqa: PLC0415

    if not studio_srt_manifest.is_safe_basename(name):
        raise HTTPException(400, "Nombre de video invalido")
    entradas = studio_keywords.sanitize_entries(body)
    studio_keywords.write_entries(TRANSCRIPTS / f"{name}_keywords.json", entradas)
    return {"guardadas": len(entradas)}


# ─── Depurador ────────────────────────────────────────────────────────────────
@app.post("/api/videos/{name}/depurar")
def start_depurar(name: str, mode: str = "seguro"):
    _validar_name(name)
    mp4 = INPUT_DIR / f"{name}.mp4"
    words_path = TRANSCRIPTS / f"{name}_words.json"
    if not mp4.exists():
        raise HTTPException(404, f"Video {name}.mp4 no encontrado")
    if not words_path.exists():
        raise HTTPException(400, "Transcribe el video antes de depurar")
    if mode not in ("seguro", "agresivo"):
        raise HTTPException(400, "mode debe ser 'seguro' o 'agresivo'")
    jid = jobs.new_job(f"Depurando {name} ({mode})...")
    threading.Thread(
        target=jobs.run_depurar, args=(jid, mp4, words_path, name, mode), daemon=True
    ).start()
    return {"job_id": jid}


# ─── Clips ────────────────────────────────────────────────────────────────────
@app.post("/api/videos/{name}/clips")
def start_clips(name: str, tipos: str = "ambos"):
    _validar_name(name)
    mp4 = INPUT_DIR / f"{name}.mp4"
    # Soportar .mov tambien
    if not mp4.exists():
        for ext in (".mov", ".MP4", ".MOV"):
            candidate = INPUT_DIR / f"{name}{ext}"
            if candidate.exists():
                mp4 = candidate
                break
    if not mp4.exists():
        raise HTTPException(404, f"Video {name} no encontrado en input/")
    words_path = TRANSCRIPTS / f"{name}_words.json"
    if not words_path.exists():
        raise HTTPException(400, "Transcribe el video antes de generar clips")
    if tipos not in ("cortos", "largos", "ambos"):
        raise HTTPException(400, "tipos debe ser 'cortos', 'largos' o 'ambos'")
    jid = jobs.new_job(f"Generando clips ({tipos}) de {name}...")
    threading.Thread(
        target=jobs.run_clips, args=(jid, mp4, words_path, name, tipos), daemon=True
    ).start()
    return {"job_id": jid}


@app.get("/api/videos/{name}/clips")
def get_clips(name: str):
    _validar_name(name)
    clips_dir = ROOT / "output" / "clips"
    clips_path = clips_dir / f"{name}_clips.json"
    if not clips_path.exists():
        return {"clips": [], "descartados": [], "casi": [], "error": None}
    return json.loads(clips_path.read_text(encoding="utf-8"))


# ─── Reframe ──────────────────────────────────────────────────────────────────


@app.post("/api/clips/{name}/detectar")
def detectar_caras_clip(name: str, detector: str = "yunet"):
    """Detecta caras en un clip y devuelve la lista con thumbnails."""
    _validar_name(name)
    clip_path = CLIPS_DIR / f"{name}.mp4"
    if not clip_path.exists():
        raise HTTPException(404, f"Clip {name}.mp4 no encontrado")
    import reframe  # noqa: PLC0415

    caras = reframe.detectar_caras_video(clip_path, detector_type=detector)
    return {"n_caras": len(caras), "caras": caras}


@app.post("/api/clips/{name}/turnos")
def save_turnos_clip(name: str, body: dict = Body(...)):
    """Guarda el archivo de turnos para un clip multi-cara."""
    _validar_name(name)
    clip_path = CLIPS_DIR / f"{name}.mp4"
    if not clip_path.exists():
        raise HTTPException(404, f"Clip {name}.mp4 no encontrado")
    turnos_path = TRANSCRIPTS / f"{name}_turnos.json"
    turnos_path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"saved": len(body.get("turnos", []))}


@app.post("/api/clips/{name}/reframe")
def start_reframe(
    name: str,
    punch_in: bool = False,
    layout: str = "tracking",
    detector: str = "yunet",
    tracker: str = "escenas",
):
    """Inicia el reencuadre 9:16: tracking (escenas default | ema) o stack."""
    _validar_name(name)
    clip_path = CLIPS_DIR / f"{name}.mp4"
    if not clip_path.exists():
        raise HTTPException(404, f"Clip {name}.mp4 no encontrado")
    if tracker not in ("escenas", "ema"):
        raise HTTPException(400, "tracker debe ser 'escenas' o 'ema'")
    if layout == "stack":
        output_path = CLIPS_DIR / f"{name}_stack_9x16.mp4"
        jid = jobs.new_job(f"Stack {name} ...")
    else:
        turnos_path = TRANSCRIPTS / f"{name}_turnos.json"
        turnos = (
            json.loads(turnos_path.read_text(encoding="utf-8")) if turnos_path.exists() else None
        )
        output_path = CLIPS_DIR / f"{name}_9x16.mp4"
        jid = jobs.new_job(f"Reencuadrando {name} a 9:16...")
    threading.Thread(
        target=jobs.run_reframe,
        args=(
            jid,
            clip_path,
            output_path,
            None if layout == "stack" else turnos,
            punch_in,
            layout,
            detector,
            tracker,
        ),
        daemon=True,
    ).start()
    return {"job_id": jid}


# ─── Render ───────────────────────────────────────────────────────────────────
def _validar_params_render(
    caption_source: str, caption_qa: str | None, densidad: str | None, position: str | None
) -> None:
    """Valida los enums del render (allowlists). Invalido -> HTTPException 400."""
    if caption_source not in ("transcript", "srt"):
        raise HTTPException(400, "caption_source debe ser 'transcript' o 'srt'.")
    if caption_qa and caption_qa not in ("alertas", "auto_seguro"):
        raise HTTPException(400, "caption_qa invalido. Opciones: alertas, auto_seguro")
    if densidad and densidad not in ("baja", "media", "alta"):
        raise HTTPException(400, "densidad invalida. Opciones: baja, media, alta")
    if position and position not in ("bottom", "center", "top"):
        raise HTTPException(400, "position invalida. Opciones: bottom, center, top")


@app.post("/api/videos/{name}/render")
def start_render(
    name: str,
    style: str = "hormozi",
    words_per_group: int | None = None,
    use_emphasis: bool = False,
    use_emojis: bool = False,
    pop: str | None = None,
    preset: str | None = None,
    intensidad: str | None = None,
    densidad: str | None = None,
    position: str | None = None,
    avoid_faces: bool | None = None,
    caption_qa: str | None = None,
    guion: str | None = None,
    caption_source: str = "transcript",
):
    _validar_name(name)
    _validar_params_render(caption_source, caption_qa, densidad, position)
    mp4 = INPUT_DIR / f"{name}.mp4"
    grp_path = TRANSCRIPTS / f"{name}_groups.json"
    if caption_source == "transcript":
        # La ruta transcript exige el mismo groups.json de siempre (contrato historico).
        if not mp4.exists():
            raise HTTPException(404, f"Video {name}.mp4 no encontrado")
        if not grp_path.exists():
            raise HTTPException(400, "Transcribe el video antes de renderizar")
    if style not in STYLES:
        raise HTTPException(400, f"Estilo invalido. Opciones: {', '.join(STYLES)}")
    if preset:
        try:
            import cve  # noqa: PLC0415

            if preset not in cve.list_presets():
                raise HTTPException(
                    400, f"Preset invalido. Opciones: {', '.join(cve.list_presets())}"
                )
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(500, "Engine CVE no disponible; renderiza sin preset") from None
    if caption_source == "srt":
        return _start_render_srt(
            name,
            style,
            pop,
            preset,
            intensidad,
            use_emojis,
            use_emphasis,
            words_per_group,
            caption_qa,
        )
    # pop/intensidad invalidos son fail-safe (usan el default del estilo/preset).
    etiqueta = preset or style
    jid = jobs.new_job(f"Renderizando {name} en {etiqueta}...")
    threading.Thread(
        target=jobs.run_render,
        args=(jid, mp4, grp_path, name, style, words_per_group, use_emphasis, use_emojis, pop),
        kwargs={
            "preset": preset,
            "intensidad": intensidad,
            "densidad": densidad,
            "position": position,
            "avoid_faces": avoid_faces,
            "qa_mode": caption_qa,
            "qa_guion": guion,
        },
        daemon=True,
    ).start()
    return {"job_id": jid}


def _verificar_timings_srt(name: str, selection, binding) -> None:
    """Valida que exista el words PRIVADO del video EXACTO y su procedencia. Traduce a HTTP.

    Los timings SRT viven en un namespace por filename; NUNCA se usan los `{stem}_words/groups`
    historicos. Falta el exacto -> 409 si ya hay transcript historico (retranscribir como SRT),
    400 si no hay ningun timing. Procedencia de otro archivo/version/corrupta -> 409.
    """
    import studio_srt_runtime  # noqa: PLC0415
    import transcript_provenance  # noqa: PLC0415

    arts = transcript_provenance.resolve_srt_timing_artifacts(
        transcripts_dir=TRANSCRIPTS, video_stem=name, video_filename=selection.video_filename
    )
    try:
        studio_srt_runtime.verify_timing_provenance(
            binding.path, words_path=arts.words_path, expected_filename=selection.video_filename
        )
    except studio_srt_runtime.StudioSrtTimingMissing:
        if (TRANSCRIPTS / f"{name}_words.json").exists():
            raise HTTPException(409, "Transcribe nuevamente el video asociado al SRT.") from None
        raise HTTPException(400, "Transcribe el video antes de renderizar el SRT.") from None
    except studio_srt_runtime.StudioSrtTimingSourceMismatch:
        raise HTTPException(
            409,
            "Los timings no corresponden al video asociado al SRT. "
            "Transcribe nuevamente el video asociado.",
        ) from None
    except studio_srt.StudioSrtError:
        raise HTTPException(500, "No se pudo leer la seleccion SRT.") from None


def _start_render_srt(
    name: str,
    style: str,
    pop: str | None,
    preset: str | None,
    intensidad: str | None,
    use_emojis: bool,
    use_emphasis: bool,
    words_per_group: int | None,
    caption_qa: str | None,
):
    """Render de Studio con el SRT seleccionado como texto oficial (S36-C2A1, D38).

    Opt-in explicito: exige una asociacion SRT activa (sin autodiscovery) y un transcript de
    palabras (solo timings). Rechaza combinaciones incompatibles con 400. El video se resuelve
    por el FILENAME EXACTO del manifiesto (`manifest.video.filename`), NUNCA por stem ni por
    prioridad de extension: un `.mp4` y un `.mov` con el mismo stem no pueden cruzarse. Nunca
    expone rutas ni cae al transcript. El worker recibe el objeto interno de seleccion.
    """
    import studio_srt_manifest  # noqa: PLC0415
    import studio_srt_runtime  # noqa: PLC0415

    if caption_qa is not None:
        raise HTTPException(400, "Caption QA no esta disponible cuando el SRT es el texto oficial.")
    if words_per_group is not None:
        raise HTTPException(400, "words_per_group no aplica cuando el SRT define los cues.")
    if use_emphasis:
        raise HTTPException(400, "use_emphasis no esta disponible para SRT en S36-C2A1.")
    # Confina el stem sin resolver por extension (la ruta SRT NO usa _resolver_video_input).
    if not studio_srt_manifest.is_safe_basename(name):
        raise HTTPException(404, "Video no encontrado en input/.")
    try:
        selection = studio_srt_runtime.resolve_selected_srt(
            name, storage_root=TRANSCRIPTS / "studio_srt", manifest_dir=TRANSCRIPTS
        )
    except studio_srt.StudioSrtError:
        raise HTTPException(500, "No se pudo leer la seleccion SRT.") from None
    if selection is None:
        raise HTTPException(400, "No hay un SRT seleccionado para este video.")
    # Enlace fuerte al video EXACTO (root/target/stat) para revalidar TOCTOU en el worker.
    try:
        binding = studio_srt_runtime.bind_selected_video(selection, input_dir=INPUT_DIR)
    except studio_srt_runtime.StudioSrtSelectedVideoMissing:
        raise HTTPException(409, "El video asociado al SRT ya no esta disponible.") from None
    except studio_srt.StudioSrtError:
        raise HTTPException(500, "No se pudo leer la seleccion SRT.") from None
    _verificar_timings_srt(name, selection, binding)
    etiqueta = preset or style
    jid = jobs.new_job(f"Renderizando {name} (SRT) en {etiqueta}...")
    threading.Thread(
        target=jobs.run_render,
        args=(jid, binding.path, None, name, style, None),
        kwargs={
            "use_emojis": use_emojis,
            "pop": pop,
            "preset": preset,
            "intensidad": intensidad,
            "srt_selection": selection,
            "srt_binding": binding,
        },
        daemon=True,
    ).start()
    return {"job_id": jid}


# ─── Submagic (motor nube opt-in) ─────────────────────────────────────────────
# Estacion independiente: el video se edita en la nube de Submagic y NO pasa por
# caption.py ni core_ass.py. Sin doble caption.


@app.post("/api/submagic/probar-key")
def submagic_probar_key():
    """Health check + validacion de la key. Nunca revela el secreto."""
    import submagic  # noqa: PLC0415

    return submagic.probar_key()


@app.get("/api/submagic/templates")
def submagic_templates(refresh: bool = False):
    """Lista plantillas reales desde la API. Fallback a Hormozi 2 si falla."""
    import submagic  # noqa: PLC0415

    nombres = submagic.listar_templates(force_refresh=refresh)
    return {"templates": nombres, "default": submagic.DEFAULT_PARAMS["templateName"]}


@app.post("/api/videos/{name}/submagic")
def start_submagic(name: str, reframe: bool = True, template: str | None = None):
    """Edita el video con Submagic (nube). Motor opt-in, sin tocar caption.py.

    reframe=True (default): reencuadra a 9:16 antes de subir si no es vertical.
    template: templateName elegido (None -> default Hormozi 2 del motor)."""
    import submagic  # noqa: PLC0415

    _validar_name(name)
    mp4 = _resolver_video_input(name)
    if mp4 is None:
        raise HTTPException(404, f"Video {name} no encontrado en input/")
    if not submagic.tiene_key():
        raise HTTPException(400, "Falta SUBMAGIC_API_KEY en .env (ver .env.example)")
    jid = jobs.new_job(f"Editando {name} con Submagic (nube)...")
    threading.Thread(
        target=jobs.run_submagic_render,
        args=(jid, mp4, name, reframe, template),
        daemon=True,
    ).start()
    return {"job_id": jid}


# ─── Modo Automatico ──────────────────────────────────────────────────────────


def _resolver_video_input(name: str) -> Path | None:
    """Busca un basename confinado en input/ (.mp4 primero, luego .mov).

    Delega en el helper puro compartido (studio_srt) para no divergir del confinamiento
    usado por el contrato SRT; usa el INPUT_DIR de este modulo (monkeypatcheable en tests).
    """
    return studio_srt.resolver_video_input(name, INPUT_DIR)


@app.get("/api/auto/capabilities")
def auto_capabilities():
    """Capacidades seguras del Automatico; solo estado local, sin requests de red."""
    return studio_auto.capacidades_auto()


@app.post("/api/videos/{name}/auto")
def start_auto(
    name: str,
    objetivo: str = "clips",
    mode: str = "classic",
    broll_enabled: bool = True,
    fx_enabled: bool = True,
    fx_preset: str = "express",
    caption_source: str = "transcript",
):
    """Configura classic/v2 y lanza el worker; nunca ejecuta el pipeline aqui."""
    _validar_name(name)
    if caption_source not in ("transcript", "srt"):
        raise HTTPException(400, "caption_source debe ser 'transcript' o 'srt'.")
    if caption_source == "srt":
        return _start_auto_srt(name, objetivo, mode, broll_enabled, fx_enabled, fx_preset)
    mp4 = _resolver_video_input(name)
    if mp4 is None:
        raise HTTPException(404, f"Video {name} no encontrado en input/")
    if objetivo != "clips":
        raise HTTPException(400, "objetivo debe ser 'clips' (unico soportado en v1)")
    try:
        config = studio_auto.construir_auto_config(
            mode=mode,
            broll_enabled=broll_enabled,
            fx_enabled=fx_enabled,
            fx_preset=fx_preset,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from None
    try:
        jid = jobs.new_job(f"Modo Automatico {mode}: {name}...")
        threading.Thread(
            target=jobs.run_auto,
            args=(jid, mp4, name, objetivo),
            kwargs={"config": config},
            daemon=True,
        ).start()
    except Exception:
        raise HTTPException(500, "No se pudo iniciar el Modo Automatico") from None
    return {"job_id": jid}


def _start_auto_srt(name, objetivo, mode, broll_enabled, fx_enabled, fx_preset):
    """Auto con caption_source=srt: usa el video EXACTO asociado (no por stem) y la selección SRT.

    La resolución de timings privados + procedencia por clip ocurre dentro de ejecutar_auto
    (auto_srt_run); aquí solo se valida selección + video para fallar rápido. Nunca cae al
    transcript. Sin selección -> 400; video exacto ausente -> 409; storage corrupto -> 500.
    """
    import studio_srt_manifest  # noqa: PLC0415
    import studio_srt_runtime  # noqa: PLC0415

    if objetivo != "clips":
        raise HTTPException(400, "objetivo debe ser 'clips' (unico soportado en v1)")
    if not studio_srt_manifest.is_safe_basename(name):
        raise HTTPException(404, "Video no encontrado en input/.")
    try:
        config = studio_auto.construir_auto_config(
            mode=mode,
            broll_enabled=broll_enabled,
            fx_enabled=fx_enabled,
            fx_preset=fx_preset,
            caption_source="srt",
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from None
    try:
        selection = studio_srt_runtime.resolve_selected_srt(
            name, storage_root=TRANSCRIPTS / "studio_srt", manifest_dir=TRANSCRIPTS
        )
    except studio_srt.StudioSrtError:
        raise HTTPException(500, "No se pudo leer la seleccion SRT.") from None
    if selection is None:
        raise HTTPException(400, "No hay un SRT seleccionado para este video.")
    try:
        binding = studio_srt_runtime.bind_selected_video(selection, input_dir=INPUT_DIR)
    except studio_srt_runtime.StudioSrtSelectedVideoMissing:
        raise HTTPException(409, "El video asociado al SRT ya no esta disponible.") from None
    except studio_srt.StudioSrtError:
        raise HTTPException(500, "No se pudo leer la seleccion SRT.") from None
    try:
        jid = jobs.new_job(f"Modo Automatico SRT: {name}...")
        threading.Thread(
            target=jobs.run_auto,
            args=(jid, binding.path, name, objetivo),
            kwargs={"config": config},
            daemon=True,
        ).start()
    except Exception:
        raise HTTPException(500, "No se pudo iniciar el Modo Automatico") from None
    return {"job_id": jid}


# ─── Editor de Paquete (S35, D26/D32) ─────────────────────────────────────────
# Vista de revision SOLO-LECTURA sobre output/paquetes/. La logica vive en el router
# studio_packages (contrato + servido de binario confinado); aqui solo se registra.
app.include_router(studio_packages.router)

# ─── Contrato SRT de Studio (S36-C1, D37) ─────────────────────────────────────
# Asociacion privada video<->SRT: upload, validacion, almacenamiento y consulta.
# La logica vive en studio_srt (dominio puro) + studio_srt_routes (HTTP); aqui solo
# se registra. El almacenamiento (transcripts/studio_srt/) nunca se monta.
app.include_router(studio_srt_routes.router)


# ─── Jobs / Estilos ───────────────────────────────────────────────────────────
@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job no encontrado")
    return job


# Descripciones legibles para el dropdown del Studio (fallback: el id crudo).
_STYLE_LABELS = {
    "hormozi": "Hormozi — blanco + amarillo",
    "clean": "Clean — blanco sobrio",
    "karaoke": "Karaoke — relleno cian",
    "bounce": "Bounce — naranja animado",
    "pms": "PMS — morado de marca",
}


@app.get("/api/styles")
def list_styles():
    return [
        {
            "id": k,
            "name": v.name,
            "animation": v.animation_type,
            "label": _STYLE_LABELS.get(k, k),
        }
        for k, v in STYLES.items()
    ]


# Labels de presets CVE para el dropdown (fallback: el id crudo).
_PRESET_LABELS = {
    "clean_podcast": "Clean Podcast — limpio profesional",
    "viral_bounce": "Viral Bounce — pop + rebote",
    "keyword_punch": "Keyword Punch — keywords gigantes + glow",
    "karaoke_highlight": "Karaoke Highlight — relleno progresivo moderno",
}

_INTENSIDAD_LABELS = [
    {"id": "minimal", "label": "Minimal — casi plano"},
    {"id": "clean", "label": "Clean — profesional"},
    {"id": "viral", "label": "Viral — recomendado"},
]


@app.get("/api/presets")
def list_presets_cve():
    """Presets del caption_viral_engine + intensidades. Fail-open: sin CVE -> vacio."""
    try:
        import cve  # noqa: PLC0415

        presets = [
            {**info, "label": _PRESET_LABELS.get(info["id"], info["id"])}
            for info in cve.info_presets()
        ]
        return {"presets": presets, "intensidades": _INTENSIDAD_LABELS}
    except Exception as exc:  # CVE roto no tumba el Studio: la UI cae a estilos clasicos
        print(f"[studio] /api/presets sin engine CVE ({exc}) - dropdown en modo clasico")
        return {"presets": [], "intensidades": []}


# H1 (P0-4): el servidor escucha SOLO en loopback. No hay modo LAN en esta fase (sin token
# ni auth); habilitar la red se difiere a una fase disenada para eso. No debe quedar 0.0.0.0
# como host de arranque de produccion.
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 8787

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host=LISTEN_HOST, port=LISTEN_PORT, reload=False)
