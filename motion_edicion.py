"""motion_edicion.py — El plan de letreros que K corrige a mano (HF-3, edicion desde el Studio).

Hasta ahora K solo podia PRENDER Y APAGAR la capa entera. El planificador decide bien la mayor
parte del tiempo, pero cuando se equivoca no habia nada que hacer salvo apagarlo todo. Este
modulo es el contrato del plan EDITADO: un sidecar junto al clip que, si existe, MANDA sobre lo
que decidiria el planificador.

Tres reglas, en orden de importancia:

1. EL SIDECAR MANDA, PERO NO A CIEGAS. Un plan editado pasa por las mismas validaciones que uno
   automatico (solapamiento, zona prohibida, limites del clip). Si no las pasa, se dice cual
   falla y NO se guarda. Guardar un plan invalido solo trasladaria el error al render, donde ya
   no hay nadie mirando.
2. SIEMPRE SE PUEDE VOLVER. Borrar el sidecar devuelve el plan automatico exacto. La edicion es
   una capa encima, nunca una sustitucion destructiva.
3. FAIL-OPEN. Un sidecar ilegible o de otra version se ignora con aviso y se replanifica. Nunca
   tumba un render.

PURO salvo la lectura y escritura del sidecar, que van por `atomic_io` como el resto del repo.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import motion_plan as mp

SUFIJO_SIDECAR = "_motion_plan.json"
# El plan EXACTO con el que se compuso el ultimo render de este clip. No es lo mismo que el
# sidecar de edicion: aquel es lo que K quiere, este es lo que de verdad se pinto. El editor
# tiene que ensenar ESTE, porque replanificar en el momento puede dar otros textos (el LLM
# recibe otro juego de huecos) y entonces K corrige un letrero que no esta en el MP4.
SUFIJO_RENDER = "_motion_render.json"
VERSION_SIDECAR = 1
# Cuanto puede durar un clip como maximo, en ms. Es un tope de cordura del validador, no una
# regla de negocio: por encima de esto lo que hay es un numero mal tecleado.
DURACION_MAX_MS = 4 * 60 * 60 * 1000

ORIGEN_AUTOMATICO = "automatico"
ORIGEN_EDITADO = "editado"


class PlanEditadoInvalido(ValueError):
    """El plan que llega del Studio no se puede componer. El mensaje dice exactamente por que."""


@dataclass(frozen=True)
class ResultadoValidacion:
    """Lo que devuelve el validador: el plan saneado o la lista de problemas."""

    plan: mp.PlanMotion | None = None
    problemas: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.plan is not None and not self.problemas


def ruta_sidecar(clip_mp4: Path) -> Path:
    """Donde vive el plan editado de un clip: junto al MP4, con su mismo stem."""
    clip_mp4 = Path(clip_mp4)
    return clip_mp4.with_name(f"{clip_mp4.stem}{SUFIJO_SIDECAR}")


def ruta_render(clip_mp4: Path) -> Path:
    """Donde queda sellado el plan con el que se compuso el ultimo render de ese clip."""
    clip_mp4 = Path(clip_mp4)
    return clip_mp4.with_name(f"{clip_mp4.stem}{SUFIJO_RENDER}")


# ── Validacion ───────────────────────────────────────────────────────────────


def _problemas_de_pieza(dato: object, indice: int, duracion_ms: int, catalogo: set[str]) -> list:
    """Problemas de UNA pieza, con el indice delante para que el Studio sepa cual senalar."""
    prefijo = f"pieza {indice + 1}"
    if not isinstance(dato, dict):
        return [f"{prefijo}: no es un objeto"]
    problemas: list[str] = []

    plantilla = dato.get("plantilla")
    if plantilla not in catalogo:
        problemas.append(
            f"{prefijo}: plantilla '{plantilla}' no esta en el catalogo "
            f"({', '.join(sorted(catalogo))})"
        )

    t0, t1 = dato.get("t0_ms"), dato.get("t1_ms")
    for nombre, valor in (("t0_ms", t0), ("t1_ms", t1)):
        if not isinstance(valor, int) or isinstance(valor, bool):
            problemas.append(f"{prefijo}: {nombre} debe ser un entero de milisegundos")
    if problemas:
        return problemas

    if t0 < 0:
        problemas.append(f"{prefijo}: empieza en {t0} ms, antes del principio del clip")
    if t1 <= t0:
        problemas.append(f"{prefijo}: termina en {t1} ms, que no es despues de {t0} ms")
    if t1 > duracion_ms:
        problemas.append(
            f"{prefijo}: termina en {t1} ms y el clip dura {duracion_ms} ms. "
            f"Ninguna pieza puede cruzar el final."
        )
    # La duracion la fija la plantilla, no el usuario: una pieza recortada se corta a media
    # animacion. Se avisa en vez de recortar en silencio.
    esperada = mp.DURACION_MS.get(plantilla)
    if esperada is not None and (t1 - t0) != esperada:
        problemas.append(
            f"{prefijo}: '{plantilla}' dura {esperada} ms y se pidieron {t1 - t0} ms. "
            f"Mueve la pieza, no la estires."
        )

    texto = dato.get("texto")
    if not isinstance(texto, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in texto.items()
    ):
        problemas.append(f"{prefijo}: texto debe ser un objeto de cadenas")

    banda = dato.get("banda", mp.BANDA_CENTRO)
    if banda not in (mp.BANDA_CENTRO, mp.BANDA_ARRIBA):
        problemas.append(f"{prefijo}: banda '{banda}' desconocida")
    return problemas


def _problemas_entre_piezas(piezas: list[mp.Pieza], orientacion: str) -> list[str]:
    """Solapamiento y separacion minima. En 9:16 el solapamiento es un error duro."""
    problemas: list[str] = []
    orden = sorted(piezas, key=lambda p: (p.t0_ms, p.t1_ms))
    for previa, siguiente in zip(orden, orden[1:], strict=False):
        if siguiente.t0_ms < previa.t1_ms:
            problemas.append(
                f"'{previa.plantilla}' y '{siguiente.plantilla}' se solapan "
                f"{previa.t1_ms - siguiente.t0_ms} ms. En 9:16 comparten carril y la ruta de "
                f"clips pintaria las dos, ganando la ultima sin avisar."
                if orientacion == "vertical"
                else f"'{previa.plantilla}' y '{siguiente.plantilla}' se solapan "
                f"{previa.t1_ms - siguiente.t0_ms} ms."
            )
        elif siguiente.t0_ms - previa.t1_ms < mp.SEPARACION_MIN_MS:
            problemas.append(
                f"entre '{previa.plantilla}' y '{siguiente.plantilla}' hay "
                f"{siguiente.t0_ms - previa.t1_ms} ms y hacen falta {mp.SEPARACION_MIN_MS}."
            )
    return problemas


def validar_plan(
    dato: object, *, duracion_ms: int, orientacion: str, catalogo: set[str]
) -> ResultadoValidacion:
    """Valida un plan que viene del Studio. Devuelve el plan saneado o TODOS los problemas.

    Se devuelven todos y no el primero a proposito: el Studio los pinta juntos y K arregla de
    una pasada en vez de descubrirlos de uno en uno.
    """
    if not isinstance(dato, dict):
        return ResultadoValidacion(problemas=("el plan debe ser un objeto",))
    if dato.get("version") != VERSION_SIDECAR:
        return ResultadoValidacion(
            problemas=(
                f"version de plan {dato.get('version')!r}; esta version de Centrito escribe "
                f"{VERSION_SIDECAR}",
            )
        )
    if orientacion not in mp.ORIENTACIONES:
        return ResultadoValidacion(problemas=(f"orientacion '{orientacion}' desconocida",))
    if not isinstance(duracion_ms, int) or duracion_ms <= 0 or duracion_ms > DURACION_MAX_MS:
        return ResultadoValidacion(problemas=(f"duracion del clip invalida: {duracion_ms!r}",))

    crudas = dato.get("piezas")
    if not isinstance(crudas, list):
        return ResultadoValidacion(problemas=("piezas debe ser una lista",))

    problemas: list[str] = []
    for i, cruda in enumerate(crudas):
        problemas.extend(_problemas_de_pieza(cruda, i, duracion_ms, catalogo))
    if problemas:
        return ResultadoValidacion(problemas=tuple(problemas))

    piezas = [
        mp.Pieza(
            plantilla=c["plantilla"],
            t0_ms=c["t0_ms"],
            t1_ms=c["t1_ms"],
            texto=dict(c["texto"]),
            banda=c.get("banda", mp.BANDA_CENTRO),
            tramo_t0=c.get("tramo_t0"),
        )
        for c in crudas
    ]
    problemas = _problemas_entre_piezas(piezas, orientacion)
    if problemas:
        return ResultadoValidacion(problemas=tuple(problemas))

    piezas.sort(key=lambda p: p.t0_ms)
    return ResultadoValidacion(plan=mp.PlanMotion(orientacion, tuple(piezas)))


# ── Serializacion ────────────────────────────────────────────────────────────


def a_sidecar(plan: mp.PlanMotion, *, duracion_ms: int) -> dict:
    """Plan -> objeto del sidecar. Incluye la duracion para poder revalidar sin abrir el MP4."""
    return {
        "version": VERSION_SIDECAR,
        "orientacion": plan.orientacion,
        "duracion_ms": int(duracion_ms),
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
    }


def guardar(clip_mp4: Path, plan: mp.PlanMotion, *, duracion_ms: int) -> Path:
    """Escribe el sidecar de forma ATOMICA. Devuelve la ruta."""
    from atomic_io import atomic_write_json  # noqa: PLC0415

    destino = ruta_sidecar(clip_mp4)
    atomic_write_json(destino, a_sidecar(plan, duracion_ms=duracion_ms))
    return destino


def sellar_render(
    clip_mp4: Path, plan: mp.PlanMotion, *, duracion_ms: int, origen: str, huella_entrada: str = ""
) -> Path:
    """Deja escrito el plan EXACTO que se acaba de componer. Un fallo no tumba el render.

    Es lo que hace honesta la previsualizacion: sin esto, el editor replanificaba y podia
    ensenar textos que no estan en el MP4, porque el LLM recibe un juego de huecos distinto
    segun los campos de marca que traiga el formulario.
    """
    from atomic_io import atomic_write_json  # noqa: PLC0415

    destino = ruta_render(clip_mp4)
    atomic_write_json(
        destino,
        {
            **a_sidecar(plan, duracion_ms=duracion_ms),
            "origen": origen,
            # Huella de TODO lo que entro al planificador. Es lo que permite reutilizar este
            # plan en la siguiente corrida en vez de volver a preguntarle al modelo, que no
            # responde dos veces igual ni a temperatura 0.
            "huella_entrada": huella_entrada,
            # Lo descartado viaja con lo colocado. Un plan reutilizado sin sus omisiones seria
            # un plan que ya no sabe explicar por que le falta una pieza, y eso es justo lo que
            # el editor le ensena a K.
            "omisiones": [
                {"plantilla": o.plantilla, "motivo": o.motivo, "detalle": o.detalle}
                for o in plan.omisiones
            ],
            "incidencias": list(plan.incidencias),
        },
    )
    return destino


def cargar_render(
    clip_mp4: Path, *, orientacion: str, catalogo: set[str], huella_entrada: str | None = None
):
    """(plan, origen) del ultimo render de ese clip, o None si no hay o no vale. FAIL-OPEN.

    La duracion sale del propio sidecar: es la que tenia el clip cuando se compuso, y es la
    unica contra la que ese plan es valido.

    Con `huella_entrada` se exige ademas que las entradas del planificador sean LAS MISMAS. El
    editor no la pasa, porque quiere ver lo que hay en el MP4 sea cual sea; el pipeline si, para
    no replanificar un clip que no ha cambiado.
    """
    ruta = ruta_render(clip_mp4)
    if not ruta.is_file():
        return None
    try:
        dato = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"[motion] plan renderizado ilegible: {ruta.name} ({exc})")
        return None
    if not isinstance(dato, dict):
        return None
    duracion_ms = dato.get("duracion_ms")
    if not isinstance(duracion_ms, int):
        return None
    if huella_entrada is not None and dato.get("huella_entrada") != huella_entrada:
        return None  # el clip, su transcripcion o los textos de marca cambiaron
    resultado = validar_plan(
        dato, duracion_ms=duracion_ms, orientacion=orientacion, catalogo=catalogo
    )
    if not resultado.ok:
        print(f"[motion] plan renderizado no valido: {'; '.join(resultado.problemas)}")
        return None
    origen = dato.get("origen")
    plan = _con_lo_descartado(resultado.plan, dato)
    return plan, (origen if isinstance(origen, str) else ORIGEN_AUTOMATICO)


def _con_lo_descartado(plan: mp.PlanMotion, dato: dict) -> mp.PlanMotion:
    """Devuelve el plan con sus omisiones e incidencias, que el validador no reconstruye."""
    crudas = dato.get("omisiones")
    omisiones = (
        tuple(
            mp.Omision(
                str(o.get("plantilla", "")), str(o.get("motivo", "")), str(o.get("detalle", ""))
            )
            for o in crudas
            if isinstance(o, dict)
        )
        if isinstance(crudas, list)
        else ()
    )
    incidencias = dato.get("incidencias")
    return mp.PlanMotion(
        plan.orientacion,
        plan.piezas,
        omisiones,
        tuple(x for x in incidencias if isinstance(x, str))
        if isinstance(incidencias, list)
        else (),
    )


def descartar(clip_mp4: Path) -> bool:
    """Borra el sidecar y vuelve al plan automatico. True si habia algo que borrar."""
    destino = ruta_sidecar(clip_mp4)
    if not destino.exists():
        return False
    destino.unlink()
    return True


def cargar(clip_mp4: Path, *, duracion_ms: int, orientacion: str, catalogo: set[str]):
    """Plan editado del clip, o None si no hay o no es utilizable. FAIL-OPEN.

    Un sidecar ilegible, de otra version o que ya no valida (por ejemplo porque el clip cambio
    de duracion al reencuadrarlo) se IGNORA con aviso y se replanifica. Preferir el plan
    automatico a un plan editado que no se puede componer es lo unico que deja el render
    funcionando sin nadie delante.
    """
    ruta = ruta_sidecar(clip_mp4)
    if not ruta.is_file():
        return None
    try:
        dato = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"[motion] plan editado ilegible, se replanifica: {ruta.name} ({exc})")
        return None
    resultado = validar_plan(
        dato, duracion_ms=duracion_ms, orientacion=orientacion, catalogo=catalogo
    )
    if not resultado.ok:
        print(
            f"[motion] plan editado no valido, se replanifica: {ruta.name} "
            f"({'; '.join(resultado.problemas)})"
        )
        return None
    return resultado.plan


__all__ = [
    "ORIGEN_AUTOMATICO",
    "ORIGEN_EDITADO",
    "SUFIJO_RENDER",
    "SUFIJO_SIDECAR",
    "VERSION_SIDECAR",
    "PlanEditadoInvalido",
    "ResultadoValidacion",
    "a_sidecar",
    "cargar",
    "cargar_render",
    "descartar",
    "guardar",
    "ruta_render",
    "ruta_sidecar",
    "sellar_render",
    "validar_plan",
]
