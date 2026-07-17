"""Tests de contrato del b-roll cutaway (imagen grande) sobre core_overlays + cve_popups.

Contratos verificados:
- Un popup HISTORICO (sin cutaway) conserva su geometria y comportamiento (xy en px, size).
- Un cutaway genera composicion CENTRADA ((W-w)/2, (H-h)/2) fuera de la zona util.
- contain preserva la imagen entera SIN deformar; cover llena el cuadro con crop proporcional.
- Funciona en resolucion horizontal y vertical.
- t0/t1 (ventana temporal) y fade siguen presentes en el filter graph.
- fit invalido -> fail-open a 'contain' con advertencia ASCII.
- Declaracion manual (cve_popups): cutaway sin behind_text -> captions encima; explicito se respeta.
- Convivencia con captions y otros overlays (emojis) en el mismo pase FFmpeg.
- FFmpeg real (skip si no hay binarios): la salida conserva resolucion y duracion.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import core_overlays as co
import cve_popups as cp

PNG_BYTES = b"\x89PNG mock"


def _png(tmp_path: Path, name: str = "broll.png") -> Path:
    p = tmp_path / name
    p.write_bytes(PNG_BYTES)
    return p


def _biblioteca(tmp_path: Path, nombres: list[str]) -> Path:
    d = tmp_path / "biblioteca"
    d.mkdir()
    for n in nombres:
        (d / n).write_bytes(PNG_BYTES)
    return d


# ── B1: popup historico intacto ──────────────────────────────────────────────


def test_popup_historico_conserva_comportamiento(tmp_path):
    p = co.Popup(png=_png(tmp_path), t0=1.0, t1=2.0, pos="top_right")  # sin cutaway
    prep = co._preparar_popup(p, 1080, 1920, y_auto=1200)
    assert prep is not None
    assert "size" in prep and not prep.get("cutaway"), (
        "popup normal: geometria de ancho, no cutaway"
    )
    assert isinstance(prep["x"], int) and isinstance(prep["y"], int), "popup normal: xy en pixeles"


# ── Default de size_pct resuelto en __post_init__ (None -> 0.20 / 0.85) ───────


def test_size_pct_default_popup_normal(tmp_path):
    p = co.Popup(png=_png(tmp_path), t0=0.0, t1=2.0)  # sin cutaway, sin size_pct
    assert p.size_pct == co.POPUP_SIZE_PCT == 0.20, "omitido + normal -> 0.20"


def test_size_pct_default_cutaway(tmp_path):
    p = co.Popup(png=_png(tmp_path), t0=0.0, t1=2.0, cutaway=True)  # sin size_pct
    assert p.size_pct == co.CUTAWAY_SIZE_PCT == 0.85, (
        "omitido + cutaway -> 0.85 (via __post_init__)"
    )


def test_size_pct_explicito_020_en_cutaway_se_conserva(tmp_path):
    p = co.Popup(png=_png(tmp_path), t0=0.0, t1=2.0, cutaway=True, size_pct=0.20)
    assert p.size_pct == 0.20, "valor explicito (incluso 0.20) NO se sobrescribe con el default"


def test_popup_llamada_posicional_historica(tmp_path):
    png = _png(tmp_path)
    # Firma historica posicional: png, t0, t1, pos, size_pct, behind_text, fade.
    p = co.Popup(png, 1.0, 3.0, "top_right", 0.30, True, False)
    assert (p.png, p.t0, p.t1, p.pos) == (png, 1.0, 3.0, "top_right")
    assert p.size_pct == 0.30 and p.behind_text is True and p.fade is False
    assert p.cutaway is False and p.fit == "contain", "campos nuevos: solo al final, con default"


# ── B2: cutaway centrado ─────────────────────────────────────────────────────


def test_cutaway_composicion_centrada(tmp_path):
    p = co.Popup(png=_png(tmp_path), t0=1.0, t1=3.0, cutaway=True, size_pct=0.85)
    prep = co._preparar_popup(p, 1080, 1920, y_auto=1200)
    assert prep["cutaway"] is True
    assert prep["x"] == "(W-w)/2" and prep["y"] == "(H-h)/2", "centrado exacto en runtime"
    assert prep["box_w"] == 918 and prep["box_h"] == 1632, "0.85 del cuadro, pares"


# ── B3: aspecto preservado ───────────────────────────────────────────────────


def test_cutaway_contain_preserva_aspecto_sin_deformar():
    f = co._filtro_png_cutaway(1, 800, 800, "contain", 1.0, 3.0, 0.2, "pf0")
    assert "force_original_aspect_ratio=decrease" in f, "contain: imagen entera dentro de la caja"
    assert "crop=" not in f, "contain no recorta"


def test_cutaway_cover_llena_y_recorta():
    f = co._filtro_png_cutaway(1, 1080, 1920, "cover", 0.0, 2.0, 0.2, "pf0")
    assert "force_original_aspect_ratio=increase" in f, "cover: escala proporcional para llenar"
    assert "crop=1080:1920" in f, "cover: recorta el excedente al cuadro"


# ── B4/B5: horizontal y vertical ─────────────────────────────────────────────


def test_cutaway_horizontal_full_frame(tmp_path):
    p = co.Popup(png=_png(tmp_path), t0=0.0, t1=2.0, cutaway=True, size_pct=1.0, fit="cover")
    prep = co._preparar_popup(p, 1920, 1080, y_auto=700)
    assert prep["box_w"] == 1920 and prep["box_h"] == 1080, "cubre el cuadro horizontal"


def test_cutaway_vertical_full_frame(tmp_path):
    p = co.Popup(png=_png(tmp_path), t0=0.0, t1=2.0, cutaway=True, size_pct=1.0)
    prep = co._preparar_popup(p, 1080, 1920, y_auto=1200)
    assert prep["box_w"] == 1080 and prep["box_h"] == 1920, "cubre el cuadro vertical"


# ── B6: t0/t1 + fade en el filter graph ──────────────────────────────────────


def test_cutaway_t0_t1_y_fade_en_filtergraph(tmp_path):
    p = co.Popup(png=_png(tmp_path), t0=2.0, t1=5.0, cutaway=True, size_pct=0.85, behind_text=True)
    cmd = co.construir_comando(
        Path("in.mp4"), "x.ass", Path("out.mp4"), [], 216, 1300, 0.12, 1080, 1920, [p]
    )
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "between(t,2.000,5.000)" in fc, "ventana temporal t0/t1 presente"
    assert "fade=t=in:st=0:d=0.200" in fc and "fade=t=out" in fc, "fade in/out presente"


# ── B7: valor invalido de fit ────────────────────────────────────────────────


def test_cutaway_fit_invalido_cae_a_contain(tmp_path, capsys):
    p = co.Popup(png=_png(tmp_path), t0=0.0, t1=2.0, cutaway=True, fit="diagonal", size_pct=0.85)
    prep = co._preparar_popup(p, 1080, 1920, y_auto=1200)
    assert prep["fit"] == "contain", "fail-open documentado a contain"
    out = capsys.readouterr().out
    assert "fit 'diagonal' desconocido" in out, "advertencia accionable"
    assert out.isascii(), "log ASCII (consola Windows)"


def test_cutaway_size_pct_mayor_a_uno_se_recorta(tmp_path, capsys):
    p = co.Popup(png=_png(tmp_path), t0=0.0, t1=2.0, cutaway=True, size_pct=1.5)
    prep = co._preparar_popup(p, 1080, 1920, y_auto=1200)
    assert prep["box_w"] == 1080 and prep["box_h"] == 1920, "size_pct>1.0 -> pantalla completa"
    assert capsys.readouterr().out.isascii()


def test_cutaway_size_pct_no_positivo_desactiva(tmp_path, capsys):
    p = co.Popup(png=_png(tmp_path), t0=0.0, t1=2.0, cutaway=True, size_pct=0.0)
    assert co._preparar_popup(p, 1080, 1920, y_auto=1200) is None, (
        "size_pct<=0 -> desactivado (fail-open)"
    )
    out = capsys.readouterr().out
    assert "size_pct<=0" in out and out.isascii(), "aviso ASCII, el render sigue sin el cutaway"


# ── Convivencia con captions y otros overlays ────────────────────────────────


def test_cutaway_convive_con_emoji_y_captions(tmp_path):
    emoji = _png(tmp_path, "emoji.png")
    broll = _png(tmp_path, "broll.png")
    p = co.Popup(png=broll, t0=3.0, t1=6.0, cutaway=True, size_pct=0.85, behind_text=True)
    cmd = co.construir_comando(
        Path("in.mp4"),
        "x.ass",
        Path("out.mp4"),
        [(emoji, 1.0, 2.2)],
        216,
        1300,
        0.12,
        1080,
        1920,
        [p],
    )
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "ass=x.ass" in fc and "[vcap][ovs0]" in fc, "cadena de emojis + ass intacta"
    assert fc.index("pb0") < fc.index("ass="), "cutaway behind -> captions/emoji encima"


# ── Declaracion manual (cve_popups) ──────────────────────────────────────────


def test_cutaway_manual_sin_behind_text_captions_encima(tmp_path):
    biblio = cp.indexar_biblioteca(_biblioteca(tmp_path, ["broll.png"]))
    data = [{"t": 1.0, "imagen": "broll", "dur": 2.0, "cutaway": True}]
    (tmp_path / "x_popups.json").write_text(json.dumps(data), encoding="utf-8")
    popups = cp.cargar_popups_manual(tmp_path / "x_popups.json", biblio)
    assert len(popups) == 1
    assert popups[0].cutaway is True
    assert popups[0].behind_text is True, "cutaway sin behind_text -> captions encima"
    assert popups[0].size_pct == co.CUTAWAY_SIZE_PCT, (
        "tamano default 0.85 aplicado en la declaracion"
    )
    cmd = co.construir_comando(
        Path("in.mp4"), "x.ass", Path("out.mp4"), [], 216, 1300, 0.12, 1080, 1920, popups
    )
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert fc.index("pb0") < fc.index("ass="), "compuesto ANTES del ass"


def test_cutaway_manual_behind_text_false_respetado(tmp_path):
    biblio = cp.indexar_biblioteca(_biblioteca(tmp_path, ["broll.png"]))
    data = [{"t": 1.0, "imagen": "broll", "dur": 2.0, "cutaway": True, "behind_text": False}]
    (tmp_path / "x_popups.json").write_text(json.dumps(data), encoding="utf-8")
    popups = cp.cargar_popups_manual(tmp_path / "x_popups.json", biblio)
    assert popups[0].behind_text is False, "behind_text explicito se respeta"
    cmd = co.construir_comando(
        Path("in.mp4"), "x.ass", Path("out.mp4"), [], 216, 1300, 0.12, 1080, 1920, popups
    )
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert fc.index("ass=") < fc.index("pf0"), "front -> compuesto DESPUES del ass"


def test_cutaway_manual_cover_full_frame_crop(tmp_path):
    biblio = cp.indexar_biblioteca(_biblioteca(tmp_path, ["broll.png"]))
    data = [
        {"t": 0.0, "imagen": "broll", "dur": 2.0, "cutaway": True, "fit": "cover", "size_pct": 1.0}
    ]
    (tmp_path / "x_popups.json").write_text(json.dumps(data), encoding="utf-8")
    popups = cp.cargar_popups_manual(tmp_path / "x_popups.json", biblio)
    prep = co._preparar_popup(popups[0], 1080, 1920, y_auto=1200)
    assert prep["box_w"] == 1080 and prep["box_h"] == 1920
    f = co._filtro_png_cutaway(1, prep["box_w"], prep["box_h"], prep["fit"], 0.0, 2.0, 0.2, "pf0")
    assert "force_original_aspect_ratio=increase" in f and "crop=1080:1920" in f


def test_cutaway_manual_contain_sin_deformacion(tmp_path):
    biblio = cp.indexar_biblioteca(_biblioteca(tmp_path, ["broll.png"]))
    data = [{"t": 0.0, "imagen": "broll", "dur": 2.0, "cutaway": True, "fit": "contain"}]
    (tmp_path / "x_popups.json").write_text(json.dumps(data), encoding="utf-8")
    popups = cp.cargar_popups_manual(tmp_path / "x_popups.json", biblio)
    prep = co._preparar_popup(popups[0], 1080, 1920, y_auto=1200)
    f = co._filtro_png_cutaway(1, prep["box_w"], prep["box_h"], prep["fit"], 0.0, 2.0, 0.2, "pf0")
    assert "force_original_aspect_ratio=decrease" in f, "conserva la imagen entera"
    assert "crop=" not in f, "sin recorte -> sin deformacion"


def test_popup_manual_historico_sin_cutaway_intacto(tmp_path):
    biblio = cp.indexar_biblioteca(_biblioteca(tmp_path, ["flecha.png"]))
    data = [{"t": 3.0, "imagen": "flecha", "dur": 2.0, "pos": "top_right"}]
    (tmp_path / "x_popups.json").write_text(json.dumps(data), encoding="utf-8")
    popups = cp.cargar_popups_manual(tmp_path / "x_popups.json", biblio)
    assert popups[0].cutaway is False and popups[0].fit == "contain"
    assert popups[0].behind_text is False, "popup historico: default sin cambios"
    assert popups[0].size_pct == co.POPUP_SIZE_PCT


# ── Verificacion FFmpeg (determinista, sin red ni assets externos) ───────────


def test_cutaway_ffmpeg_conserva_resolucion_y_duracion(tmp_path):
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("ffmpeg/ffprobe no disponible")
    import pysubs2  # noqa: PLC0415

    w, h, dur = 320, 240, 2
    src = tmp_path / "src.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=blue:s={w}x{h}:d={dur}:r=25",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={dur}",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(src),
        ],
        capture_output=True,
    )
    assert src.exists() and src.stat().st_size > 0

    png = tmp_path / "broll.png"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=100x300:d=1",
            "-frames:v",
            "1",
            str(png),
        ],
        capture_output=True,
    )
    assert png.exists()

    # ass relativo al cwd del proceso (como en produccion): sin drive-colon que el
    # parser de filter_complex confunda con la opcion original_size.
    pysubs2.SSAFile().save(str(tmp_path / "empty.ass"))
    ass_esc = "empty.ass"

    out = tmp_path / "out.mp4"
    p = co.Popup(png=png, t0=0.0, t1=1.5, cutaway=True, size_pct=1.0, fit="cover")
    cmd = co.construir_comando(src, ass_esc, out, [], 216, 100, 0.12, w, h, [p])
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(tmp_path))
    assert r.returncode == 0, r.stderr[-800:]
    assert out.exists() and out.stat().st_size > 0

    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    meta = json.loads(probe.stdout)
    assert meta["streams"][0]["width"] == w and meta["streams"][0]["height"] == h, (
        "resolucion intacta"
    )
    assert abs(float(meta["format"]["duration"]) - dur) < 0.5, "duracion conservada"
