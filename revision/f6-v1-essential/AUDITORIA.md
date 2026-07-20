# AUDITORÍA — F6 v1 esencial

Rama: `feat/f6-v1-essential` · Base: `main@a792140` (S36 COMPLETA) · Fecha: 2026-07-20

Objetivo del PASO A: mapear qué existe, qué está desconectado, qué se reutiliza,
qué contratos NO se tocan y qué archivos exactos se modifican, antes de escribir
código. No se duplican motores ni detectores.

---

## 0. Alcance F6 esencial (cierre de deuda imprescindible)

1. **Phrase spans** (pendiente #34): frases de varias palabras como span intencional.
2. **avoid_faces real**: conectar la señal de caras al posicionamiento de captions.
3. **Marca [center]**: centrar el span/caption correspondiente en el render real.
4. **cve_presets.json**: carga segura de presets de usuario con schema/allowlists.
5. **Controles CVE mínimos en Studio**.
6. **Tests E2E + evidencia visual + gate de K**.

NO: HyperFrames, hardening, F7, features creativas fuera de F6 esencial.

---

## 1. Contratos PRE-FIRMADOS (NO reabrir; implementar tal cual)

### 1.1 Phrase spans — #34 (RESUELTO, voto arquitecto s30)

`PREGUNTAS.md:704-741` + `DECISIONES.md:409-462` (D22) + `revision/fase-6/SPEC_K_CVE.md:144-157`.

- **v1 por-palabra HOY ya existe**; los spans entran con **regla pre-firmada**:
  - Un span aplica el efecto a **CADA palabra del span**.
  - Las marcas **manuales quedan EXENTAS de `kw_max_por_grupo`** (saturar es decisión del usuario).
  - Jerarquía **manual > brain > reglas**: lo manual gana.
- **Sintaxis pre-firmada** (spec de K): spans cerrados inline
  `[strong]esto cambió todo[/strong]`, `[big]10 millones[/big]`, `[center]la frase[/center]`.
- El sidecar `{stem}_keywords.json` **ya acepta el campo `frase`** (multi-palabra) —
  ver §2.2. Los spans son la ruta inline equivalente a `frase`.
- **Garantía inviolable (voto #34):** ninguna marca (`[strong]`, `[/strong]`, `[fuego]`…)
  aparece JAMÁS como texto visible en el ASS quemado. Marca inválida → texto plano, nunca crash.
  Test vigente: `tests/test_contrato_cve.py` (`test_marcas_invalidas_jamas_visibles_en_ass`).

### 1.2 Prioridad de posición (marca [center])

Orden pre-firmado por el prompt de F6:
**marca manual → decisión explícita del preset → avoid_faces → posición default.**

### 1.3 avoid_faces (comportamiento)

- Reusar el detector existente; **no duplicar detección**.
- Evitar captions sobre una cara cuando exista zona válida; sin saltos violentos.
- Respetar safe areas; **fail-open sobrio** si no hay detección; nunca bloquear el render.
- Determinista; sidecar saneado.

### 1.4 Densidad (D21, doble freno) y filtro anti-débil (D22)

- `DENSIDADES = {"baja": (5, 0.15), "media": (10, 0.20), "alta": (15, 0.30)}` (`cve_keywords.py`).
  Doble freno `min(tope, %)`; **manuales exentas**.
- `es_keyword_debil()` (`cve_keywords.py:95-109`): las manuales **jamás** pasan por él.

---

## 2. Qué EXISTE y funciona (reutilizar, no duplicar)

### 2.1 Motor CVE (`cve.py`, `cve_keywords.py`, `core_ass.py`, `core_ass_fx.py`, `core_overlays.py`)

| Símbolo | Ubicación | Rol |
|---|---|---|
| `RenderPlan` (dataclass) | `cve.py:43-59` | Contrato render↔engine. Ya trae `avoid_faces`, `position`, `kw_densidad`. |
| `_PRESETS` (4 built-ins) | `cve.py:63-106` | `clean_podcast`/`viral_bounce`/`keyword_punch`/`karaoke_highlight`. |
| `list_presets()` / `info_presets()` | `cve.py:109-130` | Nombres + metadatos para UI. |
| `resolve_preset()` / `resolver_preset_seguro()` | `cve.py:160-189` | Resuelve preset→RenderPlan; fail-safe por campo. |
| `aplicar_preset()` | `cve.py:213-240` | **Fuente única CLI+Studio** (brain + engine + fit). |
| `aplicar_engine()` | `cve.py:359-410` | Marca keywords: manual + brain + reglas; `elegir_keywords`. |
| `cargar_manual_keywords()` | `cve.py:192-210` | Lee `{stem}_keywords.json` (fail-open). |
| `hay_cara_en_rango(csv,t0,t1)` | `cve.py:282-301` | Lee `trayectoria_{stem}.csv`; `True/False/None`. **Testeada, sin consumidor.** |
| `candidatos_manuales()` | `cve_keywords.py:305-344` | Procesa sidecar: `palabra`/`frase`/`grupo`/`timestamp`/`intensidad`. |
| `parsear_marcas()` | `cve_keywords.py:360-393` | Parser inline `[strong]`/`[big]`/`[center]`. `MARCAS_VALIDAS` (`:74`). |
| `elegir_keywords()` | `cve_keywords.py:249-278` | Merge final 1/grupo + densidad; manuales exentas. |
| `ajustar_escala_punch()` | `cve_keywords.py:401-416` | Fit safe-zone (cadena REDUCIR). |
| `build_ass()` | `core_ass.py:229-275` | Genera .ass word-by-word. Recibe `style_cfg`, **no** el plan. |
| `_make_ass_style()` | `core_ass.py:192-226` | Alignment **hard-coded** `BOTTOM_CENTER` (`:216`), `marginv` (`:219`). |
| Safe zones UI | `core_overlays.py:16-20` | `SAFE_TOP/BOTTOM/RIGHT/LEFT_PCT` (fuente única, re-exportadas en `cve.py:20-26`). |

### 2.2 Sidecar de marcado manual `{stem}_keywords.json`

- Lectura fail-open: `cve.cargar_manual_keywords()` (`cve.py:192-210`), acepta lista directa
  o `{"keywords":[...]}`; encoding `utf-8-sig`.
- Esquema por entrada (`cve_keywords.py:305-344`):
  `palabra|frase` (requerido uno) · `grupo?` · `timestamp?` · `intensidad? ("big"→manual_big)` · `perfil?`.
- Se pasa a `aplicar_preset(..., manual_kw_path=TRANSCRIPTS/f"{stem}_keywords.json")`
  (`jobs_render.py` ruta transcript).

### 2.3 Detección de caras (reframe) — **reutilizar, NO duplicar**

- Detectores: **YuNet ONNX** (`reframe_detect.py`, `YUNET_SCORE_THRESHOLD=0.75`) con fallback
  **BlazeFace/MediaPipe**. Dispatch duck-typed `detectar_todas_caras_frame()` (`reframe_track.py:198-233`).
- Salida consumible por captions: **`trayectoria_{stem}.csv`** (`reframe.py:314-347`).
  Columnas: `t, cam_center_x, face_x_asignada, distancia[, conf_asignada]`.
  `conf_asignada` sólo si el reframe corrió con `--tray-dir` (detección viva vs hold/interpolado).
- **Contrato de consumo ya listo:** `hay_cara_en_rango()` (`cve.py:282-301`) lee ese CSV, puro,
  `True` (cara viva) / `False` (sólo hold) / `None` (sin archivo o sin `conf_asignada` → fail-open).

### 2.4 Studio (UI + endpoint)

- `POST /api/videos/{name}/render` (`app.py:402-468`): params `style, words_per_group,
  use_emphasis, use_emojis, pop, preset, intensidad, caption_qa, guion, caption_source`.
  Valida `preset in cve.list_presets()` (`:428-441`).
- UI `static/index.html` tab-render (`:305-399`): selects `render-preset` (`:331`),
  `render-intensidad` (`:338`), `render-pop`, etc. `startRender()` arma el payload (`:1466-1574`).
- **Modo Creador** (`:244-250`, `CREADOR_TOOLS :2248-2259`) **redirige a tab-render**; no tiene UI propia.
- Incompatibilidades SRT ya implementadas: `srtPanel._setRenderIncompatible()` (`:873-892`)
  deshabilita `render-wpg`/`use-emphasis`/`use-caption-qa` + clase `.control-disabled` + nota
  `render-srt-incompat`. **Respetar esto** al añadir controles.

---

## 3. Qué está DESCONECTADO (deuda F6 a cerrar)

| Elemento | Definido en | Estado | Cierre F6 |
|---|---|---|---|
| `plan.position` (bottom/center/top) | `cve.py:54` | Definido, **no consumido** en `build_ass` | Consumir en render (marca [center]). |
| `group["center"]` (flag `[center]`) | `cve.py:333` (asigna) | Marcado, **sin consumidor** | Consumir en render con prioridad §1.2. |
| `plan.avoid_faces` | `cve.py:53,153` | Definido, **no consumido** | Conectar a `hay_cara_en_rango` + posición. |
| `hay_cara_en_rango()` | `cve.py:282-301` | Implementada + testeada, **no llamada** en producción | Llamar desde el pipeline por grupo. |
| Phrase spans cerrados `[...]frase[/...]` | `SPEC_K_CVE.md:144` | Sintaxis NO parseada (sólo aperturas next-word) | Parsear span cerrado → marca cada palabra. |
| `cve_presets.json` (loader) | `DISENO_CVE.md:260-289` | **No existe** | Loader validado (schema/allowlist/fail-safe). |
| `{stem}_keywords.json` desde UI | `cve.py:192` | Sólo lectura; **no hay endpoint** de creación | Exponer edición mínima keywords/spans/center. |

Verificado: `grep "plan.avoid_faces"` → 0 usos productivos fuera de la definición.

---

## 4. Contratos que NO se modifican (invariantes)

- **Ruta transcript byte-idéntica**: cualquier flag nuevo con default = comportamiento histórico
  exacto (import-spy vigente). Añadir campos a `RenderPlan` con default seguro.
- **Firma pública** de `build_ass()`, `aplicar_preset()`, `run_render` (S36-C2A1: `+srt_selection=None`).
- **Marcas nunca visibles / nunca crash** (voto #34).
- **Manual siempre gana y exento de densidad/anti-débil** (D21/D22/#34).
- **Ruta SRT (S36)**: no regresión. SRT sigue rechazando `caption_qa`/`words_per_group`/`use_emphasis`
  (400); los nuevos controles CVE respetan las incompatibilidades SRT ya definidas.
- **Detección de caras**: se reutiliza el CSV de reframe; NO se instancia un detector nuevo en captions.
- **Safe zones** (`core_overlays.SAFE_*`): fuente única, no se duplican.
- `_scaled_fontsize()` (`core_ass.py:185`): fuente única de la fórmula de tamaño.

---

## 5. Archivos EXACTOS a tocar (plan de implementación)

### Producción
- `cve_keywords.py` — parser de **spans cerrados** (`parsear_marcas`/nuevo helper); marca cada
  palabra del span; resolución determinista de solapamientos/duplicados; `frase` ya soportado.
- `cve.py` — `RenderPlan` (posición efectiva por grupo/caption), wiring `avoid_faces` +
  `hay_cara_en_rango` con prioridad §1.2; pasar ruta del CSV de trayectoria; posición determinista.
- `core_ass.py` — consumir posición por-grupo en `build_ass` (override `\an`/`marginv` por evento
  cuando el grupo pide center; default sigue `BOTTOM_CENTER` byte-idéntico).
- `cve_presets.py` (**nuevo**) — loader de `cve_presets.json`: schema explícito, allowlists,
  validación de tipos/rangos, defaults seguros, built-ins intactos, ausente→built-ins,
  corrupto→fail-safe documentado, sin ejecución arbitraria, sin rutas privadas por API.
- `cve_sidecar.py` / sidecar de selección — publicar spans/center/avoid saneados (sin rutas/PII).
- `app.py` / `jobs_render.py` — controles CVE mínimos en el endpoint (posición, avoid_faces,
  densidad, keywords/spans/center) preservando incompatibilidades SRT y ruta transcript intacta.
- `static/index.html` — controles CVE mínimos en tab-render (Creador), con explicación breve,
  sin exponer JSON/rutas/tracebacks, escritorio + móvil.

### Tests (rojos primero)
- `tests/test_cve_spans.py` (spans dentro/parciales/solapados/duplicados/sin match).
- `tests/test_cve_avoid_faces.py` (cara superior/inferior/central, sin cara, detector fallido).
- `tests/test_cve_center.py` ([center], texto sin `[center]`, prioridad, compat spans/transcript/SRT).
- `tests/test_cve_presets_json.py` (válido/inválido/incompleto/desconocido/corrupto/defaults).
- `tests/test_ui_cve_controls.py` (harness JS `vm`; parámetros enviados, privacidad, SRT sin regresión).

### Evidencia (NO versionada)
- `output/revision-f6-v1-essential/`: `demo_phrase_span.mp4`, `demo_center.mp4`,
  `demo_avoid_faces.mp4`, `demo_custom_preset.mp4`, `contact_sheet.png`,
  `desktop_controls.png`, `mobile_controls.png`, `CHECKLIST_VISUAL.md`.

---

## 6. Riesgos / decisiones a fijar en implementación

1. **`build_ass` no recibe el plan** → la posición debe viajar **por-grupo** (p.ej. `group["position"]`
   / `group["center"]`) para no cambiar la firma pública; el default sigue global `BOTTOM_CENTER`.
2. **Center vertical vs safe area**: centrar respeta `SAFE_TOP/BOTTOM_PCT`; sin saltos violentos
   (una decisión de posición estable por caption, no oscilante frame a frame).
3. **avoid_faces sin CSV** (`None`) = fail-open: se mantiene la posición del preset, con log sobrio.
4. **Spans y densidad**: el span exime a sus palabras del cap; el resto sigue el doble freno D21.
5. **cve_presets.json corrupto**: fail-safe = built-ins + aviso claro (documentado), nunca crash.

---

## 7. Estado de partida verificado

- Suite base en `main`: **1709 passed, 3 skipped** (symlinks Windows, preexistentes); ruff+format+check.bat verdes.
- Rama creada: `feat/f6-v1-essential` desde `main@a792140`.
