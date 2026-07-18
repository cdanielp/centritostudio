"""auto_report.py - Reporte de calidad del Modo Automatico (funciones PURAS).

Split de auto.py (s34 B1, sin cambio de comportamiento): aqui vive la traduccion
de metricas del motor a lenguaje humano (avisos por tramos, resumen de paquete,
REPORTE.md). auto.py re-exporta estos nombres para compatibilidad.

s34 Alpha 0.1: el reporte se hace legible para testers no tecnicos (estado por
clip, detalle de Caption QA inline, linea global de emojis, recomendacion final,
tiempo total en m/s). NO se toca el pipeline ni se re-renderiza: solo texto.
"""

from __future__ import annotations

# Umbral de aviso para C1v2 en tramos single (heuristica inicial, D17)
C1V2_AVISO = 80.0

STYLE_AUTO = "hormozi"  # estilo del paquete v1 (95/100 de K en s26, D16)

# Estados por clip, de menor a mayor severidad (Alpha 0.1). Sin acentos: el
# resto del REPORTE.md ya es ASCII (Duracion/Telemetria/REVISION), se mantiene.
ESTADO_LISTO = "LISTO"
ESTADO_AVISO = "LISTO CON AVISO"
ESTADO_REVISION = "REQUIERE REVISION"
ESTADO_NO_PUBLICAR = "NO PUBLICAR AUN"
_SEVERIDAD = {ESTADO_LISTO: 0, ESTADO_AVISO: 1, ESTADO_REVISION: 2, ESTADO_NO_PUBLICAR: 3}

# Cuantas detecciones de Caption QA se listan inline antes de remitir al JSON.
_MAX_ALERTAS_REPORTE = 6


def _fmt_t(segundos: float) -> str:
    """0:39 a partir de 39.2. Puro."""
    m, s = divmod(int(segundos), 60)
    return f"{m}:{s:02d}"


def _fmt_ms(segundos: float) -> str:
    """Duracion humana: '15s', '2m 15s'. Puro (para tiempo total, Alpha 0.1)."""
    m, s = divmod(int(round(segundos)), 60)
    return f"{s}s" if m == 0 else f"{m}m {s:02d}s"


def avisos_de_segmentos(segmentos: list[dict]) -> list[dict]:
    """Traduce el seg_reporte del modo escenas a avisos humanos. Puro.

    Entrada: entradas {t_ini, t_fin, tipo, n_caras, c1v2, ...} tal como las
    devuelve reframe_escenas (via reframe_clip result['segmentos']).
    Salida: [{t_ini, t_fin, tipo, texto}] solo para tramos que requieren revision.
    El 'tipo' (multi/none/seguimiento) alimenta la recomendacion final.
    """
    avisos = []
    for s in segmentos:
        rango = f"{_fmt_t(s['t_ini'])}-{_fmt_t(s['t_fin'])}"
        if s.get("tipo") == "multi":
            avisos.append(
                {
                    "t_ini": s["t_ini"],
                    "t_fin": s["t_fin"],
                    "tipo": "multi",
                    "texto": (
                        f"revisa {rango}: {s.get('n_caras', 2)} personas en cuadro, "
                        "el sistema solo siguio a una"
                    ),
                }
            )
        elif s.get("tipo") == "none":
            avisos.append(
                {
                    "t_ini": s["t_ini"],
                    "t_fin": s["t_fin"],
                    "tipo": "none",
                    "texto": f"revisa {rango}: sin cara detectada, encuadre centrado fijo",
                }
            )
        elif s.get("c1v2") is not None and s["c1v2"] < C1V2_AVISO:
            avisos.append(
                {
                    "t_ini": s["t_ini"],
                    "t_fin": s["t_fin"],
                    "tipo": "seguimiento",
                    "texto": (
                        f"revisa {rango}: el seguimiento pudo perder a la persona "
                        f"(fiabilidad {s['c1v2']:.0f}%)"
                    ),
                }
            )
    return avisos


def estado_clip(c: dict) -> str:
    """Semaforo de un clip para testers no tecnicos. Puro.

    - NO PUBLICAR AUN: no hay metricas de tramos (clip reutilizado sin re-render);
      no se puede avalar el encuadre a ciegas.
    - REQUIERE REVISION: hay avisos de encuadre/seguimiento que un humano debe ver.
    - LISTO CON AVISO: el video esta bien encuadrado pero Caption QA detecto texto
      que quiza convenga corregir a mano.
    - LISTO: sin avisos de tramos ni detecciones de transcripcion pendientes.
    """
    if not c.get("tramos_disponibles", True):
        return ESTADO_NO_PUBLICAR
    if c.get("avisos"):
        return ESTADO_REVISION
    qa = c.get("qa") or {}
    if qa.get("pendientes", 0) > 0:
        return ESTADO_AVISO
    return ESTADO_LISTO


def _severidad(estado: str) -> int:
    return _SEVERIDAD.get(estado, 9)


def resumen_paquete(clips_info: list[dict]) -> str:
    """Resumen de una linea para el Studio. Puro.

    Ej.: "2 clips listos, 1 con aviso (clip 2 en 0:16)".
    """
    n = len(clips_info)
    if n == 0:
        return "0 clips generados"
    con_aviso = [(i + 1, c) for i, c in enumerate(clips_info) if c.get("avisos")]
    if not con_aviso:
        return f"{n} clip(s) listos, sin avisos"
    partes = [f"clip {i} en {_fmt_t(c['avisos'][0]['t_ini'])}" for i, c in con_aviso]
    return f"{n} clip(s) listos, {len(con_aviso)} con aviso ({', '.join(partes)})"


def _clip_usa_emojis(c: dict) -> bool:
    """True si el clip lleva overlays/emojis reales (msg tipo 'N overlay(s)'). Puro."""
    msg = c.get("emojis_msg", "")
    return bool(msg) and msg[0].isdigit() and not msg.startswith("0 ")


def _linea_alerta(a: dict) -> str:
    """Una deteccion de Caption QA en lenguaje llano. Puro."""
    ts = _fmt_t(a.get("timestamp", 0))
    det = a.get("texto_detectado", "?")
    sug = a.get("sugerencia") or "sin sugerencia"
    conf = a.get("confianza", "?")
    estado = "aplicada" if a.get("aplicada") else "pendiente"
    return f'{ts} "{det}" -> "{sug}" (confianza {conf}, {estado})'


def _lineas_qa(qa: dict) -> list[str]:
    """Bloque de Caption QA con detalle inline (no obliga a abrir el JSON). Puro."""
    n = qa.get("n_alertas", 0)
    if not n:
        return []
    aplicadas = qa.get("aplicadas", 0)
    pendientes = qa.get("pendientes", n)
    ref = f" · detalle completo en transcripts/{qa['alerts_file']}" if qa.get("alerts_file") else ""
    lineas = [
        f"- Caption QA: {n} deteccion(es) de transcripcion "
        f"({aplicadas} aplicadas, {pendientes} pendientes de revision){ref}"
    ]
    alertas = qa.get("alertas") or []
    for a in alertas[:_MAX_ALERTAS_REPORTE]:
        lineas.append(f"  - {_linea_alerta(a)}")
    resto = len(alertas) - _MAX_ALERTAS_REPORTE
    if resto > 0:
        lineas.append(f"  - (+{resto} deteccion(es) mas en el JSON)")
    elif not alertas:
        lineas.append("  - (detalle no disponible; ver el JSON del sidecar)")
    return lineas


def _lineas_clip(i: int, c: dict, mostrar_emojis: bool) -> list[str]:
    """Bloque de lineas de un clip dentro del REPORTE.md. Puro."""
    estado = estado_clip(c)
    lineas = [
        f"### {i}. {c.get('titulo', '(sin titulo)')} — score IA {c.get('score', '?')}/100 "
        f"[{estado}]",
        "",
        f"- Estado: {estado}",
        f"- Archivo: `{c['archivo']}`",
        f"- Duracion: {c.get('dur_s', 0):.1f}s ({_fmt_t(c.get('dur_s', 0))})",
        f"- Razon IA: {c.get('razon', '')}",
    ]
    if mostrar_emojis:
        lineas.append(f"- Emojis: {c.get('emojis_msg', 'sin overlays')}")
    qa = c.get("qa")
    if qa:
        lineas += _lineas_qa(qa)
    avisos = c.get("avisos", [])
    if avisos:
        lineas.append("- Calidad por tramos:")
        lineas += [f"  - {a['texto']}" for a in avisos]
    elif c.get("tramos_disponibles", True):
        lineas.append("- Calidad por tramos: OK en todo el clip")
    else:
        lineas.append(
            "- Calidad por tramos: no disponible (clip reutilizado de una corrida "
            "previa; no se re-renderizo para recuperar las metricas)"
        )
    lineas.append("")
    return lineas


def _herramientas_sugeridas(clips_info: list[dict]) -> str:
    """Ajuste manual segun el tipo de aviso presente en el paquete. Puro."""
    tipos = {a.get("tipo") for c in clips_info for a in c.get("avisos", [])}
    sug = []
    if "multi" in tipos:
        sug.append("Stack o Reframe Multi v2 para tramos con varias personas en cuadro")
    if "none" in tipos:
        sug.append("Reframe manual para tramos sin cara detectada")
    if "seguimiento" in tipos:
        sug.append("Reframe manual para tramos con seguimiento dudoso")
    return "; ".join(sug)


def _clip_mas_publicable(clips_info: list[dict]) -> tuple[int, dict] | None:
    """(indice-1, clip) con mejor estado y, a igualdad, mayor score. Puro."""
    if not clips_info:
        return None
    return min(
        enumerate(clips_info, 1),
        key=lambda par: (_severidad(estado_clip(par[1])), -(par[1].get("score") or 0)),
    )


def recomendacion_final(clips_info: list[dict]) -> list[str]:
    """Guia de accion para el tester: que revisar, donde y con que herramienta. Puro."""
    if not clips_info:
        return ["- Sin clips que evaluar."]
    lineas = []

    revisar = [(i, c, estado_clip(c)) for i, c in enumerate(clips_info, 1)]
    pendientes = [(i, e) for i, _c, e in revisar if e != ESTADO_LISTO]
    if pendientes:
        detalle = "; ".join(f"clip {i} ({e})" for i, e in pendientes)
        lineas.append(f"- Clips a revisar: {detalle}")
    else:
        lineas.append("- Clips a revisar: ninguno, todos quedaron LISTO")

    tramos = [
        f"clip {i} {_fmt_t(a['t_ini'])}-{_fmt_t(a['t_fin'])}"
        for i, c in enumerate(clips_info, 1)
        for a in c.get("avisos", [])
    ]
    if tramos:
        lineas.append(f"- Tramos a mirar: {', '.join(tramos)}")

    herramientas = _herramientas_sugeridas(clips_info)
    if herramientas:
        lineas.append(f"- Ajuste manual sugerido: {herramientas}")

    mejor = _clip_mas_publicable(clips_info)
    if mejor:
        i, c = mejor
        lineas.append(
            f'- Mas publicable: clip {i} "{c.get("titulo", "")}" '
            f"(score {c.get('score', '?')}/100, {estado_clip(c)})"
        )
    return lineas


def _linea_av(av: dict) -> str:
    """Una linea humana del resultado A/V de un clip v2. Puro."""
    integ = (av.get("integrity") or {}).get("status", "?")
    sync = (av.get("sync") or {}).get("status", "?")
    if av.get("skipped"):
        return "verificacion A/V omitida por config"
    return f"audio {integ} / sincronizacion {sync}"


def _lineas_v2_paquete(clips_info: list[dict]) -> list[str]:
    """Seccion del REPORTE.md SOLO para paquetes v2 (S37-B). Puro.

    Sin clips v2 devuelve [] -> el reporte clasico queda byte-identico (golden test).
    """
    v2 = [(i, c) for i, c in enumerate(clips_info, 1) if c.get("pipeline_mode") == "v2"]
    if not v2:
        return []
    lineas = ["", "## Modo Automatico v2 (b-roll + FX)", ""]
    for i, c in v2:
        b = c.get("broll") or {}
        fxs = c.get("fx") or {}
        eliminados = len(fxs.get("removed") or [])
        lineas += [
            f"- Clip {i}: b-roll {b.get('resolved', 0)}/{b.get('planned', 0)} "
            f"({b.get('images', 0)} imagen(es), {b.get('videos', 0)} video(s), "
            f"{b.get('fallbacks', 0)} fallback(s), {b.get('blocked', 0)} bloqueada(s) "
            f"por manual, {b.get('omitted', 0)} omitida(s))",
            f"  - Manual respetado: {b.get('manual_popups', 0)} popup(s), "
            f"{b.get('manual_clips', 0)} clip(s) (el sidecar manual nunca se toca)",
            f"  - FX: preset {fxs.get('preset') or 'apagado'}, "
            f"{eliminados} efecto(s) eliminados por colision con b-roll",
            f"  - A/V: {_linea_av(c.get('av') or {})}",
            f"  - Sidecars: {b.get('plan_sidecar', '?')}, {b.get('auto_sidecar', '?')}, "
            f"{b.get('resolved_sidecar', '?')}",
        ]
    lineas += [
        "",
        "REVISION HUMANA: mira el b-roll y los FX en el video completo antes de publicar.",
    ]
    return lineas


def generar_reporte_md(name: str, clips_info: list[dict], meta: dict) -> str:
    """REPORTE.md del paquete. Puro."""
    algun_emoji = any(_clip_usa_emojis(c) for c in clips_info)
    lineas = [
        f"# Paquete Modo Automatico — {name}",
        "",
        f"Generado: {meta.get('fecha', '?')} · Objetivo: Clips virales · "
        f"Estilo: {STYLE_AUTO} · Tracker: escenas",
        "",
        f"**Resumen: {resumen_paquete(clips_info)}.**",
        "",
    ]
    if not algun_emoji and clips_info:
        lineas += ["Overlays/Emojis: no usados en este paquete.", ""]
    lineas += [
        "REVISION HUMANA REQUERIDA antes de publicar (regla MAESTRO #19).",
        "",
    ]
    if clips_info:
        lineas += ["## Estado de los clips", ""]
        lineas += [
            f"- Clip {i}: {estado_clip(c)} — {c.get('titulo', '(sin titulo)')}"
            for i, c in enumerate(clips_info, 1)
        ]
        lineas.append("")
    lineas += ["## Clips", ""]
    for i, c in enumerate(clips_info, 1):
        lineas += _lineas_clip(i, c, mostrar_emojis=algun_emoji)
    lineas += ["## Recomendacion final", ""]
    lineas += recomendacion_final(clips_info)
    lineas += _lineas_v2_paquete(clips_info)  # [] sin clips v2: reporte clasico intacto
    lineas += [
        "",
        "## Telemetria",
        "",
        f"- Tiempo total: {_fmt_ms(meta.get('t_total_s', 0))}",
        f"- Costo LLM: ${meta.get('costo_usd', 0):.4f}",
        "",
        "Tiempos tecnicos:",
        "",
        f"- Transcripcion: {meta.get('t_transcripcion_s', 0):.1f}s"
        + (" (reutilizada, voto #10)" if meta.get("transcript_reutilizado") else ""),
        f"- Clipper: {meta.get('t_clipper_s', 0):.1f}s",
        f"- Reframe + captions: {meta.get('t_render_s', 0):.1f}s",
        f"- Total (seg): {meta.get('t_total_s', 0):.1f}s",
        "",
    ]
    return "\n".join(lineas)
