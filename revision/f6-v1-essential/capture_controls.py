"""capture_controls.py — Evidencia visual de los controles CVE F6 en Studio (PR #23).

Inyecta un bootstrap en el static/index.html REAL (mismo CSS, mismo JS, mismo onPresetChange)
que sólo stubbea `fetch` para devolver /api/presets con presets que traen position_default /
avoid_faces_default (incluido uno personalizado top + avoid_faces=false), selecciona el preset
y deja visible el bloque `field-cve-f6`. Demuestra que onPresetChange inicializa posición y la
casilla "Evitar tapar caras" con los defaults reales del preset (BLOQUEO 4). No añade rutas de
evidencia al código de producción. Edge headless (ya instalado), sin Playwright.

Uso:  venv\\Scripts\\python revision\\f6-v1-essential\\capture_controls.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "output" / "revision-f6-v1-essential"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

# Presets servidos por el stub de /api/presets: incluye un custom con default top + nofaces.
_PRESETS = {
    "presets": [
        {"id": "clean_podcast", "label": "Clean Podcast", "intensidad_default": "clean",
         "usa_keywords": False, "usa_brain": False,
         "position_default": "bottom", "avoid_faces_default": True},
        {"id": "mi_preset_top", "label": "Custom Top (sin avoid)", "intensidad_default": "viral",
         "usa_keywords": True, "usa_brain": False,
         "position_default": "top", "avoid_faces_default": False},
    ],
    "intensidades": [
        {"id": "minimal", "label": "Minimal"},
        {"id": "clean", "label": "Clean"},
        {"id": "viral", "label": "Viral"},
    ],
}

# (nombre_png, preset_id, window)
STATES = [
    ("desktop_controls", "mi_preset_top", (1400, 1250)),
    ("mobile_controls", "mi_preset_top", (492, 1250)),
]


def _bootstrap(preset_id: str) -> str:
    presets = json.dumps(_PRESETS)
    return f"""
<script>
(function(){{
  const PRESETS = {presets}, PRESET_ID = {preset_id!r};
  window.fetch = function(url){{
    const u = String(url);
    if (u.includes('/api/presets')) return Promise.resolve(new Response(
      JSON.stringify(PRESETS), {{status:200, headers:{{'Content-Type':'application/json'}}}}));
    return Promise.resolve(new Response('[]', {{status:200, headers:{{'Content-Type':'application/json'}}}}));
  }};
  async function drive(){{
    try {{
      if (typeof loadPresets === 'function') await loadPresets();
      if (typeof showTab === 'function') showTab('render');
      const sel = document.getElementById('render-video-select');
      if (sel && !sel.querySelector('option[value="entrevista"]')) {{
        const o = document.createElement('option'); o.value='entrevista'; o.textContent='entrevista.mp4'; sel.appendChild(o);
      }}
      if (sel) sel.value = 'entrevista';
      const p = document.getElementById('render-preset');
      if (p) {{ p.value = PRESET_ID; onPresetChange(); }}
    }} catch(e) {{ document.title = 'EVID_ERROR: ' + e.message; }}
  }}
  if (document.readyState === 'complete' || document.readyState === 'interactive') setTimeout(drive, 120);
  else document.addEventListener('DOMContentLoaded', () => setTimeout(drive, 120));
  setTimeout(drive, 1600);
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
    for name, preset_id, window in STATES:
        boot = _bootstrap(preset_id)
        html = base_html.replace("</body>", boot + "</body>")
        page = tmp_dir / f"{name}.html"
        page.write_text(html, encoding="utf-8")
        out = EVID / f"{name}.png"
        _shot(page, out, window)
        size = out.stat().st_size if out.is_file() else 0
        print(f"  {name:20s} -> {out.name} ({size} bytes) [{window[0]}x{window[1]}]")
    _kill_edge()
    # limpia las paginas temporales (no versionar)
    for p in tmp_dir.glob("*.html"):
        p.unlink(missing_ok=True)
    tmp_dir.rmdir()
    print(f"evidencia en: {EVID.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(main())
