# Checklist visual S37-B — Modo Automatico v2 (para K)

Genera la evidencia local (sin red, sin GPU, ~1 min):

```powershell
$env:PYTHONIOENCODING="utf-8"
venv\Scripts\python revision\s37-auto-v2-render\gen_evidencia.py
```

Salida en `output/revision-s37b/` (NO versionada). Los assets son sinteticos y
distinguibles a proposito: la imagen dice **"B-ROLL IMAGEN"** (naranja), el video de
b-roll dice **"B-ROLL VIDEO"** (barras en movimiento), la fuente es un patron animado.

## Linea de tiempo esperada (24s)

| Tiempo | Que debe verse |
| --- | --- |
| 0.0–3.0s | Solo fuente + captions (hook protegido, sin b-roll) |
| 4.0–8.5s | **B-ROLL VIDEO** en movimiento, captions encima |
| 10.0–13.5s | **B-ROLL IMAGEN** naranja, captions encima |
| ~15.5s y ~20.0s | Punch-in express visible (zoom sutil) sobre la fuente |
| resto | Fuente + captions |

## Pasos

1. Abrir `demo_auto_v2.mp4`.
2. Confirmar formato 9:16 (540x960).
3. Confirmar captions SIEMPRE visibles (tambien encima del b-roll).
4. Confirmar que el primer b-roll aparece DESPUES de los 3s (hook limpio).
5. Confirmar que la imagen entra y sale con fade limpio (10.0–13.5s).
6. Confirmar que el video de b-roll SE MUEVE (no es un frame congelado).
7. Confirmar que el video NO se congela al final de su ventana (vuelve a la fuente).
8. Confirmar que el video NO se repite (sin loop).
9. Confirmar ausencia de cuadros negros en entradas/salidas de cutaway.
10. Confirmar audio original CONTINUO todo el clip (tono constante, sin cortes).
11. Confirmar que NO se oye audio del b-roll (el clip va silenciado).
12. Confirmar punch-in express visible FUERA de los cutaways (~15.5s y ~20.0s).
13. Confirmar que NO hay punch/flash/scanner DURANTE los cutaways (fueron eliminados,
    no desplazados: `fx_removed=2` en el resumen).
14. Confirmar densidad razonable (2 ventanas en 24s, ~33%).
15. Comparar contra `demo_classic.mp4` (solo captions): mismo audio, mismos captions.
16. Revisar `auditoria/resolved.json` (decisiones por ventana, sin URLs ni secretos).
17. Revisar `auditoria/av.json` (integridad de audio + sync en PASS).
18. Repetir 1–13 con `demo_auto_v2_cfr_2997.mp4` (CFR 29.97 real) y
    `demo_auto_v2_vfr.mp4` (VFR real; este corre SIN FX: el punch-in exige CFR y en
    el pipeline real el input del render siempre sale del reframe re-encodeado).

## Veredicto

- [ ] APROBADO — K mergea el PR.
- [ ] CAMBIOS — anotar que ajustar; se corrige el PR sin merge.
- [ ] RECHAZADO — anotar razon; el PR no se mergea.
