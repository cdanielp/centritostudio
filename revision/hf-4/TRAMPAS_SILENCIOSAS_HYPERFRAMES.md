# Trampas silenciosas del Motor B (HyperFrames) — catálogo

**Qué es esto.** El patrón que rompió `feat/hf4-formato-dual` (hook y cierre invisibles en 9:16,
`returncode 0`, sello declarando 3 piezas y el MP4 final mostrando 1) no es nuevo: HF-1 a HF-4b
encontraron variantes de la misma familia de fallo — "el render dice éxito pero la pieza no dice
lo que debía decir" — y cada una se documentó por separado en su propio addendum de
`DECISIONES.md`. Este archivo es la primera vez que se compilan en una sola lista.

**Nota de honestidad (regla del proyecto: no maquillar).** No existía antes un catálogo numerado
de "trampas silenciosas" en el repo. Contando con cita todo lo que hay documentado con este
patrón exacto (`returncode 0` / éxito aparente que esconde un defecto), el conteo da **6
incidentes previos + este = 7**. Si el número real esperado era otro (una discusión no
documentada en los `.md` del repo), corregir aquí.

## Catálogo

1. **Variables anidadas nunca llegaban a la plantilla** (D50.1, `DECISIONES.md:2092-2098`).
   `titulo` no recibía su valor, la pieza pintaba `SIN-VARIABLE-titulo`, y el render devolvía
   `returncode 0` con `pix_fmt`, fps, tamaño y duración correctos. Solo se detectó extrayendo
   un frame y mirándolo.

2. **Dirección real de la colisión de claves reservadas** (D50.5, `DECISIONES.md:2179-2183`).
   Un slot de texto llamado igual que una clave de sistema (p. ej. `fps`) no corrompe la clave
   del sistema: **desaparece**, y la plantilla pinta el valor de sistema (`30`) donde esperaba
   una frase. Mismo efecto (`returncode 0`) que #1, sentido contrario al que se había asumido
   al escribir la guarda original.

3. **Layout fijo por defecto en 1080x1920** (D51/HF-2, `DECISIONES.md:2251-2254`). Sin
   `data-width/height` estáticos, el render sale SIEMPRE 1080x1920 pidan lo que pidan las
   variables; una sonda horizontal "funcionó" por coincidencia y salió con el canvas
   equivocado y `returncode 0`.

4. **`--json` sin `--batch` no emite nada y no avisa** (`revision/hf-2/AUDITORIA_DETERMINISMO.md:719-721,1180-1181`).
   `returncode 0`, una integración que espere JSON en stdout recibe vacío en silencio.

5. **La reproducibilidad del hash se rompía con `--workers` > 1** (D52,
   `revision/hf-2/AUDITORIA_DETERMINISMO.md`). El "mismo" contrato daba sha256 **distinto** en 9
   de 10 configuraciones; la conclusión de HF-0 ("3 corridas iguales = determinista") era
   insuficiente — cierta para SU composición, falsa en general. Arreglado fijando
   `--workers 1`.

6. **Plantillas HORIZONTALES recortadas al subir a banda superior** (HF-4b / PR #52-#53,
   `tests/test_hf4b_recorte_horizontal.py`). El desplazamiento de -34pp mandaba el borde
   superior de hook/cierre/titulo_seccion/dato_destacado a coordenada negativa cuando su
   contenido nativo era más alto de lo calibrado. Detectado renderizando con texto
   deliberadamente largo y midiendo el alfa real del MOV — no el CSS declarado. Fijado
   anclando el `#zona` horizontal en `top:54%` con crecimiento hacia abajo.

7. **[ESTE HALLAZGO, HF-4 Formato dual, 2026-08-05] Plantillas VERTICALES invisibles con
   `returncode 0`.** El `@media (orientation: portrait)` de hook/cierre/titulo_seccion/
   dato_destacado (`motion/{hook,cierre,titulo_seccion,dato_destacado}/index.html`) solo
   sobreescribía `height`/`place-items`, así que heredaba el `top:54%` del bloque horizontal
   (añadido en #6): la caja quedaba en `[54%,122%]` y con `place-items:end` el contenido se
   ancla al borde INFERIOR de esa caja — fuera del lienzo. Con un título corto el borde
   superior del contenido asomaba lo suficiente para ser visible (por eso `confirmar_banda.py`,
   HF-3, "confirmó" la banda superior con un título de una palabra); con el título real de
   `mariosoto_clip2_corto` (9 palabras) el contenido entero cayó fuera: **0 píxeles de alfa en
   los 75 frames del MOV**, en TODA la duración de la pieza, no solo recortado por un borde.
   El sello `motion_render.json` declaró 3 piezas; el MP4 final entregó 1 (`lower_third`,
   que no usa este patrón `#zona` — su ancla es `bottom:32%` fija, igual en las dos
   orientaciones). Exactamente #6, pero en la orientación que #6 no probó.

## Por qué el agujero era doble (backstop de tiempo de render)

`motion_capa.pieza_cabe_en_el_lienzo` (Paso 2 de HF-4b) ya median el alfa real de la pieza antes
de componerla, pero:

- Corría **solo en horizontal** ("el carril vertical... ya pasó su propio gate visual en
  HF-2/HF-3" — cierto para UN título corto, falso para texto real variable).
- Cuando `bbox_alfa` devolvía `None` (sin alfa medible), **fallaba ABIERTO** (`return True`,
  "sin alfa no hay nada que recortar"). Una pieza sin ningún alfa medible en su instante de
  sostenimiento es el caso MÁS grave (la pieza entera es invisible), no el más inocuo.

Las dos cosas se corrigieron en `motion_capa.py` (hotfix de esta sesión): el backstop corre en
las dos orientaciones y `bbox is None` ahora falla CERRADO.

## Las dos compuertas que quedan, para que esto no vuelva a pasar en silencio

1. **Backstop de render** (`motion_capa.pieza_cabe_en_el_lienzo`, corre en las dos
   orientaciones, `bbox is None` → rechaza la pieza): cazaría un defecto de la plantilla ANTES
   de componerla en cualquier video.
2. **Gate del artefacto final** (`motion_gate_visibilidad.piezas_declaradas_pero_invisibles`,
   `tests/test_motion_gate_visibilidad.py`, script de verificación en
   `revision/hf-4/verificar_gate_visibilidad.py`): compara, por formato, el número de piezas
   que el sello `_motion_render.json` declara contra las que de verdad se ven en el MP4
   final, midiendo píxeles del acento de marca de cada plantilla dentro de su ventana
   temporal. Es redundante A PROPÓSITO con el backstop de render: cazaría además un defecto
   del propio paso de composición/overlay, que el backstop no toca.
3. **Regresión directa** (`tests/test_hf4_recorte_vertical.py`, gemelo de
   `test_hf4b_recorte_horizontal.py`): mide el alfa real del MOV con texto deliberadamente
   largo en las dos orientaciones — ya no solo horizontal.

Corrida sobre `output/paquetes/mariosoto_00hf4_formato_dual/` tras el fix:

```
mariosoto_clip2_corto_9x16_hormozi.mp4 (vertical): 3 piezas declaradas, 3 visibles
mariosoto_clip2_corto_16x9_hormozi.mp4 (horizontal): 3 piezas declaradas, 3 visibles
GATE OK: 0 pieza(s) declaradas pero invisibles
```
