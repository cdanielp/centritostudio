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

1. [ ] El texto visible coincide EXACTAMENTE con el SRT sintético.
2. [ ] Acentos y puntuación preservados (`Hola,` `mundo.` `café` `está` `añadido`).
3. [ ] No reaparece el texto equivocado de Whisper (se ve `prueba`, nunca `prueva`).
4. [ ] Las palabras alineadas cambian de énfasis en momentos naturales.
5. [ ] El cue 4 (`Texto añadido sin audio`) aparece **estático**, sin karaoke falso.
6. [ ] No hay captions fuera de tiempo.
7. [ ] No hay captions con tiempo negativo.
8. [ ] No hay captions después del final del video.
9. [ ] El cambio entre cues es limpio (sin flash del cue anterior).
10. [ ] Multilínea (si aplica) legible.
11. [ ] Safe zone 9:16 respetada.
12. [ ] El estilo se ve consistente (aquí `clean`; Hormozi sigue igual sin `--srt`).
13. [ ] Un preset CVE sigue funcionando (probar `--srt ... --preset clean_podcast`).
14. [ ] Audio intacto.
15. [ ] Video intacto.

## Clip derivado (`clipA_clean_srt.mp4`)

16. [ ] El clip arranca en t=0.
17. [ ] El SRT derivado coincide con el segmento del clip.
18. [ ] El primer caption del clip no aparece antes de tiempo.
19. [ ] El último caption no excede el clip.
20. [ ] No hay flash de texto del cue anterior.

## Integridad

21. [ ] El archivo fuente SRT quedó intacto (verificado por el smoke).
22. [ ] El modo histórico SIN `--srt` produce el mismo resultado de siempre.
23. [ ] No hay rutas ni texto privado en UI/log visible.

## Veredicto

- [ ] APROBADO
- [ ] CAMBIOS
- [ ] RECHAZADO

Notas de K:

_________________________________________________________________
