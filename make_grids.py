"""Genera cuadriculas 2x2 de comparacion de estilos para revision visual."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REVISION = Path("revision")
STYLES = ["hormozi", "karaoke", "bounce", "pms"]
CELL_W = 420  # ancho de cada celda en el grid
LABEL_H = 36
FONT_SIZE = 22

# Intentar fuente con soporte unicode, si no hay, usar default
try:
    FONT = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", FONT_SIZE)
except Exception:
    FONT = ImageFont.load_default()


def _load_frame(path: Path, cell_w: int) -> Image.Image:
    img = Image.open(path).convert("RGB")
    ratio = cell_w / img.width
    cell_h = int(img.height * ratio)
    return img.resize((cell_w, cell_h), Image.LANCZOS)


def make_2x2_grid(
    frames: dict[str, Path],  # {label: path}
    out_path: Path,
    title: str = "",
) -> None:
    """frames debe tener exactamente 4 entradas en orden."""
    labels = list(frames.keys())
    paths = list(frames.values())

    # Cargar y escalar
    imgs = [_load_frame(p, CELL_W) for p in paths]
    cell_h = imgs[0].height  # todos deben tener misma altura

    total_w = CELL_W * 2
    total_h = (cell_h + LABEL_H) * 2 + (50 if title else 0)

    canvas = Image.new("RGB", (total_w, total_h), (15, 15, 25))
    draw = ImageDraw.Draw(canvas)

    title_offset = 0
    if title:
        draw.text((10, 10), title, fill=(200, 200, 200), font=FONT)
        title_offset = 40

    positions = [
        (0, 0),
        (1, 0),
        (0, 1),
        (1, 1),
    ]

    for _i, ((col, row), img, label) in enumerate(zip(positions, imgs, labels, strict=False)):
        x = col * CELL_W
        y = title_offset + row * (cell_h + LABEL_H)

        # Etiqueta de fondo
        draw.rectangle([x, y, x + CELL_W, y + LABEL_H], fill=(30, 30, 50))
        label_color = {
            "hormozi": (255, 220, 0),
            "karaoke": (0, 220, 220),
            "bounce": (255, 130, 0),
            "pms": (180, 100, 255),
        }.get(label.lower(), (200, 200, 200))
        draw.text((x + 8, y + 7), label.upper(), fill=label_color, font=FONT)

        # Imagen
        canvas.paste(img, (x, y + LABEL_H))

    out_path.parent.mkdir(exist_ok=True)
    canvas.save(str(out_path), quality=92)
    print(f"[grid] Guardado: {out_path.name}")


def make_2col_grid(
    frame_a: Path,
    label_a: str,
    frame_b: Path,
    label_b: str,
    out_path: Path,
    title: str = "",
) -> None:
    """Grid 1x2 para comparar 2 variantes."""
    img_a = _load_frame(frame_a, CELL_W)
    img_b = _load_frame(frame_b, CELL_W)
    cell_h = max(img_a.height, img_b.height)

    total_w = CELL_W * 2
    total_h = cell_h + LABEL_H + (45 if title else 0)

    canvas = Image.new("RGB", (total_w, total_h), (15, 15, 25))
    draw = ImageDraw.Draw(canvas)

    title_offset = 0
    if title:
        draw.text((10, 10), title, fill=(200, 200, 200), font=FONT)
        title_offset = 38

    for x_off, img, label in [(0, img_a, label_a), (CELL_W, img_b, label_b)]:
        draw.rectangle(
            [x_off, title_offset, x_off + CELL_W, title_offset + LABEL_H], fill=(30, 30, 50)
        )
        draw.text((x_off + 8, title_offset + 7), label.upper(), fill=(200, 200, 200), font=FONT)
        canvas.paste(img, (x_off, title_offset + LABEL_H))

    canvas.save(str(out_path), quality=92)
    print(f"[grid] Guardado: {out_path.name}")


def main():
    videos = {
        "tacosjuan": 2,
        "reel01": 2,
        "reel02": 2,
        "reel03": 2,
    }

    for video, n_ts in videos.items():
        for ts_idx in range(1, n_ts + 1):
            frames = {}
            all_ok = True
            for style in STYLES:
                p = REVISION / f"{video}_{style}_t{ts_idx}.png"
                if not p.exists():
                    print(f"[FALTA] {p}")
                    all_ok = False
                else:
                    frames[style] = p

            if all_ok:
                out = REVISION / f"{video}_comparacion_t{ts_idx}.png"
                make_2x2_grid(frames, out, title=f"{video} — timestamp {ts_idx}")

    # Comparacion 2words vs grupo
    for ts_idx in (1, 2):
        p_2w = REVISION / f"tacosjuan_2words_t{ts_idx}.png"
        p_gr = REVISION / f"tacosjuan_grupo_t{ts_idx}.png"
        if p_2w.exists() and p_gr.exists():
            out = REVISION / f"tacosjuan_agrupacion_t{ts_idx}.png"
            make_2col_grid(
                p_2w,
                "2 palabras / grupo",
                p_gr,
                "4-6 palabras / grupo (auto)",
                out,
                title=f"tacosjuan hormozi — comparacion agrupacion t{ts_idx}",
            )

    print("[ok] Todas las cuadriculas generadas")


if __name__ == "__main__":
    main()
