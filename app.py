"""
app.py — API FastAPI para Centrito Studio.
Levanta en puerto 8787. Sirve static/index.html como UI.
"""

from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import json
import shutil

from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import core
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

# ─── Jobs en memoria ───────────────────────────────────────────────────────────
_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()


def _new_job(description: str) -> str:
    jid = str(uuid.uuid4())[:8]
    with _JOBS_LOCK:
        _JOBS[jid] = {
            "status": "pending",
            "progress": 0,
            "message": description,
            "result": None,
            "error": None,
        }
    return jid


def _update_job(jid: str, **kwargs):
    with _JOBS_LOCK:
        _JOBS[jid].update(kwargs)


# ─── FastAPI ──────────────────────────────────────────────────────────────────
app = FastAPI(title="Centrito Studio")

# Servir archivos de input/output/thumbs
app.mount("/input", StaticFiles(directory=str(INPUT_DIR)), name="input")
app.mount("/output", StaticFiles(directory=str(OUTPUT_DIR)), name="output")
app.mount("/thumbs", StaticFiles(directory=str(THUMBS_DIR)), name="thumbs")


# ─── Root → index.html ────────────────────────────────────────────────────────
@app.get("/")
def root():
    return FileResponse(str(STATIC_DIR / "index.html"))


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ─── Videos ───────────────────────────────────────────────────────────────────
@app.get("/api/videos")
def list_videos():
    result = []
    for mp4 in sorted(INPUT_DIR.glob("*.mp4")):
        if mp4.stem.startswith("test_"):
            continue
        info_file = TRANSCRIPTS / f"{mp4.stem}_info.json"
        groups_file = TRANSCRIPTS / f"{mp4.stem}_groups.json"
        outputs = list(OUTPUT_DIR.glob(f"{mp4.stem}_*.mp4"))

        # Status
        if outputs:
            status = "renderizado"
        elif groups_file.exists():
            status = "transcrito"
        else:
            status = "sin_transcribir"

        # Info cached or fresh
        if info_file.exists():
            info = json.loads(info_file.read_text(encoding="utf-8"))
        else:
            info = core.get_video_info(mp4)
            info_file.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")

        # Thumbnail
        thumb = THUMBS_DIR / f"{mp4.stem}.jpg"
        if not thumb.exists():
            core.extract_thumb(mp4, thumb)

        # Output list
        output_names = [o.name for o in outputs]

        result.append(
            {
                "name": mp4.stem,
                "filename": mp4.name,
                "status": status,
                "duration": round(info.get("duration", 0), 2),
                "width": info.get("width", 0),
                "height": info.get("height", 0),
                "mean_volume": info.get("mean_volume", -99),
                "has_audio": info.get("has_audio", False),
                "thumb": f"/thumbs/{mp4.stem}.jpg" if thumb.exists() else None,
                "outputs": output_names,
            }
        )
    return result


@app.post("/api/videos/upload")
async def upload_video(file: UploadFile = File(...)):
    dest = INPUT_DIR / file.filename
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    # Pre-compute info
    info = core.get_video_info(dest)
    (TRANSCRIPTS / f"{dest.stem}_info.json").write_text(
        json.dumps(info, ensure_ascii=False), encoding="utf-8"
    )
    core.extract_thumb(dest, THUMBS_DIR / f"{dest.stem}.jpg")
    return {"name": dest.stem, "filename": dest.name, **info}


# ─── Transcripción (background) ───────────────────────────────────────────────
@app.post("/api/videos/{name}/transcribe")
def start_transcribe(name: str, lang: str = "es", model: str = "auto"):
    mp4 = INPUT_DIR / f"{name}.mp4"
    if not mp4.exists():
        raise HTTPException(404, f"Video {name}.mp4 no encontrado")

    # Verificar volumen
    info_file = TRANSCRIPTS / f"{name}_info.json"
    if info_file.exists():
        info = json.loads(info_file.read_text(encoding="utf-8"))
        if info.get("mean_volume", 0) < -40:
            raise HTTPException(400, "El video no tiene voz detectable (mean_volume < -40 dB)")

    jid = _new_job(f"Transcribiendo {name}...")
    threading.Thread(
        target=_run_transcribe,
        args=(jid, mp4, lang, model, name),
        daemon=True,
    ).start()
    return {"job_id": jid}


def _run_transcribe(jid: str, mp4: Path, lang: str, model_arg: str, name: str):
    try:
        _update_job(jid, status="running", progress=5, message="Cargando modelo Whisper...")
        device, compute = core.detect_device()
        model_path, label = core.resolve_model(model_arg)
        _update_job(jid, progress=15, message=f"Transcribiendo con {label}...")

        result = core.transcribe_video(mp4, lang, device, compute, model_path)
        _update_job(jid, progress=60, message="Agrupando palabras...")

        groups = core.group_words(result["words"])
        _update_job(jid, progress=85, message="Guardando transcript...")

        # Guardar
        raw_path = TRANSCRIPTS / f"{name}_words.json"
        grp_path = TRANSCRIPTS / f"{name}_groups.json"
        raw_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        grp_path.write_text(json.dumps(groups, ensure_ascii=False, indent=2), encoding="utf-8")

        _update_job(
            jid,
            status="done",
            progress=100,
            message=f"OK — {len(result['words'])} palabras, {len(groups)} grupos",
            result={"words": len(result["words"]), "groups": len(groups)},
        )
    except Exception as exc:
        _update_job(jid, status="error", message=str(exc), error=str(exc))


# ─── Transcript (lectura / escritura) ─────────────────────────────────────────
@app.get("/api/videos/{name}/transcript")
def get_transcript(name: str):
    grp_path = TRANSCRIPTS / f"{name}_groups.json"
    if not grp_path.exists():
        raise HTTPException(404, "Transcript no encontrado — transcribe primero")
    return json.loads(grp_path.read_text(encoding="utf-8"))


@app.put("/api/videos/{name}/transcript")
def save_transcript(name: str, body: list = Body(...)):
    grp_path = TRANSCRIPTS / f"{name}_groups.json"
    # Rebalancear timestamps de grupos editados
    rebalanced = []
    for g in body:
        if g.get("edited"):
            rebalanced.append(core.rebalance_timestamps(g))
        else:
            rebalanced.append(g)
    # Re-numerar IDs
    for i, g in enumerate(rebalanced):
        g["id"] = i
    grp_path.write_text(json.dumps(rebalanced, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"saved": len(rebalanced)}


# ─── Análisis IA (background) ─────────────────────────────────────────────────
@app.post("/api/videos/{name}/analyze")
def start_analyze(name: str):
    grp_path = TRANSCRIPTS / f"{name}_groups.json"
    if not grp_path.exists():
        raise HTTPException(400, "Transcribe el video antes de analizar")
    jid = _new_job(f"Analizando {name} con IA...")
    threading.Thread(target=_run_analyze, args=(jid, grp_path, name), daemon=True).start()
    return {"job_id": jid}


def _run_analyze(jid: str, grp_path: Path, name: str):
    try:
        import brain

        _update_job(jid, status="running", progress=10, message="Cargando grupos...")
        groups = json.loads(grp_path.read_text(encoding="utf-8"))
        _update_job(jid, progress=30, message="Enviando al LLM...")
        data = brain.analizar_grupos(groups, contexto=name, video_name=name)
        n_kw = sum(1 for g in data.get("groups", []) if g.get("kw") is not None)
        n_em = sum(1 for g in data.get("groups", []) if g.get("emoji"))
        _update_job(jid, status="done", progress=100,
                    message=f"OK - {n_kw} keywords, {n_em} emojis",
                    result={"keywords": n_kw, "emojis": n_em})
    except Exception as exc:
        _update_job(jid, status="error", message=str(exc), error=str(exc))


# ─── Brain (keywords + emojis guardados) ──────────────────────────────────────
@app.get("/api/videos/{name}/brain")
def get_brain(name: str):
    path = TRANSCRIPTS / f"{name}.brain.json"
    if not path.exists():
        return {"groups": []}
    return json.loads(path.read_text(encoding="utf-8"))


@app.put("/api/videos/{name}/brain")
def save_brain(name: str, body: list = Body(...)):
    path = TRANSCRIPTS / f"{name}.brain.json"
    grp_path = TRANSCRIPTS / f"{name}_groups.json"
    # Enriquecer con kw_ts para mantener re-grouping-safe tras edicion del usuario
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


# ─── Depurador (background) ───────────────────────────────────────────────────
@app.post("/api/videos/{name}/depurar")
def start_depurar(name: str, mode: str = "seguro"):
    mp4 = INPUT_DIR / f"{name}.mp4"
    words_path = TRANSCRIPTS / f"{name}_words.json"
    if not mp4.exists():
        raise HTTPException(404, f"Video {name}.mp4 no encontrado")
    if not words_path.exists():
        raise HTTPException(400, "Transcribe el video antes de depurar")
    if mode not in ("seguro", "agresivo"):
        raise HTTPException(400, "mode debe ser 'seguro' o 'agresivo'")
    jid = _new_job(f"Depurando {name} ({mode})...")
    threading.Thread(
        target=_run_depurar, args=(jid, mp4, words_path, name, mode), daemon=True
    ).start()
    return {"job_id": jid}


def _run_depurar(jid: str, mp4: Path, words_path: Path, name: str, mode: str):
    try:
        import depurador as dep

        _update_job(jid, status="running", progress=10, message="Cargando words.json...")
        raw = json.loads(words_path.read_text(encoding="utf-8"))
        words = raw.get("words", [])
        out_mp4 = OUTPUT_DIR / f"{name}_limpio.mp4"
        _update_job(jid, progress=20, message=f"Depurando en modo {mode}...")
        result = dep.depurar(mp4, words, mode, out_mp4)

        # Recalcular words.json
        new_words, drift = dep.recalcular_words(words, result["edl"])
        raw_clean = {**raw, "words": new_words}
        (TRANSCRIPTS / f"{name}_limpio_words.json").write_text(
            json.dumps(raw_clean, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        drift_note = " (re-transcribir recomendado)" if drift > dep.DRIFT_THRESHOLD else ""
        _update_job(jid, status="done", progress=100,
                    message=f"Listo - {result['cuts']} cortes, -{result['saved_s']}s{drift_note}",
                    result={**result, "output": out_mp4.name, "drift_s": drift})
    except Exception as exc:
        _update_job(jid, status="error", message=str(exc), error=str(exc))


# ─── Render (background) ──────────────────────────────────────────────────────
@app.post("/api/videos/{name}/render")
def start_render(
    name: str, style: str = "hormozi",
    words_per_group: int | None = None, use_emphasis: bool = False,
):
    mp4 = INPUT_DIR / f"{name}.mp4"
    grp_path = TRANSCRIPTS / f"{name}_groups.json"
    if not mp4.exists():
        raise HTTPException(404, f"Video {name}.mp4 no encontrado")
    if not grp_path.exists():
        raise HTTPException(400, "Transcribe el video antes de renderizar")
    if style not in STYLES:
        raise HTTPException(400, f"Estilo invalido. Opciones: {', '.join(STYLES)}")

    jid = _new_job(f"Renderizando {name} en {style}...")
    threading.Thread(
        target=_run_render,
        args=(jid, mp4, grp_path, name, style, words_per_group, use_emphasis),
        daemon=True,
    ).start()
    return {"job_id": jid}


def _run_render(
    jid: str, mp4: Path, grp_path: Path, name: str,
    style: str, words_per_group: int | None, use_emphasis: bool = False,
):
    try:
        from styles import get_style

        _update_job(jid, status="running", progress=10, message="Cargando grupos...")
        groups = json.loads(grp_path.read_text(encoding="utf-8"))
        enfasis_msg = ""

        if words_per_group is not None:
            raw_path = TRANSCRIPTS / f"{name}_words.json"
            if raw_path.exists():
                raw = json.loads(raw_path.read_text(encoding="utf-8"))
                groups = core.group_words(raw["words"], max_words=words_per_group)

        if use_emphasis:
            brain_path = TRANSCRIPTS / f"{name}.brain.json"
            if brain_path.exists():
                brain_data = json.loads(brain_path.read_text(encoding="utf-8"))
                groups = core.apply_brain(groups, brain_data)
                n_kw = sum(1 for g in brain_data.get("groups", []) if g.get("kw") is not None)
                provider = brain_data.get("provider", "?")
                latency = brain_data.get("latency_s", "?")
                tokens = brain_data.get("tokens", {}).get("total", "?")
                print(f"[render] Enfasis IA | {provider} kw={n_kw} tok={tokens} lat={latency}s")
                enfasis_msg = f"Enfasis aplicado: {n_kw} keywords"
            else:
                enfasis_msg = "Enfasis NO aplicado: sin brain.json (analiza primero)"
                print(f"[render] {enfasis_msg}")
            _update_job(jid, progress=18, message=enfasis_msg)

        _update_job(jid, progress=20, message="Leyendo video info...")
        info = core.get_video_info(mp4)
        w, h = info["width"], info["height"]

        style_cfg = get_style(style)
        suffix = f"_{style}_enfasis" if use_emphasis else f"_{style}"
        ass_path = OUTPUT_DIR / f"{name}{suffix}.ass"
        out_path = OUTPUT_DIR / f"{name}{suffix}.mp4"

        _update_job(jid, progress=35, message="Generando subtitulos ASS...")
        core.build_ass(groups, w, h, style_cfg, ass_path)

        _update_job(jid, progress=50, message="Quemando con FFmpeg...")
        elapsed = core.burn_video(mp4, ass_path, out_path)

        emphasis_result = enfasis_msg if use_emphasis else None
        _update_job(
            jid, status="done", progress=100,
            message=f"Listo en {elapsed:.1f}s",
            result={"output": out_path.name, "elapsed": elapsed, "emphasis_msg": emphasis_result},
        )
    except Exception as exc:
        _update_job(jid, status="error", message=str(exc), error=str(exc))


# ─── Jobs ─────────────────────────────────────────────────────────────────────
@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "Job no encontrado")
    return job


# ─── Estilos disponibles ──────────────────────────────────────────────────────
@app.get("/api/styles")
def list_styles():
    return [{"id": k, "name": v.name, "animation": v.animation_type} for k, v in STYLES.items()]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8787, reload=False)
