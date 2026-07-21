# H1 — Inventario previo a los fixes (seguridad e integridad)

**Base:** `9d87cc7` (merge PR #24). **Rama:** `fix/h1-seguridad-integridad`.
**Alcance:** P0-1, P0-2, P0-3, P0-4, P1-OUT-1, P1-OUT-2. NO H2/H3/HyperFrames.

Inventario levantado antes de endurecer, a partir de `AUDITORIA.md` + lectura directa del código.

---

## 1. Endpoints con identificador de usuario en la ruta (P0-1)

`app.py` — endpoints `{name}`/`{stem}` que interpolan el identificador en un `Path`.

| Endpoint | Símbolo | Rutas construidas | Estado ANTES |
|----------|---------|-------------------|--------------|
| `POST /api/videos/upload` | `upload_video` | `INPUT_DIR / file.filename` | crudo (P0-2) |
| `POST /api/videos/{name}/transcribe` | `start_transcribe` | `INPUT_DIR/{name}.mp4`, `TRANSCRIPTS/{name}_info.json` | crudo (rama transcript) |
| `GET /api/videos/{name}/transcript` | `get_transcript` | `TRANSCRIPTS/{name}_groups.json` | crudo |
| `PUT /api/videos/{name}/transcript` | `save_transcript` | idem (escritura) | crudo |
| `POST /api/videos/{name}/analyze` | `start_analyze` | `TRANSCRIPTS/{name}_groups.json` | crudo |
| `GET /api/videos/{name}/brain` | `get_brain` | `TRANSCRIPTS/{name}.brain.json` | crudo |
| `PUT /api/videos/{name}/brain` | `save_brain` | idem (escritura) | crudo |
| `GET /api/videos/{name}/keywords` | `get_keywords` | `TRANSCRIPTS/{name}_keywords.json` | **ya guardado** (is_safe_basename) |
| `POST /api/videos/{name}/keywords` | `save_keywords` | idem | **ya guardado** |
| `POST /api/videos/{name}/depurar` | `start_depurar` | `INPUT_DIR/{name}.mp4`, `TRANSCRIPTS/{name}_words.json` | crudo |
| `POST /api/videos/{name}/clips` | `start_clips` | `INPUT_DIR/{name}.mp4` | crudo |
| `GET /api/videos/{name}/clips` | `get_clips` | `ROOT/output/clips/{name}_clips.json` | crudo |
| `POST /api/videos/{name}/render` | `start_render` | `INPUT_DIR/{name}.mp4`, `TRANSCRIPTS/{name}_groups.json` | crudo (rama transcript) |
| `POST /api/videos/{name}/submagic` | `start_submagic` | vía `_resolver_video_input` | confinado por resolver |
| `POST /api/videos/{name}/auto` | `start_auto` | vía `_resolver_video_input` (rama transcript) | confinado por resolver |
| `POST /api/clips/{name}/detectar` | `detectar_caras_clip` | `CLIPS_DIR/{name}.mp4` | crudo |
| `POST /api/clips/{name}/turnos` | `save_turnos_clip` | `TRANSCRIPTS/{name}_turnos.json` (escritura) | crudo |
| `POST /api/clips/{name}/reframe` | `start_reframe` | `CLIPS_DIR/{name}*.mp4`, `TRANSCRIPTS/{name}_turnos.json` | crudo |
| `GET /api/jobs/{job_id}` | `get_job` | ninguna (lookup en dict) | no aplica |

Las ramas `caption_source=srt` de transcribe/render/auto **ya** validaban con `is_safe_basename`
(`app.py:197,572,724`), igual que keywords (`:288,299`). El resto interpolaba `{name}` crudo.

**Routers incluidos** (`app.include_router`):
- `studio_srt_routes` (contrato SRT): endurecido, valida vía `studio_srt.resolver_video_input`
  + `validate_srt_filename` + whitelist de manifiesto. **No se toca** (contrato más específico).
- `studio_packages` (Editor de paquete): confina vía `pe.resolver_hijo_seguro` /
  `resolver_archivo_paquete` + allowlist `.mp4`. **No se toca**.

**Decisión:** guard compartido `_validar_name(name)` (fuente única `path_safety.is_safe_basename`)
al INICIO de cada endpoint crudo; 404 saneado sin reflejar `name`, antes de construir cualquier
`Path`. No se altera ningún contrato ya endurecido.

## 2. Mounts públicos (P0-3, P0-4)

| Mount | ANTES | Consumo real de la UI | Decisión H1 |
|-------|-------|------------------------|-------------|
| `/input` | `StaticFiles(INPUT_DIR)` — binario fuente crudo | `index.html:1296` (`/input/${name}.mp4`) | **ELIMINADO**; nuevo endpoint validado `GET /api/videos/{name}/source` |
| `/output` | `_OutputSinPaquetes` (solo bloquea `paquetes/`) | `.mp4` de render (`index.html:1698,1701,2461`) | `_OutputMedia`: allowlist `.mp4` + bloqueo `paquetes/` |
| `/clips` | `StaticFiles(CLIPS_DIR)` | `.mp4` de clip (`index.html:1843,1853,1893`) | `_ClipsMedia`: allowlist `.mp4` |
| `/thumbs` | `StaticFiles(THUMBS_DIR)` | `.jpg` de miniatura (`/api/videos` → `thumb`) | `_ThumbsMedia`: allowlist imágenes |
| `/static` | `StaticFiles(STATIC_DIR)` | UI (HTML/CSS/JS) | sin cambio (StaticFiles confina) |

Todas las subclases allowlist añaden confinamiento por `resolve()+relative_to` (traversal +
symlink que escapa). `/input` era el único consumidor frontend que exigía reemplazo de URL.

## 3. Funciones que queman captions / publican MP4 final (P1-OUT-1/2)

- `core_ass.burn_video` (`core_ass.py:310`) — quemado ASS simple. Callers: `jobs_render` (Studio),
  `caption.py` (CLI), `auto.py`/`auto_v2.py` (vía `burn_video_with_emojis` → delega).
- `core_ass.burn_video_with_emojis` (`core_ass.py:355`) — quemado con overlays/FX/clips. Callers:
  `jobs_render.py:253,386`, `auto.py:307,400`, `auto_v2.py:199`, `caption.py:154,158`.
- Ambas retornaban tras `returncode==0` **sin** validar el archivo y **escribiendo directo al
  nombre final**. `jobs_render` marcaba `done`; `studio_packages`/`paquete_editor` publicaban con
  `is_file()`.

**Decisión:** atomicidad INTERNA a las dos funciones vía `media_integrity.publicar_mp4_atomico`
(temporal en el subdir privado `<dir_final>/.render_tmp/<uuid>.mp4` — mismo volumen → `os.replace`
atómico; **fuera** de los outputs públicos, corrección post-review P2 → un temporal en curso o
abandonado no se sirve ni se lista → validar returncode+size+ffprobe → `os.replace`). Así **todos**
los callers (jobs_render, Auto, CLI) heredan la publicación atómica sin cambiar firmas. `/output` y
`/api/videos` rechazan/ignoran además segmentos ocultos y nombres `.part-`.

## 4. Otros escritores FFmpeg de MP4 (fuera de H1 — documentados)

Escriben `.mp4` pero **NO** pasan por `burn_video*` y **NO** son alcance de P1-OUT (que la auditoría
acota a las funciones de quemado de captions). Se difieren a H2/fase posterior:

- `clipper.py` — corte de clips (`{stem}_clips`), FFmpeg directo.
- `reframe.py` / `reframe_*` — reencuadre 9:16 (`{stem}_9x16.mp4`).
- `depurador.py` — video depurado (`{stem}_limpio.mp4`).
- `broll_video_stock_base.py` — descarga/proceso de b-roll de video.
- `submagic.py` — descarga del render final desde la nube (motor opt-in).
- `auto_av.py` — compuerta A/V (probe; no publica render de captions).

**No se afirma que todos los MP4 del producto sean atómicos**: solo el render de captions
(`burn_video*`) queda endurecido en H1.
