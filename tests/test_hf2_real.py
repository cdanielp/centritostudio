"""HF-2: render REAL de las cinco plantillas del catalogo. Excluido por default.

Se corre a mano antes de cada PR de HyperFrames (regla de gate de D50.4):

    venv\\Scripts\\python -m pytest tests/test_hf2_real.py -m hf_real -q

Por plantilla se fijan cuatro cosas, ninguna por pixeles ni sha concreto:
1. Canario de influencia (D50.5): mismo proyecto, dos textos, sha256 DISTINTO.
2. La pieza sale en vertical (1080x1920) desde el proyecto del catalogo y en
   horizontal (1920x1080) desde su gemelo `horizontal/`. Un solo proyecto NO puede
   servir ambos tamanos: HyperFrames fija el lienzo con los data-width/height
   estaticos del HTML (hallazgo de HF-2, detalle en test_hf2_catalogo).
3. La duracion se adapta: la duracion natural del ejemplo y su mitad producen MOV
   cuya duracion real pasa la verificacion de HF-1 (tolerancia 120 ms).
4. pix_fmt yuva444p12le: el alfa sobrevive (HF-0).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from hyperframes import pedir_pieza
from hyperframes.catalogo import Catalogo

pytestmark = pytest.mark.hf_real

RAIZ = Path(__file__).resolve().parents[1]
CATALOGO = Catalogo.desde_archivo(RAIZ / "motion" / "catalogo.json")
NOMBRES = ("cierre", "dato_destacado", "hook", "lower_third", "titulo_seccion")

# Catalogo del gemelo 16:9. Desde HF-3 el propio catalogo declara un proyecto POR ORIENTACION,
# asi que ya no hay que fabricarlo concatenando "/horizontal" a la ruta vertical: se carga.
CATALOGO_H = Catalogo.desde_archivo(RAIZ / "motion" / "catalogo.json", "horizontal")


# Los informes de reproducibilidad viven junto al resto de la evidencia de HF-3, no en el temp
# de Windows: el fallo es intermitente y lo unico que queda de el es este archivo.
DIR_INFORMES = RAIZ / "revision" / "hf-3" / "reproducibilidad"


def _frames_gris(mov: Path, ancho: int, alto: int) -> list[bytes]:
    """Todos los frames del MOV en escala de grises, crudos. Uno por elemento."""
    crudo = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(mov), "-vf", "format=gray", "-f", "rawvideo", "-"],
        capture_output=True,
        check=True,
    ).stdout
    paso = ancho * alto
    return [crudo[i : i + paso] for i in range(0, len(crudo) - paso + 1, paso)]


def diagnostico_reproducibilidad(nombre: str, uno, otro, destino: Path) -> Path:
    """Escribe EN QUE se diferencian dos MOV que debian ser identicos, y devuelve la ruta.

    Sin esto, un fallo de reproducibilidad deja como unica pista dos hashes distintos, y como
    el evento es raro por frame, cuando alguien va a mirarlo ya no se reproduce. Aqui quedan
    los frames afectados, cuantos son sobre el total y cuanto se desvian sobre 255.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    informe: dict = {
        "plantilla": nombre,
        "sha256": [uno.sha256, otro.sha256],
        "hash_de_contrato": uno.hash,
        "entorno": dict(uno.entorno or {}),
        "sondeo": {
            "pix_fmt": [uno.pix_fmt, otro.pix_fmt],
            "fps": [uno.fps_real, otro.fps_real],
            "duracion_ms": [uno.duracion_ms_real, otro.duracion_ms_real],
        },
    }
    try:
        ancho, alto = _tamano_de(Path(uno.ruta_mov))
        a = _frames_gris(Path(uno.ruta_mov), ancho, alto)
        b = _frames_gris(Path(otro.ruta_mov), ancho, alto)
        total = min(len(a), len(b))
        distintos, deltas = [], []
        for i in range(total):
            if a[i] == b[i]:
                continue
            peor = max(abs(x - y) for x, y in zip(a[i], b[i], strict=False))
            medio = sum(abs(x - y) for x, y in zip(a[i], b[i], strict=False)) / len(a[i])
            distintos.append(i)
            deltas.append((medio, peor))
        informe["frames"] = {
            "total": total,
            "distintos": len(distintos),
            "indices": distintos[:200],
            "delta_medio_sobre_255": round(sum(d[0] for d in deltas) / len(deltas), 4)
            if deltas
            else 0.0,
            "delta_maximo_sobre_255": max((d[1] for d in deltas), default=0),
        }
    except Exception as exc:  # noqa: BLE001 - el informe nunca puede tumbar el test
        informe["frames"] = {"error": f"{type(exc).__name__}: {exc}"}
    destino.write_text(json.dumps(informe, indent=2, ensure_ascii=False), encoding="utf-8")
    return destino


def _tamano_de(mov: Path) -> tuple[int, int]:
    salida = (
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=p=0",
                str(mov),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        .stdout.strip()
        .rstrip(",")
    )
    ancho, alto = (int(v) for v in salida.split(",")[:2])
    return ancho, alto


def _ejemplo(nombre: str) -> dict:
    ruta = RAIZ / "motion" / "ejemplos" / f"{nombre}.json"
    return json.loads(ruta.read_text(encoding="utf-8"))


def _pedir(dato: dict, cache: Path, catalogo: Catalogo = CATALOGO):
    tamano = dato["tamano"]
    return pedir_pieza(
        dato,
        destino=(tamano["ancho"], tamano["alto"]),
        catalogo=catalogo,
        raiz_cache=cache,
        timeout_s=300,
    )


@pytest.mark.skipif(shutil.which("npx") is None, reason="npx no esta instalado")
@pytest.mark.parametrize("nombre", NOMBRES)
def test_render_reproducible_por_plantilla(nombre, tmp_path):
    """El MISMO contrato renderizado dos veces debe dar el MISMO sha256.

    Es el gate que nunca existio. Sin el, la auditoria de HF-2 midio 9 de 10
    configuraciones con sha distinto entre corridas identicas, y eso dejaba inerte al
    canario de influencia de aqui abajo: su asercion se cumplia por ruido.

    Las dos corridas usan RAICES DE CACHE DISTINTAS a proposito. Con la misma raiz, la
    segunda seria un hit de cache y devolveria el sha guardado sin renderizar nada: el
    test pasaria sin haber probado absolutamente nada.
    """
    base = _ejemplo(nombre)
    uno, otro = _dos_renders(base, tmp_path, "1")
    if uno.sha256 == otro.sha256:
        return

    # Los sha difieren. ANTES de fallar se escribe a disco en que se diferencian los dos MOV,
    # porque sin eso lo unico que queda es "dos hashes distintos" y el fallo es intermitente:
    # cuando alguien va a mirarlo, ya no se reproduce.
    informe = diagnostico_reproducibilidad(nombre, uno, otro, DIR_INFORMES / f"{nombre}_1.json")
    # Reintento UNA vez. El addendum D52.4 midio que este fallo es un evento RARO por frame
    # (titulo_seccion fallo una de seis corridas), asi que un fallo suelto no puede tumbar el
    # gate; pero el informe se queda escrito para que el evento no se pierda.
    tres, cuatro = _dos_renders(base, tmp_path, "2")
    if tres.sha256 == cuatro.sha256:
        print(
            f"[reproducibilidad] {nombre}: la primera pasada dio sha distinto y el reintento "
            f"paso. Informe: {informe}"
        )
        return
    diagnostico_reproducibilidad(nombre, tres, cuatro, DIR_INFORMES / f"{nombre}_2.json")
    raise AssertionError(
        f"{nombre}: dos renders del MISMO contrato dieron sha256 distinto en las DOS pasadas "
        f"({uno.sha256} vs {otro.sha256}). El render dejo de ser reproducible: revisa que el "
        f"comando siga fijando --workers 1 (ver invocador.WORKERS y la auditoria de HF-2). "
        f"Detalle frame a frame en {DIR_INFORMES}."
    )


def _dos_renders(base: dict, tmp_path: Path, sufijo: str):
    """El MISMO contrato renderizado dos veces, con raices de cache DISTINTAS.

    Con la misma raiz la segunda seria un hit de cache y devolveria el sha guardado sin
    renderizar nada: el test pasaria sin haber probado absolutamente nada.
    """
    uno = _pedir(base, tmp_path / f"cache_a{sufijo}")
    otro = _pedir(base, tmp_path / f"cache_b{sufijo}")
    assert uno.razon_fallo is None, f"{uno.razon_fallo} {uno.detalle}"
    assert otro.razon_fallo is None, f"{otro.razon_fallo} {otro.detalle}"
    assert not uno.desde_cache and not otro.desde_cache, (
        "alguna corrida salio de cache, el test no probo el render"
    )
    assert uno.hash == otro.hash, "el mismo contrato dio claves de cache distintas"
    return uno, otro


@pytest.mark.skipif(shutil.which("npx") is None, reason="npx no esta instalado")
@pytest.mark.parametrize("nombre", NOMBRES)
def test_canario_de_influencia_por_plantilla(nombre, tmp_path):
    """D50.5: cambiar el texto de un slot debe cambiar el sha256 del MOV.

    El canario solo dice algo si el render es reproducible. Mientras no lo fue, esta
    asercion se cumplia por varianza de rasterizacion aunque el slot jamas hubiera llegado
    a la plantilla, que es justo el fallo de D50.1 que viene a cazar. Por eso la premisa se
    comprueba AQUI, en el mismo test, y no se delega a otro archivo: un canario cuya
    premisa vive lejos se apaga sin que nadie lo note.
    """
    base = _ejemplo(nombre)
    primer_slot = sorted(base["texto"])[0]
    variante = dict(base, texto=dict(base["texto"], **{primer_slot: "Texto canario distinto"}))

    uno = _pedir(base, tmp_path / "cache")
    testigo = _pedir(base, tmp_path / "cache_testigo")
    otro = _pedir(variante, tmp_path / "cache")

    assert uno.razon_fallo is None, f"{nombre}: {uno.razon_fallo} {uno.detalle}"
    assert otro.razon_fallo is None, f"{nombre}: {otro.razon_fallo} {otro.detalle}"
    assert testigo.razon_fallo is None, f"{nombre}: {testigo.razon_fallo} {testigo.detalle}"

    # Premisa: sin reproducibilidad, la asercion de abajo no prueba nada.
    assert uno.sha256 == testigo.sha256, (
        f"{nombre}: el render no es reproducible, asi que este canario no puede detectar "
        "nada. Arregla la reproducibilidad ANTES de leer el resultado de abajo."
    )

    assert uno.hash != otro.hash
    assert uno.sha256 != otro.sha256, (
        f"{nombre}: el slot {primer_slot!r} no llego a la plantilla, "
        "esta pintando su valor por defecto (el fallo de D50.1)"
    )
    assert uno.pix_fmt == "yuva444p12le"


@pytest.mark.skipif(shutil.which("npx") is None, reason="npx no esta instalado")
@pytest.mark.parametrize("nombre", NOMBRES)
def test_ambos_tamanos_y_media_duracion(nombre, tmp_path):
    """9:16 con el catalogo real y 16:9 con el gemelo, a duracion natural y mitad."""
    base = _ejemplo(nombre)
    casos = [
        (dict(base, tamano={"ancho": 1920, "alto": 1080}), CATALOGO_H),
        (dict(base, duracion_ms=base["duracion_ms"] // 2), CATALOGO),
        (
            dict(
                base,
                tamano={"ancho": 1920, "alto": 1080},
                duracion_ms=base["duracion_ms"] // 2,
            ),
            CATALOGO_H,
        ),
    ]
    for dato, catalogo in casos:
        r = _pedir(dato, tmp_path / "cache", catalogo)
        assert r.razon_fallo is None, f"{nombre}: {r.razon_fallo} {r.detalle}"
        assert r.pix_fmt == "yuva444p12le"
        assert abs(r.duracion_ms_real - dato["duracion_ms"]) <= 120
