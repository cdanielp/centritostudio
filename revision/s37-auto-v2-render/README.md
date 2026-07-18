# S37-B — Modo Automatico v2: b-roll + FX end-to-end

Evidencia de revision del PR B de la fase **S37 — Wiring del Modo Automatico**.
Este PR **cambia salida visual** y por eso NO puede mergearse sin el veredicto de K
(ver `CHECKLIST_VISUAL.md`). Studio (PR C) queda fuera.

## 1. Objetivo

"Meto un video largo y obtengo clips 9:16 con captions, b-roll y FX sin escribir un
JSON manual." Conecta los motores existentes: clipper -> reframe -> brain ->
**BrollPlan (S37-A)** -> resolucion de assets -> arbitraje con manual + FX ->
render en un pase -> **verificacion A/V dura** -> paquete auditable.

## 2. Estado inicial

main en `243ab41` (S37-A mergeada), 915 passed / 1 skipped, check.bat verde.

## 3. Arquitectura

`auto.ejecutar_auto` sigue siendo el UNICO orquestador publico. Modulos aditivos:

| Modulo | Responsabilidad |
| --- | --- |
| `auto_config.py` | `AutoConfig` frozen + fingerprint SHA256 estable |
| `auto_v2.py` | Pipeline v2 de UN clip (coordinacion; import lazy solo en modo v2) |
| `auto_broll.py` | Manual intocable + resolucion imagen/video + reglas #47a/b |
| `auto_broll_io.py` | Materializacion `{stem}_popups.auto.json` + `{stem}_broll_resolved.json` |
| `auto_fx.py` | FX con motor existente + arbitraje #47e (eliminar, no desplazar) |
| `auto_av.py` | Integridad de audio (hash de paquetes) + sync A/V (#47d), errores tipados |

`auto.py` solo gana: import de `AutoConfig`, dispatch classic/v2 en el loop,
`_paquete_dir_v2` (paquetes `{name}_v2_{fecha}` con marker de fingerprint) y meta v2.
`auto_report.py` gana una seccion v2 que devuelve `[]` sin clips v2 (golden test).
`broll_plan_io.write_broll_plan` endurecido: temporal UNICO via `tempfile.mkstemp`
(excepcion autorizada; API intacta).

## 4. AutoConfig

`mode` (default **classic**), `broll_enabled`, `fx_enabled`, `fx_preset` (express),
`verify_av`, `manual_sidecars`, `target/max_coverage_pct`, `hook_protected_s`,
`max_video_windows` (0|1). Frozen, validada al construir, serializable, sin
callables/rutas/reloj/entorno. `fingerprint()` = SHA256 de `to_dict()` (incluye
`pipeline_version=2`) con `sort_keys` y separadores estables.

## 5. Compatibilidad clasica

`config=None` o `mode="classic"` = ruta historica EXACTA: sin planner, sin Pexels,
sin FX, sin sidecars S37, naming/checkpoint/reporte intactos. Los paquetes v2 se
excluyen del glob clasico (y viceversa). Cubierto por tests: import-spy (no se
importan `broll_*`/`fx`/`auto_v2`), bomba en la capa v2 (classic no la llama),
reporte sin seccion v2, meta sin campos v2, y los 915 tests previos sin cambios.

## 6. Pipeline v2 (orden exacto por clip)

reframe escenas -> copia de transcript rebasado -> brain fail-open -> groups
ORIGINALES al planner / groups enriquecidos (`apply_brain`) a captions ->
`get_video_info` -> `plan_broll` -> `{stem}_broll_plan.json` (overwrite=True) ->
manual (`cargar_popups_manual`+`cargar_clips_manual`, sin `resolver_popups` porque los
disparos por keyword no son intencion manual) -> resolucion auto de ventanas no
bloqueadas -> `{stem}_popups.auto.json` + `{stem}_broll_resolved.json` -> FX +
arbitraje -> ASS -> `burn_video_with_emojis` (emojis + popups + clips + FX, un pase)
-> `verificar_av` -> info/checkpoint. No re-transcribe ni re-llama al clipper.

## 7. Planner (S37-A intacto)

`broll_planner.py` no se toco. `broll_config_de(AutoConfig)` mapea target/max/hook/
max_video_windows; con `fx_enabled=False` pasa preset express (no se reserva outro).

## 8. Precedencia manual (#47b)

Intervalos `[start, end)`; tocar borde NO bloquea. Ventana auto que traslapa un
elemento manual RESUELTO -> `manual_precedence`, se omite ANTES de descargar. El
manual jamas se modifica (test de hash byte-a-byte). Clip manual ocupa el slot de
video: la ventana auto de video se degrada a imagen (`manual_video_occupies_slot`).

## 9. Resolver imagen

`broll_cutaway.resolver_cutaway_pexels` (fetcher existente): query del plan,
orientacion derivada del video, cover, size_pct 1.0, behind_text True, timestamps
exactos del plan. Metadata segura (provider/asset_id/author/dimensiones/basename);
sin URL, sin key, sin ruta absoluta. Error operativo -> omitida con codigo;
ValueError de contrato -> PROPAGA (bug de wiring).

## 10. Resolver video

`buscar_video_broll_seguro` (orden determinista) -> primer candidato con
`asset.duration >= window.duration_s` -> `descargar_video_asset` (cache del fetcher)
-> `ClipOverlay(t0/t1 del plan, source_start=0, loop=False, cutaway, cover,
size_pct=1.0, behind_text=True, mute=True)`. Maximo UN video (planner + slot manual).

## 11. Fallback (#47a)

NUNCA loop. Ningun candidato cubre -> imagen (`video_no_cover_fallback_image`).
Busqueda/descarga fallan -> imagen (`video_search/download_fallback_image`). El
fallback tambien falla -> omitida con AMBOS pasos (`fallback_image_failed`).

## 12. Cache (#47f)

`cache_policy = existing_fetcher_cache`: la cache de `broll_stock`/`broll_video_stock`
tal cual. Sin cache paralela. Sin keys/URLs firmadas en sidecars.

## 13. Sidecars (#47c)

Fuentes SEPARADAS: `{stem}_popups.json` (manual, intocable), `{stem}_broll_plan.json`
(plan S37-A), `{stem}_popups.auto.json` (solo lo que llego al render, formato
compatible con el manual, `source` = tipo FINAL real), `{stem}_broll_resolved.json`
(auditoria versionada con decision por ventana). El render combina EN MEMORIA; no
existe sidecar hibrido. Escritura atomica con temporal unico, UTF-8, newline final.

## 14–15. FX y arbitraje (#47e)

Motor existente (`fx.cargar_brain_fx`/`generar_plan_fx`); cero efectos nuevos.
`arbitrar_fx` (puro, no muta): punch `[t0,t1)`, flash `[t0,t0+dur)`, scanner `[t0,t1)`
que traslapan un cutaway se ELIMINAN (no se desplazan) con codigos
`punch/flash/scanner_removed_cutaway`. Logo/outro se conserva; conflicto manual en la
zona del outro -> warning `premium_outro_manual_conflict` (manual gana por intencion).

## 16. Capas

FX (zoompan/drawbox) ANTES del ass; b-roll behind_text ANTES del ass; captions
DESPUES (siempre encima); emojis y logo en su capa historica. Audio: SOLO `-map 0:a`
+ `-c:a copy`, sin amix/amerge; clips Pexels `mute=True` (contrato existente de
`core_overlays.construir_comando`, verificado por sus goldens y por la compuerta A/V).

## 17. Integridad de audio (#47d)

`ffprobe -show_packets -show_data_hash sha256` sobre `a:0` de fuente y salida: mismo
numero de paquetes, misma secuencia de hashes (payload puro, sin exigir PTS
identicos). Fallback documentado si no hubiera `data_hash`: extraccion `-c copy` a
ADTS (solo AAC, el codec del pipeline) + sha256 de bytes. Ambos sin audio -> PASS
`no_audio`; solo un lado -> FAIL. FAIL = `AudioIntegrityError` (RuntimeError): el
clip NO es valido, el checkpoint de exito no se escribe, jamas fail-open.

## 18. Sync A/V (#47d)

start de audio <=0.050s; duracion de audio <=0.050s; delta inicial A/V <=0.120s;
drift final <= max(0.120s, 2/fps_final). Metadata ausente -> fallback a
`format.duration`; irrecuperable -> `AVSyncError` (nunca PASS sin evidencia).

## 19. CFR 29.97

`demo_source_cfr_2997.mp4` con `r_frame_rate=30000/1001` verificado por ffprobe;
render v2 completo encima: A/V PASS.

## 20. VFR

`demo_source_vfr.mp4`: dos mitades (24000/1001 y 30000/1001) unidas con el FILTRO
`concat` + `-fps_mode passthrough` -> **2 deltas de PTS genuinamente distintos**
(~0.0417 y ~0.0334, verificados por ffprobe). Hallazgos documentados: el concat
DEMUXER con `-c copy`/passthrough fuerza los parametros del primer stream (corrompe
la duracion) y NO sirve como VFR real; el punch-in (zoompan) re-temporiza a fps fijo,
asi que el demo VFR corre con FX apagado — en el pipeline real el input del render
siempre es CFR (sale del reframe re-encodeado). A/V PASS sobre el VFR.

## 21. Checkpoints

Sidecar `.info.json` v2 agrega `pipeline_mode/pipeline_version/config_fingerprint` +
resumenes broll/fx/av. `checkpoint_v2_valido` exige: modo v2, fingerprint identico,
A/V en pass/no_audio, output presente y 3 sidecars presentes. Classic jamas pasa como
v2 ni al reves (paquetes separados por naming + marker `auto_v2.json`). Fingerprint
distinto -> paquete NUEVO (el anterior no se destruye; sufijo -N si coincide el minuto).

## 22. Fingerprint

SHA256 de config + pipeline_version, JSON estable (`sort_keys`, separadores fijos).
Sin rutas, sin reloj, sin progress, sin video path, sin API keys.

## 23. Paquete

`{name}_v2_{fecha}` + marker; REPORTE.md con seccion "Modo Automatico v2" (b-roll
planeado/resuelto, fallbacks, manual respetado, FX eliminados, A/V, sidecars);
paquete.json/meta con `pipeline_mode`, `config_fingerprint` y config serializada.
Classic: reporte byte-identico (la seccion v2 devuelve `[]`).

## 24. Tests

**133 nuevos** (48 auto_v2 + 37 auto_broll + 22 auto_fx + 26 auto_av); suite total
**1048 passed, 1 skipped**. Sin red (autouse bloquea sockets), sin GPU, sin Pexels,
sin Whisper/DeepSeek. El E2E usa ASS real + `burn_video_with_emojis` real + FFmpeg
real + `verificar_av` real sobre MP4 sintetico (216x384, 12s), con resolvers locales.

## 25. Evidencia

`gen_evidencia.py` -> `output/revision-s37b/` (no versionado): par principal
classic/v2, CFR 29.97 real, VFR real, auditoria completa (plan/popups.auto/resolved/
info/av por variante). Resumen ASCII final `RESULT: PASS`.

## 26. Comandos

```powershell
$env:PYTHONIOENCODING="utf-8"
venv\Scripts\python -m pytest -q tests/test_auto_v2.py tests/test_auto_broll.py tests/test_auto_fx.py tests/test_auto_av.py
venv\Scripts\python revision\s37-auto-v2-render\gen_evidencia.py
check.bat
```

## 27. Privacidad

Todo sintetico (lavfi + PIL): sin video real, sin transcript real, sin SRT real, sin
keys. Los sidecars no llevan URLs, rutas absolutas ni secretos. El smoke real con
PEXELS_API_KEY es OPCIONAL y no se ejecuto en esta sesion (no habia necesidad: la
compuerta valida es la suite local + fakes).

## 28. Riesgos (no bloqueantes)

- El punch-in (zoompan) exige input CFR; el pipeline real lo garantiza via reframe,
  pero un uso futuro del burn directo sobre VFR con FX debe pasar por la compuerta A/V
  (que lo detecta y aborta).
- La precedencia manual usa los elementos manuales RESUELTOS (lo que renderiza); una
  entrada manual rota (imagen faltante) no bloquea auto. Documentado; si K prefiere
  bloquear por INTENCION, es un ajuste menor de PR C.
- `caption_qa` en v2 es el mismo fail-open de classic (solo-lectura para el reporte).

## 29. Que no se toco

`brain.py`, `clipper*.py`, `reframe*.py`, `core.py`, `core_ass.py`, `core_overlays.py`,
`fx.py`, `styles.py`, `broll_planner.py` y todo `broll_plan_*` salvo el temp unico de
`broll_plan_io`, `broll_cutaway.py`, `broll_stock*.py`, `broll_video_*.py`,
`clip_overlay.py`, `cve_popups.py`, `cve_clips.py`, `assets_comfy.py`, `caption*.py`,
`jobs*.py`, `app.py`, `studio_packages.py`, `paquete_editor.py`, `static/index.html`,
`requirements.txt`. Cero dependencias nuevas.

## 30. Proximo PR

**S37-C** — exponer el Automatico v2 en Studio (toggle b-roll, preset FX), preview del
plan y apertura del paquete v2 en el Editor S35. **No implementado aqui.**
