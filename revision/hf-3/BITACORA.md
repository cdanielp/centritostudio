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
- **12:22 - BLOQUE 2 OK (las dos deudas de la capa).** 2.1 `semilla` sale de la clave de cache
  via `contrato.CAMPOS_FUERA_DEL_HASH`, con un test que comprueba contra las DIEZ plantillas
  reales que ninguna la consume (si algun dia una la lee, ese test truena). 2.2 los cinco
  gemelos horizontales se regeneraron: sus defaults `tamano_ancho`/`tamano_alto` declaraban
  1080x1920 dentro de un proyecto 1920x1080. La derivacion del gemelo pasa de TRES reemplazos
  a CUATRO y hay ademas un test directo que exige que el lienzo coincida en los dos sitios.
  De paso, defecto encontrado y arreglado: un kicker vacio pintaba una pastilla de color sin
  texto; `hook` sube a 1.0.2 (regla D51.1: la version es lo que invalida la cache).
  Suite `2897 passed / 4 skipped`, `ruff check . --no-cache` limpio.
- **12:35 - BLOQUE 3 OK (el planificador).** `motion_plan.py`: puro, determinista, sin IA, sin
  red, sin reloj y sin aleatoriedad. Recibe duracion, titulo del clipper, tramos del SRT,
  orientacion y el CSV de trayectoria, y devuelve piezas con sus tiempos mas las omisiones con
  su motivo. 47 tests, ninguno renderiza. Cableado en Auto v2 detras del mismo flag del bloque
  1. Dos hallazgos medidos, no inventados: (a) entre 6000 y 6700 ms el `cierre` NO cabe detras
  del `hook` con los 500 ms de aire, y como tiene menos prioridad se omite entero; (b) por
  encima de 12000 ms las tres piezas base nunca compiten entre si (barrido, no de memoria).
- **12:45 - BLOQUE 4 OK (las demos).** Tres videos en `<LAB>\demo\`, cada uno con su hoja de
  contacto de 7 frames apuntada a las piezas (una hoja a intervalos regulares se saltaba justo
  los letreros): `01_AUTO_VERTICAL.mp4` (3 piezas, por `auto_v2.procesar_clip_v2`, la misma
  funcion que `jobs.run_auto` llama por clip), `02_AUTO_HORIZONTAL.mp4` (4 piezas, por
  `jobs_render.run_render`, el worker del Studio) y `03_SIN_CAPA.mp4` (el mismo clip con la
  capa apagada). Cache borrada antes de renderizar (trampa T6). **INVARIANTE I1 PROBADO**:
  `<LAB>\smoke_i1.py` renderiza el mismo video con el arbol en `main` y con esta rama y la capa
  apagada, y los dos MP4 dan el MISMO sha256 (`a661ceb7...`, 133593964 bytes). Se prueba por la
  ruta de render y NO por Auto: Auto llama al brain (DeepSeek) por clip y un LLM devuelve
  keywords distintas entre corridas, asi que por ahi dos renders del mismo clip no son byte
  identicos ni antes ni despues de HF-3. Hallazgo de integracion cerrado en el camino: Auto v2
  no le pedia `tray_dir` al reframe, o sea que el CSV de la cara no existia nunca y la capa
  habria omitido TODAS las piezas en 9:16 sin que nada fallara. Ahora se pide, y solo con la
  capa encendida. Ademas se expuso la capa en el worker de render y en la pestana de render del
  Studio, que es lo que hace posible la demo horizontal.
- **12:52 - BLOQUE 5 OK (paletas).** Una sola hoja, : las CINCO
  piezas (filas: hook, lower_third, titulo_seccion, dato_destacado, cierre) en las TRES paletas
  (columnas), compuestas sobre un fotograma real del video de K. A = el naranja actual
  ; B = sobria de alto contraste , la que menos compite con el amarillo y el
  verde de los captions hormozi; C = , el morado que la interfaz del Studio YA usa,
  sobre su mismo fondo , para que el letrero del video y la app sean el mismo color y
  no dos morados parecidos. NINGUNA se ha implementado: K elige. Aplicarla es cambiar
  , los fallbacks CSS de  y subir la version de cada
  plantilla. Gotcha del arnes: componer la pieza con  de ENTRADA sobre un PNG fijo daba
  fotogramas en blanco de forma erratica (el still tiene un solo frame y el overlay se quedaba
  sin base al rebasar el MOV); se extrae el fotograma de la pieza con seek de SALIDA y luego se
  componen dos imagenes fijas.
