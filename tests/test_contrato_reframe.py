"""Tests de contrato de la geometria de reframe (Fase 4.1 — sesion de disenio).

Verifican las matematicas deterministas del pipeline de reencuadre:
ventana de crop, EMA, deadzone, interpolacion, manejo de cara perdida.
Ningun test requiere video, OpenCV ni mediapipe.
Disenio: revision/fase-4.1/DISENO_REFRAME.md
"""

import pytest

import reframe_track as rt

# Resoluciones de referencia
SOURCE_W, SOURCE_H = 1920, 1080
CROP_W = SOURCE_H * 9 // 16  # 607 para 1080p


# ── calcular_ventana_crop ─────────────────────────────────────────────────────


def test_ventana_crop_centrada():
    x, y, w, h = rt.calcular_ventana_crop(960.0, SOURCE_W, SOURCE_H)
    assert y == 0
    assert h == SOURCE_H
    assert w == CROP_W
    assert x == (SOURCE_W - CROP_W) // 2  # 656


def test_ventana_crop_w_formula():
    _, _, w, h = rt.calcular_ventana_crop(960.0, SOURCE_W, SOURCE_H)
    assert w == SOURCE_H * 9 // 16
    assert h == SOURCE_H


def test_ventana_crop_clamped_izquierda():
    x, _, _, _ = rt.calcular_ventana_crop(0.0, SOURCE_W, SOURCE_H)
    assert x == 0


def test_ventana_crop_clamped_derecha():
    x, _, w, _ = rt.calcular_ventana_crop(float(SOURCE_W), SOURCE_W, SOURCE_H)
    assert x == SOURCE_W - CROP_W


def test_ventana_crop_y_siempre_cero():
    for cx in [0.0, 480.0, 960.0, 1440.0, 1920.0]:
        _, y, _, _ = rt.calcular_ventana_crop(cx, SOURCE_W, SOURCE_H)
        assert y == 0


def test_ventana_crop_720p():
    # Fuente 1280x720 -> crop_w = 720*9//16 = 405
    x, y, w, h = rt.calcular_ventana_crop(640.0, 1280, 720)
    assert w == 405
    assert h == 720
    assert y == 0
    assert 0 <= x <= 1280 - 405


# ── ema_smooth ────────────────────────────────────────────────────────────────


def test_ema_lista_vacia():
    assert rt.ema_smooth([], 0.1) == []


def test_ema_un_elemento():
    assert rt.ema_smooth([100.0], 0.1) == [100.0]


def test_ema_converge():
    pos = [0.0] * 20 + [100.0] * 80
    smooth = rt.ema_smooth(pos, 0.08)
    assert smooth[-1] > 90.0


def test_ema_alpha_uno_es_instantaneo():
    pos = [0.0, 50.0, 100.0, 75.0]
    assert rt.ema_smooth(pos, 1.0) == pos


def test_ema_monotono_en_rampa():
    pos = [float(i) for i in range(100)]
    smooth = rt.ema_smooth(pos, 0.1)
    for a, b in zip(smooth, smooth[1:], strict=False):
        assert b > a


# ── aplicar_deadzone ─────────────────────────────────────────────────────────


def test_deadzone_pequeno_no_mueve():
    # Cara se mueve 100px; deadzone_w=576px (30% de 1920) -> sigue en zona muerta
    result = rt.aplicar_deadzone(960.0 + 100.0, 960.0, deadzone_w=576.0)
    assert result == 960.0


def test_deadzone_grande_si_mueve():
    # Cara se mueve 400px -> sale de la zona muerta (>288px)
    result = rt.aplicar_deadzone(960.0 + 400.0, 960.0, deadzone_w=576.0)
    assert result == 960.0 + 400.0


def test_deadzone_exactamente_en_borde():
    # 288px = deadzone_w/2: exactamente en el limite -> NO debe moverse (condicion <=)
    result = rt.aplicar_deadzone(960.0 + 288.0, 960.0, deadzone_w=576.0)
    assert result == 960.0


def test_deadzone_un_pixel_fuera():
    # 289px > 288px: sale de la zona muerta
    result = rt.aplicar_deadzone(960.0 + 289.0, 960.0, deadzone_w=576.0)
    assert result == 960.0 + 289.0


def test_deadzone_secuencia_cara_quieta():
    # Cara quieta en 960 todo el tiempo -> cero movimiento de camara
    centers = [960.0] * 30
    targets = rt.aplicar_deadzone_secuencia(centers, deadzone_w=576.0)
    assert all(t == 960.0 for t in targets)


def test_deadzone_secuencia_vacia():
    assert rt.aplicar_deadzone_secuencia([], deadzone_w=576.0) == []


# ── interpolar_detecciones ───────────────────────────────────────────────────


def test_interpolar_vacia():
    result = rt.interpolar_detecciones({}, total_frames=10)
    assert result == [None] * 10


def test_interpolar_extremos():
    sparsa = {0: 100.0, 9: 200.0}
    result = rt.interpolar_detecciones(sparsa, total_frames=10)
    assert result[0] == 100.0
    assert result[9] == 200.0


def test_interpolar_lineal():
    sparsa = {0: 0.0, 4: 100.0}
    result = rt.interpolar_detecciones(sparsa, total_frames=5)
    assert result[2] == pytest.approx(50.0)


def test_interpolar_sin_relleno_fuera_de_rango():
    # Frames antes del primero y despues del ultimo: deben ser None
    sparsa = {2: 100.0, 4: 200.0}
    result = rt.interpolar_detecciones(sparsa, total_frames=7)
    assert result[0] is None
    assert result[1] is None
    assert result[5] is None
    assert result[6] is None


def test_interpolar_longitud():
    sparsa = {0: 0.0, 9: 100.0}
    result = rt.interpolar_detecciones(sparsa, total_frames=10)
    assert len(result) == 10


# ── manejar_cara_perdida ─────────────────────────────────────────────────────


def test_cara_perdida_dentro_de_patience():
    # Cara conocida en 0, perdida frames 1-5, patience=10 -> mantener ultimo
    raw: list[float | None] = [100.0] + [None] * 5
    result = rt.manejar_cara_perdida(raw, patience=10, source_center_x=960.0)
    assert len(result) == 6
    for v in result[1:]:
        assert v == pytest.approx(100.0)


def test_cara_perdida_supera_patience_recentra():
    # Cara conocida en 0.0, perdida 20 frames, patience=5 -> EMA hacia 960
    raw: list[float | None] = [0.0] + [None] * 20
    result = rt.manejar_cara_perdida(raw, patience=5, source_center_x=960.0)
    assert len(result) == 21
    assert result[5] == pytest.approx(0.0)  # todavia dentro de patience
    assert result[6] > 0.0  # primer frame de recentrado
    assert result[20] > result[10]  # se acerca monotonicamente al centro


def test_cara_perdida_recover():
    # Cara perdida y luego reaparece: el ultimo valor es el de la nueva deteccion
    raw: list[float | None] = [500.0] + [None] * 5 + [800.0]
    result = rt.manejar_cara_perdida(raw, patience=10, source_center_x=960.0)
    assert result[0] == 500.0
    assert result[-1] == 800.0


def test_cara_perdida_lista_sin_none():
    raw: list[float | None] = [100.0, 200.0, 300.0]
    result = rt.manejar_cara_perdida(raw, patience=10, source_center_x=960.0)
    assert result == [100.0, 200.0, 300.0]


def test_cara_perdida_recenter_alpha_parametrizable():
    # recenter_alpha=1.0 debe saltar al centro en el primer frame post-patience
    raw: list[float | None] = [0.0] + [None] * 10
    result = rt.manejar_cara_perdida(raw, patience=2, source_center_x=960.0, recenter_alpha=1.0)
    assert result[3] == pytest.approx(960.0)  # primer frame post-patience con alpha=1


# ── cara_en_frame (logica de turnos multi-cara) ──────────────────────────────

TURNOS_EJEMPLO = [
    {"t_ini": 0.0, "t_fin": 12.5, "cara_id": 0},
    {"t_ini": 12.5, "t_fin": 28.0, "cara_id": 1},
]


def test_cara_en_frame_dentro_primer_turno():
    assert rt.cara_en_frame(0, 30.0, TURNOS_EJEMPLO) == 0
    assert rt.cara_en_frame(100, 30.0, TURNOS_EJEMPLO) == 0  # t=3.33s


def test_cara_en_frame_corte_seco_exacto():
    # t_ini=12.5s == frame 375 exacto -> cara_id=1 (corte seco)
    assert rt.cara_en_frame(374, 30.0, TURNOS_EJEMPLO) == 0  # t=12.467s
    assert rt.cara_en_frame(375, 30.0, TURNOS_EJEMPLO) == 1  # t=12.5s


def test_cara_en_frame_fallback_sin_turno():
    # Frame fuera de todos los turnos -> cara_id=0 (fallback documentado)
    assert rt.cara_en_frame(9999, 30.0, TURNOS_EJEMPLO) == 0
    assert rt.cara_en_frame(0, 30.0, []) == 0


# ── calcular_crops_por_turnos (corte seco multi-cara) ────────────────────────

TURNOS_2CARAS = [
    {"t_ini": 0.0, "t_fin": 1.0, "cara_id": 0},
    {"t_ini": 1.0, "t_fin": 2.0, "cara_id": 1},
]


def test_calcular_crops_por_turnos_longitud():
    total = 60
    sparsa_multi = {0: {0: 700.0}, 1: {30: 1200.0}}
    crops = rt.calcular_crops_por_turnos(sparsa_multi, TURNOS_2CARAS, 30.0, total, 1920, 1080)
    assert len(crops) == total


def test_calcular_crops_por_turnos_corte_seco():
    # Cara 0 siempre a x=700, Cara 1 siempre a x=1200 (bien separadas)
    sparsa_multi = {
        0: {fi: 700.0 for fi in range(0, 30, rt.DETECT_EVERY_N)},
        1: {fi: 1200.0 for fi in range(30, 60, rt.DETECT_EVERY_N)},
    }
    crops = rt.calcular_crops_por_turnos(sparsa_multi, TURNOS_2CARAS, 30.0, 60, 1920, 1080)
    x_antes, *_ = crops[29]  # ultimo frame de turno 0 (cara a x=700)
    x_despues, *_ = crops[30]  # primer frame de turno 1 (cara a x=1200): corte seco
    assert x_despues > x_antes + 100  # salto significativo: no hay suavizado entre turnos


def test_calcular_crops_por_turnos_sin_datos_usa_default():
    # Sin detecciones: debe rellenar con center-crop default (no fallar)
    sparsa_multi: dict[int, dict[int, float]] = {0: {}, 1: {}}
    crops = rt.calcular_crops_por_turnos(sparsa_multi, TURNOS_2CARAS, 30.0, 60, 1920, 1080)
    assert len(crops) == 60
    for c in crops:
        assert len(c) == 4
