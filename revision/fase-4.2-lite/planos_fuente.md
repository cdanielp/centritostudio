# Inventario de planos — podcast_test_60s.mp4

**Fuente:** `input/podcast_test_60s.mp4` (60.03s, 1920x1080, 60fps)
**Deteccion:** `ffmpeg select='gt(scene,0.25)'` + muestreo MediaPipe 3 pts/plano
**Cortes:** umbral=0.25 — todos los scores detectados >=0.877 (cortes de escena duros)

---

## Tabla de planos

| # | t_ini | t_fin | dur | score_corte | n_caras_ini | n_caras_mid | n_caras_fin | notas |
|---|-------|-------|-----|------------|-------------|-------------|-------------|-------|
| 0 | 0.00s | 1.95s | 1.95s | — | 2 | 1 | 1 | 2 caras al inicio, luego 1 |
| 1 | 1.95s | 22.17s | 20.22s | 0.878 | 1 | 1 | 1 | UNA SOLA CARA cx≈1090-1123 |
| 2 | 22.17s | 24.13s | 1.96s | 0.879 | 1 | 1 | 1 | corto, 1 cara |
| 3 | 24.13s | 41.07s | 16.94s | 0.884 | 1* | 1 | 1 | *1 cara real (ver nota) |
| 4 | 41.07s | 44.62s | 3.55s | 1.000 | 2 | 2 | 1 | caras cambian |
| 5 | 44.62s | 49.33s | 4.71s | 0.885 | 1 | 1 | 1 | 1 cara |
| 6 | 49.33s | 51.38s | 2.05s | 0.886 | 1 | 1 | 1 | 1 cara |
| 7 | 51.38s | 60.03s | 8.65s | 1.000 | 2† | 2† | 2† | †doble deteccion (ver nota) |

### Notas criticas

**Plano 3 — la "2 caras" al inicio era un artefacto del borde de corte:**
Muestreo denso (11 puntos) confirma 1 sola cara en todo el plano:
- cx≈1074-1123 en todos los puntos muestreados
- La deteccion doble en t_ini+0.1s (t=24.23s) coincide con el artefacto de motion blur del corte

**Plano 7 — doble deteccion de la MISMA persona:**
Las dos "caras" tienen cx muy proximos: ['936','946'], ['870','963'], etc.
No son dos personas en posiciones separadas (cx=719 y cx=1362) sino la misma
persona detectada dos veces por MediaPipe (common false positive en angulos laterales).

---

## Candidatos para stack >= 15s con 2 caras reales

| Plano | dur | 2 caras reales | candidato? |
|-------|-----|----------------|-----------|
| 1 | 20.22s | NO (1 cara) | NO |
| 3 | 16.94s | NO (1 cara real) | NO |
| 7 | 8.65s | NO (doble det. misma persona) | NO — ademas dur < 15s |

**Conclusion:** ningun plano en el clip de 60s tiene 2 caras DISTINTAS de forma continua
durante >=15s. El clip es material EDITADO con cortes entre planos de personas diferentes.
Tarea 3b aplica: K aportara fuente de toma fija con 2 personas.

---

## Cruce retrospectivo: cortes vs tramos C2 y HOLD de s15

| Evento | t_ini | t_fin | corte cercano | delta | interpretacion |
|--------|-------|-------|--------------|-------|----------------|
| C2 tramo 1 | 2.73s | 4.70s | corte en 1.95s | 0.78s antes | cam entra zona tras corte, no causal directo |
| C2 tramo 2 | 9.13s | 10.12s | ninguno ±5s | >5s | movimiento natural de cara en plano continuo |
| C2 tramo 3 | 19.18s | 22.18s | corte en 22.17s | **0.01s** | **tramo TERMINA exactamente en el corte** |
| C2 tramo 4 | 24.98s | 41.98s | cortes en 24.13s y 41.07s | 0.85s / 0.91s | plano nuevo post-corte genera/cierra zona |
| HOLD t=54-60s | 54.00s | 60.03s | corte en 51.38s | 2.62s antes | nuevo plano tiene caras a cx≈870-1010 (fuera del gate de ancla=1362) => 0 detecciones => HOLD |

**Causa raiz del HOLD en t=54-60s (diagostico anterior era incompleto):**
El corte en t=51.38s introduce un plano con la persona a cx≈870-1010, que esta
FUERA del gate del ancla (ancla_0=1362, gate=288px => zona valida [1074,1650]).
Todas las detecciones post-corte son rechazadas por el gate => HOLD desde t=51.38s.
La distancia cam=1182, face=1134 vista en el diagnostico es residual de la posicion
pre-corte. La causa NO es la deteccion debil de cara_1; es la falta de detecciones
validas de cara_0 porque la cara migro fuera del gate tras el corte de escena.
