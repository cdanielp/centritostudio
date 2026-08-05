"""capture_editor.py — Evidencia visual del editor de letreros con previsualizacion (HF-3).

Carga el `static/index.html` REAL (mismo CSS, mismas funciones `abrirEditorLetreros` y
`previsualizarPieza`) y le inyecta un bootstrap que solo sustituye el TRANSPORTE: en vez de
hablar con el servidor, `fetch` devuelve lo que el backend real ya calculo en este mismo
proceso (`studio_motion.ver_plan` y `studio_motion.previsualizar`). Ni el plan ni las imagenes
son de mentira: son las que responderia el Studio levantado. Lo unico que se evita es tener que
arrancar el servidor y automatizar clics.

Captura con Edge headless, que ya esta instalado, sin Playwright.

Uso:
    venv\\Scripts\\python revision\\hf-3\\capture_editor.py <clip> --salida <ruta.png>
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# Cuantas piezas llevan su vista ya generada en la captura. Las demas quedan con su boton, que
# es como las ve K al abrir el editor: la vista se pide bajo demanda.
PIEZAS_CON_VISTA = (0, 2)
# Alto generoso a proposito: el pie del editor lleva los botones de guardar, descartar y pedir
# otro plan, y una captura que los corte no sirve como evidencia de que existen.
VENTANA = (1500, 1560)
TIEMPO_VIRTUAL_MS = 8000


def _edge() -> str:
    """Ruta del Edge instalado. Sin rutas de una maquina concreta en el repo."""
    candidatas = [
        Path(os.environ.get("EDGE_BINARIO", "")),
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
        / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        / "Microsoft/Edge/Application/msedge.exe",
    ]
    for ruta in candidatas:
        if str(ruta) and ruta.is_file():
            return str(ruta)
    raise SystemExit("no encuentro msedge.exe; define EDGE_BINARIO")


def _bootstrap(clip: str, plan: dict, vistas: dict[int, str]) -> str:
    """Script que stubea la red con las respuestas reales y dispara las mismas interacciones."""
    return f"""
<script>
(function(){{
  const CLIP = {json.dumps(clip)}, PLAN = {json.dumps(plan)}, VISTAS = {json.dumps(vistas)};
  // Transporte stubeado. El cuerpo de cada respuesta es exactamente el que devuelve el backend.
  window.fetch = function(url, opts){{
    const u = String(url);
    if (u.includes('/api/motion/plan/')) return Promise.resolve(new Response(
      JSON.stringify(PLAN), {{status:200, headers:{{'Content-Type':'application/json'}}}}));
    if (u.includes('/api/motion/previsualizar/')) {{
      const i = (JSON.parse(opts.body).pieza || {{}}).__i;
      if (VISTAS[i] === undefined) return Promise.resolve(new Response(
        JSON.stringify({{detail:'no se pudo generar la vista'}}),
        {{status:503, headers:{{'Content-Type':'application/json'}}}}));
      // El tipo tiene que viajar: un blob sin `Content-Type` no lo pinta el navegador como
      // imagen, y la celda quedaria con el texto alternativo en vez de la vista.
      const cruda = atob(VISTAS[i]);
      const bytes = new Uint8Array(cruda.length);
      for (let k = 0; k < cruda.length; k++) bytes[k] = cruda.charCodeAt(k);
      return Promise.resolve(new Response(bytes, {{status:200, headers:{{'Content-Type':'image/png'}}}}));
    }}
    return Promise.resolve(new Response('[]', {{status:200, headers:{{'Content-Type':'application/json'}}}}));
  }};
  async function conducir(){{
    try {{
      await abrirEditorLetreros(CLIP);
      // La pieza que viaja al backend lleva un indice para que el stub sepa que PNG devolver.
      (mePlan.piezas || []).forEach((p, i) => {{ p.__i = i; }});
      for (const i of Object.keys(VISTAS)) await previsualizarPieza(Number(i));
      document.getElementById('motion-editor').scrollIntoView(true);
    }} catch(e) {{ document.title = 'EVID_ERROR: ' + e.message; }}
  }}
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => setTimeout(conducir, 60));
  else setTimeout(conducir, 60);
}})();
</script>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip", help="stem del clip, tal como lo resuelve studio_motion")
    ap.add_argument("--salida", required=True, help="ruta del png de salida")
    args = ap.parse_args()

    import studio_motion as sm

    plan = sm.ver_plan(args.clip)
    print(f"plan real: {len(plan['piezas'])} pieza(s), origen={plan['origen']}")

    vistas: dict[int, str] = {}
    for i in PIEZAS_CON_VISTA:
        if i >= len(plan["piezas"]):
            continue
        arranque = time.monotonic()
        png = sm.previsualizar(args.clip, plan["piezas"][i])
        vistas[i] = base64.b64encode(png.read_bytes()).decode("ascii")
        print(f"  vista pieza {i} ({plan['piezas'][i]['plantilla']}): {time.monotonic() - arranque:.1f}s")

    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    html = html.replace("</body>", _bootstrap(args.clip, plan, vistas) + "</body>")
    tmp = Path(tempfile.mkdtemp())
    pagina = tmp / "editor.html"
    pagina.write_text(html, encoding="utf-8")

    salida = Path(args.salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.unlink(missing_ok=True)
    perfil = Path(tempfile.mkdtemp())
    subprocess.run(
        [_edge(), "--headless=new", "--disable-gpu", "--hide-scrollbars",
         "--no-first-run", "--no-default-browser-check",
         f"--user-data-dir={perfil}",
         f"--window-size={VENTANA[0]},{VENTANA[1]}",
         f"--virtual-time-budget={TIEMPO_VIRTUAL_MS}",
         f"--screenshot={salida.as_posix()}",
         pagina.as_uri()],
        capture_output=True, env=dict(os.environ, MSYS_NO_PATHCONV="1"), timeout=180,
    )
    if not salida.is_file():
        print("Edge no escribio la captura", file=sys.stderr)
        return 1
    print(f"captura: {salida}  ({salida.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
