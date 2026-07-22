# H5 — Matriz de portabilidad de tests (gate remoto ligero)

Base `3cbac46` (cierre H4). Clasificación **empírica**: cada `tests/test_*.py` se ejecutó en un
venv **limpio** Python 3.12 (solo `requirements-ci.txt`) con la **red bloqueada** (`pytest-socket`)
y, para simular el runner Ubuntu, con **PATH saneado sin FFmpeg ni Node**. Un archivo entra al gate
(`INCLUIR`) solo si corre **completo, verde y con cero skips** en esas condiciones.

- Suite total del repo: `2410 passed, 4 skipped`.
- Subconjunto CI: **44 archivos**, **1302 tests**, **0 skips**, sin red/FFmpeg/GPU/modelos/Node.
- Manifiesto: `ci/pytest-light.txt` · Runner: `ci/run_pytest_light.py`.
- Portabilidad confirmada por la **ejecución real en Ubuntu** (GitHub Actions), no solo por el
  sondeo Windows: se excluyó `test_studio_srt_runtime` tras fallar en Linux por semántica de
  symlink divergente (ver tabla de excluidos).

Regla aplicada: no se excluye un archivo por "mencionar" FFmpeg (suele ser un comentario "no usa
FFmpeg"); se excluye solo si al quitar el binario/dep el archivo **falla o se salta**. No se tocó
producción para volver portable ningún test.

## Incluidos (45) — categoría INCLUIR

| Área del contrato (§2) | Archivos |
|---|---|
| Path safety / confinamiento | `test_h1_path_traversal` (214, TestClient sin socket), `test_h1_bind_localhost` |
| atomic_io / publicación | `test_h2_atomic_io` |
| Jobs y estados | `test_jobs`, `test_jobs_render_srt` |
| Preflight (mocks) | `test_h3_preflight`, `test_h3_launcher` |
| NVENC selección/fallback (mocks) | `test_nvenc_encoder` |
| SRT parser/validación/manifest puros | `test_srt_import`, `test_srt_align`, `test_srt_slice`, `test_caption_srt`, `test_clip_srt`, `test_clip_transcript`, `test_clipper_srt`, `test_auto_srt_manifest`, `test_auto_srt_artifacts`, `test_auto_srt_run`, `test_studio_auto` |
| Caption QA puro | `test_contrato_caption_qa` |
| Planner de b-roll puro | `test_broll_planner` |
| Procedencia / resume / checkpoints | `test_transcript_provenance`, `test_h2_classic_provenance`, `test_h2_classic_reuse`, `test_h2_paquete_marker` |
| Arranque / check.bat (contrato) | `test_h3_check_bat` |
| Contratos puros (CVE / estilos / fx / popups / core / clipper / alpha / paquete) | `test_contrato_core`, `test_contrato_cve`, `test_contrato_styles`, `test_contrato_fx`, `test_contrato_popups`, `test_contrato_clipper`, `test_contrato_alpha`, `test_contrato_paquete_editor`, `test_cve_spans`, `test_cve_avoid_faces`, `test_cve_center`, `test_cve_naming`, `test_cve_presets_json`, `test_estilos`, `test_spans_glow_align`, `test_auto_fx`, `test_depurador`, `test_ui_auto_contract` |

Verificación puntual de la fila TestClient: `test_h1_path_traversal` importa `app` (FastAPI) y usa
`starlette.testclient.TestClient`; corre **verde con `--disable-socket`**, lo que prueba que NO abre
sockets reales. Por eso `fastapi` + `httpx` + `python-multipart` están justificados en
`requirements-ci.txt` (sin ellos, `import app` y `TestClient` fallan — verificado quitándolos).

## Excluidos con motivo

| Test | Motivo de exclusión | Categoría |
|---|---|---|
| `test_auto_av` | Construye/valida MP4 con `ffmpeg`/`ffprobe` reales | EXCLUIR — FFMPEG REAL |
| `test_h1_media_integrity` | `ffprobe` real para integridad de video | EXCLUIR — FFMPEG REAL |
| `test_h2_resume_integrity` | `ffprobe` real para reanudabilidad | EXCLUIR — FFMPEG REAL |
| `test_contrato_cutaway` | `skipif shutil.which("ffmpeg")` → 1 skip sin FFmpeg | EXCLUIR — FFMPEG REAL |
| `test_h2_job_polling_js` | Harness `job_polling_harness.cjs` con Node | EXCLUIR — NODE |
| `test_h2_ui_polling` | Harness JS (Node) — 7 skips sin Node | EXCLUIR — NODE |
| `test_h3_ui_capabilities` | Harness JS (Node) — 6 skips sin Node | EXCLUIR — NODE |
| `test_ui_auto_failed_clips` | Harness JS (Node) — 7 skips sin Node | EXCLUIR — NODE |
| `test_ui_cve_controls` | Harness JS (Node) — 7 skips sin Node | EXCLUIR — NODE |
| `test_ui_srt_controls` | Harness JS (Node) — 9 skips sin Node | EXCLUIR — NODE |
| `test_app` | Endpoints con FFmpeg/ffprobe real (fallos sin binario) | EXCLUIR — FFMPEG REAL |
| `test_auto_broll` | Depende de fetchers/entorno real (fallos) | EXCLUIR — GATE LOCAL |
| `test_auto_srt_e2e` | E2E con render FFmpeg real | EXCLUIR — FFMPEG REAL |
| `test_auto_srt_partial_resume` | Resume con render/integridad real | EXCLUIR — FFMPEG REAL |
| `test_auto_v2` | E2E Auto v2 con render real | EXCLUIR — FFMPEG REAL |
| `test_contrato_assets` | `rembg`/onnxruntime (remoción de fondo) | EXCLUIR — GPU/MODELO |
| `test_contrato_auto` | Ruta que toca render/entorno real | EXCLUIR — FFMPEG REAL |
| `test_contrato_broll_stock` / `_cutaway` / `_video_stock` / `_video_cutaway` | Import de fetchers Pexels (`requests`) — colección falla sin dep | EXCLUIR — RED |
| `test_contrato_submagic` | Cliente Submagic (`requests`) | EXCLUIR — RED |
| `test_contrato_reframe` | `cv2`/mediapipe (import a nivel de módulo) | EXCLUIR — GPU/MODELO |
| `test_h1_mounts` / `test_h1_upload` | Montan y suben con FFmpeg/ffprobe real | EXCLUIR — FFMPEG REAL |
| `test_h3_depurar` / `test_h3_media_deps` / `test_h3_models` | FFmpeg/modelos reales | EXCLUIR — FFMPEG REAL / GPU-MODELO |
| `test_nvenc_pipelines` / `_reframe_atomic` / `_submagic` | Pipelines con `cv2`/render/ffmpeg real | EXCLUIR — GPU/MODELO / FFMPEG REAL |
| `test_reframe_face_y` / `test_reframe_multi_cy` | `cv2`/mediapipe | EXCLUIR — GPU/MODELO |
| `test_studio_cve_controls` / `test_studio_packages` | API con render/ffprobe real | EXCLUIR — FFMPEG REAL |
| `test_studio_srt_api` / `_render_api` / `_transcribe_api` / `_view` | API que consulta ffprobe/duración real | EXCLUIR — FFMPEG REAL |
| `test_studio_srt_runtime` | Pasa en Windows pero falla en Ubuntu: `rechaza_symlink_fuera` depende de la semántica de symlink de la plataforma (confirmado en la 1ª ejecución de Actions) | EXCLUIR — WINDOWS |
| `test_tray_resolve` | Resolución de assets con entorno real | EXCLUIR — GATE LOCAL |
| `test_paquete_editor` | 1 skip (fixture opcional) | EXCLUIR — LOCAL (skip) |
| `test_studio_srt` | 1 skip (fixture opcional) | EXCLUIR — LOCAL (skip) |
| `test_estilos`… (incluidos) | — | (ver tabla de incluidos) |

Todos los excluidos siguen cubiertos por el **gate local completo** (`check.bat`), que corre la
suite entera con FFmpeg/modelos/Node reales en Windows.
