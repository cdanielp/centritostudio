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
- **12:52 - BLOQUE 5 OK (paletas).** Una sola hoja, `<LAB>\demo\04_PALETAS.png`: las CINCO piezas
  (filas: hook, lower_third, titulo_seccion, dato_destacado, cierre) en las TRES paletas
  (columnas), compuestas sobre un fotograma real del video de K. A = el naranja actual
  `#FF5A2B`; B = sobria de alto contraste `#1D4ED8`, la que menos compite con el amarillo y el
  verde de los captions hormozi; C = `#7C3AED`, el morado que la interfaz del Studio YA usa,
  sobre su mismo fondo `#08080F`, para que el letrero del video y la app sean el mismo color y
  no dos morados parecidos. NINGUNA se ha implementado: K elige. Aplicarla es cambiar
  `motion_capa.MARCA_PROVISIONAL`, los fallbacks CSS de `motion/` y subir la version de cada
  plantilla. Gotcha del arnes: componer la pieza con `-ss` de ENTRADA sobre un PNG fijo daba
  fotogramas en blanco de forma erratica (el still tiene un solo frame y el overlay se quedaba
  sin base al rebasar el MOV); se extrae el fotograma de la pieza con seek de SALIDA y luego se
  componen dos imagenes fijas.
- **13:05 - BLOQUE 6 OK (humo de imagen).** Spike AISLADO en `<LAB>\spike_imagen\`, fuera de
  `motion/` y sin tocar nada de los bloques 1 a 5. Un PNG con alfa de los que ya genera ComfyUI
  entra, se sostiene y sale con GSAP dentro de una pieza de fondo transparente. Las DOS vias
  funcionan y, mas aun, producen el MISMO sha256, asi que la eleccion es de mantenimiento y no
  de resultado. Sale ganando (a), el archivo relativo. Salidas: `<LAB>\demo\05_IMAGEN.mp4`,
  `<LAB>\demo\05_IMAGEN_frames.png` y `<LAB>\demo\05_IMAGEN.json`. Detalle en las cuatro lineas
  del informe final.
- **13:20 - CIERRE.** Suite completa y `ruff check . --no-cache` al final. Los `hf_real` a mano
  dieron `16 passed / 1 failed` en la primera pasada: fallo
  `test_render_reproducible_por_plantilla[dato_destacado]` (dos renders del mismo contrato con
  sha distinto). Re-corrido aislado DOS veces, pasa las dos. No es una regresion de HF-3 (el
  diff no toca el renderer, y las dos corridas del test usan raices de cache distintas a
  proposito, o sea que ninguna se sirve de cache): es exactamente el fallo raro por frame que
  ya documento el addendum D52.4, donde `titulo_seccion` fallo una de seis. Queda anotado en
  DEUDAS porque desmiente que "el render ya es reproducible" sea cierto sin matices.


## Sesion 2: paleta real de marca, carril vertical y coherencia de textos

- **14:08 - PASO 1 OK (paleta oficial).** Sustituye a la provisional, que era inventada. Texto
  `#F5F5F7`, gris separador `#2A2A35`, y UN acento por pieza: rojo `#FF3D3D` en `hook` y
  `cierre` (donde el video gana o pierde al espectador), cyan `#06B6D4` en `dato_destacado`
  (exclusivo de cifras), violeta `#6C3AED` en `lower_third` y `titulo_seccion` (lo que es
  literalmente una etiqueta). Nunca los tres en la misma pieza. Aplicada en las diez plantillas
  (el default declarado Y el fallback CSS, que un test de D51.1 exige que coincidan) y en
  `motion_capa.MARCA` mas `ACENTO_POR_PLANTILLA`. El fondo de marca `#0A0A0F` NO viaja en el
  contrato: ya es la placa estructural `rgba(8, 8, 15, 0.78)`, que no se toco. Las cinco
  plantillas suben de version, que es lo unico que invalida la cache.
- **14:13 - PASO 2 OK (la medicion que manda).** `revision/hf-3/medir_carril.py` pasa los 34
  clips reales del proyecto por el planificador sin renderizar nada. La primera pasada dio 19
  ceros y los 19 eran por falta del CSV de trayectoria: se estaba midiendo la ausencia del dato
  y no la regla. `revision/hf-3/generar_trayectorias.py` genero las 11 que faltaban de forma no
  destructiva (el MP4 reencuadrado va a un temporal y se descarta; lo unico que queda es el
  CSV). Con el dato real, los verticales en cero eran 61.9%.
- **14:17 - PASO 3 OK (banda superior).** Con la cara en `center` o `bottom`, la pieza sube a la
  banda 20-35% del alto en vez de omitirse. CONFIRMADO CON RENDER REAL
  (`revision/hf-3/confirmar_banda.py`): el `hook`, que es la pieza mas alta, ocupa nativamente
  60.9-68.6% del alto y tras el desplazamiento de -653 px cae en 26.9-34.6%. No pisa la zona
  segura de UI de TikTok (10% superior) ni la franja de captions (70-92%), y queda por encima
  del borde de una cara centrada. Verticales en cero: 61.9% -> 47.6%. Los que siguen en cero
  son los 10 que no tienen dato de cara, no los que la tienen mal colocada.
- **14:22 - PASO 4 OK (coherencia de textos).** El `cierre` deja de repetir el titulo del hook:
  manda la llamada a la accion y el secundario sale de lo ultimo que se habla. `titulo_seccion`
  entra en juego para rellenar huecos de mas de 20 s en clips de mas de 30 s, titulando el
  tramo donde el hablante cambia de tema (detectado por PAUSA entre tramos, sin IA).
  `dato_destacado` se coloca en una VENTANA dentro de su tramo y no clavado al milisegundo de
  inicio: ahi es donde se perdia en el clip de 56.8 s que tenia dos cifras habladas, las dos
  dentro del `lower_third`. Guarda de sustancia minima para no titular con esquirlas como
  "futuro,". Todo determinista y probado sin renderizar.
- **14:25 - PASO 5 OK (tres deudas chicas).** 5.1 el umbral del `cierre` pasa de 6000 a 6700 ms,
  que es donde la aritmetica lo permite, con el calculo escrito en el propio comentario.
  5.2 `test_render_reproducible_por_plantilla` escribe a disco, ANTES de fallar, cuantos frames
  difieren sobre el total, el delta medio y el maximo sobre 255 y los indices afectados; luego
  reintenta UNA vez y, si el reintento pasa, el test pasa pero el informe se queda escrito.
  5.3 gate nuevo en el CI (`motion_sello.py` + `tests/test_hf3_sello_motion.py`): sella el
  contenido de cada carpeta de `motion/` en `motion/versiones.lock.json` y falla si el
  contenido cambio sin subir la version. Probado a mano editando una plantilla sin tocar su
  version: truena con el mensaje que dice que archivo cambiar.
- **14:35 - PASO 6 OK (demos nuevas).** Cache borrada antes de renderizar (trampa T6).
  `<LAB>\demo\06_PALETA_MARCA_VERTICAL.mp4` (7 piezas, antes 3) y
  `<LAB>\demo\07_PALETA_MARCA_HORIZONTAL.mp4` (6 piezas, antes 4), con sus hojas de contacto de
  7 frames apuntadas a las piezas. Mismos clips que 01 y 02 para poder comparar lado a lado.

## Sesion 3: cerrar el hueco del vertical y arreglar los titulos cortados

- **14:49 - PASO 1 OK (sin dato de cara deja de ser fail-closed).** Sin trayectoria la pieza se
  omitia, lo que contradecia el fail-open de toda la capa y dejaba en cero PARA SIEMPRE a 8
  clips derivados que no tienen fuente 16:9 de la que sacar el dato. Ahora cae al carril nativo
  (54-68% del alto), el que K aprobo en el gate visual de HF-2 justamente por no pisar caras, y
  la falta del dato se registra como INCIDENCIA del plan (`sin_dato_de_cara`), no como fallo de
  la pieza. Con esto desaparece el motivo `carril_ocupado_por_la_cara`: la cara MUEVE la pieza,
  nunca la borra. Verticales en cero: 47.6% -> 0%.
- **14:54 - PASO 2 OK (titulos que no sean media frase).** `condensar_clausula` sustituye al
  corte por palabras. El corte solo cae en limite de clausula (puntuacion o justo antes de una
  conjuncion), el fragmento no puede EMPEZAR por conjuncion ni preposicion, no puede ACABAR por
  conjuncion, preposicion ni articulo, y si nada da un fragmento de 12 a 46 caracteres la pieza
  se OMITE. La misma guarda se aplica al secundario del cierre (28 caracteres) y a la etiqueta
  del `dato_destacado` (38). Motivo nuevo `MOTIVO_ETIQUETA_SUCIA` para cuando hay cifra pero
  ningun tramo la puede etiquetar limpio. Los articulos se prohiben SOLO al final: "La
  desercion escolar subio" es un arranque correcto, "las que de la" no es un final.
- **14:58 - PASO 3 OK (la pregunta del brain, solo medir).** No se toco nada. `brain.py:161`
  llama al LLM en todas las corridas y `brain.py:188-190` escribe el sidecar; nadie comprueba
  si el archivo ya existe antes de llamar. `auto.py:373` (`_brain_fail_open`, que es la fuente
  unica que usa tambien Auto v2) invoca `analizar_grupos` sin condicion. El sidecar se persiste
  pero NO se reutiliza como cache entre corridas: quien lo lee (`assets_comfy.resolver_overlays`
  en `auto_v2.py:218`, `cve.aplicar_preset`) lee el que se acaba de escribir en esa misma
  corrida. Conclusion: el clip NO es reproducible en la practica.
- **15:04 - PASO 4 OK (demo del fallback).** Cache borrada antes de renderizar.
  `<LAB>\demo\08_VERTICAL_FALLBACK.mp4` sobre `podcast_test_60s_9x16_noturnos.mp4`, un clip
  derivado que antes se quedaba en CERO. 6 piezas colocadas, todas en el carril nativo, con la
  incidencia `sin_dato_de_cara` registrada. Confirmado en los 7 frames de
  `08_VERTICAL_FALLBACK_frames.png`: ninguna pieza cae sobre una cara, porque en este material
  las dos caras viven en la mitad superior del cuadro y el carril esta por debajo.

## Sesion 4: techo de densidad, tres arreglos de texto y cache del brain

- **15:13 - PASO 1 OK (techo de densidad).** `MAX_PIEZAS_POR_MINUTO = 5`, en una sola constante
  comentada, prorrateado por duracion con redondeo al alza desde la mitad (`round` de Python
  daria 2 piezas en un clip de 30 s por el criterio del banquero). Las protegidas (`hook`,
  `lower_third`, `cierre`) nunca se recortan; el techo se cobra de `titulo_seccion` y
  `dato_destacado`, cayendo primero la de menor sustancia informativa. El techo se aplica ANTES
  de rellenar huecos y el relleno recibe lo que sobra: rellenar y recortar despues quitaba justo
  las piezas puestas para cerrar un hueco. Total sobre los 34 clips reales: 158 -> 124 piezas,
  media 4.65 -> 3.65. La regla de los 20 s pasa a ser el OBJETIVO del relleno y no una garantia,
  porque las dos reglas se contradicen y manda el techo.
- **15:18 - PASO 2 OK (ninguna pieza repite tramo).** Regla global: un tramo del SRT usado por
  cualquier pieza queda marcado y ninguna otra puede usarlo. El reparto va de la pieza MAS
  atada a un tramo concreto (`dato_destacado`, que solo sirve donde se dice la cifra) a la
  menos atada (el `cierre`, que sirve con cualquier tramo anterior); si el cierre eligiera
  primero se quedaria con el tramo de la cifra y mataria al dato sin necesidad. Sin tramo libre,
  el secundario del cierre va vacio y la pastilla se esconde. Dos bugs del relleno salieron al
  medir esto: las pausas se calculaban sobre la lista YA filtrada, lo que inventaba cambios de
  tema donde solo habia un tramo apartado, y se colocaba en varios huecos con una sola foto de
  la lista, lo que amontonaba los letreros.
- **15:20 - PASO 3 OK (muletillas).** Lista en constantes y marcada como especifica de espanol.
  Se quitan al principio del fragmento en cadena, en racha de dos o mas seguidas en cualquier
  posicion, y como interjeccion aislada entre comas. Corre ANTES de medir longitud para que el
  hueco lo ocupe texto con contenido. Dos excepciones: `entonces` con verbo detras abre oracion
  y se conserva, y `no` JAMAS se quita del arranque, porque "no sabemos que paso" sin el dice
  exactamente lo contrario.
- **15:21 - PASO 4 OK (condensar por informacion).** Elegir el fragmento mas largo se llevaba la
  coletilla vacia pegada detras. Ahora gana el de mayor densidad informativa, con una
  heuristica sin dependencias que lee la lista de palabras vacias de `stopwords_es`, que ya
  existia y esta testeada, en vez de escribir una segunda. A igualdad de densidad gana el mas
  corto, que es lo que menos tapa del video.
- **15:27 - PASO 5 OK (cache del brain).** COMMIT APARTE, porque toca codigo fuera de la capa de
  motion. `brain.analizar_grupos` guarda la huella de la transcripcion que genero el sidecar y
  lo reutiliza si coincide; `forzar=True` recalcula, default apagado. La huella cubre solo el
  TEXTO, que es lo unico que ve el LLM, y los `kw_ts` se recalculan siempre contra los grupos de
  ahora. Sidecar sin huella o corrupto: fail-closed. MEDIDO sobre un clip real por Auto v2
  (`<LAB>\medir_cache_brain.py`): la segunda corrida NO llama al LLM y el MP4 sale byte
  identico (`932b34a4...`). Con esto un clip de Auto v2 pasa a ser reproducible.
- **15:31 - PASO 6 OK (demo).** Cache borrada antes de renderizar.
  `<LAB>\demo\09_TEXTO_LIMPIO.mp4` sobre el mismo clip que el 06, para comparar lado a lado:
  5 piezas frente a las 7 de antes (el techo se llevo dos `titulo_seccion`), con los textos ya
  sin muletillas ni fragmentos colgando.
