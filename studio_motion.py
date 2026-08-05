"""studio_motion.py — Contrato del editor de letreros expuesto por Studio.

El Studio CONFIGURA y MUESTRA; `motion_plan` decide y `motion_edicion` valida. Este modulo es
la capa delgada entre los dos: resuelve el clip que K esta mirando, arma la vista del plan para
la interfaz y traduce cada operacion (editar, mover, borrar, anadir, descartar) a una escritura
del sidecar que YA paso por el validador.

No renderiza, no llama al LLM y no escribe nada fuera del sidecar del clip. Los errores de
contrato salen como `StudioMotionError` con el motivo en claro, para que la interfaz los pinte
en vez de tragarselos.
"""

from __future__ import annotations

import json
from pathlib import Path

import motion_capa
import motion_edicion as me
import motion_plan as mp
from path_safety import is_safe_basename

ROOT = Path(__file__).resolve().parent
CLIPS_DIR = ROOT / "output" / "clips"
PAQUETES_DIR = ROOT / "output" / "paquetes"
TRANSCRIPTS = ROOT / "transcripts"
CATALOGO = ROOT / "motion" / "catalogo.json"


class StudioMotionError(ValueError):
    """Error de contrato del editor. El mensaje va tal cual a la interfaz."""


def _exigir_basename(valor: str, campo: str) -> str:
    if not is_safe_basename(valor):
        raise StudioMotionError(f"{campo} invalido")
    return valor


def resolver_clip(clip: str) -> Path:
    """MP4 del clip que se esta editando. Busca en `output/clips/` y en los paquetes.

    Se acepta el basename SIN extension para que la interfaz no tenga que saber donde vive el
    archivo, pero el nombre pasa por el mismo guard de basename que el resto de los endpoints:
    de aqui sale un Path construido, y un traversal seria un archivo escrito fuera del proyecto.
    """
    _exigir_basename(clip, "clip")
    stem = clip[:-4] if clip.endswith(".mp4") else clip
    directo = CLIPS_DIR / f"{stem}.mp4"
    if directo.is_file():
        return directo
    for paquete in sorted(PAQUETES_DIR.glob("*")):
        if not paquete.is_dir():
            continue
        candidato = paquete / f"{stem}.mp4"
        if candidato.is_file():
            return candidato
    raise StudioMotionError(f"no se encontro el clip '{stem}'")


def _meta_del_clip(mp4: Path) -> tuple[int, str, int]:
    """(duracion_ms, orientacion, fps) leidos del MP4 con el mismo helper que el render."""
    import core  # noqa: PLC0415

    info = core.get_video_info(mp4)
    duracion_ms = int(round(float(info["duration"]) * 1000))
    orientacion = motion_capa.orientacion_de(info["width"], info["height"])
    return duracion_ms, orientacion, int(round(float(info.get("fps") or 30)))


def _tramos_del_clip(mp4: Path) -> list[mp.Tramo]:
    """Tramos del transcript del clip, si existe. Sin transcript, lista vacia (fail-open)."""
    ruta = TRANSCRIPTS / f"{mp4.stem}_groups.json"
    if not ruta.is_file():
        return []
    try:
        return motion_capa.tramos_de_groups(json.loads(ruta.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return []


def _tray_del_clip(mp4: Path):
    import tray_resolve  # noqa: PLC0415

    return tray_resolve.resolver_tray_csv(mp4, TRANSCRIPTS)


def catalogo_para_ui() -> list[dict]:
    """Plantillas que K puede anadir, con su duracion fija y sus slots de texto.

    La duracion viaja porque la interfaz NO deja elegirla: la fija la plantilla, y una pieza
    recortada se corta a media animacion.
    """
    versiones = motion_capa.versiones_del_catalogo(CATALOGO)
    datos = json.loads(CATALOGO.read_text(encoding="utf-8")) if CATALOGO.is_file() else []
    return [
        {
            "nombre": d["nombre"],
            "version": versiones.get(d["nombre"], ""),
            "slots": list(d["slots_texto"]),
            "duracion_ms": mp.DURACION_MS.get(d["nombre"]),
            "acento": motion_capa.ACENTO_POR_PLANTILLA.get(d["nombre"]),
        }
        for d in datos
    ]


def _vista_de_plan(plan: mp.PlanMotion, origen: str, duracion_ms: int) -> dict:
    return {
        "origen": origen,
        "editable": True,
        "duracion_ms": duracion_ms,
        "orientacion": plan.orientacion,
        "piezas": [
            {
                "plantilla": p.plantilla,
                "t0_ms": p.t0_ms,
                "t1_ms": p.t1_ms,
                "texto": dict(p.texto),
                "banda": p.banda,
                "tramo_t0": p.tramo_t0,
            }
            for p in sorted(plan.piezas, key=lambda x: x.t0_ms)
        ],
        "omisiones": [
            {"plantilla": o.plantilla, "motivo": o.motivo, "detalle": o.detalle}
            for o in plan.omisiones
        ],
        "incidencias": list(plan.incidencias),
    }


def _hay_cambios_sin_renderizar(
    mp4: Path, piezas_selladas: list, origen: str, duracion_ms: int, orientacion: str, catalogo: set
) -> bool:
    """True si lo que K guardo ya no es lo que hay en el MP4.

    Desde que el editor ensena el plan del RENDER, guardar o descartar deja de cambiar el video
    hasta que se vuelve a lanzar Automatico. Callarse eso convertiria la correccion del punto 3
    en otra forma de mentir: el plan seria real y el aviso de "guardado" no.
    """
    editado = me.cargar(mp4, duracion_ms=duracion_ms, orientacion=orientacion, catalogo=catalogo)
    if editado is None:
        return origen == me.ORIGEN_EDITADO  # se descarto la edicion y el MP4 aun la lleva
    return me.a_sidecar(editado, duracion_ms=duracion_ms)["piezas"] != piezas_selladas


def ver_plan(clip: str, *, textos: motion_capa.OpcionesMotion | None = None) -> dict:
    """El plan EXACTO con el que se compuso el ultimo render de ese clip.

    El editor NO replanifica, y esto es una correccion, no una preferencia: al replanificar en
    el momento, el LLM recibia un juego de huecos distinto (los campos de marca del formulario
    cambian que piezas caben) y devolvia otros textos. K corregia un letrero y el MP4 tenia
    otro. Una previsualizacion que miente es peor que ninguna.

    Si el clip no se ha compuesto todavia no hay plan que ensenar y se dice tal cual. Inventar
    uno seria repetir el fallo con otra cara.

    `textos` se acepta por compatibilidad de la firma y ya no decide nada: lo que se muestra
    esta sellado en disco.
    """
    del textos
    mp4 = resolver_clip(clip)
    duracion_ms, orientacion, _fps = _meta_del_clip(mp4)
    versiones = motion_capa.versiones_del_catalogo(CATALOGO)
    sellado = me.cargar_render(mp4, orientacion=orientacion, catalogo=set(versiones))
    if sellado is None:
        raise StudioMotionError(
            f"'{mp4.stem}' no tiene letreros compuestos todavia. Lanza Automatico sobre ese "
            f"video con la capa encendida y vuelve: el editor ensena el plan del render, no uno "
            f"calculado al vuelo."
        )
    plan, origen = sellado
    vista = _vista_de_plan(plan, origen, duracion_ms)
    vista["pendiente_de_render"] = _hay_cambios_sin_renderizar(
        mp4, vista["piezas"], origen, duracion_ms, orientacion, set(versiones)
    )
    vista["clip"] = mp4.stem
    vista["catalogo"] = catalogo_para_ui()
    vista["separacion_min_ms"] = mp.SEPARACION_MIN_MS
    vista["tramos"] = [
        {"t0_ms": t.t0_ms, "t1_ms": t.t1_ms, "texto": t.texto} for t in _tramos_del_clip(mp4)
    ]
    return vista


PREVIS_DIR = ROOT / "output" / ".previsualizaciones"
PREVIS_ALTO = 420  # suficiente para leer el letrero, pequeno para que viaje rapido al navegador
TIMEOUT_PREVIS_S = 180


def _clave_previsualizacion(pieza: dict, ancho: int, alto: int, fps: int, version: str) -> str:
    """sha256 de todo lo que cambia la imagen: pieza, tamano, fps y version de plantilla.

    Es la MISMA idea que la clave de cache de las piezas: si K no toco nada, la vista sale de
    disco y no se renderiza otra vez. Y el instante SI entra, porque el fotograma del video de
    debajo cambia con el.
    """
    import hashlib  # noqa: PLC0415

    payload = json.dumps(
        {
            "plantilla": pieza.get("plantilla"),
            "t0_ms": pieza.get("t0_ms"),
            "texto": pieza.get("texto"),
            "banda": pieza.get("banda"),
            "tamano": [ancho, alto],
            "fps": fps,
            "version": version,
            "alto_previs": PREVIS_ALTO,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def previsualizar(clip: str, pieza: object) -> Path:
    """PNG del fotograma del video con la pieza compuesta encima, en su instante de entrada.

    Bajo demanda y con cache: la vista de una pieza que no cambio sale de disco. Se compone con
    los MISMOS modulos que el render (`hyperframes.pedir_pieza` y el desplazamiento de banda de
    `motion_capa`), asi que lo que K ve aqui es lo que va a salir en el video, no una maqueta.
    """
    if not isinstance(pieza, dict):
        raise StudioMotionError("la pieza debe ser un objeto")
    mp4 = resolver_clip(clip)
    duracion_ms, orientacion, fps = _meta_del_clip(mp4)
    versiones = motion_capa.versiones_del_catalogo(CATALOGO)
    plantilla = pieza.get("plantilla")
    if plantilla not in versiones:
        raise StudioMotionError(f"plantilla '{plantilla}' no esta en el catalogo")

    resultado = me.validar_plan(
        {"version": me.VERSION_SIDECAR, "piezas": [pieza]},
        duracion_ms=duracion_ms,
        orientacion=orientacion,
        catalogo=set(versiones),
    )
    if not resultado.ok:
        raise StudioMotionError(" | ".join(resultado.problemas))
    objeto = resultado.plan.piezas[0]

    import core  # noqa: PLC0415

    info = core.get_video_info(mp4)
    clave = _clave_previsualizacion(pieza, info["width"], info["height"], fps, versiones[plantilla])
    destino = PREVIS_DIR / f"{clave}.png"
    if destino.is_file():
        return destino
    PREVIS_DIR.mkdir(parents=True, exist_ok=True)
    return _componer_previsualizacion(mp4, objeto, info, fps, versiones[plantilla], destino)


def _componer_previsualizacion(
    mp4: Path, objeto, info: dict, fps: int, version: str, destino: Path
) -> Path:
    """Renderiza la pieza, saca el fotograma del video y los compone. Lanza si algo falla."""
    import subprocess  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    from hyperframes import pedir_pieza  # noqa: PLC0415
    from hyperframes.catalogo import Catalogo  # noqa: PLC0415

    ancho, alto = info["width"], info["height"]
    dato = motion_capa.contrato_de_pieza(
        objeto, version=version, ancho=ancho, alto=alto, fps=fps, marca=motion_capa.MARCA
    )
    catalogo = Catalogo.desde_archivo(CATALOGO, motion_capa.orientacion_de(ancho, alto))
    r = pedir_pieza(
        dato,
        destino=(ancho, alto),
        catalogo=catalogo,
        raiz_cache=ROOT / "output" / ".piezas",
        timeout_s=TIMEOUT_PREVIS_S,
    )
    if r.razon_fallo is not None:
        raise StudioMotionError(f"no se pudo renderizar la pieza: {r.razon_fallo.value}")

    # Instante del fotograma: el MEDIO de la pieza, no su entrada, porque en la entrada la
    # animacion todavia esta apareciendo y el letrero sale a medias.
    medio_pieza = objeto.duracion_ms * 0.0006
    medio_video = min(
        (objeto.t0_ms + objeto.duracion_ms / 2) / 1000.0, float(info["duration"]) - 0.1
    )
    desplazamiento = motion_capa.desplazamiento_de_banda(objeto.banda, alto) or (0, 0)
    with tempfile.TemporaryDirectory(prefix="hf3_previs_") as tmp:
        capa = Path(tmp) / "capa.png"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(r.ruta_mov),
                "-ss",
                f"{medio_pieza:.3f}",
                "-frames:v",
                "1",
                "-vf",
                "format=rgba",
                "-pix_fmt",
                "rgba",
                str(capa),
            ],
            check=True,
            timeout=TIMEOUT_PREVIS_S,
        )
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-ss",
                f"{max(medio_video, 0):.3f}",
                "-i",
                str(mp4),
                "-i",
                str(capa),
                "-filter_complex",
                f"[0:v][1:v]overlay={desplazamiento[0]}:{desplazamiento[1]},scale=-2:{PREVIS_ALTO}",
                "-frames:v",
                "1",
                str(destino),
            ],
            check=True,
            timeout=TIMEOUT_PREVIS_S,
        )
    return destino


def guardar_plan(clip: str, piezas: object) -> dict:
    """Valida y guarda el plan editado. Devuelve la vista nueva o lanza con TODOS los problemas.

    El plan se valida ANTES de tocar el disco: guardar uno invalido solo trasladaria el error
    al render, donde ya no hay nadie mirando.
    """
    mp4 = resolver_clip(clip)
    duracion_ms, orientacion, _fps = _meta_del_clip(mp4)
    versiones = motion_capa.versiones_del_catalogo(CATALOGO)
    dato = {"version": me.VERSION_SIDECAR, "piezas": piezas}
    resultado = me.validar_plan(
        dato, duracion_ms=duracion_ms, orientacion=orientacion, catalogo=set(versiones)
    )
    if not resultado.ok:
        raise StudioMotionError(" | ".join(resultado.problemas))
    me.guardar(mp4, resultado.plan, duracion_ms=duracion_ms)
    vista = _vista_de_plan(resultado.plan, me.ORIGEN_EDITADO, duracion_ms)
    vista["clip"] = mp4.stem
    # Recien guardado es, por definicion, lo que el MP4 todavia no lleva.
    vista["pendiente_de_render"] = True
    return vista


def descartar_edicion(clip: str) -> dict:
    """Borra el sidecar y devuelve el plan automatico. Nunca falla por no haber nada que borrar."""
    mp4 = resolver_clip(clip)
    habia = me.descartar(mp4)
    vista = ver_plan(clip)
    vista["descartado"] = habia
    return vista


__all__ = [
    "StudioMotionError",
    "catalogo_para_ui",
    "descartar_edicion",
    "PREVIS_DIR",
    "guardar_plan",
    "previsualizar",
    "resolver_clip",
    "ver_plan",
]
