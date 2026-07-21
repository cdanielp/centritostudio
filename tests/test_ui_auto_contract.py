"""Contratos semanticos de la UI S37-C sin Playwright ni dependencias nuevas."""

from pathlib import Path

HTML = (Path(__file__).parents[1] / "static" / "index.html").read_text(encoding="utf-8")


def test_modos_y_default_classic_visibles():
    assert 'id="auto-mode" value="classic"' in HTML
    assert 'data-auto-mode="classic"' in HTML and 'data-auto-mode="v2"' in HTML
    assert "Clásico" in HTML and "Automático v2" in HTML


def test_controles_v2_y_presets_exactos():
    for token in ('id="auto-broll-enabled"', 'id="auto-fx-enabled"', 'id="auto-fx-preset"'):
        assert token in HTML
    for preset in ('value="express"', 'value="pro"', 'value="premium"'):
        assert preset in HTML


def test_av_fijo_visible_sin_toggle_y_plan_honesto():
    assert "Audio verificado" in HTML and "Verificación A/V obligatoria" in HTML
    assert "auto-verify-av" not in HTML
    assert "El plan temporal real se calcula por clip después del análisis." in HTML


def test_request_v2_envia_solo_parametros_publicos():
    assert "new URLSearchParams({objetivo, mode})" in HTML
    for param in ("broll_enabled", "fx_enabled", "fx_preset"):
        assert f"params.set('{param}'" in HTML
    for forbidden in ("fingerprint", "target_coverage", "hook_protected", "max_video_windows"):
        assert f"params.set('{forbidden}'" not in HTML


def test_resultado_v2_y_editor_reutilizado():
    assert "AUTO V2" in HTML and "renderAutoV2Clip" in HTML
    assert "B-roll" in HTML and "Integridad A/V" in HTML and "Eliminados" in HTML
    assert HTML.count("function openPaqueteEnEditor(") == 1
    assert "openPaqueteEnEditor('${esc(pkgId)}',${i})" in HTML
    assert "c.brain_ok===true?'disponible'" in HTML and "_diagN(b.planned)" in HTML


def test_progreso_empieza_en_transcripcion_y_classic_conserva_tarjeta_historica():
    assert "if (pct < 20) return 'Transcripción';" in HTML
    assert "if (pct < 5) return 'Preparando';" not in HTML
    assert 'style="border:var(--border);border-radius:8px;padding:12px"' in HTML


def test_datos_no_confiables_se_escapan():
    assert "avisos.map(escHtml)" in HTML
    assert "escHtml(c.titulo || c.archivo)" in HTML
    assert "encodeURIComponent(pkgId)" in HTML and "encodeURIComponent(c.archivo)" in HTML


def test_markers_broll_y_responsive_sin_ancho_fijo_peligroso():
    assert ".mk-tag.broll_image" in HTML and ".mk-tag.broll_video" in HTML
    assert "broll_image: 'B-roll imagen'" in HTML and "broll_video: 'B-roll video'" in HTML
    assert "@media (max-width:620px)" in HTML
    assert ".auto-mode-grid,.auto-summary-list,.auto-diag-grid{grid-template-columns:1fr}" in HTML
    assert "overflow-x:hidden" in HTML


def test_polling_reactiva_controles_si_se_pierde_conexion():
    # H2: pollJob es ahora una capa adapter sobre el motor compartido con fallo SEGURO por defecto
    # (cierra P1-POLL-1). Sigue re-habilitando los controles de Auto y conservando el mensaje.
    assert "function pollJob(jid, cb, interval = 900, onFailure = null)" in HTML
    assert "jobPoller.track(" in HTML
    assert "setAutoControlsLocked(false);" in HTML
    assert "Se perdió la conexión con el Studio." in HTML


def test_no_hay_endpoint_publico_de_sidecars():
    assert "/api/sidecar" not in HTML and "/broll_resolved.json" not in HTML
