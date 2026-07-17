# Evidencia — Pexels como b-roll cutaway (`feat/broll-pexels-cutaway-integration`)

## Qué se construyó

El **puente** que conecta el fetcher Pexels (ya mergeado, PR #2) con la capa de overlays, para
que una **entrada explícita** de b-roll termine convertida en un `Popup(cutaway=True)` y se
renderice con los captions encima. Camino real, pequeño y auditable:

```
entrada manual {stem}_popups.json  (source="pexels", query, t, dur, fit, size_pct, behind_text)
   -> cve_popups._entrada_pexels()          (dispatch por `source`, fail-open)
   -> broll_cutaway.resolver_cutaway_pexels()
        -> buscar_broll_seguro(query, orientation)   (fetcher; primer candidato, determinista)
        -> descargar_asset(...)                       (cache + sidecar del fetcher, sin HTTP nuevo)
        -> Popup(cutaway=True, png=<imagen descargada>, t0, t1, fit, size_pct, behind_text)
   -> core_overlays.construir_comando()  ->  un solo pase FFmpeg  ->  captions ASS encima
```

## Archivos principales

- `broll_cutaway.py` (nuevo) — puente. `resolver_cutaway_pexels(...)` y `orientacion_para_video(...)`.
  Reutiliza el fetcher; **no** habla HTTP, no duplica caché/sidecar ni la geometría del cutaway.
- `cve_popups.py` — dispatch por `source`: `pexels` descarga b-roll; ausente/`biblioteca`/`local`
  conserva el flujo PNG histórico (compatibilidad total, incluido cutaway PNG). `_entrada_pexels`
  es fail-open: nunca lanza; omite con log ASCII si algo falla.
- `caption.py` — pasa `video_w/video_h` a `resolver_popups` (necesario para elegir orientación).

## Contrato público agregado

```python
resolver_cutaway_pexels(
    query, t0, t1, *, orientation, fit="cover", size_pct=1.0, behind_text=True, cache_dir=None
) -> ResultadoCutawayPexels(popup, codigo, mensaje, asset)

orientacion_para_video(video_w, video_h) -> (orientation_pexels, destino)
```

- **Timestamps de la entrada**, no de Pexels. Selección **determinista**: primer candidato.
- **Fail-open** sólo para `PexelsError` (sin_resultados / rate_limit / timeout / auth / http / …):
  devuelve `codigo` visible y **sin** Popup — el render omite el b-roll y sigue.
- **ValueError** de contrato (query vacía, `t1<=t0`, fit/size_pct/orientation inválidos) y
  errores de programación (RuntimeError/…) se **propagan** — no se ocultan bugs.
- **Orientación**: 9:16 → `portrait`/`vertical`; 16:9 → `landscape`/`horizontal`; cuadrado →
  `landscape`/`horizontal`. No se hardcodea vertical.

## Cómo regenerar la evidencia

```powershell
$env:PYTHONIOENCODING="utf-8"
.\venv\Scripts\python revision\broll-pexels-cutaway\gen_evidencia.py [base.mp4] [query]
```

El script:
1. Se niega limpiamente si falta `PEXELS_API_KEY`.
2. Usa un **video base real con una persona** si lo encuentra (`input/reel01.mp4`, …) o el que se
   le pase; si no hay, cae a `testsrc` y **avisa** que no prueba el caso "tapa la cara/mic".
3. Genera captions ASS reales, busca+descarga una imagen (query inocua) vía el fetcher, crea el
   Popup cutaway y renderiza 5s en **un solo pase**: 0–1s original · 1–4s cutaway · 4–5s original.
4. Extrae 3 frames (`frame_antes.png` / `frame_durante.png` / `frame_despues.png`), corre ffprobe
   e imprime sólo datos seguros (asset_id, autor, dimensiones, variante, rutas, duración).
   **Nunca** imprime la API key.

`ejemplo_popups.json` muestra el formato de entrada (una entrada Pexels + una PNG conviviendo).

## Qué NO se commitea (regla del proyecto)

- La imagen real descargada de Pexels y la caché (`assets/broll/cache/`, gitignored).
- El MP4 de salida (`*.mp4`, gitignored) y los 3 frames PNG (contienen la foto de Pexels).

Los frames se entregan a K para su visto bueno visual; el repo sólo guarda este README + el script.

## Verificación automática

`tests/test_contrato_broll_cutaway.py` — 27 tests, **todos sin red** (se monkeypatchea el fetcher).
Cubre: disparo de búsqueda, PNG que no toca Pexels, validación de contrato, Popup correcto
(t0/t1/fit/size_pct/behind_text), orientación, fail-open (sin_resultados/rate_limit/timeout),
propagación de RuntimeError, reutilización de `descargar_asset` sin HTTP, ruta en el Popup, orden
de overlays con captions encima y compatibilidad con el cutaway PNG anterior.

## Limitaciones (alcance de este PR)

- Entrada **explícita/manual** ({stem}_popups.json). Aún **no** elige automáticamente cuántos
  b-rolls poner ni cuándo (eso vive en el brain, fuera de alcance).
- Sólo **imágenes**; todavía no clips de video de Pexels.
- Un solo candidato (V1), sin ranking con LLM ni traducción de la query.
- Sin UI de aprobación/rechazo, sin Ken Burns ni matting. La **curación humana sigue siendo
  necesaria** (qué foto, si tapa a la persona, legibilidad).

## Qué debe revisar K visualmente (frames)

- Que el cutaway `cover` full-frame **no tape la cara ni el micrófono** de forma que arruine el
  mensaje (durante 1–4s el b-roll toma la pantalla; el `behind_text` mantiene los captions encima).
- Legibilidad de los captions sobre una **foto real** (no barras de color).
- Pertinencia semántica de la imagen elegida por la query.
