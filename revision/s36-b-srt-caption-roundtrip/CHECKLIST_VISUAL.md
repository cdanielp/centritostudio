# CHECKLIST VISUAL — S36-B (para K)

Revisar los MP4 en `work/` tras correr el smoke. Todo es SINTÉTICO; el objetivo es
validar que el **texto del SRT manda** y que los tiempos se ven naturales.

Comando para extraer frames (opcional):

```powershell
$env:PYTHONIOENCODING="utf-8"
$W="revision\s36-b-srt-caption-roundtrip\work"
ffmpeg -y -i $W\s36b_fixture_clean_srt.mp4 -ss 0.6 -vframes 1 $W\f_cue1.png
ffmpeg -y -i $W\s36b_fixture_clean_srt.mp4 -ss 2.3 -vframes 1 $W\f_cue2.png
ffmpeg -y -i $W\s36b_fixture_clean_srt.mp4 -ss 3.8 -vframes 1 $W\f_cue3.png
ffmpeg -y -i $W\s36b_fixture_clean_srt.mp4 -ss 5.2 -vframes 1 $W\f_cue4.png
ffmpeg -y -i $W\clipA_clean_srt.mp4        -ss 0.2 -vframes 1 $W\f_clip.png
```

## Render principal (`s36b_fixture_clean_srt.mp4`)

1. [x] El texto visible coincide EXACTAMENTE con el SRT sintético.
2. [x] Acentos y puntuación preservados (`Hola,` `mundo.` `café` `está` `añadido`).
3. [x] No reaparece el texto equivocado de Whisper (se ve `prueba`, nunca `prueva`).
4. [x] Las palabras alineadas cambian de énfasis en momentos naturales.
5. [x] El cue 4 (`Texto añadido sin audio`) aparece **estático**, sin karaoke falso.
6. [x] No hay captions fuera de tiempo.
7. [x] No hay captions con tiempo negativo.
8. [x] No hay captions después del final del video.
9. [x] El cambio entre cues es limpio (sin flash del cue anterior).
10. [x] Multilínea (si aplica) legible.
11. [x] Safe zone 9:16 respetada.
12. [x] El estilo se ve consistente (aquí `clean`; Hormozi sigue igual sin `--srt`).
13. [x] Un preset CVE sigue funcionando (probar `--srt ... --preset clean_podcast`).
14. [x] Audio intacto.
15. [x] Video intacto.

## Clip derivado (`clipA_clean_srt.mp4`)

16. [x] El clip arranca en t=0.
17. [x] El SRT derivado coincide con el segmento del clip.
18. [x] El primer caption del clip no aparece antes de tiempo.
19. [x] El último caption no excede el clip.
20. [x] No hay flash de texto del cue anterior.

## Integridad

21. [x] El archivo fuente SRT quedó intacto (verificado por el smoke).
22. [x] El modo histórico SIN `--srt` produce el mismo resultado de siempre.
23. [x] No hay rutas ni texto privado en UI/log visible.

## Veredicto

- [x] **APROBADO** — K, 2026-07-18
- [ ] CAMBIOS
- [ ] RECHAZADO

## Notas de K (2026-07-18)

**VEREDICTO VISUAL: APROBADO.** S36-B aprobada técnica y visualmente.

Renders revisados:
- Render limpio (`s36b_fixture_clean_srt.mp4`): texto = SRT exacto, acentos y puntuación
  preservados, `prueba` (no `prueva`), cue 4 estático sin karaoke falso.
- Preset CVE + FX (`keyword_punch` + `express`): el énfasis word-by-word solo cae sobre
  los cues alineados; el cue fallback permanece estático.
- Clip derivado (`clipA_clean_srt.mp4`): arranca en t=0, el SRT rebasado coincide con el
  segmento, sin flash del cue anterior.

Audio **idéntico** entre renders (mismo `-c:a`, el habla no se re-muxea). Video intacto.
SRT fuente sin modificar. Sin rutas ni texto privado en logs/UI.

S36-B CERRADA. S36 sigue ABIERTA (S36-C pendiente).
