"""auto_report.py - Reporte de calidad del Modo Automatico (funciones PURAS).

Split de auto.py (s34 B1, sin cambio de comportamiento): aqui vive la traduccion
de metricas del motor a lenguaje humano (avisos por tramos, resumen de paquete,
REPORTE.md). auto.py re-exporta estos nombres para compatibilidad.
"""

from __future__ import annotations

# Umbral de aviso para C1v2 en tramos single (heuristica inicial, D17)
C1V2_AVISO = 80.0

STYLE_AUTO = "hormozi"  # estilo del paquete v1 (95/100 de K en s26, D16)


def _fmt_t(segundos: float) -> str:
    """0:39 a partir de 39.2. Puro."""
    m, s = divmod(int(segundos), 60)
    return f"{m}:{s:02d}"


def avisos_de_segmentos(segmentos: list[dict]) -> list[dict]:
    """Traduce el seg_reporte del modo escenas a avisos humanos. Puro.

    Entrada: entradas {t_ini, t_fin, tipo, n_caras, c1v2, ...} tal como las
    devuelve reframe_escenas (via reframe_clip result['segmentos']).
    Salida: [{t_ini, t_fin, texto}] solo para tramos que requieren revision.
    """
    avisos = []
    for s in segmentos:
        rango = f"{_fmt_t(s['t_ini'])}-{_fmt_t(s['t_fin'])}"
        if s.get("tipo") == "multi":
            avisos.append(
                {
                    "t_ini": s["t_ini"],
                    "t_fin": s["t_fin"],
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
                    "texto": f"revisa {rango}: sin cara detectada, encuadre centrado fijo",
                }
            )
        elif s.get("c1v2") is not None and s["c1v2"] < C1V2_AVISO:
            avisos.append(
                {
                    "t_ini": s["t_ini"],
                    "t_fin": s["t_fin"],
                    "texto": (
                        f"revisa {rango}: el seguimiento pudo perder a la persona "
                        f"(fiabilidad {s['c1v2']:.0f}%)"
                    ),
                }
            )
    return avisos


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


def _lineas_clip(i: int, c: dict) -> list[str]:
    """Bloque de lineas de un clip dentro del REPORTE.md. Puro."""
    lineas = [
        f"### {i}. {c.get('titulo', '(sin titulo)')} — score IA {c.get('score', '?')}/100",
        "",
        f"- Archivo: `{c['archivo']}`",
        f"- Duracion: {c.get('dur_s', 0):.1f}s ({_fmt_t(c.get('dur_s', 0))})",
        f"- Razon IA: {c.get('razon', '')}",
        f"- Emojis: {c.get('emojis_msg', 'sin overlays')}",
    ]
    qa = c.get("qa")
    if qa:
        detalle = f"; detalle en transcripts/{qa['alerts_file']}" if qa.get("alerts_file") else ""
        lineas.append(
            f"- Caption QA: {qa['n_alertas']} alerta(s) de transcripcion "
            f"({qa['aplicadas']} aplicadas, {qa['pendientes']} pendientes de revision{detalle})"
        )
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


def generar_reporte_md(name: str, clips_info: list[dict], meta: dict) -> str:
    """REPORTE.md del paquete. Puro."""
    lineas = [
        f"# Paquete Modo Automatico — {name}",
        "",
        f"Generado: {meta.get('fecha', '?')} · Objetivo: Clips virales · "
        f"Estilo: {STYLE_AUTO} · Tracker: escenas",
        "",
        f"**Resumen: {resumen_paquete(clips_info)}.**",
        "",
        "REVISION HUMANA REQUERIDA antes de publicar (regla MAESTRO #19).",
        "",
        "## Clips",
        "",
    ]
    for i, c in enumerate(clips_info, 1):
        lineas += _lineas_clip(i, c)
    lineas += [
        "## Telemetria",
        "",
        f"- Transcripcion: {meta.get('t_transcripcion_s', 0):.1f}s"
        + (" (reutilizada, voto #10)" if meta.get("transcript_reutilizado") else ""),
        f"- Clipper: {meta.get('t_clipper_s', 0):.1f}s · costo LLM ${meta.get('costo_usd', 0):.4f}",
        f"- Reframe + captions: {meta.get('t_render_s', 0):.1f}s",
        f"- Total: {meta.get('t_total_s', 0):.1f}s",
        "",
    ]
    return "\n".join(lineas)
