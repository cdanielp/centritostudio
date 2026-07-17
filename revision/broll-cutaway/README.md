# Evidencia — B-roll cutaway (imagen grande)

Rama: `feat/broll-cutaway-image`. B-roll de IMAGEN en modo cutaway grande, reutilizando el
sistema de overlays PNG (`core_overlays.Popup`). Sin dependencias nuevas.

## Qué se implementó

- `core_overlays.Popup` gana `cutaway: bool=False` y `fit: str="contain"` (defaults compatibles;
  los popups históricos no cambian).
- `_preparar_cutaway`: caja centrada de `size_pct` del cuadro (1.0 = pantalla completa), **sin**
  confinar a la zona útil; centrado exacto con `(W-w)/2 / (H-h)/2`; `fit` inválido → `contain`
  con aviso ASCII (fail-open).
- `_filtro_png_cutaway`: `contain` = `scale ...:decrease` (imagen entera, sin recorte);
  `cover` = `scale ...:increase` + `crop` (llena y recorta). Ambos preservan aspecto.
- `cve_popups._entrada_manual`: declara cutaway por JSON (`{stem}_popups.json`). Si `cutaway`
  y no hay `behind_text`, default **True** → captions encima del b-roll; `behind_text` explícito
  se respeta.
- **Default de tamaño centralizado:** `Popup.size_pct` es `float|None=None`; `Popup.__post_init__`
  resuelve None → 0.20 (popup) o 0.85 (cutaway). Un valor explícito, incluido 0.20, se conserva.
  Así `Popup(cutaway=True)` directo también da 0.85, no solo la ruta manual.
- La cadena de emojis SIN popups sigue BYTE-IDÉNTICA (golden test intacto).

## Cómo reproducir

```
venv\Scripts\python revision\broll-cutaway\gen_evidencia.py
```

Genera extractos cortos de un clip real + un PNG de b-roll ANCHO (aspecto 3.2:1, muy distinto
al cuadro, para distinguir contain de cover), quema un **caption real de dos líneas** con el
pipeline existente (`core_ass.build_ass` + estilo hormozi) y renderiza con el código real
(`construir_comando`). El cutaway va `behind_text=True`.

## Validación de captions sobre el cutaway (actualizado)

Antes la evidencia usaba un ASS **vacío**, así que no probaba la convivencia con captions.
Ahora el ASS lleva un caption visible de dos líneas (`B-ROLL DE PRUEBA` /
`LOS CAPTIONS DEBEN QUEDAR ENCIMA`) durante la ventana activa del cutaway (0.3–2.7 s). El
frame se extrae a t=1.5 s (dentro de esa ventana). Verificado con ojos (regla #7):

- **Overlay detrás del ASS:** el cutaway se compone ANTES del filtro `ass` (`behind_text=True`),
  por lo que el caption queda **por encima** del b-roll, no tapado.
- **Caption visible encima:** las dos líneas hormozi (blanco + contorno, con la palabra activa
  del instante resaltada en amarillo por el estilo — no es un keyword marcado) se leen sobre el
  b-roll a pantalla completa (cover) y sobre la lámina centrada (contain).
- **Legibilidad básica:** el contorno negro mantiene el texto legible incluso sobre las barras
  saturadas del testsrc.

## Frames (verificados con ojos, regla #7)

| Frame | Caso | Qué prueba |
|---|---|---|
| `cutaway_vertical_contain_85.png` | vertical 1080x1920, contain, 0.85, **con caption** | imagen entera centrada, aspecto preservado (barras sin deformar), no recorta; caption legible encima |
| `cutaway_vertical_cover_fullframe.png` | vertical 1080x1920, cover, 1.0, **con caption** | llena todo el cuadro, recorte proporcional, sin bandas ni deformación; caption legible encima |
| `cutaway_horizontal_cover_fullframe.png` | horizontal 1920x1080, cover, 1.0, **con caption** | funciona en horizontal; llena y recorta; caption legible encima |

ffprobe confirma en los 3 renders: resolución de la fuente conservada y duración = 3.00s
(caption ASS + overlay cutaway conviven en un solo comando FFmpeg).

## Verificación automática

`tests/test_contrato_cutaway.py` (21 tests), incluye `test_cutaway_ffmpeg_conserva_resolucion_y_duracion`
(render real + ffprobe, skip si no hay binarios). `check.bat`: ruff + format + imports + **405 tests**.

## Qué debe revisar K visualmente

- Que el tamaño default 0.85 (contain) se vea bien sobre material real (no testsrc).
- Elegir por caso de uso `contain` (b-roll completo visible, tipo lámina) vs `cover` (b-roll
  inmersivo full-frame). Con imágenes de aspecto cercano al cuadro la diferencia es sutil.
- Confirmar que la legibilidad del caption sobre un b-roll real (foto/ilustración, no barras
  de color) sigue siendo suficiente; el testsrc es el caso más hostil de contraste.
