"""motion_capa.py — Cableado de la capa de letreros del Motor B (HF-3, bloque 1).

Es el unico puente entre el planificador (`motion_plan`, que solo produce datos) y
`hyperframes.pedir_pieza` (que produce MOV con alfa). Devuelve `clip_overlay.ClipOverlay`
listos para la ruta de clips que Centrito ya usa para el b-roll de video, mas un informe
auditable de lo que se coloco y lo que no.

Tres reglas de esta capa, en orden de importancia:

1. APAGADA NO EXISTE. `opciones.enabled=False` devuelve cero clips sin importar nada, sin
   tocar disco, sin importar `hyperframes` y sin escribir un solo log. El render de arriba
   queda byte identico al historico.
2. FAIL-OPEN. Cualquier fallo (binario ausente, plantilla desconocida, timeout, contrato
   invalido, disco lleno) se registra en el informe y devuelve cero clips. El video sale sin
   letreros. Un motion graphic que no sale JAMAS tumba un paquete de clips.
3. EL SOLAPAMIENTO EN 9:16 ES UN ERROR, NO UN AVISO. `core_overlays._tejer_clips` encadena N
   overlays con su propia ventana `enable=between(t,t0,t1)` y no valida interseccion: dos
   piezas que se cruzan se pintan las dos, gana la ultima y nadie se entera. Aqui se comprueba
   antes de componer y, si ocurre, cae la capa ENTERA con un mensaje que nombra las dos piezas
   y su interseccion. Cae entera y no solo la pieza culpable a proposito: un solapamiento
   significa que el planificador tiene un bug, y servir media capa lo esconderia.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import motion_plan as mp
from clip_overlay import ClipOverlay

NOMBRE_CACHE = "piezas"  # subcarpeta de piezas DENTRO del paquete (sobrevive al resume)
CATALOGO_REL = Path("motion") / "catalogo.json"
FIT_DEFAULT = "nativo"

# Paleta OFICIAL de Prompt Models Studio. Sustituye a la provisional que se colo desde un
# fixture de HF-1. El fondo de marca (#0A0A0F) NO viaja en el contrato: ya vive en la placa
# estructural rgba(8, 8, 15, 0.78) de las plantillas, que es el mismo color.
MARCA_TEXTO = "#F5F5F7"
MARCA_SEPARADOR = "#2A2A35"
ACENTO_PRINCIPAL = "#FF3D3D"
ACENTO_SECUNDARIO = "#06B6D4"
ACENTO_TERCIARIO = "#6C3AED"

# Un acento por pieza, NUNCA tres en la misma. El principal va donde el video gana o pierde al
# espectador (el gancho y la llamada a la accion), el secundario es exclusivo de cifras, y el
# terciario va en lo que es literalmente una etiqueta: quien habla y de que se habla.
ACENTO_POR_PLANTILLA = {
    "hook": ACENTO_PRINCIPAL,
    "cierre": ACENTO_PRINCIPAL,
    "dato_destacado": ACENTO_SECUNDARIO,
    "lower_third": ACENTO_TERCIARIO,
    "titulo_seccion": ACENTO_TERCIARIO,
}

MARCA = {"primario": ACENTO_PRINCIPAL, "secundario": MARCA_SEPARADOR, "texto": MARCA_TEXTO}


def marca_de(plantilla: str, base: dict | None = None) -> dict:
    """Marca del contrato para UNA plantilla: la base con su acento en `primario`.

    Se resuelve aqui y no en el CSS porque el acento es un dato del contrato: asi el default
    declarado en el HTML y lo que manda Centrito dicen lo mismo, que es justo lo que exige el
    test de coherencia entre defaults y fallbacks.
    """
    marca = dict(base or MARCA)
    marca["primario"] = ACENTO_POR_PLANTILLA.get(plantilla, marca.get("primario"))
    return marca


class SolapamientoDePiezas(ValueError):
    """Dos piezas comparten instante en 9:16. Bug del planificador, no dato del usuario."""


@dataclass(frozen=True)
class OpcionesMotion:
    """Lo que la CLI o el Studio deciden sobre la capa. Default OFF en todos los campos."""

    enabled: bool = False
    titulo: str = ""
    kicker: str = ""
    nombre: str = ""
    rol: str = ""
    cta: str = ""
    # Los textos los escribe el LLM por default. Las heuristicas de espanol se quedan como
    # RESPALDO y entran solas si el modelo falla, devuelve basura o no hay clave configurada.
    textos_llm: bool = True

    def textos(self) -> mp.TextosMarca:
        return mp.TextosMarca(
            titulo=self.titulo, kicker=self.kicker, nombre=self.nombre, rol=self.rol, cta=self.cta
        )


@dataclass(frozen=True)
class ResultadoMotion:
    """Clips listos para componer + informe. `clips` vacio siempre es una salida valida."""

    clips: tuple[ClipOverlay, ...] = ()
    informe: dict = field(default_factory=dict)

    @property
    def activo(self) -> bool:
        return bool(self.clips)


def resolver_plan(
    *,
    clip_mp4: Path | None,
    duracion_ms: int,
    orientacion: str,
    textos: mp.TextosMarca,
    tramos: list[mp.Tramo] | None,
    tray_csv: Path | None,
    catalogo: set[str],
    textos_llm: bool = False,
    stem: str = "",
) -> tuple[mp.PlanMotion, str]:
    """(plan, origen). El plan EDITADO manda sobre el automatico si existe y es utilizable.

    El origen viaja al informe para que el Studio pueda decirle a K si lo que esta viendo es lo
    que decidio la maquina o lo que corrigio el. Sin ese dato, "por que salio asi" no tiene
    respuesta.
    """
    import motion_edicion as me  # noqa: PLC0415 (solo con la capa encendida)

    if clip_mp4 is not None:
        editado = me.cargar(
            clip_mp4, duracion_ms=duracion_ms, orientacion=orientacion, catalogo=catalogo
        )
        if editado is not None:
            print(f"[motion] plan EDITADO a mano: {len(editado.piezas)} pieza(s)")
            return editado, me.ORIGEN_EDITADO
    lista = list(tramos or [])
    plan = mp.planificar(
        duracion_ms=duracion_ms,
        orientacion=orientacion,
        textos=textos,
        tramos=lista,
        tray_csv=tray_csv,
        llm=_textos_del_llm(textos_llm, lista, duracion_ms, stem),
    )
    # SEGUNDA PASADA. La primera deja al modelo proponer instantes y solo se usan los que caen
    # donde el planificador abrio hueco; el resto volvia al respaldo de reglas. Aqui los
    # instantes YA estan fijados y se le pide texto para cada uno, con el fragmento hablado
    # delante, asi que no se descarta ninguno.
    if textos_llm:
        plan = rellenar_textos_con_llm(plan, lista, duracion_ms, stem)
    return plan, me.ORIGEN_AUTOMATICO


# Que slot de cada plantilla escribe el modelo en la segunda pasada, y con que limite. Los
# demas slots (nombre, rol, cta, cifra) NO se tocan: salen de la configuracion o de la primera
# pasada, y pedirselos otra vez solo los cambiaria sin motivo.
SLOT_A_RELLENAR = {
    "hook": ("titulo", mp.TITULO_SECCION_MAX_CHARS),
    "titulo_seccion": ("titulo", mp.TITULO_SECCION_MAX_CHARS),
    "cierre": ("titulo", mp.TITULO_SECCION_MAX_CHARS),
    "dato_destacado": ("etiqueta", mp.DATO_ETIQUETA_MAX_CHARS),
}
# Cuanto texto hablado se le da al modelo como contexto de cada pieza. Suficiente para que la
# frase se entienda, corto para que no se ponga a resumir el clip entero.
CONTEXTO_MS = 6000


def contexto_hablado(tramos: list[mp.Tramo], t0_ms: int, ventana_ms: int = CONTEXTO_MS) -> str:
    """Lo que se habla alrededor de `t0_ms`. PURO.

    Es lo que convierte la segunda pasada en algo util: el modelo no escribe sobre el clip en
    abstracto, escribe sobre lo que se dice JUSTO donde va el letrero.
    """
    desde, hasta = t0_ms - ventana_ms // 3, t0_ms + ventana_ms
    trozos = [
        " ".join((t.texto or "").split())
        for t in sorted(tramos, key=lambda x: x.t0_ms)
        if t.t1_ms >= desde and t.t0_ms <= hasta
    ]
    return " ".join(x for x in trozos if x).strip()


def rellenar_textos_con_llm(
    plan: mp.PlanMotion, tramos: list[mp.Tramo], duracion_ms: int, stem: str
) -> mp.PlanMotion:
    """Reescribe con el LLM el slot principal de cada pieza YA colocada. FAIL-OPEN.

    Mapeo uno a uno: una pieza, un texto. Lo que el modelo no devuelva se queda como estaba,
    que es el texto de las reglas. El plan sale con las mismas piezas en los mismos instantes:
    aqui solo cambian las palabras.
    """
    if not plan.piezas or not tramos:
        return plan
    try:
        import motion_textos_llm  # noqa: PLC0415

        huecos = []
        for i, pieza in enumerate(plan.piezas):
            slot = SLOT_A_RELLENAR.get(pieza.plantilla)
            if slot is None or slot[0] not in pieza.texto:
                continue
            contexto = contexto_hablado(tramos, pieza.t0_ms)
            if not contexto:
                continue
            huecos.append(
                {
                    "id": i,
                    "plantilla": pieza.plantilla,
                    "t0_ms": pieza.t0_ms,
                    "limite": slot[1],
                    "contexto": contexto,
                    # La cifra viaja para que la etiqueta no la repita: la tarjeta ya la pinta
                    # en grande justo encima, y decirla dos veces en el mismo cuadro se ve mal.
                    "cifra": pieza.texto.get("cifra", ""),
                }
            )
        if not huecos:
            return plan
        escritos = motion_textos_llm.pedir_textos_para(
            huecos,
            duracion_ms,
            stem=stem,
            transcripcion=" ".join((t.texto or "") for t in tramos),
        )
    except Exception as exc:  # noqa: BLE001 - la segunda pasada jamas tumba un plan
        print(f"[motion] relleno del LLM no disponible, se conservan las reglas: {exc}")
        return plan

    if not escritos:
        return plan
    piezas = []
    for i, pieza in enumerate(plan.piezas):
        texto = escritos.get(i)
        slot = SLOT_A_RELLENAR.get(pieza.plantilla)
        if not texto or slot is None or slot[0] not in pieza.texto:
            piezas.append(pieza)
            continue
        piezas.append(
            mp.Pieza(
                pieza.plantilla,
                pieza.t0_ms,
                pieza.t1_ms,
                {**pieza.texto, slot[0]: texto},
                pieza.banda,
                pieza.tramo_t0,
            )
        )
    return mp.PlanMotion(plan.orientacion, tuple(piezas), plan.omisiones, plan.incidencias)


def _textos_del_llm(activo: bool, tramos, duracion_ms: int, stem: str):
    """Textos del LLM, o None para que manden las reglas. FAIL-OPEN en todos los caminos."""
    if not activo:
        return None
    try:
        import motion_textos_llm  # noqa: PLC0415 (solo con la capa encendida)

        return motion_textos_llm.pedir_textos(list(tramos or []), duracion_ms, stem=stem)
    except Exception as exc:  # noqa: BLE001 - la capa de textos jamas tumba un plan
        print(f"[motion] textos del LLM no disponibles, se usan las reglas: {exc}")
        return None


def plan_automatico(
    *,
    duracion_ms: int,
    orientacion: str,
    textos: mp.TextosMarca,
    tramos: list[mp.Tramo] | None = None,
    tray_csv: Path | None = None,
) -> mp.PlanMotion:
    """El plan que propondria la maquina, ignorando cualquier edicion. Lo usa el Studio para
    ofrecer el boton de volver al automatico sin tener que borrar el sidecar antes."""
    return mp.planificar(
        duracion_ms=duracion_ms,
        orientacion=orientacion,
        textos=textos,
        tramos=tramos,
        tray_csv=tray_csv,
    )


def tramos_de_groups(groups: list[dict]) -> list[mp.Tramo]:
    """Grupos de subtitulo (transcript o SRT) -> tramos del planificador, en ms. PURO.

    Es el mismo objeto que ya alimenta los captions, asi que la busqueda de cifras mira
    exactamente el texto que el espectador va a leer. Un grupo sin tiempos numericos se salta:
    sin `start`/`end` no hay donde colocar el letrero.
    """
    tramos: list[mp.Tramo] = []
    for g in groups or []:
        inicio, fin = g.get("start"), g.get("end")
        if not isinstance(inicio, (int, float)) or not isinstance(fin, (int, float)):
            continue
        tramos.append(
            mp.Tramo(int(round(inicio * 1000)), int(round(fin * 1000)), g.get("text", ""))
        )
    return tramos


def orientacion_de(ancho: int, alto: int) -> str:
    """9:16 y cualquier retrato -> vertical. Cuadrado -> horizontal (lienzo 1920x1080)."""
    return "vertical" if alto > ancho else "horizontal"


def contrato_de_pieza(
    pieza: mp.Pieza, *, version: str, ancho: int, alto: int, fps: int, marca: dict[str, str]
) -> dict:
    """Contrato de pieza (HF-1) para una pieza ya planificada. PURO.

    `fps` es el del VIDEO DESTINO, no un default: la cadena de clips fuerza el fps de la base,
    asi que una pieza a 30 sobre un destino a 24 perderia 1 de cada 5 frames de animacion.
    `posicion.modo=cuadro_completo` porque las plantillas ya se colocan solas dentro de su
    lienzo; la caja queda disponible para quien la necesite, no se usa aqui.
    """
    return {
        "contrato": 1,
        "pieza_id": f"{pieza.plantilla}_{pieza.t0_ms}",
        "plantilla": {"nombre": pieza.plantilla, "version": version},
        "duracion_ms": pieza.duracion_ms,
        "fps": int(fps),
        "tamano": {"ancho": int(ancho), "alto": int(alto)},
        "texto": dict(pieza.texto),
        "marca": marca_de(pieza.plantilla, marca),
        "posicion": {"modo": "cuadro_completo"},
        "fit": FIT_DEFAULT,
        "audio": False,
        "semilla": 0,
    }


def versiones_del_catalogo(ruta_json: Path) -> dict[str, str]:
    """{nombre de plantilla: version} leido del catalogo en disco.

    El contrato de pieza tiene que citar la version EXACTA que declara el catalogo: escrita a
    mano en un literal, el dia que una plantilla suba de version `Catalogo.exigir` rechazaria la
    pieza y la capa entera se apagaria por un numero desactualizado.
    """
    import json  # noqa: PLC0415

    ruta = Path(ruta_json)
    if not ruta.is_file():
        return {}
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    return {str(d["nombre"]): str(d["version"]) for d in datos}


def validar_sin_solape(piezas: list[mp.Pieza], orientacion: str) -> None:
    """Lanza SolapamientoDePiezas si dos piezas se cruzan en el tiempo. Solo en 9:16.

    En 16:9 las bandas del catalogo son disjuntas (lower_third abajo a la izquierda, el resto
    centradas arriba), asi que dos piezas simultaneas se leen bien y el cruce es tolerable.
    """
    if orientacion != "vertical":
        return
    ordenadas = sorted(piezas, key=lambda p: (p.t0_ms, p.t1_ms))
    for previa, siguiente in zip(ordenadas, ordenadas[1:], strict=False):
        if siguiente.t0_ms < previa.t1_ms:
            raise SolapamientoDePiezas(
                f"las piezas '{previa.plantilla}' [{previa.t0_ms}, {previa.t1_ms}] ms y "
                f"'{siguiente.plantilla}' [{siguiente.t0_ms}, {siguiente.t1_ms}] ms se solapan "
                f"{previa.t1_ms - siguiente.t0_ms} ms en 9:16, donde comparten carril. La ruta "
                f"de clips las pintaria las dos y ganaria la ultima sin avisar."
            )


def _sellar_plan_renderizado(
    clip_mp4: Path | None, plan: mp.PlanMotion, duracion_ms: int, origen: str
) -> None:
    """Deja junto al clip el plan EXACTO que se va a componer. Un fallo aqui no tumba el render.

    Es lo unico que permite que el editor ensene lo que de verdad esta en el MP4 en vez de
    replanificar, que puede dar otros textos porque el LLM recibe otro juego de huecos.
    """
    if clip_mp4 is None:
        return
    try:
        import motion_edicion as me  # noqa: PLC0415

        me.sellar_render(clip_mp4, plan, duracion_ms=duracion_ms, origen=origen)
    except Exception as exc:  # noqa: BLE001
        print(f"[motion] no se pudo sellar el plan renderizado: {exc}")


def _informe_base(plan: mp.PlanMotion | None) -> dict:
    return {
        "enabled": True,
        "plan": plan.a_dict() if plan else None,
        "piezas_ok": [],
        "piezas_fallidas": [],
        "error": None,
    }


def clips_de_motion(
    *,
    opciones: OpcionesMotion,
    ancho: int,
    alto: int,
    fps: float,
    duracion_s: float,
    raiz_cache: Path,
    root: Path,
    marca: dict[str, str] | None = None,
    tramos: list[mp.Tramo] | None = None,
    tray_csv: Path | None = None,
    timeout_s: float = 180.0,
    clip_mp4: Path | None = None,
) -> ResultadoMotion:
    """Planifica, pide las piezas y devuelve los overlays. NUNCA lanza.

    `raiz_cache` debe apuntar DENTRO del paquete (ver `raiz_cache_de_paquete`): asi las piezas
    viajan con el paquete y una reanudacion las encuentra en vez de volver a renderizarlas.
    """
    if not opciones.enabled:
        return ResultadoMotion((), {"enabled": False})
    try:
        return _clips_de_motion(
            opciones=opciones,
            ancho=ancho,
            alto=alto,
            fps=fps,
            duracion_s=duracion_s,
            marca=dict(marca or MARCA),
            raiz_cache=Path(raiz_cache),
            root=Path(root),
            tramos=tramos,
            tray_csv=tray_csv,
            timeout_s=timeout_s,
            clip_mp4=clip_mp4,
        )
    except Exception as exc:  # noqa: BLE001 - fail-open duro: la capa jamas tumba el render
        print(f"[motion] capa desactivada por un fallo, el video sale sin letreros: {exc}")
        return ResultadoMotion((), {"enabled": True, "plan": None, "error": f"{exc}"})


def _clips_de_motion(
    *,
    opciones: OpcionesMotion,
    ancho: int,
    alto: int,
    fps: float,
    duracion_s: float,
    marca: dict[str, str],
    raiz_cache: Path,
    root: Path,
    tramos: list[mp.Tramo] | None,
    tray_csv: Path | None,
    timeout_s: float,
    clip_mp4: Path | None,
) -> ResultadoMotion:
    from hyperframes import pedir_pieza  # noqa: PLC0415 (solo con la capa encendida)
    from hyperframes.catalogo import Catalogo  # noqa: PLC0415

    orientacion = orientacion_de(ancho, alto)
    fps_destino = max(int(round(float(fps) or 30.0)), 1)
    duracion_ms = int(round(float(duracion_s) * 1000))
    ruta_catalogo = root / CATALOGO_REL
    versiones = versiones_del_catalogo(ruta_catalogo)

    plan, origen = resolver_plan(
        clip_mp4=clip_mp4,
        duracion_ms=duracion_ms,
        orientacion=orientacion,
        textos=opciones.textos(),
        tramos=tramos,
        tray_csv=tray_csv,
        catalogo=set(versiones),
        textos_llm=opciones.textos_llm,
        stem=Path(clip_mp4).stem if clip_mp4 else "",
    )
    informe = _informe_base(plan)
    informe["origen"] = origen
    _sellar_plan_renderizado(clip_mp4, plan, duracion_ms, origen)
    if plan.vacio:
        print(f"[motion] el planificador no coloco ninguna pieza ({len(plan.omisiones)} omitidas)")
        return ResultadoMotion((), informe)

    validar_sin_solape(list(plan.piezas), orientacion)

    catalogo = Catalogo.desde_archivo(ruta_catalogo, orientacion)
    raiz_cache.mkdir(parents=True, exist_ok=True)

    clips: list[ClipOverlay] = []
    for pieza in plan.piezas:
        dato = contrato_de_pieza(
            pieza,
            version=versiones.get(pieza.plantilla, ""),
            ancho=ancho,
            alto=alto,
            fps=fps_destino,
            marca=marca,
        )
        r = pedir_pieza(
            dato,
            destino=(int(ancho), int(alto)),
            catalogo=catalogo,
            raiz_cache=raiz_cache,
            timeout_s=timeout_s,
        )
        if r.razon_fallo is not None:
            print(
                f"[motion] pieza '{pieza.plantilla}' omitida: {r.razon_fallo.value} ({r.detalle})"
            )
            informe["piezas_fallidas"].append(
                {"plantilla": pieza.plantilla, "razon": r.razon_fallo.value, "detalle": r.detalle}
            )
            continue
        informe["piezas_ok"].append(
            {
                "plantilla": pieza.plantilla,
                "t0_ms": pieza.t0_ms,
                "t1_ms": pieza.t1_ms,
                "hash": r.hash,
                "sha256": r.sha256,
                "desde_cache": r.desde_cache,
            }
        )
        clips.append(_overlay_de(pieza, r, alto))

    print(f"[motion] {len(clips)}/{len(plan.piezas)} piezas compuestas en {orientacion}")
    return ResultadoMotion(tuple(clips), informe)


def desplazamiento_de_banda(banda: str, alto: int) -> tuple[int, int] | None:
    """(x, y) de composicion para la banda pedida, o None si va donde el HTML la dibuja.

    La pieza SIEMPRE se renderiza a cuadro completo con su contenido en el carril nativo; para
    llevarla a la banda superior no se toca la plantilla, se compone el overlay desplazado hacia
    arriba. Asi hay UN solo HTML por pieza y no dos que se desincronizan, y el desplazamiento
    queda donde se puede probar sin renderizar.
    """
    if banda != mp.BANDA_ARRIBA:
        return None
    y = int(round(mp.DESPLAZAMIENTO_SUPERIOR * int(alto)))
    return (0, y)


def _overlay_de(pieza: mp.Pieza, resultado, alto: int) -> ClipOverlay:
    """Pieza + resultado de HyperFrames -> ClipOverlay con los ajustes medidos en HF-0.

    `loop=False` porque la pieza dura exactamente su ventana y repetirla la reiniciaria a media
    animacion. `behind_text=True` para que los captions queden ENCIMA del letrero: el texto
    hablado manda. `fade`, `fit` y `mute` salen de `consumo_sugerido`, que es donde HyperFrames
    publica como quiere ser consumido, en vez de repetirse aqui.
    """
    consumo = dict(resultado.consumo_sugerido)
    return ClipOverlay(
        clip=Path(resultado.ruta_mov),
        t0=pieza.t0_ms / 1000.0,
        t1=pieza.t1_ms / 1000.0,
        loop=False,
        fit=consumo.get("fit", FIT_DEFAULT),
        size_pct=1.0,
        behind_text=True,
        fade=bool(consumo.get("fade", False)),
        mute=bool(consumo.get("mute", True)),
        # cuadro_completo: la plantilla ya se coloca dentro de su lienzo. El unico caso con
        # posicion explicita es la banda superior, donde el overlay entero sube.
        posicion=desplazamiento_de_banda(pieza.banda, alto),
    )


def raiz_cache_de_paquete(paquete_dir: Path) -> Path:
    """Donde viven las piezas de un paquete. Fuente UNICA para las dos rutas de paquete.

    `auto._paquete_dir` (classic) y `auto._paquete_dir_v2` eligen carpeta por caminos distintos;
    si cada uno decidiera por su cuenta donde guardar las piezas, una de las dos rutas quedaria
    con las piezas fuera del paquete y nadie se enteraria hasta que un resume las buscase y no
    estuviesen. Por eso el nombre se decide aqui y en un solo sitio.
    """
    return Path(paquete_dir) / NOMBRE_CACHE


__all__ = [
    "NOMBRE_CACHE",
    "OpcionesMotion",
    "ResultadoMotion",
    "SolapamientoDePiezas",
    "ACENTO_POR_PLANTILLA",
    "MARCA",
    "CONTEXTO_MS",
    "SLOT_A_RELLENAR",
    "clips_de_motion",
    "contexto_hablado",
    "contrato_de_pieza",
    "desplazamiento_de_banda",
    "marca_de",
    "orientacion_de",
    "plan_automatico",
    "raiz_cache_de_paquete",
    "rellenar_textos_con_llm",
    "resolver_plan",
    "tramos_de_groups",
    "validar_sin_solape",
    "versiones_del_catalogo",
]
