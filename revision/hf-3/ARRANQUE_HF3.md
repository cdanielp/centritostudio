# HF-3: punto de arranque (cableado del Motor B en Auto v2 y Studio)

Escrito al cierre de HF-2 (merge `67faf75`, 2026-08-03). Este documento basta para arrancar
HF-3 en una sesion sin contexto, sin preguntarle nada a K. Leer junto con D50 y D51 (y sus
addenda) en `DECISIONES.md`.

## Que es HF-3

Cablear `hyperframes.pedir_pieza` (hoy huerfano: ningun modulo del pipeline lo importa) en la
ruta de clips de Auto v2 y en el Studio, para que los paquetes puedan llevar piezas de motion
graphics del catalogo de `motion/`. HF-4 (lo que venga despues del cableado) NO se toca.

## Decisiones YA tomadas por K (no se re-litigan)

1. **La orientacion se expresa como CAMPO en el catalogo**: `proyecto` pasa de string a mapa
   por orientacion (por ejemplo `{"vertical": "motion/hook", "horizontal":
   "motion/hook/horizontal"}`). NO se queda como convencion de ruta `+ "/horizontal"` (eso fue
   el puente de HF-2 para no tocar `hyperframes/`). NO se espera soporte upstream de lienzo
   por variables: eso obligaria a desfijar la version 0.7.90 de HyperFrames, y la clave de
   cache depende del entorno fijado. Esto implica tocar `hyperframes/catalogo.py` (y el
   validador de campos exactos), que en HF-3 YA esta permitido.
2. **Se prohibe el solapamiento temporal de piezas en 9:16.** Hoy nada lo impide:
   `core_overlays._tejer_clips` encadena overlays con ventana `enable=between(t,t0,t1)` y no
   valida interseccion; si dos ventanas se cruzan, la ultima de la cadena se pinta encima sin
   aviso (medido en D51.3: las cinco piezas comparten la franja vertical 50-70%). HF-3 lo hace
   cumplir AL PROGRAMAR las piezas, no en el render. En 16:9 las bandas son disjuntas
   (lower_third abajo-izquierda, centradas arriba) y el solapamiento es tolerable.

## Lo que HF-3 debe desbloquear (archivo y linea, verificado al cierre de HF-2)

- `clip_overlay.py:20` (`FIT_VALIDOS` solo `cover`), `:73` (mute obligatorio), `:124` (encaje
  cover), `:144` (overlay fijo centrado): son los cuatro limites que el perfil de capacidad
  (`hyperframes/capacidad.py`, `PERFIL_RUTA_CLIPS`) cita hoy como razon de rechazo de
  `posicion.modo=caja` y `fit != nativo`.
- `cve.py:302` `tag_variante` (K lo cito como 296; la linea derivo con S39-S41): toda dimension
  nueva que cambie la salida (una pieza HF en el paquete) tiene que entrar al tag de variante
  para que dos salidas distintas jamas se pisen.
- `auto.py:179` `_paquete_dir` (y su hermano v2 `_paquete_dir_v2` en `auto.py:278`): donde el
  paquete decide su carpeta y su resume; las piezas del Motor B tienen que quedar dentro del
  paquete y sobrevivir a un resume.

## La via ya prevista para la cara (no inventar otra)

El esquema del contrato YA admite `posicion.modo=caja` (D50 separo esquema y capacidad
exactamente para esto); solo el perfil v1 la rechaza. El dato de la cara vive en el CSV de
trayectoria del reframe: columna `face_y_asignada` (fraccion 0..1 del alto, por fila de tiempo
`t`, con `conf_asignada` como senal de deteccion viva), y `cve.zona_cara_en_rango(csv, t0, t1)`
ya devuelve el bucket `top/center/bottom` (cortes 0.40/0.60, fail-open a None). Cuando la caja
se desbloquee en `clip_overlay.py`, Auto calcula la posicion desde ese bucket y la plantilla NI
SE ENTERA (pregunta abierta de D51.2, resuelta en esa direccion por diseno).

## Bloqueante suave

La paleta `#FF5A2B / #111111 / #FFFFFF` de los defaults y ejemplos de `motion/` es
**PROVISIONAL**: nacio de un fixture de los tests de HF-1, no de una identidad verificada
(D51.3). K debe entregar los hex reales ANTES de HF-4. Cambiarlos es barato: defaults +
fallbacks CSS (un test fija que coincidan) + ejemplos, y las piezas ya renderizadas se
invalidan subiendo la version de plantilla (regla D51.1: el contenido del proyecto no se
hashea, la version es lo que invalida).

## Reglas vigentes que no se re-litigan

- `hf_real` a mano antes de cada merge de HyperFrames (D50.4); excluido del CI por diseno.
- Canario de influencia por cada plantilla nueva (D50.5): dos textos, sha256 distinto.
- `ruff check . --no-cache` siempre (D50.3: el cache miente con paquetes nuevos).
- Sin em dashes en ningun texto.
- Un PR por tarea; rama sin borrar tras el merge; merge commit de dos padres.
- Toda capa nueva es aditiva y default-off: sin activarla, salida byte-identica.

## Estado del que se parte

- `main` = `67faf75` (merge PR #41). Suite `2839 passed, 4 skipped`. CI de Actions verde
  (subconjunto de 54 archivos / 1524 tests, incluye los 10 de HyperFrames con dobles).
- Catalogo: 5 plantillas en `motion/` (hook 1.0.1, lower_third 1.0.2, titulo_seccion 1.0.1,
  dato_destacado 1.0.1, cierre 1.0.1), cada una con gemelo `horizontal/` que es derivacion
  pura del primario (test lo fija). Zonas y bandas medidas en la tabla de D51.
- Banda de captions medida (estilo default): vertical 80.2-89.9% del alto, horizontal
  72.5-89.9%; zona prohibida de diseno 70-92%. OJO: con `avoid_faces` o posiciones alternas
  la banda SE MUEVE (D51.1).

## Addendum de determinismo (2026-08-04, D52). Leer ANTES de tocar la cache o el resume

Dos PRs apilados, ABIERTOS y sin mergear cuando se escribio esto: **#43** (auditoria, rama
`docs/hf2-auditoria-determinismo`) y **#44** (reparacion, rama `fix/hf2-render-reproducible`,
apilada sobre la de #43). Orden de merge obligatorio: primero #43, despues #44.

Lo que cambia para HF-3:

1. **El render YA es reproducible, y eso es una precondicion que HF-3 daba por sentada sin
   que fuera cierta.** `hyperframes/invocador.py` fija ahora `WORKERS = "1"`. Antes, dos
   renders del mismo contrato daban sha256 distinto en 9 de 10 configuraciones. Sin ese
   arreglo, la pieza que HF-3 mete en el paquete y vuelve a producir tras un resume NO seria
   la misma que ya se compuso, y la propiedad "los clips no reprocesados quedan byte
   identicos" (verificada en el proyecto desde S36-C2C) no valdria para el Motor B.
   **No quites `--workers 1` para ganar velocidad: ademas de romper esto, seria mas lento**
   (el catalogo entero tarda 58.7 s con 1 worker contra 121.2 s con el reparto `auto`).

2. **Hay dos gates `hf_real` que HF-3 tiene que mantener verdes**, los dos sobre las cinco
   plantillas, en `tests/test_hf2_real.py`:
   `test_render_reproducible_por_plantilla` (mismo contrato dos veces, sha igual) y
   `test_canario_de_influencia_por_plantilla` (texto distinto, sha distinto, con su premisa
   de reproducibilidad comprobada dentro del propio test). Se corren a mano (D50.4):
   `venv\Scripts\python -m pytest tests/test_hf2_real.py -m hf_real -q`.

3. **Fisura conocida de la clave de cache, medida y NO reparada.** Editar el contenido de una
   plantilla (por ejemplo una propiedad de CSS) produce un MOV distinto y deja la clave de
   `contrato.calcular_hash` IDENTICA: un hit de cache devolveria la pieza vieja. Hoy lo tapa
   la regla D51.1 (subir la version de plantilla es lo que invalida), que depende de que
   nadie se olvide. El `compositionHash` del CLI si detecta ese cambio, pero solo se conoce
   DESPUES de lanzar el render, asi que adoptarlo obliga a un esquema de dos niveles (clave
   de contrato para buscar, `compositionHash` en el sidecar para validar el hit). Es rediseno
   del almacen, no un ajuste: **si HF-3 va a tocar la cache, esta es la decision que hay que
   tomar de paso.**

4. **Regla metodologica que hereda HF-3:** tres corridas no son evidencia de determinismo
   cuando el fallo es un evento raro por frame. `titulo_seccion` parecia determinista con dos
   corridas y fallo una de seis. Cualquier afirmacion de "sale igual" necesita un numero de
   corridas proporcional a cuantos frames rasterizan texto.

5. **Cuatro deudas no bloqueantes** siguen abiertas y documentadas en el bloque 6.2 del
   addendum de `revision/hf-2/AUDITORIA_DETERMINISMO.md`: `semilla` declarada y no consumida,
   defaults de lienzo de los gemelos horizontales apuntando a vertical, `Math.random` y
   `Date.now` en el GSAP vendorizado, y `--json` sin `--batch` que no emite nada en silencio.

Detalle completo, con comandos y salidas literales, en el ADDENDUM de
`revision/hf-2/AUDITORIA_DETERMINISMO.md` y en D52 de `DECISIONES.md`.
