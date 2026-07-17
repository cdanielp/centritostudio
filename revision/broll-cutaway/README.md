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
al cuadro, para distinguir contain de cover) y renderiza con el código real (`construir_comando`).

## Frames (verificados con ojos, regla #7)

| Frame | Caso | Qué prueba |
|---|---|---|
| `cutaway_vertical_contain_85.png` | vertical 1080x1920, contain, 0.85 | imagen entera centrada, aspecto preservado (barras sin deformar), no recorta |
| `cutaway_vertical_cover_fullframe.png` | vertical 1080x1920, cover, 1.0 | llena todo el cuadro, recorte proporcional, sin bandas ni deformación |
| `cutaway_horizontal_cover_fullframe.png` | horizontal 1920x1080, cover, 1.0 | funciona en horizontal; llena y recorta |

ffprobe confirma en los 3 renders: resolución de la fuente conservada y duración = 3.00s
(coexistencia con el pase ASS + overlays en un solo comando FFmpeg).

## Verificación automática

`tests/test_contrato_cutaway.py` (21 tests), incluye `test_cutaway_ffmpeg_conserva_resolucion_y_duracion`
(render real + ffprobe, skip si no hay binarios). `check.bat`: ruff + format + imports + **405 tests**.

## Qué debe revisar K visualmente

- Que el tamaño default 0.85 (contain) se vea bien sobre material real con captions activos.
- Elegir por caso de uso `contain` (b-roll completo visible, tipo lámina) vs `cover` (b-roll
  inmersivo full-frame). Con imágenes de aspecto cercano al cuadro la diferencia es sutil.
- Que `behind_text=True` (default de cutaway manual) deje los captions legibles sobre el b-roll.
