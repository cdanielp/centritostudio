"""capture_srt_ui.py — Evidencia visual de la UI SRT de Studio (S36-C2B).

Inyecta un bootstrap de evidencia en el `static/index.html` REAL (mismo CSS, mismo `srtPanel`,
mismos renderers) que sólo hace dos cosas: stubbea `fetch` para devolver un view model saneado
de fixture y dispara las MISMAS interacciones que haría un usuario (elegir video, cambiar la
fuente a SRT). No añade rutas de evidencia al código de producción. Captura con Edge headless
(ya instalado) sin Playwright. Salida en output/revision-s36-c2b/ (gitignored).

Uso:  venv\\Scripts\\python revision\\s36-c2b\\capture_srt_ui.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "output" / "revision-s36-c2b"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

_READY = {
    "selected": True, "source_name": "entrevista.srt", "timings": "valid",
    "video_available": True, "ready_render": True, "ready_auto": True, "action": "ready",
}
_MISSING = {
    "selected": True, "source_name": "entrevista.srt", "timings": "missing",
    "video_available": True, "ready_render": False, "ready_auto": False, "action": "transcribe",
}
# Fallo parcial en Auto v2 + SRT: el clip 2 falló. La ruta v2 debe mostrarlo como tarjeta de
# fallo segura (roja, sin descarga ni Editor) igual que classic (P2 S36-C2B corregido).
_AUTO_PARTIAL = {
    "resumen": "3 clips generados; 1 falló (clip 2).",
    "paquete": "output/paquetes/demo_v2_20260720",
    "meta": {"pipeline_mode": "v2"},
    "clips": [
        {"titulo": "Gancho inicial", "archivo": "clip1.mp4", "score": 88, "dur_s": 5.0,
         "pipeline_mode": "v2", "broll": {"resolved": 2, "planned": 2, "images": 1, "videos": 1},
         "fx": {"preset": "express", "removed": []}, "av": {"integrity": {"status": "pass"},
         "sync": {"status": "pass"}}, "brain_ok": True},
        {"titulo": "Momento débil", "archivo": "clip2.mp4", "status": "error", "dur_s": 4.0,
         "pipeline_mode": "v2"},
        {"titulo": "Cierre", "archivo": "clip3.mp4", "score": 81, "dur_s": 4.0,
         "pipeline_mode": "v2", "broll": {"resolved": 1, "planned": 1, "images": 1, "videos": 0},
         "fx": {"preset": "express", "removed": []}, "av": {"integrity": {"status": "pass"},
         "sync": {"status": "pass"}}, "brain_ok": True},
    ],
}

# Cada estado: (nombre_png, tab, source, srt_view_json, auto_result_json, window)
STATES = [
    ("desktop_transcript", "render", "transcript", "null", "null", (1400, 950)),
    ("desktop_srt_missing", "render", "srt", _MISSING, "null", (1400, 950)),
    ("desktop_srt_ready", "render", "srt", _READY, "null", (1400, 950)),
    ("desktop_auto_srt", "auto", "srt", _READY, "null", (1400, 950)),
    ("desktop_partial", "auto", "srt", _READY, _AUTO_PARTIAL, (1400, 2050)),
    ("mobile_srt", "render", "srt", _READY, "null", (492, 950)),
]


def _bootstrap(tab: str, source: str, srt_view, auto_result) -> str:
    import json

    sv = json.dumps(srt_view) if srt_view != "null" else "null"
    ar = json.dumps(auto_result) if auto_result != "null" else "null"
    return f"""
<script>
(function(){{
  const SRT_VIEW = {sv}, AUTO_RESULT = {ar}, TAB = {tab!r}, SOURCE = {source!r};
  const MODE = TAB === 'auto' ? 'auto' : 'render';
  // Determinismo del nav: tras fijar la vista objetivo, ignorar cualquier showTab('home')
  // tardío (hooks async del arranque) para que el botón activo del nav no vuelva a Inicio.
  let LOCKED = false;
  const _origShowTab = showTab;
  showTab = function(id){{ if (LOCKED && id === 'home') return; return _origShowTab.apply(this, arguments); }};
  // Stub de red: el navegador NO reconstruye estado privado; recibe el view model saneado.
  const realFetch = window.fetch;
  window.fetch = function(url, opts){{
    const u = String(url);
    if (u.includes('/srt/view')) return Promise.resolve(new Response(
      JSON.stringify({{caption_source: SOURCE, srt: SRT_VIEW || {{selected:false}}}}),
      {{status:200, headers:{{'Content-Type':'application/json'}}}}));
    return Promise.resolve(new Response('[]', {{status:200, headers:{{'Content-Type':'application/json'}}}}));
  }};
  function drive(){{
    try {{
      const sel = document.getElementById(MODE === 'auto' ? 'auto-video-select' : 'render-video-select');
      if (sel && !sel.querySelector('option[value="entrevista"]')) {{
        const o = document.createElement('option'); o.value='entrevista'; o.textContent='entrevista'; sel.appendChild(o);
      }}
      if (sel) sel.value = 'entrevista';
      showTab(TAB);
      const cs = document.getElementById(MODE + '-caption-source');
      if (cs) {{ cs.value = SOURCE; srtPanel.onSource(MODE); }}
      // Coherencia: si el resultado es v2, seleccionar la card "Automático v2" (no "Clásico").
      if (AUTO_RESULT && AUTO_RESULT.meta && AUTO_RESULT.meta.pipeline_mode === 'v2'
          && typeof setAutoMode === 'function') {{ setAutoMode('v2'); }}
      if (AUTO_RESULT) {{ document.getElementById('auto-result').style.display='block'; renderAutoResult(AUTO_RESULT); }}
      LOCKED = true;  // desde aquí, ningún showTab('home') tardío roba el nav
    }} catch(e) {{ document.title = 'EVID_ERROR: ' + e.message; }}
  }}
  // Re-aserta la vista tras asentarse el arranque (evita que un hook async del home inicial
  // deje el nav en otra pestaña) y fija explícitamente el botón activo del nav + encuadre.
  function finalize(){{
    try {{
      showTab(TAB);
      const primary = {{render:'creador', auto:'auto'}}[MODE] || TAB;
      document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
      const btn = document.querySelector('nav button[data-tab="' + primary + '"]');
      if (btn) btn.classList.add('active');
      if (AUTO_RESULT) document.getElementById('auto-result').scrollIntoView(true);
    }} catch(e) {{}}
  }}
  if (document.readyState === 'complete' || document.readyState === 'interactive') setTimeout(drive, 60);
  else document.addEventListener('DOMContentLoaded', () => setTimeout(drive, 60));
  setTimeout(finalize, 1500);
  setTimeout(finalize, 3200);
}})();
</script>
"""


def _kill_edge():
    subprocess.run(["taskkill", "/F", "/IM", "msedge.exe"], capture_output=True)


def _shot(html_path: Path, out_png: Path, window: tuple[int, int]):
    _kill_edge()
    time.sleep(2)
    profile = Path(tempfile.mkdtemp())
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    subprocess.run(
        [EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         "--no-first-run", "--no-default-browser-check",
         f"--user-data-dir={profile}",
         f"--window-size={window[0]},{window[1]}",
         "--virtual-time-budget=4000",
         f"--screenshot={out_png.as_posix()}",
         html_path.as_uri()],
        capture_output=True, env=env, timeout=90,
    )
    time.sleep(1)


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    base_html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    tmp_dir = EVID / "_pages"
    tmp_dir.mkdir(exist_ok=True)
    for name, tab, source, srt_view, auto_result, window in STATES:
        boot = _bootstrap(tab, source, srt_view, auto_result)
        html = base_html.replace("</body>", boot + "</body>")
        page = tmp_dir / f"{name}.html"
        page.write_text(html, encoding="utf-8")
        out = EVID / f"{name}.png"
        _shot(page, out, window)
        size = out.stat().st_size if out.is_file() else 0
        print(f"  {name:22s} -> {out.name} ({size} bytes) [{window[0]}x{window[1]}]")
    _kill_edge()
    print(f"evidencia en: {EVID.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(main())
