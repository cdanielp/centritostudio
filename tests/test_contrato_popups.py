"""Tests de contrato de image_popups v1 (F6 S31): cve_popups + core_overlays.

Contratos verificados:
- La biblioteca indexa PNG/WebP con ids sanitizados; vacia/ausente no rompe.
- Disparo por keyword (palabra == id) y por timestamp (popups.json manual).
- popups.json invalido o entradas invalidas no rompen (fail-open, se omiten).
- Maximo 1 popup simultaneo: manual gana a keyword.
- Safe zones: las 9 anclas caen dentro de la zona util; pos invalida cae a auto_safe.
- Cadena de conflicto minima: REDUCIR (no cabe), SIMPLIFICAR (sin fade), DESACTIVAR.
- Sin popups, el comando FFmpeg de la ruta de emojis es BYTE-IDENTICO al historico.
- behind_text compone el popup ANTES del filtro ass (captions encima).
"""

from __future__ import annotations

import json
from pathlib import Path

import core_overlays as co
import cve_popups as cp

PNG_BYTES = b"\x89PNG mock"


def _biblioteca(tmp_path: Path, nombres: list[str]) -> Path:
    d = tmp_path / "biblioteca"
    d.mkdir()
    for n in nombres:
        (d / n).write_bytes(PNG_BYTES)
    return d


# ── sanitizar_id / indexar_biblioteca ────────────────────────────────────────


def test_sanitizar_id():
    assert cp.sanitizar_id("Acción!.PNG"[:-4]) == "accion"
    assert cp.sanitizar_id("MAGIA") == "magia"
    assert cp.sanitizar_id("flecha_roja-2") == "flecha_roja-2"
    assert cp.sanitizar_id("¿?¡!") == ""


def test_indexar_biblioteca(tmp_path):
    d = _biblioteca(tmp_path, ["Magia.png", "flecha.webp", "notas.txt"])
    index = cp.indexar_biblioteca(d)
    assert set(index) == {"magia", "flecha"}, "solo PNG/WebP, ids sanitizados"
    assert index["magia"].name == "Magia.png"


def test_indexar_biblioteca_ausente_devuelve_vacio(tmp_path):
    assert cp.indexar_biblioteca(tmp_path / "no_existe") == {}


def test_indexar_biblioteca_colision_primera_gana(tmp_path):
    d = _biblioteca(tmp_path, ["MAGIA.png", "magia.webp"])
    index = cp.indexar_biblioteca(d)
    assert index["magia"].name == "MAGIA.png", "orden alfabetico: primera gana"


# ── disparo por keyword ──────────────────────────────────────────────────────


def test_popups_por_keyword(tmp_path):
    d = _biblioteca(tmp_path, ["magia.png"])
    groups = [
        {"words": [{"text": "pura", "start": 1.0}, {"text": "MAGIA,", "start": 2.5}]},
        {"words": [{"text": "magia", "start": 9.0}]},  # segunda aparicion: no dispara
    ]
    popups = cp.popups_por_keyword(groups, cp.indexar_biblioteca(d))
    assert len(popups) == 1, "primera aparicion por id"
    assert popups[0].t0 == 2.5
    assert popups[0].t1 == 2.5 + cp.POPUP_DURATION_S


# ── popups.json manual ───────────────────────────────────────────────────────


def test_cargar_popups_manual(tmp_path):
    d = _biblioteca(tmp_path, ["flecha.png"])
    biblioteca = cp.indexar_biblioteca(d)
    data = [{"t": 3.0, "imagen": "flecha", "dur": 2.0, "pos": "top_right"}]
    path = tmp_path / "x_popups.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    popups = cp.cargar_popups_manual(path, biblioteca)
    assert len(popups) == 1
    assert popups[0].t0 == 3.0 and popups[0].t1 == 5.0
    assert popups[0].pos == "top_right"


def test_popups_json_invalido_no_rompe(tmp_path):
    path = tmp_path / "x_popups.json"
    path.write_text("{esto no es json", encoding="utf-8")
    assert cp.cargar_popups_manual(path, {}) == []


def test_entradas_invalidas_se_omiten(tmp_path):
    d = _biblioteca(tmp_path, ["flecha.png"])
    biblioteca = cp.indexar_biblioteca(d)
    data = [
        {"t": 1.0, "imagen": "flecha"},  # valida
        {"imagen": "flecha"},  # sin t
        {"t": 2.0, "imagen": "no_existe"},  # imagen faltante
        "no soy un objeto",  # tipo invalido
        {"t": 4.0, "imagen": "flecha", "pos": "marte"},  # pos invalida -> auto_safe
    ]
    path = tmp_path / "x_popups.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    popups = cp.cargar_popups_manual(path, biblioteca)
    assert len(popups) == 2, "solo las entradas validas sobreviven"
    assert popups[1].pos == "auto_safe"


# ── resolver_popups (cascada + frenos) ───────────────────────────────────────


def test_resolver_sin_biblioteca_no_rompe(tmp_path):
    groups = [{"words": [{"text": "magia", "start": 1.0}]}]
    popups = cp.resolver_popups(
        groups, "x", transcripts_dir=tmp_path, biblioteca_dir=tmp_path / "nada"
    )
    assert popups == []


def test_max_un_simultaneo_manual_gana(tmp_path):
    d = _biblioteca(tmp_path, ["magia.png", "flecha.png"])
    (tmp_path / "x_popups.json").write_text(
        json.dumps([{"t": 2.0, "imagen": "flecha", "dur": 2.0}]), encoding="utf-8"
    )
    groups = [{"words": [{"text": "magia", "start": 2.5}]}]  # solapa con el manual
    popups = cp.resolver_popups(groups, "x", transcripts_dir=tmp_path, biblioteca_dir=d)
    assert len(popups) == 1
    assert popups[0].png.name == "flecha.png", "manual gana a keyword en el solape"


def test_simplificar_fade_si_dur_corta(tmp_path):
    d = _biblioteca(tmp_path, ["magia.png"])
    (tmp_path / "x_popups.json").write_text(
        json.dumps([{"t": 1.0, "imagen": "magia", "dur": 0.15}]), encoding="utf-8"
    )
    popups = cp.resolver_popups([], "x", transcripts_dir=tmp_path, biblioteca_dir=d)
    assert len(popups) == 1
    assert popups[0].fade is False, "SIMPLIFICAR: muy corto para fade -> sin animacion"


# ── safe zones y anclas (core_overlays) ──────────────────────────────────────


def test_anclas_dentro_de_zona_util():
    w, h, size = 1080, 1920, 216
    x0, y0, x1, y1 = co.zona_util(w, h)
    for pos in sorted(co.ANCLAS) + ["auto_safe"]:
        x, y = co.calcular_xy(pos, w, h, size, y_auto=1200)
        assert x0 <= x <= x1 - size, f"{pos}: x={x} fuera de zona util"
        assert y0 <= y <= y1 - size, f"{pos}: y={y} fuera de zona util"


def test_pos_invalida_cae_auto_safe():
    x_bad, y_bad = co.calcular_xy("marte", 1080, 1920, 216, y_auto=1200)
    x_auto, y_auto = co.calcular_xy("auto_safe", 1080, 1920, 216, y_auto=1200)
    assert (x_bad, y_bad) == (x_auto, y_auto)


def test_auto_safe_clampa_a_zona_util():
    _x, y = co.calcular_xy("auto_safe", 1080, 1920, 216, y_auto=1900)  # bajo la UI
    _x0, y0, _x1, y1 = co.zona_util(1080, 1920)
    assert y == y1 - 216, "auto_safe fuera de zona util se recorta (MOVER)"
    assert y >= y0


def test_preparar_popup_reduce_si_no_cabe(tmp_path):
    png = tmp_path / "grande.png"
    png.write_bytes(PNG_BYTES)
    p = co.Popup(png=png, t0=1.0, t1=2.0, size_pct=0.95)  # 95% > zona util (81%)
    prep = co._preparar_popup(p, 1080, 1920, y_auto=1200)
    x0, _y0, x1, _y1 = co.zona_util(1080, 1920)
    assert prep is not None
    assert prep["size"] <= x1 - x0, "REDUCIR: el popup baja hasta caber"


def test_preparar_popup_desactiva_si_falta_imagen(tmp_path):
    p = co.Popup(png=tmp_path / "no_existe.png", t0=1.0, t1=2.0)
    assert co._preparar_popup(p, 1080, 1920, y_auto=1200) is None


# ── comando FFmpeg: ruta emojis byte-identica + popups ───────────────────────


def _cmd_emojis_legacy(input_video, ass_esc, output_video, overlays, size_px, y_px, fade):
    """Replica literal del constructor historico de burn_video_with_emojis (pre-S31).

    NO EDITAR: copia congelada del codigo en el commit 3f2509e — es el golden que
    garantiza que la ruta de emojis sin popups no cambia ni un byte.
    """
    cmd = ["ffmpeg", "-y", "-i", str(input_video)]
    for png, t_start, t_end in overlays:
        dur = max(t_end - t_start, 0.1)
        cmd += ["-loop", "1", "-t", f"{dur:.3f}", "-i", str(png)]
    fc_parts = [f"[0:v]ass={ass_esc}[vcap]"]
    for i, (_png, t_start, t_end) in enumerate(overlays):
        dur = max(t_end - t_start, 0.1)
        fade_out_st = max(dur - fade, 0.0)
        fc_parts.append(
            f"[{i + 1}:v]format=rgba,scale={size_px}:-2,"
            f"fade=t=in:st=0:d={fade:.3f}:alpha=1,"
            f"fade=t=out:st={fade_out_st:.3f}:d={fade:.3f}:alpha=1,"
            f"setpts=PTS-STARTPTS+{t_start:.3f}/TB[ovs{i}]"
        )
    current = "[vcap]"
    for i, (_png, t_start, t_end) in enumerate(overlays):
        next_label = f"[vo{i}]"
        enable = f"between(t,{t_start:.3f},{t_end:.3f})"
        fc_parts.append(
            f"{current}[ovs{i}]overlay=x=(W-w)/2:y={y_px}:"
            f"eof_action=pass:enable='{enable}'{next_label}"
        )
        current = next_label
    cmd += ["-filter_complex", ";".join(fc_parts)]
    cmd += ["-map", current, "-map", "0:a"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "copy"]
    cmd.append(str(output_video))
    return cmd


def test_comando_emojis_sin_popups_byte_identico(tmp_path):
    overlays = [(tmp_path / "a.png", 1.0, 2.2), (tmp_path / "b.png", 5.0, 6.2)]
    args = (Path("in.mp4"), "out/x.ass", Path("out.mp4"), overlays, 216, 1300, 0.12)
    esperado = _cmd_emojis_legacy(*args)
    obtenido = co.construir_comando(*args, video_w=1080, video_h=1920, popups=None)
    assert obtenido == esperado, "sin popups la cadena de emojis no cambia ni un byte"
    tambien = co.construir_comando(*args, video_w=1080, video_h=1920, popups=[])
    assert tambien == esperado


def test_comando_popup_front(tmp_path):
    png = tmp_path / "flecha.png"
    png.write_bytes(PNG_BYTES)
    p = co.Popup(png=png, t0=3.0, t1=4.5, pos="top_right")
    cmd = co.construir_comando(
        Path("in.mp4"), "x.ass", Path("out.mp4"), [], 216, 1300, 0.12, 1080, 1920, [p]
    )
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "[0:v]ass=x.ass[vcap]" in fc
    assert fc.index("ass=") < fc.index("pf0"), "popup front se compone DESPUES del ass"
    assert cmd[cmd.index("-map") + 1] == "[vp0]"
    assert str(png) in cmd


def test_comando_popup_behind_text(tmp_path):
    png = tmp_path / "logo.png"
    png.write_bytes(PNG_BYTES)
    p = co.Popup(png=png, t0=0.0, t1=2.0, pos="center", behind_text=True)
    cmd = co.construir_comando(
        Path("in.mp4"), "x.ass", Path("out.mp4"), [], 216, 1300, 0.12, 1080, 1920, [p]
    )
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "[vb0]ass=x.ass[vcap]" in fc, "el ass se aplica SOBRE el resultado del popup"
    assert fc.index("pb0") < fc.index("ass="), "popup behind se compone ANTES del ass"
    assert cmd[cmd.index("-map") + 1] == "[vcap]"


def test_comando_emojis_y_popups_conviven(tmp_path):
    e_png = tmp_path / "emoji.png"
    p_png = tmp_path / "popup.png"
    e_png.write_bytes(PNG_BYTES)
    p_png.write_bytes(PNG_BYTES)
    p = co.Popup(png=p_png, t0=8.0, t1=9.0, pos="bottom_left")
    cmd = co.construir_comando(
        Path("in.mp4"),
        "x.ass",
        Path("out.mp4"),
        [(e_png, 1.0, 2.2)],
        216,
        1300,
        0.12,
        1080,
        1920,
        [p],
    )
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "[1:v]" in fc and "[2:v]" in fc, "emoji = input 1, popup = input 2"
    assert "[vcap][ovs0]" in fc, "cadena de emojis intacta"
    assert "[vo0][pf0]" in fc, "el popup se encadena tras el ultimo emoji"
    assert cmd[cmd.index("-map") + 1] == "[vp0]"


# ── burn_video_with_emojis: flujo anterior intacto ───────────────────────────


def test_burn_sin_overlays_ni_popups_delega_en_burn_video(monkeypatch, tmp_path):
    import core_ass

    llamado = []
    monkeypatch.setattr(core_ass, "burn_video", lambda *a: llamado.append(a) or 1.0)
    r = core_ass.burn_video_with_emojis(
        tmp_path / "in.mp4", tmp_path / "x.ass", tmp_path / "out.mp4", [], None, None
    )
    assert llamado and r == 1.0, "sin emojis ni popups delega en burn_video (flujo anterior)"
