# F5-s2 — sabor del suave 1.08 (s28D) · DECISION PENDIENTE DE K

**Contexto (D20):** K juzgo 1.30/1.45 (s28C) demasiado fuertes y prefiere el suave. Default
provisional = **suave 1.08 sin rebote**. Falta que K fije el sabor exacto viendo estos 2 MP4
EN MOVIMIENTO (el rebote no se ve en frame fijo — por eso no dejo frames, solo videos).

## Los 2 renders (mismo clip, en output/)

| Opcion | Archivo | Que es |
|---|---|---|
| (a) suave SIN rebote | `output/videolargo_clip1_largo_9x16_hormozi_suave_plano.mp4` | palabra crece a 108% y se queda (plano) |
| (b) suave CON rebote | `output/videolargo_clip1_largo_9x16_hormozi_suave_reb.mp4` | overshoot a ~121% y baja a 108% (rebotecito) |

Ambas reposan igual (108%, suave); la UNICA diferencia es el rebote de entrada. Mismo clip
base (grabacion de pantalla, 67.8s), transcript reutilizado, ~7.3s cada render.

Verificado en el .ass:
- plano: `\t(0,90,\fscx108)` — un tramo.
- reb:   `\t(0,70,\fscx121)\t(70,200,\fscx108)` — overshoot y asiento.

## Que decide K
Cual queda como default final del estilo hormozi (y del autopiloto): (a) plano o (b) con
rebote. Se aplica cambiando `overshoot` de hormozi en styles.py (una linea). Reproducible:
`caption.py <clip> --style hormozi --pop suave --rebote {off|on}`.
