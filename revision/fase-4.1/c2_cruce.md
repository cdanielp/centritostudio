# C2 × CARA — Cruce de Trayectoria noturnos s13

**Fuente:** `revision/fase-4.1/trayectoria_podcast_test_60s_noturnos_s13.csv`
**Nota:** el CSV tiene `t, cam_center_x, face_x_asignada, distancia`. Confianza y
area del bbox NO estan disponibles en el CSV — requieren un log de deteccion separado
que no se genero en la sesion 13. Los valores reportados usan `face_x_asignada`
(posicion rellena por hold/interpolacion, no la deteccion cruda).

---

## Estadisticas globales

| Metrica | Valor |
|---------|-------|
| Total frames | 3602 (60.02s, 60fps) |
| Zona C2 [900-1100] | 1514 frames (42.0%) |
| En zona: dist ≤80px | **1514 / 1514 = 100%** |
| En zona: dist  >80px | **0 / 1514 = 0%** |
| Distancia media en zona | 20.2px |
| face_x media en zona | 1104.5px |
| face_x rango en zona | [1073.5, 1168.7]px |

**Confianza media en zona C2:** N/A — no capturada en el CSV.
Referencia de la sesion 13: cara_id=0 (ancla=1362) tiene score ≈0.40 en el scan
inicial con ambas caras presentes; score sube a ≈0.40-0.70 cuando aparece sola.

---

## Tramos continuos en zona C2 (>0.5s)

| # | t_ini | t_fin | dur | dist_media | face_x_rango |
|---|-------|-------|-----|-----------|--------------|
| 1 | 2.20s | 4.63s | 2.43s | 25.7px | [1077, 1169] |
| 2 | 8.53s | 10.08s | 1.55s | 13.0px | [1074, 1166] |
| 3 | 18.43s | 22.17s | 3.73s | 18.7px | [1083, 1136] |
| 4 | 24.40s | 41.92s | 17.52s | 20.4px | [1074, 1160] |

Tramo 4 (17.52s) es el dominante. En todos los tramos la distancia media es <30px —
la camara sigue una cara real, no esta "varada" en el vacio.

---

## C2v2 provisional

```
C2v2 = frames con (cam en [900,1100]) Y (dist > 80px) / total
     = 0 / 3602
     = 0.0%
```

**Interpretacion:** en el 100% de frames donde la camara entra en la zona
[900,1100], hay una cara asignada a ≤80px. La camara no esta parqueada en el
vacio — esta siguiendo la cara derecha (ancla=1362) cuando esta se inclina hacia
su extremo izquierdo natural (posiciones x=[1074-1169]).

El C2 original falla al 42% porque la cara REAL llega a esa zona. El bug de
drift de sesion 12 (camara instalada en el vacio por detecciones intermedias)
fue corregido en sesion 13.

---

## Dato de face_x en zona

La cara derecha orbita en x=[1074, 1169] durante los 4 tramos. El solapamiento
con la zona ancla [1074, 1650] y la zona C2 [900, 1100] es:

```
Solapamiento C2 ∩ zona-ancla: [1074, 1100] = 26px
face_x visto en zona C2:      [1074, 1169]
```

La camara entra en C2 solo cuando la cara esta en su extremo izquierdo natural
([1074, 1100]). No es drift: es la cara moviendose al borde de su zona valida.

---

## Archivos generados

- `c2_cruce.md` — este reporte
- `c2_cruce_detalle.csv` — frame-a-frame con columnas: t, cam_center_x,
  face_x_asignada, distancia, en_c2 (0/1), dist_le_80 (0/1), tramo_id (1-4, 0=fuera)
