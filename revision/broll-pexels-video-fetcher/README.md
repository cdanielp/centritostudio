# B-roll Pexels — Fetcher de VIDEOS (PR A)

Plomería del fetcher de **clips de video** de Pexels: búsqueda, selección determinista de
`video_file` MP4, descarga atómica, cache por `video_id + file_id` y sidecar de atribución.
**Sin integración con FFmpeg / render / UI / brain** — eso es el PR B.

## Módulos

| Archivo | Rol | Líneas |
|---|---|---|
| `broll_video_stock_base.py` | Tipos, errores (`PexelsVideoError`), cache/IO atómica, sidecar, `verificar_mp4_ffprobe` | ~388 |
| `broll_video_select.py` | Selección determinista de `video_file` (pura, sin red) | ~101 |
| `broll_video_stock.py` | Config, búsqueda HTTP, descarga por streaming, orquestador seguro | ~383 |

Reutiliza de `broll_stock_base` (fetcher de imágenes, ya mergeado) la escritura atómica, el reloj
UTC, la normalización de query y el tipo `RateLimitInfo`. Cero dependencias nuevas (`requests` ya
estaba). Cada archivo ≤ 400 líneas; funciones ≤ 50 líneas.

## Endpoint

`GET https://api.pexels.com/v1/videos/search` (verificado contra la doc oficial de Pexels).

Parámetros: `query`, `orientation` (landscape|portrait|square), `size` (large|medium|small,
**opcional — por defecto NO se envía**), `locale`, `page`, `per_page` (máx 80). Un `Video` trae
`id, width, height, url, image, duration, user{id,name,url}, video_files[]`; cada `video_file`
trae `id, quality, file_type, width, height, fps, link`.

`size=None` por defecto: la resolución final la decide `seleccionar_variante_video` sobre los
`video_files`, no el filtro de búsqueda.

## Política de selección (V1, determinista)

1. Filtra MP4 directos válidos: descarta HLS, `.m3u8`, `file_type != video/mp4`, dimensiones ≤ 0,
   links vacíos.
2. Prioriza candidatos cuya orientación coincide con el destino (`vertical`→portrait,
   `horizontal`→landscape).
3. Entre los que **alcanzan** `target_width` y `target_height`: el de **menor área suficiente**
   (evita 4K si una Full HD cubre el destino).
4. Si ninguno alcanza: el de **mayor área** disponible.
5. Desempate determinista: menor diferencia de aspect ratio, luego `file_id`. Nunca aleatorio.

Ejemplos: salida 1080x1920 prefiere 1080x1920 sobre 2160x3840; salida 1920x1080 prefiere
1920x1080 sobre 4096x2160; si solo hay 720x1280, se usa como fallback vertical.

## Cache

- **Archivo:** `pexels_{video_id}_{video_file_id}.mp4` (+ sidecar `.json`). El `file_id` en la
  identidad evita colisiones entre variantes del mismo video. Cache hit solo si el MP4 sigue con
  firma `ftyp` válida **y** el sidecar coincide en provider/asset_id/video_file_id/download_url.
- **Búsqueda:** JSON con TTL de 24 h; identidad incluye `media_type=video`, query normalizada,
  orientation, size, locale, per_page, page. Atómica, versionada, se ignora si vence o se corrompe.
- Todo vive en `assets/broll/cache/pexels_video/` (**gitignored**: ni MP4 ni sidecar entran al repo).

## Fail-open

- Capa baja (`buscar_videos_pexels`, `descargar_video_asset`): **honesta**, lanza
  `PexelsVideoError` tipado.
- Orquestador (`buscar_video_broll_seguro`): atrapa **solo** `PexelsVideoError` → `BrollVideoError`
  saneado (sin secretos) para que el pipeline omita el b-roll y siga.
- `RuntimeError/TypeError/ValueError/AssertionError` (bugs) **se propagan**.

## Seguridad

`PEXELS_API_KEY` vive en el entorno y **nunca** se imprime, serializa ni aparece en sidecars,
errores o logs. El header `Authorization` jamás se loguea. `_sanitizar` redacta la key si se colara
en un mensaje.

## Tests

`tests/test_contrato_broll_video_stock.py`: **52 tests, todos offline** (fixture autouse bloquea
`requests.get`, caches redirigidas a `tmp_path`, nunca una key real).

## Smoke real (manual, requiere API key)

```powershell
$env:PYTHONIOENCODING="utf-8"
.\venv\Scripts\python revision\broll-pexels-video-fetcher\smoke_video_pexels.py
.\venv\Scripts\python revision\broll-pexels-video-fetcher\smoke_video_pexels.py "montanas nevadas"
```

Se niega limpiamente sin key; busca portrait, descarga un MP4, corre `ffprobe` e imprime
`video_id, file_id, autor, duration, dimensiones, quality, ruta, cuota`. **Nunca imprime la key;
el MP4 descargado no se commitea** (queda en la cache gitignored).

### Resultado del smoke real ejecutado en esta sesión

```
video_id    : 35568501
file_id     : 15070864
autor       : C1 Superstar
duration    : 11s
dimensiones : 1080x1920 (video 1080x1920)
quality     : (Pexels devolvio quality vacio para ese file_file; se selecciona por dimensiones)
ffprobe     : codec_name=h264 width=1080 height=1920 duration=11.6
cuota       : limit=25000 remaining=24996
```

Descarga real (no cache, no mock). El MP4 quedó en la cache local gitignored; **no se commiteó**.
