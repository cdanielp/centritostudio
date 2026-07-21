# H1 — Evidencia de cierre (seguridad e integridad pre-HyperFrames)

**Base:** `9d87cc7` (merge PR #24). **Rama:** `fix/h1-seguridad-integridad`. **PR abierto, NO mergeado.**
**Alcance:** P0-1, P0-2, P0-3, P0-4, P1-OUT-1, P1-OUT-2. **NO** H2/H3/HyperFrames.

Todas las pruebas usan `TemporaryDirectory`/fixtures sintéticos, sin GPU/red y sin tocar
`input/0717_corregido.srt` (nunca se abre, imprime, hashea ni versiona).

---

## P0 cerrados

### P0-1 · Path traversal en endpoints `{name}` — CERRADO
- **Fuente única:** `path_safety.is_safe_basename` (extraído de `studio_srt_manifest`, que ahora lo
  reexporta; sin duplicar). Endurecido: además de separadores/control, rechaza `.`/`..` y los
  nombres con **punto/espacio final** (que Windows recorta y colisionan). Acepta letras, números,
  espacios internos, guion, underscore y Unicode acentuado.
- **Guard:** `app._validar_name(name)` → 404 saneado (no refleja `name`) al inicio de cada endpoint
  crudo, antes de construir ningún `Path`: transcribe, transcript get/put, analyze, brain get/put,
  depurar, clips get/post, render, auto, submagic, detectar, turnos, reframe.
- **Tests:** `tests/test_h1_path_traversal.py` — matriz `..\`, `../`, `/x`, `C:\x`, UNC, `.`, `..`,
  NUL/control, trailing `.`/espacio × 15 endpoints (read+write) → 404, sin job, sin escape; centinela
  fuera del sandbox nunca se crea; `test_write_traversal_no_escribe_fuera`.

### P0-2 · Upload inseguro — CERRADO
- `upload_video` (`app.py`): exige `filename`, basename seguro, extensión `.mp4/.mov`
  (case-insensitive); tope de bytes `CENTRITO_MAX_VIDEO_BYTES` (default 20 GiB; valor inválido →
  default + warning, sin tumbar); rechazo temprano por `Content-Length` **y** tope duro por chunks
  aunque falte/mienta; temporal único en `input/.uploads/` con la extensión final; validación
  `media_integrity.verificar_video` (ffprobe) → 422 si no es multimedia; `os.replace` atómico solo
  tras validar; limpieza del temporal ante cualquier error; nunca escribe el destino final durante
  la carga ni borra el final anterior si la nueva falla.
- **Status:** filename inválido 400 · extensión inválida 400 · demasiado grande 413 · no-multimedia
  422 · error interno 500 saneado.
- **Tests:** `tests/test_h1_upload.py` — traversal (no escapa), extensión, mayúsculas válidas,
  vacío, oversize (Content-Length) 413, límite inválido → default, tope por chunks sin
  Content-Length, no-multimedia 422, excepción en publicación 500 saneado, reemplazo exitoso,
  reemplazo fallido preserva original, cero temporales residuales.

### P0-3 · Texto privado servido por `/output` — CERRADO
- `_OutputMedia` (allowlist `.mp4`) reemplaza a `_OutputSinPaquetes`: `.ass`/`.json`/`.srt`/sidecars
  → 404; el subárbol `paquetes/` sigue bloqueado (servido solo por el router validado). El
  `.ass`/`.keyword_selection.json` no cambian de ubicación (no hay cambio de render): dejan de ser
  **servibles** por HTTP.
- **Tests:** `tests/test_h1_mounts.py::test_output_solo_mp4`,
  `tests/test_studio_packages.py::test_mount_output_allowlist_y_confina_paquetes`; smoke
  `output_no_expone_texto=PASS`.

### P0-4 · Exposición LAN sin auth — CERRADO
- **Bind loopback:** `app.LISTEN_HOST="127.0.0.1"` en `__main__` y `arranque.bat --host 127.0.0.1`.
  Sin modo LAN, sin token/auth (diferido a una fase dedicada). No queda `0.0.0.0` de producción.
- **Mount `/input` ELIMINADO** → binario fuente servido por `GET /api/videos/{name}/source`
  (basename seguro + confinado en `INPUT_DIR` vía `resolver_video_input` + `FileResponse` con Range).
- **`/thumbs`** (`_ThumbsMedia`, imágenes) y **`/clips`** (`_ClipsMedia`, `.mp4`) por allowlist
  estricta; sidecars privados (`.ass`/`.json`) → 404. Confinamiento `resolve()+relative_to` bloquea
  symlink que escapa.
- **Tests:** `tests/test_h1_bind_localhost.py` (host loopback en app y arranque, sin `0.0.0.0`);
  `tests/test_h1_mounts.py` (thumbs/clips allowlist, `/input` eliminado 404, symlink rechazado,
  endpoint `/source` sirve mp4/mov y rechaza traversal); smoke `mounts_no_expuestos_lan=PASS`.

## P1 cerrados

### P1-OUT-1 · Outputs sin validar (size/ffprobe/duración) — CERRADO
### P1-OUT-2 · FFmpeg escribe directo al nombre final — CERRADO
- `media_integrity.publicar_mp4_atomico(final, quemar)`: quema a `*.part-<uuid>.mp4` en la misma
  carpeta → `verificar_video` (archivo regular, size>0, ffprobe OK, ≥1 stream de video, duración
  finita>0; **audio NO exigido** porque el pipeline admite fuentes sin audio y `-c:a copy`) →
  `os.replace`. Ante cualquier fallo: borra el temporal, conserva el final anterior, lanza excepción
  tipada (`MediaIntegrityError`/`RuntimeError`), sin dejar temporales.
- Aplicado **internamente** a `core_ass.burn_video` y `core_ass.burn_video_with_emojis` → todos los
  callers (jobs_render, Auto classic/v2, CLI `caption.py`) heredan la publicación atómica sin cambio
  de firma.
- **Tests:** `tests/test_h1_media_integrity.py` — returncode≠0, excepción, temp inexistente, temp
  0-byte, ffprobe inválido, duración 0/NaN/Inf/ausente, sin stream de video, output válido,
  preserva final anterior al fallar, reemplaza al éxito, temporal único, cero residuales, e
  integración: el worker de render deja el job en `error` (no `done`) con mensaje saneado.

## Writers FFmpeg endurecidos vs diferidos
- **Endurecidos (H1):** `burn_video`, `burn_video_with_emojis` (render de captions).
- **Diferidos (documentados, NO atómicos aún):** `clipper.py`, `reframe*.py`, `depurador.py`,
  `broll_video_stock_base.py`, `submagic.py`, `auto_av.py`. Ver `H1_INVENTARIO.md §4`. **No** se
  afirma que todos los MP4 del producto sean atómicos.

## Smoke
- `smoke_pre_hyperframes.py --self-test` → **VERDE (20/20)**.
- `smoke_pre_hyperframes.py` → `checks=12 blockers=0 fails=0`, `aislamiento_datos_reales=PASS`,
  `sin_centinelas_residuales=PASS`, **exit 0**.
- Adaptaciones legítimas del arnés (contrato seguro, no ocultan P0): `_rebuild_mounts` preserva la
  subclase real del mount; `probe_lan_exposure` verifica el nuevo contrato (`/input` eliminado +
  allowlist en thumbs/clips) en vez de asumir "cualquier serve = BLOCKER". Los mensajes SKIP de
  cobertura y E2E se actualizaron a la realidad post-H1.

## Suite / calidad
- `pytest` → **2173 passed, 4 skipped** (baseline 1894/3; incluye correcciones P2 post-review). El +1 skip vs baseline es el test de symlink en
  `test_h1_mounts.py`, que usa **el mismo patrón de skip conocido** que `test_paquete_editor.py:206`,
  `test_studio_packages.py:60` y `test_studio_srt.py:83` (Windows sin privilegio de symlink),
  sancionado por el alcance de la Fase 6.F. Ningún test verde depende de que el código siga vulnerable.
- `ruff check .` limpio · `ruff format --check .` limpio · `git diff --check` limpio · `check.bat`
  → `===== TODO OK =====`.

## Riesgos restantes / fuera de alcance
- P1-OUT-3 (resume acepta 0-byte), P1-POLL-1..4 (spinner infinito), atomicidad de estado → **H2**.
- Preflight FFmpeg/modelos, guards de arranque → **H3**. Docs (ESTADO/DECISIONES/PREGUNTAS/ALPHA) →
  **H4**. CI ligero → **H5**. Writers FFmpeg diferidos (§ arriba) → H2/posterior.
- **No** se añadió autenticación/LAN (diferido por diseño). **No** se cambió apariencia ni salida
  audiovisual: no aplica gate visual de K; sí verificación funcional de que previews/clips/fuente
  se reproducen (endpoint `/source` + mounts allowlist).

## Correcciones post-review (Codex, 2 P2 del PR #25)

### P2-1 · Validar también el STEM del upload — CERRADO
- `upload_video` valida ahora `Path(filename).stem` con el **mismo** `path_safety.is_safe_basename`
  (helper `_validar_filename_upload`), **antes** de escribir ningún temporal. Un filename como
  `clip .mp4`/`clip..mp4` (stem `clip `/`clip.`) se rechaza con **400** en vez de aceptar un video
  cuyo `name` el resto de endpoints (`/source`, `/transcript`) rechazaría → carga inusable. No se
  recorta ni normaliza; el `name` devuelto es exactamente ese stem ya validado.
- **Tests:** `tests/test_h1_upload.py` — stems inseguros (`clip .mp4`, `clip..mp4`, `clip...mp4`,
  `.mp4`, ` .mp4`, trailing punto/espacio) → 400 sin archivo final, sin `.uploads/` residual, sin
  ffprobe, sin info/thumbnail; controles válidos (`mi clip.mp4`, `vídeo_final.MP4`, `clase-01.mov`)
  → 200 y el stem sirve de inmediato en `/api/videos/{stem}/source` y pasa el guard de `/transcript`.

### P2-2 · Temporales de render fuera de los outputs públicos — CERRADO
- `media_integrity.ruta_temporal` escribe ahora en `<dir_final>/.render_tmp/<uuid>.mp4` (subdir
  privado reservado, **mismo volumen** → `os.replace` sigue atómico; sin el stem del usuario en el
  nombre). Un temporal en curso o abandonado tras un **hard-kill** ya no es un `/output/*.mp4`.
- **`_OutputMedia`/`_AllowlistStatic`** rechaza además, por nombre pedido **y** por ruta REAL
  resuelta, cualquier segmento oculto (`.`) o reservado (`.part-`): bloquea `/output/.render_tmp/…`,
  `/output/*.part-*.mp4` y un symlink servible que apunte a un temporal interno.
- **`/api/videos`** filtra defensivamente los globs de outputs/clips (ignora `.render_tmp` y
  `.part-`): un temporal abandonado **no** marca `renderizado` ni se lista como output descargable.
- **No** se añadió recolección automática de temporales abandonados en el arranque (política de GC
  documentada para H2/H3 si se decide necesaria).
- **Tests:** `tests/test_h1_mounts.py` — `/output/.render_tmp/x.mp4`→404, `/output/x.part-*.mp4`→404,
  symlink→temporal interno→404 (misma guarda de skip conocida), `/api/videos` ignora temporal
  abandonado (status `sin_transcribir`, `outputs=[]`) y `.part-` suelto, render real sí aparece;
  `tests/test_h1_media_integrity.py` — `ruta_temporal` en `.render_tmp` sin stem, atomicidad y cero
  residuales adaptados al subdir privado.
- **Sin cambio de salida audiovisual:** solo cambia la ubicación del temporal y el momento de
  publicación; el MP4 final es byte-idéntico.

Suite tras P2: **2173 passed, 4 skipped** (4 skips = misma limitación de symlink en Windows; el
test de symlink de `.render_tmp` se pliega al test de symlink existente para no añadir skips).
ruff/format/diff-check/`check.bat` verdes; smoke self-test 20/20 y `blockers=0 fails=0`.

## H2 / H3 / HyperFrames
**No iniciados.**
