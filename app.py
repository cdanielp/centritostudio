"""
app.py — API FastAPI para Centrito Studio.
Levanta en puerto 8787. Sirve static/index.html como UI.
Workers de background en jobs.py.
"""

from __future__ import annotations

import os
import shutil
import threading
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import json

from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import core
import jobs
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

app.mount("/input", StaticFiles(directory=str(INPUT_DIR)), name="input")
app.mount("/output", StaticFiles(directory=str(OUTPUT_DIR)), name="output")
app.mount("/clips", StaticFiles(directory=str(CLIPS_DIR)), name="clips")
app.mount("/thumbs", StaticFiles(directory=str(THUMBS_DIR)), name="thumbs")


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


@app.post("/api/videos/upload")
async def upload_video(file: UploadFile = File(...)):
    dest = INPUT_DIR / file.filename
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    info = core.get_video_info(dest)
    (TRANSCRIPTS / f"{dest.stem}_info.json").write_text(
        json.dumps(info, ensure_ascii=False), encoding="utf-8"
    )
    core.extract_thumb(dest, THUMBS_DIR / f"{dest.stem}.jpg")
    return {"name": dest.stem, "filename": dest.name, **info}


# ─── Transcripcion ────────────────────────────────────────────────────────────
@app.post("/api/videos/{name}/transcribe")
def start_transcribe(name: str, lang: str = "es", model: str = "auto"):
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


# ─── Transcript ───────────────────────────────────────────────────────────────
@app.get("/api/videos/{name}/transcript")
def get_transcript(name: str):
    grp_path = TRANSCRIPTS / f"{name}_groups.json"
    if not grp_path.exists():
        raise HTTPException(404, "Transcript no encontrado — transcribe primero")
    return json.loads(grp_path.read_text(encoding="utf-8"))


@app.put("/api/videos/{name}/transcript")
def save_transcript(name: str, body: list = Body(...)):
    grp_path = TRANSCRIPTS / f"{name}_groups.json"
    rebalanced = [core.rebalance_timestamps(g) if g.get("edited") else g for g in body]
    for i, g in enumerate(rebalanced):
        g["id"] = i
    grp_path.write_text(json.dumps(rebalanced, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"saved": len(rebalanced)}


# ─── Analisis IA ──────────────────────────────────────────────────────────────
@app.post("/api/videos/{name}/analyze")
def start_analyze(name: str):
    grp_path = TRANSCRIPTS / f"{name}_groups.json"
    if not grp_path.exists():
        raise HTTPException(400, "Transcribe el video antes de analizar")
    jid = jobs.new_job(f"Analizando {name} con IA...")
    threading.Thread(target=jobs.run_analyze, args=(jid, grp_path, name), daemon=True).start()
    return {"job_id": jid}


# ─── Brain ────────────────────────────────────────────────────────────────────
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


# ─── Depurador ────────────────────────────────────────────────────────────────
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
    jid = jobs.new_job(f"Depurando {name} ({mode})...")
    threading.Thread(
        target=jobs.run_depurar, args=(jid, mp4, words_path, name, mode), daemon=True
    ).start()
    return {"job_id": jid}


# ─── Clips ────────────────────────────────────────────────────────────────────
@app.post("/api/videos/{name}/clips")
def start_clips(name: str, tipos: str = "ambos"):
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
    clips_dir = ROOT / "output" / "clips"
    clips_path = clips_dir / f"{name}_clips.json"
    if not clips_path.exists():
        return {"clips": [], "descartados": [], "casi": [], "error": None}
    return json.loads(clips_path.read_text(encoding="utf-8"))


# ─── Reframe ──────────────────────────────────────────────────────────────────


@app.post("/api/clips/{name}/detectar")
def detectar_caras_clip(name: str, detector: str = "yunet"):
    """Detecta caras en un clip y devuelve la lista con thumbnails."""
    clip_path = CLIPS_DIR / f"{name}.mp4"
    if not clip_path.exists():
        raise HTTPException(404, f"Clip {name}.mp4 no encontrado")
    import reframe  # noqa: PLC0415

    caras = reframe.detectar_caras_video(clip_path, detector_type=detector)
    return {"n_caras": len(caras), "caras": caras}


@app.post("/api/clips/{name}/turnos")
def save_turnos_clip(name: str, body: dict = Body(...)):
    """Guarda el archivo de turnos para un clip multi-cara."""
    clip_path = CLIPS_DIR / f"{name}.mp4"
    if not clip_path.exists():
        raise HTTPException(404, f"Clip {name}.mp4 no encontrado")
    turnos_path = TRANSCRIPTS / f"{name}_turnos.json"
    turnos_path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"saved": len(body.get("turnos", []))}


@app.post("/api/clips/{name}/reframe")
def start_reframe(
    name: str, punch_in: bool = False, layout: str = "tracking", detector: str = "yunet"
):
    """Inicia el reencuadre 9:16: tracking (default) o stack (bandas estaticas)."""
    clip_path = CLIPS_DIR / f"{name}.mp4"
    if not clip_path.exists():
        raise HTTPException(404, f"Clip {name}.mp4 no encontrado")
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
        ),
        daemon=True,
    ).start()
    return {"job_id": jid}


# ─── Render ───────────────────────────────────────────────────────────────────
@app.post("/api/videos/{name}/render")
def start_render(
    name: str,
    style: str = "hormozi",
    words_per_group: int | None = None,
    use_emphasis: bool = False,
    use_emojis: bool = False,
):
    mp4 = INPUT_DIR / f"{name}.mp4"
    grp_path = TRANSCRIPTS / f"{name}_groups.json"
    if not mp4.exists():
        raise HTTPException(404, f"Video {name}.mp4 no encontrado")
    if not grp_path.exists():
        raise HTTPException(400, "Transcribe el video antes de renderizar")
    if style not in STYLES:
        raise HTTPException(400, f"Estilo invalido. Opciones: {', '.join(STYLES)}")
    jid = jobs.new_job(f"Renderizando {name} en {style}...")
    threading.Thread(
        target=jobs.run_render,
        args=(jid, mp4, grp_path, name, style, words_per_group, use_emphasis, use_emojis),
        daemon=True,
    ).start()
    return {"job_id": jid}


# ─── Jobs / Estilos ───────────────────────────────────────────────────────────
@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job no encontrado")
    return job


@app.get("/api/styles")
def list_styles():
    return [{"id": k, "name": v.name, "animation": v.animation_type} for k, v in STYLES.items()]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8787, reload=False)
