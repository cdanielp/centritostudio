# S32 — keyword_punch: filtro anti-débil + marcado manual v1 (validación)

Clip fuente: `output/clips/videolargo_clip1_largo_9x16.mp4` (1080x1920, 9:16, grabación
de pantalla PMS). Transcript + brain reutilizados (voto #10). Preset `keyword_punch`
`--intensidad viral` (145 + glow = **energía clásica preferida por K**, D22, regla #15).

## Renders (en `output/`, gitignored — locales)

| Archivo | Qué es | Estado |
|---|---|---|
| `videolargo_clip1_largo_9x16_keyword_punch.mp4` | **VIEJO** preferido por K (s29) | **INTACTO, no sobrescrito** |
| `videolargo_clip1_largo_9x16_keyword_punch_clean.mp4` | variante sobria (s31) | INTACTO |
| `videolargo_clip1_largo_9x16_keyword_punch_classic_s32.mp4` | **classic con filtro anti-débil** (S32) | nuevo |
| `videolargo_clip1_largo_9x16_keyword_punch_manual_s32.mp4` | **classic + marcado manual v1** (S32) | nuevo |

## BLOQUE 4.1 — classic con filtro anti-stopword

`classic_keyword_selection.json`: keywords finales = **kit, parece, carpeta, PNG**
(todas de contenido). El filtro D22 descartó **12 stopwords del brain**
(en, un, la, en, a, un, con, esta, como, todo, o, vas) — antes (s31 clean) entraban
"en" y "un". `kit` y `PNG` (3 chars, dominio) **sobreviven**: el filtro débil solo
corta 1-2 chars, los stopwords se cazan por lista.

Frames: `classic_kit_2s.png`, `classic_carpeta_18s.png`.

## BLOQUE 4.2 — marcado manual v1

`ejemplo_manual_keywords.json` (vive en `transcripts/{stem}_keywords.json`):
`workflow` (big), `magia`, `custom`. `manual_keyword_selection.json` confirma:
- `workflow` → `manual_big` (fuente manual), `magia` y `custom` → `manual`.
- **manual gana**: en "ahora algo que parece **magia** para", el brain había elegido
  "parece"; el manual forzó "magia" (frame `manual_magia_9s.png`).
- **manual_big + stopword**: en "para reabrir **un** workflow", `un` queda en blanco
  (stopword) y `WORKFLOW` se destaca grande (frame `manual_workflow_12s.png`).
- Los manuales están **exentos del freno de densidad** (9 keywords vs tope auto 4).

## BLOQUE 4.3 — clean vs classic (mismo instante, "CARPETA" @18.7s)

`clean_carpeta_18s.png` (130, sin glow) vs `classic_carpeta_18s.png` (145 + glow):
en classic "CARPETA" es más grande y con halo/glow verde; en clean es más chica y
sin halo. Verificado con ojos: la energía del classic es claramente mayor.

## Confirmaciones

- image_popups **APROBADO** por K (D22).
- keyword_punch **viejo NO sobrescrito** (bytes intactos).
- keyword_punch sigue **opt-in, nunca default** (D21/D22).
- Motores (reframe/clipper/depurador/brain) **no tocados** — solo lectura del brain.json.
