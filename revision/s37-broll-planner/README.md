# S37-A — B-roll Planner puro, determinista y auditable

Evidencia de revisión del PR A de la fase **S37 — Wiring del Modo Automático**.
Este PR entrega **solo** la capa de planeación; no toca `brain.py` ni `auto.py`, no
usa Pexels/FFmpeg/red, no descarga assets y no cambia la salida visual del producto.

## 1. Problema

Hoy `brain.py` aporta señales editoriales (grupo, keyword, timestamp, emoji) pero el
sistema **no tiene una capa pura que decida ventanas de b-roll** de forma determinista y
auditable. El Modo Automático v2 necesita ese contrato antes de conectar resolvers.

## 2. Alcance (S37-A)

Una capa pura y reusable que recibe `groups.json` + `brain.json` + duración + `BrollConfig`
y produce un `BrollPlan v1`: ventanas de b-roll con tipo (image/video), query trazable,
zonas protegidas, decisiones aceptadas, candidatos rechazados con razón, resumen de
cobertura y un sidecar JSON versionado.

## 3. No alcance

- No conecta Pexels ni ningún resolver (PR B).
- No descarga imágenes ni videos.
- No modifica `auto.py`, `brain.py`, `render`, `core_overlays`, ni `Studio`.
- No escribe `{stem}_popups.json` ni `{stem}_popups.auto.json`.
- No usa red, FFmpeg, ffprobe, GPU, LLM, traducción, random ni reloj.

## 4. Arquitectura

```
groups.json + brain.json + BrollConfig
                    |
                    v
   broll_planner.plan_broll  (PURO)
                    |
                    v
              BrollPlan v1
                    |
         broll_plan_io.write_broll_plan
                    |
                    v
       {stem}_broll_plan.json   (auditoría, NO sidecar de render)
```

Principio rector (D34): **brain señala, el planner decide, auto orquesta (PR B), los
resolvers descargan, el render compone.** Cada responsabilidad queda separada.

Módulos (todos ≤400 líneas, funciones ≤50, solo stdlib):

| Módulo | Responsabilidad |
| --- | --- |
| `broll_plan_types.py` | Dataclasses frozen, errores, códigos de rechazo, validación de config |
| `broll_plan_query.py` | Normalización, tokenización, query determinista, detección de movimiento |
| `broll_plan_place.py` | Colocación temporal + greedy de cobertura (geometría pura) |
| `broll_planner.py` | Orquestación pura: validación de inputs, extracción de señales, `plan_broll` |
| `broll_plan_io.py` | Serialización (contrato JSON v1) + escritura atómica del sidecar |

`broll_planner` reexporta `broll_plan_to_dict`, `write_broll_plan` y `load_broll_inputs`
como fachada pública.

## 5. Contrato de entrada

- `groups`: lista de grupos reales de Centrito. Cada grupo: `id`, `start`, `end`, `text`,
  `words` (lista de `{text, start, end, line_idx}`). El planner localiza el grupo por `g`
  contra `group["id"]` (no asume `id == posición`; conserva `group_position`).
- `brain_data`: dict con `groups` = lista de items `{g, kw, kw_ts, emoji?}`. `kw_ts` se toma
  del brain (no se recalcula si ya es válido). `kw=None` significa que el brain no eligió
  keyword (no es error).
- `clip_duration_s`: número real finito > 0.
- `config`: `BrollConfig` (opcional; default válido).

Un input de nivel superior inválido (`groups` no-lista, `brain` no-dict, duración inválida,
config incoherente) lanza `BrollInputError`/`BrollConfigError`. Un item individual
malformado se **rechaza** con código y **no borra** las señales válidas posteriores.

## 6. Contrato de salida

`BrollPlan` inmutable con: `version`, `clip_duration_s`, `config`, `protected_zones`,
`windows`, `rejected`, `warnings`, `signals_total`, `candidates_valid`. `broll_plan_to_dict`
lo serializa al **contrato JSON v1** (ver §20). Sin `Path`, sin bytes, sin rutas absolutas,
sin secretos, sin datos de Pexels, sin IDs de asset remoto, sin URLs.

## 7. Tipos

`BrollConfig`, `BrollSignal`, `ProtectedZone`, `BrollWindow`, `BrollRejected`, `BrollPlan`
(dataclasses frozen). `BrollPlanError` (base) → `BrollConfigError`, `BrollInputError`.

## 8. Algoritmo (extracción → query → movimiento → colocación → densidad → rechazo)

Greedy temporal **explícito y determinista en orden de brain**:

1. **Extracción**: por cada item de brain se valida `g`, `words`, `kw`, la palabra y `kw_ts`;
   se construye un `BrollSignal` o un `BrollRejected` con código estable.
2. **Query**: se deriva del texto real del grupo (keyword primero, sin stopwords ni
   duplicados, hasta `max_query_terms`).
3. **Movimiento**: image por default; video solo con señal léxica explícita de movimiento.
4. **Colocación**: la ventana se ancla en `kw_ts - lead_in` dentro del hueco libre que la
   contiene, respetando hook, outro, solapes y densidad.
5. **Densidad**: se acepta hasta acercarse al target (27%) sin superar el máximo duro (35%).
6. **Rechazo**: cada descarte queda registrado con su código.

## 9. Query determinista

`build_query(keyword, group_text, max_terms)`: toma la keyword como primer término,
tokeniza el `group_text`, elimina stopwords (lista local plegada), quita duplicados y
puntuación periférica, y conserva orden fuente hasta `max_terms`. **No traduce al inglés,
no llama LLM, no consulta disponibilidad.** Preserva acentos y ñ en la salida; el matching
usa forma plegada (casefold + plegado de acentos). Registra `query_terms` en la traza.

Ejemplo: grupo `"Ahora conectamos el modelo al workflow"`, keyword `"conectamos"` →
query `"conectamos Ahora modelo workflow"` (según `max_query_terms`).

## 10. Clasificación image/video

- **Default: image.**
- **Video** solo si `detect_motion` encuentra una señal textual explícita de
  movimiento/acción/proceso, y hay cupo (`max_video_windows`, V1 = 0 o 1).
- Si hay varias señales de movimiento, **máximo un video**; las demás se **degradan a image**
  (código `video_limit_fallback_to_image`) si caben.
- La razón de la ventana registra qué término activó el video.

## 11. Motion terms

Lista pequeña, conservadora y auditable (forma plegada) con familias verbales e inflexiones
comunes en tutoriales, incluida la voz "nosotros" (`caminamos`, `conectamos`, `cocinamos`):
mover, caminar, correr, saltar, girar, rotar, avanzar, retroceder, subir, bajar, entrar,
salir, abrir, cerrar, mezclar, cortar, cocinar, construir, instalar, conectar, montar,
transformar, convertir, cambiar, crecer, caer, volar, conducir, manejar, viajar, proceso…
y frases (`paso a paso`, `antes y despues`). Sin stems amplios (p.ej. NO `corr`, para no
casar `correo`). Un sustantivo estático, marca, número o adjetivo **no** activa video.

## 12. Hook

Zona protegida `hook` siempre: `start=0.0`, `end=min(3.0, clip)`, razón `hook_protected`.
Una señal con `kw_ts` dentro del hook se rechaza (`protected_hook`) y el lead-in nunca entra
al hook.

## 13. Outro

Solo con `fx_preset == "premium"` se reserva `premium_outro_s` (2.5s) al final, razón
`premium_outro_reserved`. Con `express`/`pro` no se reserva y no se crea zona artificial de
duración cero. Si hook y outro consumen todo el clip, plan vacío + warning `no_usable_timeline`.

## 14. Duraciones

| Tipo | min | preferred | max |
| --- | --- | --- | --- |
| image | 2.5 | 3.5 | 4.5 |
| video | 3.0 | 4.5 | 6.0 |

El planner solicita la duración **deseada** (no sabe la duración real del asset remoto: eso
es PR B). Se reduce dentro del rango solo si el hueco lo obliga, nunca bajo el mínimo. Tiempos
redondeados a 3 decimales de forma estable.

## 15. Densidad

`coverage_pct = coverage_s / clip_duration_s` (sin solapes). Target **0.27**, máximo duro
**0.35** (nunca se supera). El target detiene el greedy (señales posteriores →
`target_coverage_reached`); puede quedar por debajo si no hay suficientes señales.

## 16. Traslapes

Semántica `[start, end)`: una ventana que termina justo donde empieza otra **no** solapa.
Una candidata cuya ancla cae dentro de una ventana aceptada se rechaza (`overlap_unresolvable`)
sin desplazamientos agresivos; solo se ajusta dentro del hueco que la contiene.

## 17. Rechazos

Códigos estables: `brain_item_not_object`, `group_not_found`, `group_words_invalid`,
`keyword_not_selected`, `keyword_index_invalid`, `keyword_empty`, `kw_ts_missing`,
`kw_ts_invalid`, `kw_ts_out_of_range`, `query_empty`, `protected_hook`, `protected_outro`,
`duration_below_min`, `overlap_unresolvable`, `max_coverage_exceeded`,
`target_coverage_reached`, `duplicate_query`, `video_limit_fallback_to_image`. Warnings de
plan: `no_usable_timeline`, `disabled_by_config`, `brain_missing_groups`.

## 18. Pureza

`plan_broll` **no** lee red, reloj, random, entorno, GPU, cwd ni filesystem, y **jamás muta**
`groups`, `brain` ni `config`. La E/S (leer fixtures, escribir sidecar) vive en
`broll_plan_io`, fuera del núcleo puro. Errores por capas (D31): input superior inválido
lanza; item individual malformado se rechaza y continúa; bug de programación se propaga (sin
`except Exception: return empty`).

## 19. Determinismo

Misma entrada + misma config = mismo JSON semántico. IDs de ventana (`broll-0001`…) se
asignan tras ordenar por inicio. Sin dependencia de orden de dicts no contractual, sin
`PYTHONHASHSEED`, sin random. Verificado por tests (`test_determinismo_*`, `test_pureza_*`).

## 20. Escritura del sidecar

`write_broll_plan(plan, dest, *, overwrite=False)`: exige sufijo `.json`, rechaza directorios,
no sobreescribe por default, crea el parent, escribe UTF-8 con `ensure_ascii=False`, `indent=2`
y newline final, de forma **atómica** (`.tmp` + `os.replace`, limpia el tmp si falla).
El nombre de auditoría es `{stem}_broll_plan.json` — **no** es el sidecar de render y **jamás**
sobreescribe el `{stem}_popups.json` manual del usuario.

## 21. Privacidad

Fixtures 100% sintéticas (taller de café inventado). Sin transcript real, sin el SRT privado del usuario,
sin videos/audios reales, sin brain real, sin rutas locales, sin secretos ni keys. El JSON de
salida solo incluye el texto del grupo fuente de cada ventana, nunca la transcripción completa.

## 22. Tests

`tests/test_broll_planner.py` — **161 tests** nuevos, sin red/GPU/FFmpeg/Pexels/keys/archivos
reales. Cubren config, clip duration, inputs, query, movimiento, hook, outro, duraciones,
solapes, densidad, plan desactivado, determinismo, pureza, propiedades parametrizadas y el
sidecar JSON v1. Total de la suite tras el PR: **915 passed, 1 skipped**.

## 23. Smoke

`smoke_broll_planner.py` carga las fixtures, corre el planner, valida invariantes, hace
round-trip del sidecar a un temporal y compara dos corridas. Salida ASCII:

```
S37-A BROLL PLANNER SMOKE
signals: 8
candidates: 5
windows: 2
image: 1
video: 1
coverage: 25.0%
rejected: 6
overlaps: 0
deterministic: PASS
sidecar: PASS
RESULT: PASS
```

## 24. Cómo ejecutar

```powershell
$env:PYTHONIOENCODING="utf-8"
venv\Scripts\python -m pytest -q tests/test_broll_planner.py
venv\Scripts\python revision\s37-broll-planner\smoke_broll_planner.py
```

## 25. Qué no se tocó

`brain.py`, `auto.py`, `auto_report.py`, `clipper*.py`, `reframe*.py`, `core*.py`, `fx.py`,
`cve_popups.py`, `cve_clips.py`, `broll_*` (cutaway/stock/video), `clip_overlay.py`, `jobs*.py`,
`app.py`, `studio_packages.py`, `paquete_editor.py`, `static/index.html`, `requirements.txt`.
Sin nuevas dependencias.

## 26. Riesgos (no bloqueantes)

- La lista de motion terms es conservadora: puede clasificar como image algún verbo de
  movimiento poco común. Es ampliable sin cambiar contratos.
- El greedy prioriza orden de brain; una regla de scoring alternativa podría diferirse a PR B
  si K lo pide tras ver resultados reales.

## 27. Próximo PR

**S37-B** — extender `auto.py` para consumir el `BrollPlan`, resolver assets existentes
(Pexels imagen/video), materializar `{stem}_popups.auto.json` sin pisar sidecars manuales,
arbitrar FX/b-roll, validar integridad y sincronización A/V, y producir el paquete completo.
Requiere veredicto visual de K. **No implementado en este PR.**
