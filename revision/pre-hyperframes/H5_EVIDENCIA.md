# H5 — Evidencia del gate remoto ligero (pre-HyperFrames)

Sin logs completos, sin variables de entorno, sin URLs con tokens.

## Base

- Rama base `main` en `3cbac46922f85c452b65ee8e6bd81b1f4efa3b24` (merge PR #29, cierre H4).
- Rama de trabajo: `ci/h5-quality-gate`. PR único, **abierto y NO mergeado**.
- Sin cambios de producción ni audiovisuales. HyperFrames/F7 no iniciado.

## Workflow

- Archivo: `.github/workflows/quality.yml` · nombre visible **Quality Gate**.
- Runner: `ubuntu-latest` · un solo job `quality`.
- **Triggers:** `pull_request`, `push` (solo rama `main`), `workflow_dispatch`. Sin
  `pull_request_target`, sin `schedule`.
- **Permisos:** `contents: read` (solo lectura). Sin secrets, sin escritura, sin deploys/uploads.
- `concurrency` con `cancel-in-progress: true` · `timeout-minutes: 15`.
- Env: `PIP_DISABLE_PIP_VERSION_CHECK=1`, `PYTHONIOENCODING=utf-8`, `PYTHONDONTWRITEBYTECODE=1`.
- **Sin cache.** Solo acciones oficiales: `actions/checkout@v6`, `actions/setup-python@v6`.
- Python **3.12**.

### Pasos (en orden)

1. Checkout · 2. Setup Python 3.12 · 3. `pip install -r requirements-ci.txt` ·
4. `python -m ruff check .` · 5. `python -m ruff format --check .` ·
6. `smoke_h4_docs.py --self-test` · 7. `smoke_h4_docs.py --real` ·
8. `smoke_h5_ci.py --self-test` · 9. `smoke_h5_ci.py --real` · 10. `python ci/run_pytest_light.py`.

No instala `requirements.txt`, no ejecuta `check.bat`, ni pytest completo, ni FFmpeg/GPU/modelos/Node,
ni `curl`/`wget`, ni `continue-on-error`.

## Dependencias CI

`requirements-ci.txt` (versiones fijadas, verificadas en venv 3.12 limpio): `ruff`, `pytest`,
`pytest-socket`, `PyYAML`, `pysubs2`, `fastapi`, `httpx`, `python-multipart`.

**Excluidas a propósito** (viven solo en el gate local): `faster-whisper`, `mediapipe`, `rembg`,
`onnxruntime`, `edge-tts`, `openai`, `torch`, `ctranslate2`, `uvicorn`, `cv2/opencv`, CUDA y modelos.
`fastapi`/`httpx`/`python-multipart` justificadas: `test_h1_path_traversal` importa `app` y usa
`TestClient`; sin ellas `import app`/`TestClient` fallan (verificado quitándolas).

## Matriz y subconjunto de tests

- Detalle y clasificación empírica: `H5_TEST_MATRIX.md`.
- Manifiesto explícito `ci/pytest-light.txt` (una ruta por línea, orden determinista, sin globs).
- Runner `ci/run_pytest_light.py`: rechaza manifiesto ausente/vacío, duplicados, rutas fuera de
  `tests/` (incl. `..`) y tests inexistentes; ejecuta `python -m pytest -q --disable-socket` con el
  **mismo intérprete**, **sin `shell=True`**, propaga exit code e imprime `archivos-seleccionados=N`.
- Plugin `ci/_pytest_light_plugin.py`: cualquier skip/xfail/xpass pone el gate en ROJO (invariante
  de cero-skips). Verificado: al apuntar a un archivo con `skip` el runner sale con código 1.
- **44 archivos · 1302 tests · 0 skips** en el subconjunto.
- La primera ejecución en Actions detectó `test_studio_srt_runtime` como no portable (falla en
  Ubuntu por semántica de symlink); se excluyó del manifiesto (sin tocar producción) y la
  siguiente ejecución quedó verde. Es exactamente el valor de correr el gate en Linux real.

## Bloqueo de red

`pytest-socket` (`--disable-socket`) en el runner. El subconjunto corre verde con sockets
bloqueados, lo que demuestra que ningún test incluido abre red (incluidas las pruebas con
`TestClient`, que usan transporte ASGI en proceso).

## Smokes

- `smoke_h5_ci.py --self-test`: **36/36** VERDE. Cubre las 23 condiciones prohibidas del §6
  (workflow ausente, `pull_request_target`, permisos write, `secrets.*`, acción no permitida,
  versión de acción no admitida, Python ≠ 3.12, sin timeout, sin concurrency, `continue-on-error`,
  `curl/wget`, pytest completo, `check.bat`, `requirements.txt`, cache, manifiesto ausente, entrada
  duplicada, test inexistente, ruta fuera de `tests/`, dep pesada, sin `pytest-socket`, runner con
  `shell=True`, H5/HyperFrames cerrados indebidamente) + negativos.
- `smoke_h5_ci.py --real`: **16 checks, 0 fails** VERDE.
- `smoke_h4_docs.py` actualizado al nuevo estado (H4 cerrado en main `3cbac46`, H5 en curso,
  HyperFrames no iniciado): `--self-test` **28/28**, `--real` **1083 checks, 0 fails** VERDE.

## Venv limpio (portabilidad)

Venv temporal Python 3.12 **fuera del árbol versionado**, con **solo** `requirements-ci.txt`
instalado. Los 7 comandos del gate corren en verde, con **cero skips** en el subconjunto, **cero
acceso a red**, ningún paquete pesado instalado y ningún archivo generado dentro del repo. El venv
se elimina al terminar.

## Ejecución real de GitHub Actions

- PR **#30** `ci: añadir quality gate remoto ligero` (abierto, NO mergeado).
- 1ª ejecución (HEAD `9609a86`): **failure** — solo `test_studio_srt_runtime` falló en Ubuntu por
  symlink; se excluyó del manifiesto (sin tocar producción).
- **Runs verdes previos** (workflow **Quality Gate**, evento `pull_request`, `conclusion=success`,
  14 pasos verdes): `3f1239d` (run 29880434212), `ba2bb83` (run 29880490796),
  `64cf6b0` (run 29880890712, fix de Codex), **`51e5c98` (run 29881420932)**.
- El run del **HEAD final** (commit de normalización de evidencia) queda registrado en el body del
  PR #30 con su run ID y `conclusion=success` una vez completado.

## Review de Codex

- **Ronda 1** (sobre `ba2bb83`): 1 hallazgo **P2** — el smoke aceptaba `permissions: read-all`
  aunque el contrato exige exactamente `contents: read`. **Corregido en `64cf6b0`**
  (`violaciones_workflow_estructura` exige el mapping exacto; +3 self-tests).
- **Ronda 2** solicitada: **sin hallazgos**.
- Hilos de review: **total=1, resolved=1, unresolved=0** — el único hilo quedó **formalmente
  resuelto** en GitHub (respondido + marcado como resolved). No se solicita una tercera ronda.

## Gate local (autoritativo) y limitaciones del CI

- El gate autoritativo sigue siendo **`check.bat`** / `check.bat full` en Windows 11 (entorno real,
  FFmpeg/ffprobe, modelos, suite completa `2410 passed / 4 skipped`, smoke render GPU sintético).
- El gate remoto **NO** valida: render, codificación, CUDA, NVENC, FFmpeg real, modelos, Node, red
  ni experiencia visual. Solo cubre lo portable y determinista.

## Fuera de alcance

- HyperFrames/F7 no iniciado. Gate final pendiente.
- Cero cambios de producción; cero cambios audiovisuales; sin refactor para forzar el verde del CI.
