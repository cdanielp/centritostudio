# S35 · PR A — Contrato y endurecimiento del Editor de Paquete (D32)

Rama: `refactor/studio-package-review-contract`

Este PR deja el **backend** del Editor de Paquete pequeno, seguro, determinista,
solo-lectura y cubierto por tests. **No hay cambio visual**: la salida visual y el
veredicto de K pertenecen al PR B (`feat/studio-package-review-alpha`).

## Arquitectura

- `paquete_editor.py` — logica PURA: agregacion de paquete.json + sidecars y
  **validacion de rutas** (helpers nuevos). Reutiliza `auto_report` como fuente
  unica de estado/recomendacion. Nunca escribe, nunca recalcula.
- `studio_packages.py` (NUEVO) — `APIRouter` con las rutas HTTP del Studio:
  `GET /api/paquetes`, `GET /api/paquetes/{pkg}`, y el servido confinado
  `GET /api/paquetes/{pkg}/video/{archivo}` + `GET /api/paquetes/{pkg}/reporte`.
- `app.py` — solo `app.include_router(studio_packages.router)`. Se saco la logica
  inline de paquetes del monolito (app.py baja de 569 lineas; no se agranda).

Sin ciclos de import: `studio_packages -> paquete_editor -> auto_report`.

## Contrato API (conservado + aditivo)

`GET /api/paquetes` → lista de tarjetas, mas recientes primero, fail-open por
paquete (dir sin paquete.json o JSON corrupto se omite, no derriba la lista).
Cada tarjeta: `id, name, fecha, n_clips, resumen, estados[]` + `salud`
("completo|incompleto", **aditivo**).

`GET /api/paquetes/{pkg}` → detalle: `id, meta, resumen, recomendacion,
reporte_url|null, clips[]`. Cada clip: `archivo, titulo, razon, score, dur_s,
emojis_msg, estado, video_url|null, video_disponible, ruta_fs|null, avisos[],
tramos_disponibles, qa|null, markers[]`. Campos nuevos (`video_disponible`) son
aditivos; el JavaScript actual (usa `video_url`/`reporte_url` opacos) no se rompe.

## Seguridad (rutas + servido de binario)

- **Path-safety pura** en `paquete_editor`: `es_nombre_seguro` (rechaza vacio,
  `.`, `..`, `/`, `\`, unidad de Windows) y `resolver_hijo_seguro` (basename +
  `resolve()`, rechaza el symlink que escapa del root). Nunca se confia en
  `clip["archivo"]`, `qa["alerts_file"]` ni en el `pkg` de la URL.
- **Confinamiento del binario por dos lados:** (a) el `.mp4` de un clip se sirve
  SOLO por el endpoint validado `/api/paquetes/{pkg}/video/{archivo}` — basename
  seguro, existente y con sufijo `.mp4`; pedir `paquete.json`, `REPORTE.md` o un
  sidecar por esa ruta devuelve **404**. `reporte_url` va por
  `/api/paquetes/{pkg}/reporte` (solo ese archivo). (b) el mount estatico `/output`
  se subclasea (`_OutputSinPaquetes`): TODA peticion a `/output/paquetes/**` da 404,
  cerrando tambien la ruta abierta. El resto de `output/` (renders de otras
  estaciones) se sigue sirviendo; la tarjeta del Modo Automatico se repunto a los
  endpoints validados.
- `video_url` se construye unicamente para un archivo seguro y existente; si falta
  o es inseguro → `null` + `video_disponible=false` (el resto del detalle sigue).

## Tests (40 nuevos)

- `tests/test_studio_packages.py` — path-safety (traversal, separadores, unidad,
  symlink que escapa), router via `TestClient` (lista fail-open + orden reciente,
  detalle, 404 de traversal incl. URL-encoded, **confinamiento** del video contra
  json/md/sidecars, reporte, sin rutas absolutas, `<script>` como texto), el
  **confinamiento del mount** `/output` (bloquea `paquetes/**`, sirve el resto), y
  solo-lectura (la entrada no se muta, un `RuntimeError` interno se propaga).
- `tests/test_contrato_paquete_editor.py` — actualizado al nuevo contrato
  (video_url del endpoint validado, `video_disponible`, `reporte_url` null).

Total suite: **616 passed, 1 skipped** (el skip es el test de symlink cuando el
SO no lo permite — Windows sin Developer Mode). Sin red, sin GPU, sin FFmpeg.

## Alcance cerrado

Backend solo-lectura, rutas confinadas, contratos estables, cero motores, cero
cambio visual. La UI premium (lista, preview, timeline clicable, responsive) es el
PR B y requiere el veredicto visual de K.
