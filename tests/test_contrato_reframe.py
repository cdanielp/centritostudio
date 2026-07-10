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
    # Cara conocida en frame 0, perdida frames 1-5 -> hold en 100.0
    raw: list[float | None] = [100.0] + [None] * 5
    result = rt.manejar_cara_perdida(raw, source_center_x=960.0)
    assert len(result) == 6
    for v in result[1:]:
        assert v == pytest.approx(100.0)


def test_cara_perdida_hold_indefinido():
    # Cara conocida en 0.0, perdida 20 frames -> hold en 0.0 siempre (sin recentrado)
    raw: list[float | None] = [0.0] + [None] * 20
    result = rt.manejar_cara_perdida(raw, source_center_x=960.0)
    assert len(result) == 21
    for v in result:
        assert v == pytest.approx(0.0)  # jamas se mueve hacia el centro


def test_cara_perdida_recover():
    # Cara perdida y luego reaparece: el ultimo valor es el de la nueva deteccion
    raw: list[float | None] = [500.0] + [None] * 5 + [800.0]
    result = rt.manejar_cara_perdida(raw, source_center_x=960.0)
    assert result[0] == 500.0
    assert result[-1] == 800.0


def test_cara_perdida_lista_sin_none():
    raw: list[float | None] = [100.0, 200.0, 300.0]
    result = rt.manejar_cara_perdida(raw, source_center_x=960.0)
    assert result == [100.0, 200.0, 300.0]


def test_cara_perdida_hold_nunca_recentra():
    # Incluso con muchos frames perdidos, la posicion se mantiene en la ultima conocida
    raw: list[float | None] = [100.0] + [None] * 50
    result = rt.manejar_cara_perdida(raw, source_center_x=960.0)
    assert all(v == pytest.approx(100.0) for v in result)


# ── calcular_alpha_fps (normalizacion por fps) ───────────────────────────────


def test_calcular_alpha_fps_en_referencia():
    # A 30fps (fps_ref), alpha efectivo debe ser identico al base
    assert rt.calcular_alpha_fps(0.08, 30.0) == pytest.approx(0.08)


def test_calcular_alpha_fps_60fps_menor():
    # A 60fps hay mas frames/s => alpha por frame debe ser MENOR para mantener el mismo tau real
    alpha_30 = rt.calcular_alpha_fps(0.08, 30.0)
    alpha_60 = rt.calcular_alpha_fps(0.08, 60.0)
    assert alpha_60 < alpha_30


def test_calcular_alpha_fps_nunca_supera_1():
    # Alpha efectivo siempre <= 1 para cualquier fps razonable
    assert rt.calcular_alpha_fps(0.08, 120.0) < 1.0
    assert rt.calcular_alpha_fps(1.0, 60.0) == pytest.approx(1.0)


# ── calcular_alpha_adaptativo + ema_smooth_adaptativo ────────────────────────

_DZ_W = 150.0   # deadzone_w de referencia (podcast 1920x1080 aprox)
_DZ_HALF = _DZ_W / 2  # 75.0


def test_alpha_adaptativo_invariante_reposo():
    # error <= dz_half => SIEMPRE alpha_base_lento (invariante de reposo)
    for error in [0.0, _DZ_HALF / 2, _DZ_HALF]:
        alpha = rt.calcular_alpha_adaptativo(error, _DZ_W, 30.0)
        assert alpha == pytest.approx(rt.calcular_alpha_fps(rt.ALPHA_BASE_LENTO, 30.0))


def test_alpha_adaptativo_maximo_en_umbral_rapido():
    # error = dz_half * RAMP_RAPIDO_FACTOR => alpha_base_rapido
    umbral_rapido = _DZ_HALF * rt.RAMP_RAPIDO_FACTOR
    alpha = rt.calcular_alpha_adaptativo(umbral_rapido, _DZ_W, 30.0)
    assert alpha == pytest.approx(rt.calcular_alpha_fps(rt.ALPHA_BASE_RAPIDO, 30.0))


def test_alpha_adaptativo_monotono():
    # alpha no decrece al aumentar el error
    errores = [0.0, 30.0, _DZ_HALF, _DZ_HALF * 1.5, _DZ_HALF * 2.0, _DZ_HALF * 3.0, 400.0]
    alphas = [rt.calcular_alpha_adaptativo(e, _DZ_W, 30.0) for e in errores]
    for i in range(len(alphas) - 1):
        assert alphas[i] <= alphas[i + 1] + 1e-9


def test_alpha_adaptativo_continuidad_borde_lento():
    # En el borde lento, limite izq e inter producen el mismo alpha (sin salto)
    e = _DZ_HALF * rt.RAMP_LENTO_FACTOR
    alpha_borde = rt.calcular_alpha_adaptativo(e, _DZ_W, 30.0)
    alpha_lento = rt.calcular_alpha_fps(rt.ALPHA_BASE_LENTO, 30.0)
    assert alpha_borde == pytest.approx(alpha_lento, rel=1e-6)


def test_alpha_adaptativo_continuidad_borde_rapido():
    # En el borde rapido, limite inter y regimen rapido producen el mismo alpha
    e = _DZ_HALF * rt.RAMP_RAPIDO_FACTOR
    alpha_borde = rt.calcular_alpha_adaptativo(e, _DZ_W, 30.0)
    alpha_rapido = rt.calcular_alpha_fps(rt.ALPHA_BASE_RAPIDO, 30.0)
    assert alpha_borde == pytest.approx(alpha_rapido, rel=1e-6)


def test_alpha_adaptativo_tau_fps():
    # El mismo error en distinto fps debe dar taus similares en segundos
    # (ambas bases normalizadas correctamente por calcular_alpha_fps)
    error = _DZ_HALF * 2.0  # en zona intermedia
    for fps in [24.0, 30.0, 60.0]:
        a = rt.calcular_alpha_adaptativo(error, _DZ_W, fps)
        tau_s = (1.0 / a) / fps
        # tau debe estar entre los taus de lento y rapido con ~10% tolerancia
        tau_lento = (1.0 / rt.calcular_alpha_fps(rt.ALPHA_BASE_LENTO, 30.0)) / 30.0
        tau_rapido = (1.0 / rt.calcular_alpha_fps(rt.ALPHA_BASE_RAPIDO, 30.0)) / 30.0
        assert tau_rapido * 0.9 <= tau_s <= tau_lento * 1.1


def test_ema_smooth_adaptativo_vacio():
    assert rt.ema_smooth_adaptativo([], 60.0, _DZ_W) == []


def test_ema_smooth_adaptativo_un_elemento():
    result = rt.ema_smooth_adaptativo([500.0], 30.0, _DZ_W)
    assert result == [500.0]


def test_ema_smooth_adaptativo_sin_movimiento():
    # Posiciones identicas: smooth permanece igual
    result = rt.ema_smooth_adaptativo([300.0] * 10, 30.0, _DZ_W)
    assert all(v == pytest.approx(300.0) for v in result)


def test_ema_smooth_adaptativo_gran_salto_converge():
    # Salto grande: el adaptativo debe converger mas rapido que el EMA fijo lento
    pos_lento = [0.0] + [500.0] * 30
    smooth_adapt = rt.ema_smooth_adaptativo(pos_lento, 60.0, _DZ_W)
    smooth_fijo = rt.ema_smooth(pos_lento, rt.calcular_alpha_fps(rt.ALPHA_BASE_LENTO, 60.0))
    # A mitad de la secuencia, adaptativo debe estar mas cerca del target
    assert smooth_adapt[15] > smooth_fijo[15]


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


# ── aplanar_conf_por_turnos (math puro) ──────────────────────────────────────

_TURNOS_CONF = [
    {"t_ini": 0.0, "t_fin": 1.0, "cara_id": 0},
    {"t_ini": 1.0, "t_fin": 2.0, "cara_id": 1},
]
_CONF_MULTI_EJ = {
    0: {0: 0.5, 3: 0.6, 27: 0.7},   # frames en turno 0 (f=0..29 a 30fps)
    1: {30: 0.8, 33: 0.9},            # frames en turno 1 (f=30..59)
}


def test_aplanar_conf_por_turnos_cara_correcta():
    # Frames del turno 0 usan confs de cara_id=0; turno 1 usa cara_id=1
    result = rt.aplanar_conf_por_turnos(_CONF_MULTI_EJ, _TURNOS_CONF, 30.0, 60)
    assert result[0] == pytest.approx(0.5)
    assert result[3] == pytest.approx(0.6)
    assert result[30] == pytest.approx(0.8)
    assert result[33] == pytest.approx(0.9)


def test_aplanar_conf_por_turnos_no_filtra_entre_turnos():
    # frame 27 pertenece al turno 0 (f_ini=0, f_fin=29 a 30fps) -- debe estar
    result = rt.aplanar_conf_por_turnos(_CONF_MULTI_EJ, _TURNOS_CONF, 30.0, 60)
    assert 27 in result


def test_aplanar_conf_por_turnos_vacio_sin_crash():
    # Sin detecciones: devuelve dict vacio
    result = rt.aplanar_conf_por_turnos({0: {}, 1: {}}, _TURNOS_CONF, 30.0, 60)
    assert result == {}
