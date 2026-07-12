# Evidencia motor Submagic (nube) — S-Submagic-1

Reframe antes de subir (TAREA 1) + templates reales (TAREA 2).
Path ejercitado: `jobs.run_submagic_render` (el worker real del Studio).

## TAREA 1 — Reframe antes del upload
| etapa | dimensiones |
|-------|-------------|
| Clip horizontal original (`test_16_9.mp4`) | **1920x1080** |
| Archivo intermedio subido (`test_16_9_9x16_for_submagic.mp4`) | **1080x1920** |
| MP4 descargado de Submagic (`test_16_9_submagic.mp4`) | **1080x1920** |

Evidencia de reframe (del job.result): `{'origen': '1920x1080', 'aplicado': True, 'subido': '1080x1920', 'motivo': 'horizontal reencuadrado'}`

Demuestra: **horizontal 1920x1080 -> vertical 1080x1920 antes del upload -> vertical 1080x1920 descargado.**

## TAREA 2 — Templates reales
- Templates obtenidas desde la API (GET /v1/templates): **45**
- Muestra de nombres reales: `['Matt', 'Jess', 'Jack', 'Nick', 'Laura', 'Kelly 2', 'Claire', 'Michael', 'Caleb', 'Kendrick']`
- Template elegido para esta corrida: **Hormozi 2** (default fallback: Hormozi 2)
- JSON completo (sin secretos): `templates.json`

## Tiempos
- Upload: 3.7s
- Poll (transcripción + render en nube): 80.2s
- Descarga: 1.5s
- Total worker (incluye reframe local): 93.2s

## Garantías
- **NO pasó por caption.py ni core_ass.py**: `sin_caption_local=True`.
- FX intacto: el worker Submagic no llama al motor local de efectos.
- Key leída de `SUBMAGIC_API_KEY` (.env en .gitignore). Nunca impresa.
- MP4 no se commitea (output/ y *.mp4 en .gitignore); se adjunta frame.

## Traza del flujo real
```
[19:56:12] Clip fuente: test_16_9.mp4 dims=1920x1080 (320372 bytes)
[19:56:13] templates reales: 45 | muestra=['Matt', 'Jess', 'Jack', 'Nick', 'Laura', 'Kelly 2', 'Claire', 'Michael']
[19:56:13] template elegido: Hormozi 2
[19:57:46] reframe: {'origen': '1920x1080', 'aplicado': True, 'subido': '1080x1920', 'motivo': 'horizontal reencuadrado'}
[19:57:46] staged subido dims=1080x1920 | descargado dims=1080x1920
[19:57:46] tiempos_s={'upload': 3.7, 'poll': 80.2, 'download': 1.5} | total_worker=93.2s
[19:57:46] frame -> revision\submagic-s1\frame_resultado.png
```
