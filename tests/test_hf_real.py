"""Render REAL de una pieza minima. Excluido por default (`-m "not hf_real"` en pytest.ini).

Se corre a mano cuando se quiere verificar la cadena completa contra HyperFrames instalado:

    venv\\Scripts\\python -m pytest tests/test_hf_real.py -m hf_real -q

Verifica pix_fmt y duracion REALES con ffprobe. NO compara pixeles ni sha256 del MOV: la
regla dura 3 lo prohibe, y HF-0 ya documento que la salida deriva entre versiones.
El proyecto HyperFrames que usa es un fixture minimo escrito aqui mismo, no una plantilla
del catalogo (el catalogo es de HF-2).
"""

from __future__ import annotations

import shutil

import pytest

from hyperframes import pedir_pieza
from hyperframes.catalogo import Catalogo, Plantilla

pytestmark = pytest.mark.hf_real

# El texto ejercita el riesgo de encoding a proposito: acentos, enie, dieresis, signos de
# apertura, punto medio y comillas dobles (que ademas prueban el escapado JSON).
TITULO = "Configuración básica de ComfyUI"
SUBTITULO = 'año 2026 · ñ á é í ó ú ü ¿? ¡! "comillas"'

# La plantilla declara sus variables PLANAS y con defaults distintos del valor real: si el
# mapeo se rompe otra vez, la pieza pinta "SIN-VARIABLE-*" en vez del texto y se ve en el frame.
INDEX_MINIMO = """<!doctype html>
<html lang="es" data-composition-variables='[
  {"id":"titulo","type":"string","label":"Titulo","default":"SIN-VARIABLE-titulo"},
  {"id":"subtitulo","type":"string","label":"Subtitulo","default":"SIN-VARIABLE-subtitulo"}
 ]'>
  <head>
    <meta charset="UTF-8" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <style>
      * { margin: 0; padding: 0; box-sizing: border-box; }
      html, body { width: 1920px; height: 1080px; overflow: hidden; background: transparent; }
      #tarjeta { position: absolute; left: 120px; bottom: 110px; background: #fff;
                 padding: 24px 40px; border-radius: 16px; color: #111; }
      #t { font-size: 52px; }
      #s { font-size: 32px; color: #444; }
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="2"
         data-width="1920" data-height="1080">
      <div id="tarjeta" class="clip" data-start="0" data-duration="2" data-track-index="1">
        <div id="t">?</div>
        <div id="s">?</div>
      </div>
    </div>
    <script>
      var v = window.__hyperframes.getVariables();
      document.getElementById("t").textContent = String(v.titulo);
      document.getElementById("s").textContent = String(v.subtitulo);
      window.__timelines = window.__timelines || {};
      var tl = gsap.timeline({ paused: true });
      tl.from("#tarjeta", { opacity: 0, y: 30, duration: 0.6 }, 0);
      window.__timelines["main"] = tl;
    </script>
  </body>
</html>
"""

PIEZA = {
    "contrato": 1,
    "pieza_id": "prueba_real",
    "plantilla": {"nombre": "minima", "version": "1.0.0"},
    "duracion_ms": 2000,
    "fps": 30,
    "tamano": {"ancho": 1920, "alto": 1080},
    "texto": {"titulo": TITULO, "subtitulo": SUBTITULO},
    "marca": {"primario": "#FF5A2B", "secundario": "#111111", "texto": "#FFFFFF"},
    "posicion": {"modo": "cuadro_completo"},
    "fit": "nativo",
    "audio": False,
    "semilla": 0,
}


@pytest.mark.skipif(shutil.which("npx") is None, reason="npx no esta instalado")
def test_render_real_produce_mov_con_alfa(tmp_path):
    proyecto = tmp_path / "proyecto"
    proyecto.mkdir()
    (proyecto / "index.html").write_text(INDEX_MINIMO, encoding="utf-8")

    catalogo = Catalogo(
        [
            Plantilla(
                nombre="minima",
                version="1.0.0",
                slots_texto=("titulo", "subtitulo"),
                proyecto=str(proyecto),
            )
        ]
    )
    r = pedir_pieza(
        PIEZA,
        destino=(1920, 1080),
        catalogo=catalogo,
        raiz_cache=tmp_path / "cache",
        timeout_s=300,
    )

    assert r.razon_fallo is None, f"el render real fallo: {r.razon_fallo}"
    assert r.ruta_mov is not None and r.ruta_mov.exists()
    assert r.pix_fmt == "yuva444p12le"
    assert abs(r.duracion_ms_real - 2000) <= 100
    assert r.fps_real == 30
    assert r.segundos_render > 0

    # Segunda pasada: debe salir de cache sin volver a renderizar.
    otra = pedir_pieza(
        PIEZA,
        destino=(1920, 1080),
        catalogo=catalogo,
        raiz_cache=tmp_path / "cache",
        timeout_s=300,
    )
    assert otra.desde_cache is True
    assert otra.hash == r.hash

    # El texto acentuado llego al archivo de variables tal cual. Que se VEA bien en el
    # frame es inspeccion humana (queda fuera de la suite: aqui no se fijan pixeles);
    # esto solo fija que lo que se le entrego a la CLI eran los bytes correctos.
    from hyperframes.invocador import variables_de

    v = variables_de(PIEZA)
    assert v["titulo"] == TITULO
    assert v["subtitulo"] == SUBTITULO
    assert "texto" not in v, "los slots deben ir PLANOS o la plantilla pinta sus defaults"
