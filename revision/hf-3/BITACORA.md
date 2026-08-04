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
