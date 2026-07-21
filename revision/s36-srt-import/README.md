# S36-A — Contrato seguro de importacion SRT

Infraestructura PURA para que los siguientes PR de S36 puedan usar un archivo `.srt`
como fuente oficial de captions. **Este PR NO integra captions, render, UI ni word
alignment.** Sin salida visual.

## Alcance

Una capa pequena, pura y reusable que:

- parsea un `.srt` a un documento inmutable de **cues** (frases con tiempo);
- valida su estructura y reporta **diagnosticos estructurados**;
- serializa de vuelta a SRT canonico (round-trip **semantico**);
- produce un **contrato JSON v1** estable para S36-B;
- expone una **CLI local** (`srt_tool.py`) para validar/inspeccionar/normalizar/contrato.

Principio rector (DECISIONES **D33**): un SRT es un documento de cues, **no** un
transcript por palabra. El parser **nunca** inventa timing por palabra. Los tiempos
canonicos son **milisegundos enteros** (jamas floats). El texto del usuario se conserva
tal cual (acentos, ñ, emojis, `<i>`/`<script>` como texto literal, mayusculas, comillas).

## Arquitectura

| Archivo | Responsabilidad | Lineas |
|---|---|---|
| `srt_types.py` | tipos (`SrtCue`/`SrtDiagnostic`/`SrtDocument`), excepciones, limites, codigos | ~150 |
| `srt_time.py` | `parse_timestamp` / `format_timestamp` (ms enteros) | ~32 |
| `srt_parse.py` | decodificacion (UTF-8/BOM/cp1252) + parser de estado + `load_srt` | ~208 |
| `srt_validate.py` | `validate_srt` + checks independientes | ~205 |
| `srt_serialize.py` | `serialize_srt` + `srt_to_contract` + `write_srt_contract` | ~98 |
| `srt_import.py` | **fachada publica** — unico punto de import | ~56 |
| `srt_tool.py` | CLI delgada | ~136 |

Ningun archivo de produccion supera 400 lineas; ninguna funcion supera 50. Cero
dependencias nuevas (solo libreria estandar). No se toco `caption.py`, `core.py`,
`core_ass.py`, `app.py`, `jobs.py`, `static/index.html` ni ningun motor.

## API publica (importar siempre desde `srt_import`)

```
parse_timestamp(value) -> int
format_timestamp(ms) -> str
parse_srt_text(text, *, source_name=None, strict=False) -> SrtDocument
parse_srt_bytes(data, *, source_name=None, encoding="auto", strict=False) -> SrtDocument
load_srt(path, *, encoding="auto", strict=False, max_bytes=...) -> SrtDocument
validate_srt(document, *, video_duration_ms=None) -> tuple[SrtDiagnostic, ...]
serialize_srt(document, *, reindex=False, newline="\n") -> str
srt_to_contract(document) -> dict
write_srt_contract(document, destination) -> None
```

Tipos: `SrtCue`, `SrtDiagnostic`, `SrtDocument`. Excepciones: `SrtError` (base),
`SrtDecodeError`, `SrtParseError`, `SrtLimitError`.

## Estricto vs tolerante

- **tolerante** (`strict=False`, default): recupera los cues validos, registra
  diagnosticos por cada bloque rechazado, no borra nada en silencio.
- **estricto** (`strict=True`): ante el primer diagnostico de severidad `error`
  lanza `SrtParseError` con mensaje accionable (sin volcar el transcript). Los
  `warning` nunca abortan.

**ERROR** (aborta en strict): indice no entero, falta linea temporal, timestamp
ilegible, `end <= start`, cue sin texto, NUL, bloque truncado, limite excedido,
indice `<= 0`, start negativo, documento sin cues.
**WARNING** (nunca aborta): indice duplicado / no consecutivo, orden no monotono,
overlap, punto decimal normalizado, fallback cp1252, cue fuera/parcial del video,
duracion excesiva, demasiadas lineas, linea muy larga, caracteres de control,
espacios de la linea temporal normalizados.

Los **overlaps se diagnostican, no se corrigen** (algunos SRT reales los usan aposta).

## Encoding

`encoding="auto"`: (1) BOM UTF-8 -> decodifica y reporta `utf-8`; (2) UTF-8 estricto;
(3) fallback controlado a **Windows-1252** con warning `encoding_cp1252_fallback`. Nunca
se usa `errors="replace"`. Si nada decodifica -> `SrtDecodeError` con offset (sin
contenido privado). Se manejan CRLF y LF (normalizacion estructural silenciosa).

## Diagnosticos

`SrtDiagnostic(code, severity, message, cue_position, cue_index)`. `code` es estable
(strings en `srt_types.py`). `source_position` es el ordinal **0-based** del bloque y se
usa para diagnosticos aun con indices duplicados. La validacion es **determinista** y en
orden fuente (no depende de hash randomization).

## Limites de seguridad (defaults)

`MAX_SRT_BYTES=10MiB`, `MAX_CUES=100_000`, `MAX_LINES_PER_CUE=20`,
`MAX_CHARS_PER_LINE=10_000`, `MAX_TOTAL_TEXT_CHARS=5_000_000`. `load_srt` revisa tamano
antes de leer, exige extension `.srt` (case-insensitive), rechaza directorios y archivos
inexistentes y no serializa rutas absolutas.

## Round-trip semantico (v1)

`parse -> serialize -> parse` conserva: cantidad de cues, indices (salvo `reindex=True`),
`start_ms`, `end_ms`, `lines`, orden y texto exacto por linea. **No** se promete
byte-identidad: BOM y line endings pueden normalizarse y el separador decimal se
serializa siempre con coma.

## Contrato JSON v1

`srt_to_contract` produce `{version, source{format,name,encoding,sha256},
summary{n_cues,start_ms,end_ms,duration_ms,n_errors,n_warnings}, cues[], diagnostics[]}`.
Tiempos enteros, `ensure_ascii=False`, `name` = basename saneado, `sha256` de los bytes
fuente, sin rutas absolutas. `write_srt_contract` escribe de forma **atomica** y se niega
a sobreescribir un destino existente.

## CLI

```
python srt_tool.py validate  PATH [--video-duration-s SEG]   # exit 1 si hay errores
python srt_tool.py inspect   PATH
python srt_tool.py normalize PATH --output DEST [--reindex]   # nunca sobre el origen
python srt_tool.py contract  PATH --output DEST.json
```

Salida ASCII, sin emojis, sin texto completo del SRT, sin rutas absolutas. Errores de
usuario -> `[error] ...` + exit 1 (sin traceback). Los bugs de programacion propagan.

## Pruebas

`tests/test_srt_import.py`: **132 tests** (timestamps, decodificacion, parser,
validacion, serializacion, contrato JSON, CLI y propiedades parametrizadas). Sin red,
GPU ni FFmpeg. El CI pasa aunque el SRT real no exista.

## Smoke real (local, opcional)

```
venv\Scripts\python revision\s36-srt-import\smoke_srt_real.py input\el SRT privado del usuario
```

Verifica contra los datos conocidos, hace round-trip en un temp dir, confirma que el
original queda intacto (mismo sha256) y solo imprime resumen + PASS/FAIL. **No** imprime
frases privadas, **no** copia el archivo, **no** lo commitea.

Resultado registrado (2026-07-17): `0 err`, ultimo index `1072`, ultimo
`start_ms=`, ultimo `end_ms=`, `0` errores, `0` warnings, encoding
`utf-8`, round-trip PASS, original intacto. **RESULTADO: PASS.**

## Privacidad

El SRT real esta gitignoreado (`input/`). No se versiona el archivo, ni copias, ni JSON
o normalizados derivados de el, ni frases suyas. Solo las fixtures sinteticas pequenas de
`fixtures/` entran al repo.

## Lo que este PR NO implemento (deuda de S36-B/C)

Integracion con `caption.py` (`--srt`), upload en FastAPI, UI de SRT en el Studio,
alineacion palabra-por-palabra (forced alignment), interpolacion o timing sintetico por
palabra, generacion de ASS desde SRT, render, templates 9:16, rebase tras cortes.

## Siguiente PR recomendado

**S36-B** — Integrar SRT como fuente oficial de captions y disenar la alineacion palabra
por palabra (motor + umbral de confianza + fallback de timing).
