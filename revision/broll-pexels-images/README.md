# Evidencia — B-roll: fetcher de imágenes Pexels (`feat/broll-pexels-images`)

## Qué se construyó

Capa **opcional y aislada** que busca, selecciona, descarga y cachea imágenes de stock de
Pexels para b-roll cutaway. **No** conecta con brain, render, `core_overlays`/`Popup`, UI
ni `auto.py` (fuera de alcance por diseño). Solo produce assets tipados y archivos en caché
que una integración futura consumirá.

Dos archivos (split por la regla anti-spaghetti, archivo ≤ 400 líneas):
- `broll_stock.py` (390 L) — API pública: config, HTTP, selección, descarga, orquestación.
- `broll_stock_base.py` (317 L) — tipos, errores, caché de búsqueda + I/O atómica + sidecar.

Capas sin ciclo: `broll_stock_base` no depende de red ni de la key; `broll_stock` la consume
y re-exporta el contrato público (`from broll_stock import StockAsset, buscar_broll_seguro`).

Cliente HTTP: `requests` (ya en `requirements.txt`, mismo patrón que `submagic.py`).
**Cero dependencias nuevas.**

## Contrato público

- `StockAsset` (frozen): candidato de imagen; `local_path`/`metadata_path` son `None`
  hasta descargar (nunca strings vacíos). `descargar_asset` devuelve una nueva instancia
  con rutas reales.
- `SeleccionVariante(nombre, url, motivo)` — resultado determinista de elegir variante.
- `RateLimitInfo(limit, remaining, reset)` — headers de rate limit (solo en 2xx).
- `BrollError(code, message, retry_after)` y `BrollResult(assets, error, rate_limit)` —
  contrato fail-open; mensajes saneados, nunca contienen la key ni `Authorization`.
- Excepciones tipadas, todas subclase de `PexelsError` (familia operativa): `PexelsDeshabilitado`,
  `PexelsRateLimit`, `PexelsAuthError`, `PexelsHTTPError`, `PexelsTimeout`,
  `PexelsRespuestaInvalida`, `PexelsSinVariante`, `PexelsDescargaError`.
- Funciones: `tiene_api_key()`, `estado_pexels()`, `buscar_imagenes_pexels(...)` (capa
  honesta que lanza), `buscar_broll_seguro(...)` (fail-open sólo para `PexelsError`; los errores
  de programación se propagan), `seleccionar_variante(...)`, `descargar_asset(...)`.

## Decisiones clave

- **429: sin reintento, sin sleep** (V1). Lanza `PexelsRateLimit` conservando `Retry-After`
  como dato opcional; `buscar_broll_seguro` lo convierte en error tipado y el pipeline sigue.
- **Selección de variante prioriza resolución** (la orientación ya se resolvió en la
  búsqueda vía `orientation`):
  - `contain`: `large2x → original → large`
  - `cover` + vertical: `large2x → original → portrait`
  - `cover` + horizontal: `large2x → original → landscape`
  - `large2x` (~1880px) conserva mejor detalle en Full HD que los crops `portrait`
    (~800×1200) y `landscape` (~1200×627), que quedan como último fallback orientado.
- **Doble caché:** (a) archivo descargado con identidad `provider+asset_id+variante`
  (`pexels_{id}_{variante}.{ext}`) — la variante se resuelve **antes** de la ruta, así dos
  variantes del mismo `asset_id` nunca colisionan; (b) respuesta de búsqueda JSON (24 h, clave
  determinista por query normalizada + orientation + per_page + page). Ambas atómicas
  (temporal + `os.replace`), deshabilitables (`usar_cache=False`), se ignoran/renuevan si
  vencen o se corrompen. Ninguna guarda la API key. El **cache hit** de archivo exige que la
  imagen siga siendo válida (firma de bytes) y que el sidecar coincida en `provider`,
  `asset_id`, `selected_variant` y `download_url`; cualquier desajuste re-descarga.
- **Extensión por firma de bytes** (JPEG/PNG/WebP), no por la URL. Content-Type se valida
  cuando está disponible. Contenido no reconocido → se rechaza.
- **Sidecar de atribución/licencia** por imagen: `provider_url`, `attribution_text`
  ("Photo by {author} on Pexels"), `source_url`, `author_url`, dimensiones, `selected_variant`,
  `selection_reason`, `download_url`, `downloaded_utc`, `last_used_utc`, `sidecar_version` y
  bloque de licencia (uso comercial sí; redistribución como stock no; datasets/entrenamiento IA
  no). **Sin API key.** En un **cache hit** válido el sidecar se reescribe atómicamente
  actualizando sólo `query`, `selection_reason` y `last_used_utc`; `downloaded_utc` se preserva.
- **Fail-open acotado:** `buscar_broll_seguro` sólo atrapa la familia `PexelsError` (errores
  operativos conocidos). Errores de programación (RuntimeError/TypeError/ValueError) se propagan.

## Tests

`tests/test_contrato_broll_stock.py` — **45 tests, todos sin red** (fixture `autouse`
bloquea `requests.get` por default; se stubea explícitamente por caso). Cubre los 25 casos
del brief + los 10 órdenes de selección de variante + caché de búsqueda (hit/expira/
corrupta/normalización).

```
45 passed in 0.28s
```

## Smoke test manual (NO forma parte de pytest)

`revision/broll-pexels-images/smoke_pexels.py` — requiere `PEXELS_API_KEY`; se niega
limpiamente si falta. Busca un término inocuo, descarga un asset e imprime id, dimensiones,
autor y ruta. **Nunca imprime la key.**

```powershell
$env:PYTHONIOENCODING="utf-8"
.\venv\Scripts\python revision\broll-pexels-images\smoke_pexels.py "cafe"
```

Requiere prueba manual con API key real (ver reporte de la sesión). Las imágenes
descargadas viven en `assets/broll/cache/pexels/` (gitignored) y **no** entran al repo.
