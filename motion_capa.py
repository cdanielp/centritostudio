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

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

import motion_plan as mp
import motion_plan_spatial as mps
from clip_overlay import ClipOverlay
from hyperframes.contrato import ESTILOS_VALIDOS

NOMBRE_CACHE = "piezas"  # subcarpeta de piezas DENTRO del paquete (sobrevive al resume)
CATALOGO_REL = Path("motion") / "catalogo.json"
FIT_DEFAULT = "nativo"
ESTILO_DEFAULT = ESTILOS_VALIDOS[0]  # "pms": el estilo de fabrica, siempre declarado primero

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
    # Variantes de estilo de lower_third (HF-4). La clave es el nombre de PLANTILLA resuelto
    # ("<funcion>_<estilo>"), no el estilo suelto: asi marca_de() sigue siendo el UNICO sitio
    # que decide el acento, sea cual sea el eje que lo dispara.
    "lower_third_claro": ACENTO_PRINCIPAL,
    "lower_third_minimo": ACENTO_SECUNDARIO,
    "lower_third_rudo": ACENTO_PRINCIPAL,
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


def resolver_estilo(funcion: str, estilo: str, versiones: dict[str, str]) -> tuple[str, str, bool]:
    """(nombre_de_plantilla, version, cayo_a_pms) para UNA funcion y el estilo pedido.

    Hoy una plantilla se resolvia por (funcion, orientacion); esto anade el eje estilo sin
    tocar `Catalogo`: la variante de estilo es una entrada MAS del catalogo, con su propio
    nombre "<funcion>_<estilo>" (HF-4). Si esa combinacion no esta declarada, cae a la funcion
    a secas (el estilo "pms" de fabrica) en vez de fallar: hoy solo `lower_third` tiene las
    cuatro variantes, y que las otras cuatro funciones caigan siempre es lo esperado, no un
    error. NUNCA lanza: sin plantilla para la funcion a secas, `version` sale vacio y quien
    llama (Catalogo.exigir, aguas abajo) es quien se queja con detalle.
    """
    if estilo != ESTILO_DEFAULT:
        candidato = f"{funcion}_{estilo}"
        version_candidata = versiones.get(candidato)
        if version_candidata is not None:
            return candidato, version_candidata, False
    return funcion, versiones.get(funcion, ""), estilo != ESTILO_DEFAULT


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
    # Estilo visual pedido para TODAS las piezas del video (HF-4). "pms" es el de fabrica.
    # Una funcion sin variante para el estilo pedido cae a "pms" sola; ver `resolver_estilo`.
    estilo: str = ESTILO_DEFAULT

    def textos(self) -> mp.TextosMarca:
        return mp.TextosMarca(
            titulo=self.titulo, kicker=self.kicker, nombre=self.nombre, rol=self.rol, cta=self.cta
        )


@dataclass(frozen=True)
class ResultadoMotion:
    """Clips listos para componer + informe. `clips` vacio siempre es una salida valida.

    `plan` (HF-4, Formato dual) es el `PlanMotion` TEMPORAL vivo detras de `informe["plan"]`
    (que solo trae el dict serializado). Una pierna extra de formato lo necesita para
    `plan_para_otro_formato`, sin volver a llamar al LLM. `None` cuando la capa esta apagada o
    fallo: sin plan primario no hay de donde derivar una pierna extra.
    """

    clips: tuple[ClipOverlay, ...] = ()
    informe: dict = field(default_factory=dict)
    plan: mp.PlanMotion | None = None

    @property
    def activo(self) -> bool:
        return bool(self.clips)


def huella_de_entrada(
    *,
    duracion_ms: int,
    orientacion: str,
    textos: mp.TextosMarca,
    tramos: list[mp.Tramo],
    tray_csv: Path | None,
    catalogo: set[str],
    textos_llm: bool,
    estilo: str = ESTILO_DEFAULT,
) -> str:
    """sha256 de TODO lo que entra al planificador. PURO.

    Si esto no cambia, el plan tampoco tiene por que cambiar, y lo unico que introduciria una
    diferencia seria volver a preguntarle al modelo. Por eso la trayectoria entra por su
    contenido y no por su ruta: el mismo CSV movido de sitio no es una entrada distinta.

    `estilo` entra aqui (HF-4) aunque el planificador nunca lo lee: sin el, cambiar de estilo
    con el mismo clip reutilizaria el plan sellado del render anterior (mismas entradas segun
    esta huella) y el sidecar `<clip>_motion_render.json` seguiria describiendo el estilo
    viejo. La huella tiene que ver el estilo para que el sello quede honesto, no porque el
    estilo mueva una sola pieza.
    """
    import hashlib  # noqa: PLC0415

    firma_tray = ""
    if tray_csv is not None and Path(tray_csv).is_file():
        firma_tray = hashlib.sha256(Path(tray_csv).read_bytes()).hexdigest()
    payload = json.dumps(
        {
            "duracion_ms": int(duracion_ms),
            "orientacion": orientacion,
            "textos": [textos.titulo, textos.kicker, textos.nombre, textos.rol, textos.cta],
            "tramos": [[t.t0_ms, t.t1_ms, t.texto] for t in tramos],
            "tray": firma_tray,
            "catalogo": sorted(catalogo),
            "textos_llm": bool(textos_llm),
            "estilo": estilo,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
    estilo: str = ESTILO_DEFAULT,
) -> tuple[mp.PlanMotion, str]:
    """(plan, origen). El plan EDITADO manda sobre el automatico si existe y es utilizable.

    El origen viaja al informe para que el Studio pueda decirle a K si lo que esta viendo es lo
    que decidio la maquina o lo que corrigio el. Sin ese dato, "por que salio asi" no tiene
    respuesta.

    `estilo` no cambia UNA sola decision del planificador (ver `huella_de_entrada`): viaja
    hasta aqui solo para que la huella del plan reutilizado lo vea.
    """
    import motion_edicion as me  # noqa: PLC0415 (solo con la capa encendida)

    lista = list(tramos or [])
    if clip_mp4 is not None:
        editado = me.cargar(
            clip_mp4, duracion_ms=duracion_ms, orientacion=orientacion, catalogo=catalogo
        )
        if editado is not None:
            print(f"[motion] plan EDITADO a mano: {len(editado.piezas)} pieza(s)")
            return editado, me.ORIGEN_EDITADO
        # El plan del render anterior manda si NADA de lo que entra al planificador ha cambiado.
        # Sin esto, procesar dos veces el mismo clip da dos planes distintos, porque el modelo
        # no responde igual dos veces ni a temperatura 0: se midio con `dato_destacado` saliendo
        # en 6 clips y en 7 con el mismo codigo. El plan es un ARTEFACTO del clip, no algo que
        # se vuelva a negociar en cada corrida.
        marca = huella_de_entrada(
            duracion_ms=duracion_ms,
            orientacion=orientacion,
            textos=textos,
            tramos=lista,
            tray_csv=tray_csv,
            catalogo=catalogo,
            estilo=estilo,
            textos_llm=textos_llm,
        )
        previo = me.cargar_render(
            clip_mp4, orientacion=orientacion, catalogo=catalogo, huella_entrada=marca
        )
        if previo is not None:
            print(
                f"[motion] plan REUTILIZADO del render anterior: {len(previo[0].piezas)} pieza(s)"
            )
            return previo
    else:
        marca = ""
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
    # El sello va AQUI y no en el render: es lo que hace que la proxima corrida reutilice este
    # plan en vez de volver a negociarlo, y lo que el editor ensena.
    _sellar_plan_renderizado(clip_mp4, plan, duracion_ms, me.ORIGEN_AUTOMATICO, marca)
    return plan, me.ORIGEN_AUTOMATICO


# HF-4 Paso 1/3 (Formato dual): una pieza cuya banda en ESTA orientacion invade su propia
# franja de captions (que puede ser distinta de la orientacion primaria) se omite EN ESE
# FORMATO, no en los dos. No es lo mismo que MOTIVO_NO_CABE_EN_EL_LIENZO (ese es el backstop de
# alfa medido tras renderizar; este es una comprobacion de banda ANTES de pedir la pieza).
MOTIVO_BANDA_INVADE_CAPTIONS_EN_FORMATO = "banda_invade_captions_en_este_formato"


def plan_para_otro_formato(
    plan_base: mp.PlanMotion,
    *,
    clip_mp4: Path | None,
    duracion_ms: int,
    orientacion: str,
    tray_csv: Path | None,
    catalogo: set[str],
    huella_entrada: str = "",
) -> tuple[mp.PlanMotion, str]:
    """(plan, origen) para una pierna EXTRA de formato (HF-4, Formato dual).

    Reusa integramente el plan TEMPORAL ya resuelto por `resolver_plan()` para la pierna
    primaria (piezas, tiempos, textos): CERO llamadas al LLM ni a Pexels. Solo redistribuye
    banda para esta orientacion vía `motion_plan_spatial.colocar_bandas` (el PASO ESPACIAL), y
    omite -con motivo propio- cualquier pieza cuya banda en ESTA orientacion invada su franja
    de captions, sin tocar la lista de omisiones de la pierna primaria.

    Como con la pierna primaria: un plan editado a mano para ESTE `clip_mp4` (que ya es un
    nombre distinto al de la primaria) manda sobre el derivado automaticamente.

    Sella el plan derivado ella misma (mismo trato que `resolver_plan`, PASO 3 de HF-4): al
    saltarse `resolver_plan()` por completo (no hay LLM que pedirle) tambien se salta SU sello,
    y sin este paso el sidecar `<clip>_motion_render.json` de esta pierna nunca se escribiria
    -- el editor la encontraria como "sin componer" a pesar de que el MP4 si tiene letreros.
    """
    import motion_edicion as me  # noqa: PLC0415 (solo con la capa encendida)

    if clip_mp4 is not None:
        editado = me.cargar(
            clip_mp4, duracion_ms=duracion_ms, orientacion=orientacion, catalogo=catalogo
        )
        if editado is not None:
            print(f"[motion] plan EDITADO a mano ({orientacion}): {len(editado.piezas)} pieza(s)")
            return editado, me.ORIGEN_EDITADO

    recolocadas = mps.colocar_bandas(plan_base.piezas, orientacion=orientacion, tray_csv=tray_csv)
    piezas_ok: list[mp.Pieza] = []
    omisiones = list(plan_base.omisiones)
    for pieza in recolocadas:
        if mps.banda_invade_captions(pieza.banda, orientacion):
            print(
                f"[motion] pieza '{pieza.plantilla}' omitida en {orientacion}: "
                f"{MOTIVO_BANDA_INVADE_CAPTIONS_EN_FORMATO}"
            )
            omisiones.append(
                mp.Omision(pieza.plantilla, MOTIVO_BANDA_INVADE_CAPTIONS_EN_FORMATO, orientacion)
            )
        else:
            piezas_ok.append(pieza)
    plan = replace(
        plan_base, orientacion=orientacion, piezas=tuple(piezas_ok), omisiones=tuple(omisiones)
    )
    _sellar_plan_renderizado(clip_mp4, plan, duracion_ms, me.ORIGEN_AUTOMATICO, huella_entrada)
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
    pieza: mp.Pieza,
    *,
    version: str,
    ancho: int,
    alto: int,
    fps: int,
    marca: dict[str, str],
    nombre_plantilla: str | None = None,
    estilo: str = ESTILO_DEFAULT,
) -> dict:
    """Contrato de pieza (HF-1) para una pieza ya planificada. PURO.

    `fps` es el del VIDEO DESTINO, no un default: la cadena de clips fuerza el fps de la base,
    asi que una pieza a 30 sobre un destino a 24 perderia 1 de cada 5 frames de animacion.
    `posicion.modo=cuadro_completo` porque las plantillas ya se colocan solas dentro de su
    lienzo; la caja queda disponible para quien la necesite, no se usa aqui.

    `nombre_plantilla` es el nombre YA RESUELTO por `resolver_estilo` (puede diferir de
    `pieza.plantilla` cuando el estilo pedido tiene variante propia); por default es
    `pieza.plantilla`, que es exactamente el comportamiento historico previo a HF-4. `estilo`
    viaja como campo propio del contrato (no solo codificado en el nombre de plantilla) porque
    entra a la clave de cache vía `calcular_hash` sin que este modulo tenga que tocarla, y
    porque el Studio y el sello del plan lo necesitan legible sin tener que parsear un nombre
    compuesto.
    """
    nombre = nombre_plantilla or pieza.plantilla
    return {
        "contrato": 1,
        "pieza_id": f"{pieza.plantilla}_{pieza.t0_ms}",
        "plantilla": {"nombre": nombre, "version": version},
        "estilo": estilo,
        "duracion_ms": pieza.duracion_ms,
        "fps": int(fps),
        "tamano": {"ancho": int(ancho), "alto": int(alto)},
        "texto": dict(pieza.texto),
        "marca": marca_de(nombre, marca),
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
    clip_mp4: Path | None,
    plan: mp.PlanMotion,
    duracion_ms: int,
    origen: str,
    huella_entrada: str = "",
) -> None:
    """Deja junto al clip el plan EXACTO que se va a componer. Un fallo aqui no tumba el render.

    Es lo unico que permite que el editor ensene lo que de verdad esta en el MP4 en vez de
    replanificar, que puede dar otros textos porque el LLM recibe otro juego de huecos.
    """
    if clip_mp4 is None:
        return
    try:
        import motion_edicion as me  # noqa: PLC0415

        me.sellar_render(
            clip_mp4,
            plan,
            duracion_ms=duracion_ms,
            origen=origen,
            huella_entrada=huella_entrada,
        )
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
    plan_precomputado: tuple[mp.PlanMotion, str] | None = None,
) -> ResultadoMotion:
    """Planifica, pide las piezas y devuelve los overlays. NUNCA lanza.

    `raiz_cache` debe apuntar DENTRO del paquete (ver `raiz_cache_de_paquete`): asi las piezas
    viajan con el paquete y una reanudacion las encuentra en vez de volver a renderizarlas.

    `plan_precomputado` (HF-4, Formato dual): cuando se pasa, se SALTA `resolver_plan()` (y por
    tanto el LLM) y se usa ese `(plan, origen)` tal cual -- ver `plan_para_otro_formato`. Sigue
    pidiendo las piezas a HyperFrames a este `ancho`/`alto` (necesario: el MOV y el desplazamiento
    de banda dependen del lienzo de destino) y sigue sellando su propio `_motion_render.json`
    junto a `clip_mp4` (que ya es un nombre distinto al de la pierna primaria).
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
            plan_precomputado=plan_precomputado,
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
    plan_precomputado: tuple[mp.PlanMotion, str] | None = None,
) -> ResultadoMotion:
    from hyperframes import pedir_pieza  # noqa: PLC0415 (solo con la capa encendida)
    from hyperframes.catalogo import Catalogo  # noqa: PLC0415

    orientacion = orientacion_de(ancho, alto)
    fps_destino = max(int(round(float(fps) or 30.0)), 1)
    duracion_ms = int(round(float(duracion_s) * 1000))
    ruta_catalogo = root / CATALOGO_REL
    versiones = versiones_del_catalogo(ruta_catalogo)

    estilo_pedido = opciones.estilo or ESTILO_DEFAULT
    if plan_precomputado is not None:
        plan, origen = plan_precomputado
    else:
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
            estilo=estilo_pedido,
        )
    informe = _informe_base(plan)
    informe["origen"] = origen
    informe["estilo"] = estilo_pedido
    informe["incidencias_estilo"] = []
    if plan.vacio:
        print(f"[motion] el planificador no coloco ninguna pieza ({len(plan.omisiones)} omitidas)")
        return ResultadoMotion((), informe, plan=plan)

    validar_sin_solape(list(plan.piezas), orientacion)

    catalogo = Catalogo.desde_archivo(ruta_catalogo, orientacion)
    raiz_cache.mkdir(parents=True, exist_ok=True)

    clips: list[ClipOverlay] = []
    for pieza in plan.piezas:
        nombre_resuelto, version_resuelta, cayo_a_pms = resolver_estilo(
            pieza.plantilla, estilo_pedido, versiones
        )
        estilo_efectivo = ESTILO_DEFAULT if cayo_a_pms else estilo_pedido
        if cayo_a_pms:
            mensaje = (
                f"estilo '{estilo_pedido}' no existe para '{pieza.plantilla}', se uso "
                f"'{ESTILO_DEFAULT}'"
            )
            print(f"[motion] {mensaje}")
            informe["incidencias_estilo"].append(mensaje)
        dato = contrato_de_pieza(
            pieza,
            version=version_resuelta,
            nombre_plantilla=nombre_resuelto,
            estilo=estilo_efectivo,
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
        # Backstop de Paso 2 (HF-4b): el anclaje de las plantillas horizontales (Paso 1) ya
        # cubre el caso normal; esto es lo que evita que una pieza SALGA CORTADA cuando el
        # texto es tan largo que ni el anclaje alcanza. Solo horizontal: el carril vertical no
        # se toca en esta sesion y ya paso su propio gate visual en HF-2/HF-3.
        if orientacion == "horizontal" and not pieza_cabe_en_el_lienzo(
            pieza, Path(r.ruta_mov), int(ancho), int(alto), orientacion=orientacion
        ):
            print(f"[motion] pieza '{pieza.plantilla}' omitida: {MOTIVO_NO_CABE_EN_EL_LIENZO}")
            informe["piezas_fallidas"].append(
                {"plantilla": pieza.plantilla, "razon": MOTIVO_NO_CABE_EN_EL_LIENZO, "detalle": ""}
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
                "estilo": estilo_efectivo,
            }
        )
        clips.append(_overlay_de(pieza, r, alto))

    huella = huella_de_entrada(
        duracion_ms=duracion_ms,
        orientacion=orientacion,
        textos=opciones.textos(),
        tramos=list(tramos or []),
        tray_csv=tray_csv,
        catalogo=set(versiones),
        textos_llm=opciones.textos_llm,
        estilo=estilo_pedido,
    )
    _resellar_con_incidencias_de_estilo(clip_mp4, plan, origen, duracion_ms, huella, informe)
    print(f"[motion] {len(clips)}/{len(plan.piezas)} piezas compuestas en {orientacion}")
    return ResultadoMotion(tuple(clips), informe, plan=plan)


def _resellar_con_incidencias_de_estilo(
    clip_mp4: Path | None,
    plan: mp.PlanMotion,
    origen: str,
    duracion_ms: int,
    huella_entrada: str,
    informe: dict,
) -> None:
    """Deja las incidencias de estilo TAMBIEN en `<clip>_motion_render.json`, no solo en el
    informe en memoria. Un fallo aqui no tumba el render (mismo trato que
    `_sellar_plan_renderizado`).

    Solo resella el plan AUTOMATICO: uno EDITADO a mano vive en un sidecar aparte que esta
    funcion no toca, para no pisar silenciosamente lo que K corrigio. `huella_entrada` se
    recalcula con las MISMAS entradas que uso `resolver_plan` (estilo incluido) para que el
    resello no deje el sello sin huella y rompa la reutilizacion de planes de la proxima corrida.
    """
    incidencias_estilo: list[str] = informe.get("incidencias_estilo") or []
    if clip_mp4 is None or not incidencias_estilo:
        return
    import motion_edicion as me  # noqa: PLC0415

    if origen != me.ORIGEN_AUTOMATICO:
        return
    plan_con_incidencias = mp.PlanMotion(
        plan.orientacion,
        plan.piezas,
        plan.omisiones,
        plan.incidencias + tuple(incidencias_estilo),
    )
    try:
        me.sellar_render(
            clip_mp4,
            plan_con_incidencias,
            duracion_ms=duracion_ms,
            origen=origen,
            huella_entrada=huella_entrada,
        )
    except Exception as exc:  # noqa: BLE001 - el resello nunca tumba el render
        print(f"[motion] no se pudo resellar el plan con incidencias de estilo: {exc}")


def desplazamiento_de_banda(banda: str, alto: int) -> tuple[int, int] | None:
    """(x, y) de composicion para la banda pedida, o None si va donde el HTML la dibuja.

    La pieza SIEMPRE se renderiza a cuadro completo con su contenido en el carril nativo; para
    llevarla a la banda superior o a la inferior no se toca la plantilla, se compone el overlay
    desplazado hacia arriba o hacia abajo. Asi hay UN solo HTML por pieza y no dos que se
    desincronizan, y el desplazamiento queda donde se puede probar sin renderizar.
    """
    if banda == mp.BANDA_ARRIBA:
        return (0, int(round(mp.DESPLAZAMIENTO_SUPERIOR * int(alto))))
    if banda == mp.BANDA_INFERIOR:
        return (0, int(round(mp.DESPLAZAMIENTO_INFERIOR * int(alto))))
    return None


MOTIVO_NO_CABE_EN_EL_LIENZO = "no_cabe_en_el_lienzo_sin_invadir_captions"
# Instante del fotograma que se mide: el mismo "medio" que usa la previsualizacion del editor
# (`studio_motion._componer_previsualizacion`), pasada la entrada y antes de la salida.
_FRACCION_INSTANTE_MEDIO = 0.0006
_UMBRAL_ALFA = 8  # 8/255: ignora la cola casi invisible de una sombra, no el texto


def bbox_alfa(
    mov: Path, t_s: float, ancho: int, alto: int, timeout_s: int = 180
) -> tuple[int, int] | None:
    """(primera_fila, ultima_fila) con alfa perceptible en el frame de `mov` en `t_s`.

    Mide el ALFA DEL RENDER, no lo que declara el CSS: la altura real de una pieza depende del
    texto (un titulo de tres lineas mide mas que uno de una), asi que es la unica fuente que no
    miente. None si no hay alfa medible ahi (pieza vacia o instante fuera de rango).
    """
    import subprocess  # noqa: PLC0415

    crudo = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-ss", f"{t_s:.3f}", "-i", str(mov), "-frames:v", "1",
            "-vf", "alphaextract,format=gray", "-f", "rawvideo", "-",
        ],
        capture_output=True, check=True, timeout=timeout_s,
    ).stdout
    if len(crudo) < alto * ancho:
        return None
    primera = ultima = None
    for y in range(alto):
        fila = crudo[y * ancho : (y + 1) * ancho]
        if max(fila) > _UMBRAL_ALFA:
            primera = y if primera is None else primera
            ultima = y
    return (primera, ultima) if primera is not None else None


def pieza_cabe_en_el_lienzo(
    pieza: mp.Pieza, ruta_mov: Path, ancho: int, alto: int, *, orientacion: str = "horizontal"
) -> bool:
    """True si el contenido de la pieza, ya desplazado por su banda, queda DENTRO del lienzo
    y sin invadir la franja de captions DE ESA orientacion. Backstop de tiempo de ejecucion
    (Paso 2 de HF-4b): el anclaje estatico de las plantillas (Paso 1) cubre el caso normal, esto
    cubre el extremo que ese anclaje no pueda absorber. Sin alfa medible no hay nada que
    recortar: pasa.
    """
    bbox = bbox_alfa(ruta_mov, pieza.duracion_ms * _FRACCION_INSTANTE_MEDIO, ancho, alto)
    if bbox is None:
        return True
    y0, y1 = bbox
    dy = (desplazamiento_de_banda(pieza.banda, alto) or (0, 0))[1]
    y0, y1 = y0 + dy, y1 + dy
    if y0 < 0 or y1 > alto:
        return False
    return (y1 / alto) <= mps.ZONA_CAPTIONS_POR_ORIENTACION[orientacion][0]


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
    "ESTILO_DEFAULT",
    "ESTILOS_VALIDOS",
    "MARCA",
    "CONTEXTO_MS",
    "SLOT_A_RELLENAR",
    "clips_de_motion",
    "contexto_hablado",
    "contrato_de_pieza",
    "desplazamiento_de_banda",
    "bbox_alfa",
    "pieza_cabe_en_el_lienzo",
    "MOTIVO_NO_CABE_EN_EL_LIENZO",
    "MOTIVO_BANDA_INVADE_CAPTIONS_EN_FORMATO",
    "huella_de_entrada",
    "marca_de",
    "orientacion_de",
    "plan_automatico",
    "plan_para_otro_formato",
    "raiz_cache_de_paquete",
    "rellenar_textos_con_llm",
    "resolver_estilo",
    "resolver_plan",
    "tramos_de_groups",
    "validar_sin_solape",
    "versiones_del_catalogo",
]
