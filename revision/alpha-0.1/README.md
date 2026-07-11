# Evidencia S34 — Smoke Alpha 0.1

**Fecha:** 2026-07-11 · **Sesión:** 34 · **Bloque:** B5

## 1. Modo Automático E2E (video real, ruta completa)

`auto.ejecutar_auto(input/pruebaedicionvideoyo.mov)` — 75s de video, grabación de
pantalla real de K (caso conocido #27: caras de contenido, sin webcam).

- **Paquete completo generado**: `output/paquetes/pruebaedicionvideoyo_20260711-1254/`
  (clip 9:16 con captions hormozi + REPORTE.md + paquete.json + sidecar .info.json).
- **Total 44.6s**: transcript reutilizado (0.1s, voto #10), análisis del clipper
  reutilizado ($0), brain del clip $0.0009, reframe+captions 44.6s.
- **REPORTE.md incluye Caption QA** (línea nueva s33/s34): "Caption QA: 0 alerta(s)
  de transcripción (0 aplicadas, 0 pendientes...)" — 0 alertas es honesto: este
  transcript no contiene errores del glosario. Copia: `REPORTE_smoke.md`.
- Aviso por tramos honesto: "2 personas en cuadro, el sistema solo siguió a una"
  (caras de contenido de la grabación, limitación conocida #27/#28).
- **Verificación con ojos del clip final** (frames a t=3s y t=26s, no commiteados
  porque el material fuente de K contiene contenido explícito de su herramienta de
  generación): captions visibles y sincronizados, énfasis IA aplicado (keywords
  "SEEDANCE" en verde y "SERÍA" en amarillo), 1080x1920 vertical correcto.

## 2. Ruta Studio (worker run_render) con y sin Caption QA

Sobre `qa_demo_s33` (video real + transcript sintético declarado de s33):

| Corrida | Resultado |
|---|---|
| `run_render` SIN QA | done en 3.1s, `qa_msg=None` — **flujo actual intacto** |
| `run_render` con `qa_mode=auto_seguro` | done en 3.0s, `qa_msg="Caption QA: 3 alerta(s), 2 aplicadas, 1 pendientes - detalle en transcripts/qa_demo_s33_caption_alerts.json"` |

- `frame_studio_autoseguro_comfyui.png` — **"COMFYUI" quemado** por la ruta Studio
  (verificado con ojos): la corrección alta se aplicó igual que en la CLI.
- `frame_studio_sinqa_confeti.png` — sin QA sigue diciendo "CONFETI UI" (baseline).
- `qa_demo_s33_caption_alerts.json` — sidecar con las 3 alertas (2 altas aplicadas,
  1 media pendiente del guion).

## 3. UI del Studio (B2/B4)

Checkbox "Revisar subtítulos con Caption QA" + selector de modo + campo de ruta de
guion en la pestaña Render; pestaña renombrada a "Modo Automático"; el resultado del
render muestra el mensaje QA. Validación visual de K en el navegador: pendiente, no
bloqueante (mismo precedente s22/s30) — el backend de la ruta está probado arriba y
por tests de contrato.

## Confirmaciones B5

- [x] Paquete completo se genera (Modo Automático real).
- [x] REPORTE.md incluye Caption QA.
- [x] Flujo sin Caption QA sigue funcionando (CLI smoke + run_render sin qa_mode).
- [x] auto_seguro probado también (ruta Studio, corrección quemada).
