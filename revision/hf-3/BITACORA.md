# Bitacora de HF-3 (rama `feat/hf-3-integracion`)

Una linea por bloque, con la hora de cierre. Es lo que lee una sesion nueva sin contexto.
`<REPO>` = raiz del repositorio. `<LAB>` = raiz del laboratorio de HyperFrames (fuera del repo).

- **11:43 - BLOQUE 0 OK.** Las cinco piezas del catalogo compuestas sobre un video real 9:16
  (1080x1920 @ 30 fps, ventana de 22 s) por la ruta de clips que ya existe, con el arnes
  `<LAB>\demo_b0.py` (fuera del repo, importa Centrito en solo lectura). Salidas:
  `<LAB>\demo\00_ANTES.mp4` y `<LAB>\demo\00_ANTES_frames.png`. Las cinco piezas salieron con
  `pix_fmt=yuva444p12le` y duracion exacta. Hallazgo: `core_ass._ffmpeg_ass_path` solo escapa
  bien la ruta del `.ass` cuando es relativa al cwd; con una ruta absoluta fuera del cwd,
  FFmpeg 8.0 rompe el filtro `ass` (ver DEUDAS). El arnes escribe el `.ass` dentro del repo
  para esquivarlo, sin tocar `core_ass` (invariante I4).
- **12:05 - BLOQUE 1 OK (cableado).** `hyperframes.pedir_pieza` deja de estar huerfano.
  1.1 `clip_overlay.FIT_VALIDOS` admite `nativo` (sin escala ni crop). 1.2 `exigir_mute` es
  parametro del validador. 1.3 `ClipOverlay.posicion=(x, y)`; None conserva el centrado.
  1.4 `cve.tag_variante(..., motion=)` + `cve.TOKEN_MOTION` como grafia unica. 1.5 la carpeta
  de piezas la decide `motion_capa.raiz_cache_de_paquete`, la MISMA para las dos rutas de
  paquete. 1.6 `fade=False` y 1.7 fps del destino salen de `consumo_sugerido`. 1.8
  `motion_capa.validar_sin_solape` es error explicito en 9:16 y tolerante en 16:9.
  1.9 expuesto: casilla `auto-motion-enabled` en el Studio y `--motion` en la CLI, los dos OFF.
  Modulos nuevos `motion_capa.py` y `motion_plan.py`; el catalogo declara `proyecto` POR
  ORIENTACION (decision 1 del arranque). Con la capa apagada los filtros FFmpeg salen byte
  identicos (test) y el fingerprint de config es el historico (test).
