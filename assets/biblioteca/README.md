# Biblioteca de popups — assets/biblioteca/

Imágenes del usuario que el pipeline puede superponer sobre el video
(capa `image_popups` del caption_viral_engine, F6 S31 — diseño en
`revision/fase-6/DISENO_CVE.md` §3.2 y §5).

## Formato

- **PNG o WebP con transparencia** (canal alpha). Otros formatos se ignoran.
- **El nombre del archivo ES el id** (sin extensión): `flecha.png` → id `flecha`.
- Los ids se sanitizan: minúsculas, sin acentos, solo `a-z 0-9 _ -`.
  `Acción!.png` → id `accion`. Dos archivos que colisionan en el mismo id:
  gana el primero en orden alfabético (se loguea).
- Biblioteca vacía o carpeta ausente **no rompe nada**: la capa se omite con log.

## Cómo se dispara un popup (v1)

1. **Manual por timestamp** — `transcripts/{stem}_popups.json`:

   ```json
   [
     {"t": 12.5, "imagen": "flecha", "dur": 1.2, "pos": "top_right"},
     {"t": 0.0,  "png": "biblioteca/logo.png", "dur": 2.0, "behind_text": true}
   ]
   ```

   - `t` (obligatorio): segundo de aparición. `t: 0` = inicio del clip.
   - `imagen`: id de esta biblioteca, o `png`: ruta relativa a `assets/`.
   - `dur` (opcional, default 1.2s), `pos` (opcional, ver posiciones),
     `behind_text` (opcional: el popup queda DEBAJO de los captions).
   - Entrada inválida o imagen faltante = esa entrada se omite con log;
     JSON roto = solo se pierden los popups manuales. Jamás rompe el render.

2. **Por keyword** — si una palabra del transcript coincide con un id de la
   biblioteca (`magia.png` + la palabra "magia"), el popup aparece en el
   timestamp de esa palabra (primera aparición por id).

Los popups manuales tienen prioridad sobre los de keyword. Máximo 1 popup
simultáneo (default v1): si dos se solapan en el tiempo, el de menor
prioridad se desactiva con log.

## Posiciones

9 anclas: `top_left`, `top`, `top_right`, `left`, `center`, `right`,
`bottom_left`, `bottom`, `bottom_right` — todas dentro de la zona útil
(fuera de la UI de TikTok/Reels/Shorts, §5.1). Default: `auto_safe`
(centrado, arriba del bloque de captions). Si un popup no cabe se aplica
la cadena reducir → mover → simplificar → desactivar (§5.3).

## Cómo se usa

```powershell
.\venv\Scripts\python caption.py output\clips\clip.mp4 --popups
```

ComfyUI NO se requiere para esta capa: las imágenes son locales.
