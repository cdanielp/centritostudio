"""motion_textos_llm.py — Los textos de los letreros los escribe el LLM, no las reglas.

Las heuristicas de espanol llegaron hasta donde podian llegar: distinguen una frase de media
frase, pero no saben si lo que dice vale la pena. El sintoma medido: `dato_destacado` solo se
colocaba en 4 de 34 clips reales, porque la regla exige una unidad LITERAL detras del numero y
la gente dice "diez y medio por ciento" o "la mitad de los alumnos". Un modelo lee eso y saca
el dato; una expresion regular no.

Este modulo pide TODOS los textos de un clip en UNA sola llamada y devuelve JSON estricto. Las
reglas se quedan como RESPALDO, intactas: si el LLM falla, devuelve basura o no hay clave, el
plan sale con los textos de siempre y nadie se entera salvo el log.

Tres cosas que no se negocian:

1. FAIL-OPEN. Ningun camino de aqui puede tumbar un render. Todo error acaba en `None` y el
   llamador usa las reglas.
2. CACHE CON LA MISMA HUELLA QUE EL BRAIN. Texto + prompt + modelo + proveedor. Sin ella, dos
   corridas del mismo clip darian textos distintos y el MP4 dejaria de ser reproducible, que es
   justo lo que se acaba de arreglar en `brain.py`.
3. EL LLM PROPONE, EL PLANIFICADOR DISPONE. El modelo escribe frases; donde va cada pieza y
   cuantas caben lo sigue decidiendo `motion_plan`, que es puro y determinista.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path

import motion_plan as mp

TRANSCRIPTS = Path(__file__).resolve().parent / "transcripts"
SUFIJO_SIDECAR = ".motion_textos.json"
SCHEMA_CACHE = 1  # sube si cambia la FORMA del sidecar, para invalidar los viejos de golpe

# Limites por slot. Son los mismos que ya respeta el respaldo de reglas: el LLM no puede
# inventarse mas espacio del que la plantilla sabe pintar.
LIMITES = {
    "hook_titulo": mp.TITULO_SECCION_MAX_CHARS,
    "hook_kicker": 18,
    "seccion": mp.TITULO_SECCION_MAX_CHARS,
    "dato_cifra": 12,
    "dato_etiqueta": mp.DATO_ETIQUETA_MAX_CHARS,
    "cierre_titulo": mp.TITULO_SECCION_MAX_CHARS,
}
MAX_SECCIONES = 8  # tope de cordura de la respuesta, no una regla de colocacion
# Estos textos acaban quemados en un MP4 y guardados en una cache, asi que la respuesta tiene
# que ser REPRODUCIBLE: dos corridas del mismo clip dan el mismo plan, no uno parecido. Entra a
# las dos huellas para que los sidecars generados con la temperatura de antes se invaliden.
TEMPERATURA_TEXTOS = 0.0

_NUMERO_INICIAL = re.compile(r"\d+(?:[.,]\d+)?")

_SYSTEM = (
    "Eres editor de video en espanol de Mexico. Escribes los letreros que van sobre un clip "
    "vertical de redes sociales. Cada letrero se lee en menos de dos segundos y va SOLO en "
    "pantalla, sin contexto. Respondes UNICAMENTE con JSON valido, sin texto adicional."
)

_PROMPT = """\
Este es un clip de {dur_s:.0f} segundos. Su transcripcion por tramos, con el milisegundo en que
empieza cada uno:

{tramos}

Escribe los letreros del clip. Reglas de escritura, todas obligatorias:
- En espanol, con las tildes correctas.
- Cada texto tiene que entenderse SOLO, sin leer los demas ni la transcripcion.
- Frases enteras: nada que empiece por "que", "y", "de", "porque" ni que quede cortado.
- Sin muletillas: nada de "pues", "este", "o sea", "digamos", "bueno", "entonces".
- No copies el tramo literal si suena a habla suelta: reescribelo para que se lea.
- Respeta el limite de caracteres de cada campo. Si no cabe, di lo mismo mas corto.

Campos:
- "hook_titulo" ({l_hook} car.): el gancho del clip. Lo que hace que alguien no siga scrolleando.
- "hook_kicker" ({l_kicker} car.): dos o tres palabras de categoria, en MAYUSCULAS. "" si no aplica.
- "secciones": lista de hasta {max_sec} objetos {{"t0_ms": int, "titulo": str}} ({l_sec} car.),
  uno por cada CAMBIO DE TEMA del clip. `t0_ms` es el milisegundo del tramo donde empieza ese
  tema. Lista vacia si el clip trata de una sola cosa.
- "dato_cifra" ({l_cifra} car.) y "dato_etiqueta" ({l_etiq} car.): el numero mas contundente que
  se dice, CON su unidad ("10.5%", "26 anos", "5 millones"), y de que es ese numero. Cuenta
  tambien si el numero se dice con palabras ("diez y medio por ciento" -> "10.5%"). Los dos en
  "" si el clip no dice ninguna cifra que valga la pena destacar. Un ano de calendario NO es
  una cifra destacable.
- "dato_t0_ms": milisegundo del tramo donde se dice esa cifra, o null si no hay cifra.
- "cierre_titulo" ({l_cierre} car.): con que idea se queda el espectador. NO repitas el hook.

JSON: {{"hook_titulo":str,"hook_kicker":str,"secciones":[{{"t0_ms":int,"titulo":str}}],\
"dato_cifra":str,"dato_etiqueta":str,"dato_t0_ms":int|null,"cierre_titulo":str}}\
"""


@dataclass(frozen=True)
class TextosLLM:
    """Lo que el modelo propone. Todo opcional: un campo vacio cae al respaldo de reglas."""

    hook_titulo: str = ""
    hook_kicker: str = ""
    secciones: tuple[tuple[int, str], ...] = ()
    dato_cifra: str = ""
    dato_etiqueta: str = ""
    dato_t0_ms: int | None = None
    cierre_titulo: str = ""

    @property
    def vacio(self) -> bool:
        return not (self.hook_titulo or self.secciones or self.dato_cifra or self.cierre_titulo)

    def a_dict(self) -> dict:
        return {
            "hook_titulo": self.hook_titulo,
            "hook_kicker": self.hook_kicker,
            "secciones": [{"t0_ms": t, "titulo": s} for t, s in self.secciones],
            "dato_cifra": self.dato_cifra,
            "dato_etiqueta": self.dato_etiqueta,
            "dato_t0_ms": self.dato_t0_ms,
            "cierre_titulo": self.cierre_titulo,
        }


# ── Huella y cache ───────────────────────────────────────────────────────────


def ruta_sidecar(stem: str) -> Path:
    return TRANSCRIPTS / f"{stem}{SUFIJO_SIDECAR}"


def huella(tramos: list[mp.Tramo], duracion_ms: int) -> str:
    """sha256 de TODO lo que determina la respuesta: texto, tiempos, prompt, modelo, proveedor.

    Los tiempos SI entran aqui, al reves que en el brain: el modelo los ve en el prompt y los
    devuelve en `t0_ms`, asi que moverlos cambia la respuesta.
    """
    import brain  # noqa: PLC0415 (fuente unica del modelo y el proveedor)

    payload = json.dumps(
        {
            "schema": SCHEMA_CACHE,
            "duracion_ms": duracion_ms,
            "tramos": [[t.t0_ms, t.t1_ms, t.texto] for t in tramos],
            "system": _SYSTEM,
            "prompt": _PROMPT,
            "modelo": brain.MODEL,
            "proveedor": brain.PROVIDER,
            "temperatura": TEMPERATURA_TEXTOS,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sidecar_reutilizable(stem: str, marca: str) -> dict | None:
    """Sidecar previo si lo genero EXACTAMENTE esta entrada. Cualquier problema -> None."""
    if not stem:
        return None
    ruta = ruta_sidecar(stem)
    if not ruta.is_file():
        return None
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(datos, dict) or datos.get("huella") != marca:
        return None
    # Se devuelve el valor CRUDO: la primera pasada guarda un objeto y la segunda una lista, y
    # cada llamador valida su forma. Filtrar aqui por dict hacia que la cache del relleno no
    # acertara nunca y se pagara una llamada por render.
    return datos.get("textos")


# Lo que la guarda cazo en la ULTIMA llamada a `pedir_textos_para`, con cache o sin ella. No es
# estado del pipeline: es una ventana para medir, y por eso se limpia en cada llamada.
INCIDENCIAS: list[dict] = []


def reiniciar_incidencias() -> None:
    """Vacia el registro. Lo hace sola `pedir_textos`, que es la primera llamada de un clip.

    Existe aparte para quien use SOLO la segunda pasada: si esa limpiara, se llevaria por
    delante la incidencia de la cifra, que se detecta en la primera.
    """
    INCIDENCIAS.clear()


def incidencias_guardadas(sufijo: str) -> list[dict]:
    """Incidencias escritas en un sidecar de relleno. Cualquier problema -> lista vacia."""
    ruta = ruta_sidecar(sufijo)
    if not ruta.is_file():
        return []
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    guardadas = datos.get("incidencias") if isinstance(datos, dict) else None
    return [x for x in guardadas if isinstance(x, dict)] if isinstance(guardadas, list) else []


# ── Saneado de la respuesta ──────────────────────────────────────────────────


def _texto_valido(valor: object, limite: int) -> str:
    """Cadena de una linea, recortada al limite. Cualquier otra cosa se descarta."""
    if not isinstance(valor, str):
        return ""
    limpio = " ".join(valor.split())
    return limpio if 0 < len(limpio) <= limite else ""


def _secciones_validas(valor: object, duracion_ms: int) -> tuple[tuple[int, str], ...]:
    """Secciones con t0 dentro del clip y titulo que cabe. El resto se tira sin ruido."""
    if not isinstance(valor, list):
        return ()
    salida: list[tuple[int, str]] = []
    for item in valor[:MAX_SECCIONES]:
        if not isinstance(item, dict):
            continue
        t0 = item.get("t0_ms")
        titulo = _texto_valido(item.get("titulo"), LIMITES["seccion"])
        if not titulo or not isinstance(t0, int) or isinstance(t0, bool):
            continue
        if not 0 <= t0 < duracion_ms:
            continue
        salida.append((t0, titulo))
    salida.sort(key=lambda x: x[0])
    return tuple(salida)


def _sin_la_cifra_delante(etiqueta: str, cifra: str) -> str:
    """La etiqueta sin la cifra que la tarjeta ya pinta en grande encima. PURO.

    Medido a ojo sobre la demo 16: la tarjeta decia "10.5%" en grande y "10.5% dejo la prepa en
    2023-2024" debajo. La etiqueta es el CONTEXTO de la cifra, no la cifra otra vez.

    Se quita solo si va DELANTE, que es como la devuelve el modelo. Si la cifra aparece a mitad
    de la frase suele estar haciendo falta ahi, y recortarla dejaria un texto roto.
    """
    if not etiqueta or not cifra:
        return etiqueta
    numero = _NUMERO_INICIAL.match(cifra)
    candidatos = [cifra, cifra.rstrip("%").strip()]
    if numero:
        candidatos.append(numero.group(0))
    for aguja in candidatos:
        if aguja and etiqueta.lower().startswith(aguja.lower()):
            # Lo que queda pegado es puntuacion o el conector que unia la cifra a la frase.
            limpio = etiqueta[len(aguja) :].lstrip(" %:,.-").strip()
            return limpio or etiqueta
    return etiqueta


def sanear(dato: object, duracion_ms: int) -> TextosLLM | None:
    """Respuesta cruda del modelo -> `TextosLLM`, o None si no hay nada aprovechable.

    Se sanea campo a campo y NO se rechaza la respuesta entera por un campo malo: si el modelo
    acerta con el hook y falla con la cifra, se usa el hook y la cifra cae al respaldo. Tirar
    todo por una parte seria desperdiciar una llamada que ya se pago.
    """
    if not isinstance(dato, dict):
        return None
    t0_dato = dato.get("dato_t0_ms")
    if not isinstance(t0_dato, int) or isinstance(t0_dato, bool) or not 0 <= t0_dato < duracion_ms:
        t0_dato = None
    cifra = _texto_valido(dato.get("dato_cifra"), LIMITES["dato_cifra"])
    textos = TextosLLM(
        hook_titulo=_texto_valido(dato.get("hook_titulo"), LIMITES["hook_titulo"]),
        hook_kicker=_texto_valido(dato.get("hook_kicker"), LIMITES["hook_kicker"]),
        secciones=_secciones_validas(dato.get("secciones"), duracion_ms),
        dato_cifra=cifra,
        # Una etiqueta sin cifra no significa nada: se descarta con ella. Y si la trae delante,
        # se le quita: la tarjeta pinta la cifra en grande justo encima, asi que repetirla en la
        # etiqueta la dice dos veces en el mismo cuadro.
        dato_etiqueta=_sin_la_cifra_delante(
            _texto_valido(dato.get("dato_etiqueta"), LIMITES["dato_etiqueta"]), cifra
        )
        if cifra
        else "",
        dato_t0_ms=t0_dato if cifra else None,
        cierre_titulo=_texto_valido(dato.get("cierre_titulo"), LIMITES["cierre_titulo"]),
    )
    return None if textos.vacio else textos


# ── La llamada ───────────────────────────────────────────────────────────────


def _prompt_de(tramos: list[mp.Tramo], duracion_ms: int) -> str:
    lineas = "\n".join(f"[{t.t0_ms}] {' '.join((t.texto or '').split())}" for t in tramos)
    return _PROMPT.format(
        dur_s=duracion_ms / 1000.0,
        tramos=lineas,
        l_hook=LIMITES["hook_titulo"],
        l_kicker=LIMITES["hook_kicker"],
        l_sec=LIMITES["seccion"],
        l_cifra=LIMITES["dato_cifra"],
        l_etiq=LIMITES["dato_etiqueta"],
        l_cierre=LIMITES["cierre_titulo"],
        max_sec=MAX_SECCIONES,
    )


def pedir_textos(
    tramos: list[mp.Tramo], duracion_ms: int, *, stem: str = "", forzar: bool = False
) -> TextosLLM | None:
    """Textos del clip segun el LLM, o None si no hay nada utilizable. NUNCA lanza.

    None es una respuesta normal, no un fallo: el llamador sigue con las reglas de siempre.
    """
    if not tramos or duracion_ms <= 0:
        return None
    # Primera llamada del clip: aqui empieza el registro de incidencias que la segunda pasada
    # completa. Si no se limpiara, la cuenta arrastraria las del clip anterior.
    INCIDENCIAS.clear()
    try:
        marca = huella(tramos, duracion_ms)
    except Exception as exc:  # noqa: BLE001 - ni siquiera calcular la huella puede tumbar nada
        print(f"[motion-llm] no se pudo calcular la huella, se usan las reglas: {exc}")
        return None

    if not forzar:
        previo = _sidecar_reutilizable(stem, marca)
        if isinstance(previo, dict):
            textos = sanear(previo, duracion_ms)
            if textos is not None:
                print(f"[motion-llm] cache HIT {stem}{SUFIJO_SIDECAR} | sin llamada al LLM")
                INCIDENCIAS.extend(incidencias_guardadas(stem))
                return textos

    try:
        import brain  # noqa: PLC0415

        # TEMPERATURA 0. Este texto va a un MP4 y a una cache: dos corridas del mismo
        # clip tienen que dar el mismo plan, no uno parecido.
        with brain.temperatura(TEMPERATURA_TEXTOS):
            crudo = brain.llm(
                [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": _prompt_de(tramos, duracion_ms)},
                ]
            )
    except Exception as exc:  # noqa: BLE001 - fail-open duro
        print(f"[motion-llm] fallo la llamada, se usan las reglas: {type(exc).__name__}: {exc}")
        return None

    textos = sanear(crudo, duracion_ms)
    if textos is None:
        print("[motion-llm] respuesta sin nada aprovechable, se usan las reglas")
        return None
    textos, incidencias = _cifra_verificada(textos, tramos)
    INCIDENCIAS.extend(incidencias)
    _guardar(stem, marca, textos, incidencias)
    print(
        f"[motion-llm] OK | hook={'si' if textos.hook_titulo else 'no'} "
        f"secciones={len(textos.secciones)} cifra={textos.dato_cifra or 'no'}"
    )
    return textos


def _tramo_en(tramos: list[mp.Tramo], t0_ms: int | None) -> str:
    """Texto del tramo que contiene ese instante, o el mas cercano. PURO."""
    if not tramos:
        return ""
    if t0_ms is None:
        return " ".join((t.texto or "") for t in tramos)
    dentro = [t for t in tramos if t.t0_ms <= t0_ms <= t.t1_ms]
    elegido = dentro[0] if dentro else min(tramos, key=lambda t: abs(t.t0_ms - t0_ms))
    return elegido.texto or ""


def _cifra_verificada(textos: TextosLLM, tramos: list[mp.Tramo]) -> tuple[TextosLLM, list[dict]]:
    """Vacia el dato destacado si su NUMERO no se dijo. ESTRICTO, y solo aqui. PURO.

    Es el unico campo donde la transcripcion manda: un titular puede abstraer lo que quiera,
    pero una cifra que nadie pronuncio es un dato falso a pantalla completa. Vaciarla devuelve
    ese slot al respaldo de reglas, que no inventa numeros porque solo copia los que encuentra.
    """
    import motion_guarda  # noqa: PLC0415

    hablado = _tramo_en(tramos, textos.dato_t0_ms)
    clip = " ".join((t.texto or "") for t in tramos)
    if not textos.dato_cifra or motion_guarda.cifra_dicha(textos.dato_cifra, hablado, clip=clip):
        return textos, []
    incidencia = {
        "campo": "dato_cifra",
        "tipo": "cifra",
        "palabras": [textos.dato_cifra],
        "resuelto": "respaldo",
    }
    print(f"[motion-llm] guarda: la cifra '{textos.dato_cifra}' no se dice, se usan las reglas")
    return (
        replace(textos, dato_cifra="", dato_etiqueta="", dato_t0_ms=None),
        [incidencia],
    )


def _guardar(stem: str, marca: str, textos: TextosLLM, incidencias: list[dict]) -> None:
    """Persiste el sidecar. Un fallo de escritura no puede tumbar el render."""
    if not stem:
        return
    try:
        from atomic_io import atomic_write_json  # noqa: PLC0415

        atomic_write_json(
            ruta_sidecar(stem),
            {
                "schema": SCHEMA_CACHE,
                "huella": marca,
                "textos": textos.a_dict(),
                "incidencias": incidencias,
            },
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[motion-llm] no se pudo guardar el sidecar: {exc}")


_SYSTEM_RELLENO = (
    "Eres editor de video en espanol de Mexico. Te dan los HUECOS exactos de un clip que ya "
    "estan decididos y el fragmento que se habla en cada uno. Escribes el letrero de cada "
    "hueco, uno por uno, sin saltarte ninguno. Respondes UNICAMENTE con JSON valido."
)

_PROMPT_RELLENO = """\
Clip de {dur_s:.0f} segundos. Estos letreros YA estan colocados. Para cada uno tienes el
fragmento que se habla justo ahi. Escribe el TITULO de cada letrero.

{huecos}

Un titulo NO es el fragmento. Es una frase CORTA que resume lo que ahi se dice.

Ejemplo. Fragmento: "porque un dato, la desercion escolar del ciclo del 2023 al 2024 este fue
en un 10.5 por ciento de medias superiores". Titulo correcto: "10.5% dejo la prepa en un ano".
Titulo INCORRECTO: copiar el fragmento entero.

Reglas, todas obligatorias:
- NUNCA superes el limite de caracteres de cada linea. Es un limite duro: si no cabe, di lo
  mismo con menos palabras. Un titulo de 30 caracteres es mejor que uno de 60.
- No copies el fragmento literal. Reescribe.
- En espanol, con las tildes correctas.
- Cada titulo se entiende SOLO, sin leer los demas.
- Frases enteras: nada cortado ni que empiece por "que", "y", "de", "porque".
- Sin muletillas: "pues", "este", "o sea", "digamos", "bueno", "entonces".
- Puedes resumir con tus palabras, pero NO inventes datos, nombres ni cifras que no se digan.
- NINGUN letrero puede repetir el tema ni la frase de otro. Se leen seguidos en el mismo video:
  si dos dicen lo mismo, sobra uno. Mira la lista COMPLETA antes de escribir.
- VARIA LA CONSTRUCCION entre letreros. Dos no pueden empezar por la misma palabra, ni seguir
  el mismo molde. Si uno arranca con el sujeto, que el siguiente arranque con la accion, con la
  cifra o con la consecuencia.
- La cifra del letrero de dato es SUYA. Ningun otro letrero puede llevar ese numero: la tarjeta
  ya lo pinta en grande y verlo dos veces en el mismo video sobra.
- Devuelve un texto por CADA id de la lista, con EL MISMO id que se te dio. No los renumeres.

JSON: {{"textos":[{{"id":int,"texto":str}}]}}"""


def _prompt_relleno(huecos: list[dict], duracion_ms: int) -> str:
    lineas = "\n".join(
        f"[{h['id']}] {h['plantilla']} en el segundo {h['t0_ms'] / 1000:.1f}, "
        f'maximo {h["limite"]} caracteres. Se habla: "{h["contexto"]}"'
        + (
            f'. Este letrero ya pinta "{h["cifra"]}" en grande: escribe SOLO el contexto de esa '
            f"cifra, sin repetirla"
            if h.get("cifra")
            else ""
        )
        for h in huecos
    )
    return _PROMPT_RELLENO.format(dur_s=duracion_ms / 1000.0, huecos=lineas)


def huella_relleno(huecos: list[dict], duracion_ms: int) -> str:
    """sha256 de los huecos y su contexto, mas prompt, modelo y proveedor."""
    import brain  # noqa: PLC0415

    payload = json.dumps(
        {
            "schema": SCHEMA_CACHE,
            "duracion_ms": duracion_ms,
            "huecos": [
                [
                    h["id"],
                    h["plantilla"],
                    h["t0_ms"],
                    h["limite"],
                    h["contexto"],
                    h.get("cifra", ""),
                ]
                for h in huecos
            ],
            "system": _SYSTEM_RELLENO,
            "prompt": _PROMPT_RELLENO,
            "modelo": brain.MODEL,
            "proveedor": brain.PROVIDER,
            "temperatura": TEMPERATURA_TEXTOS,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def pedir_textos_para(
    huecos: list[dict],
    duracion_ms: int,
    *,
    stem: str = "",
    forzar: bool = False,
    transcripcion: str = "",
) -> dict[int, str]:
    """{id: texto} para los huecos que el PLANIFICADOR ya decidio. NUNCA lanza.

    Es la segunda pasada, y es la que hace que no se descarte nada. En la primera, el modelo
    proponia secciones con su instante y solo se usaban las que caian en un hueco de mas de
    20 s; el resto volvia al respaldo de reglas y por eso seguian saliendo titulos como
    "futbol americano, basquetas". Aqui el orden esta invertido: los instantes ya estan fijados
    y al modelo se le pide texto PARA ESOS, con el fragmento hablado de cada uno delante.

    Devuelve solo los ids que vinieron con texto utilizable. Los que falten caen al respaldo,
    que es lo mismo que pasaba antes pero ahora por excepcion y no por diseno.
    """
    if not huecos or duracion_ms <= 0:
        return {}
    try:
        marca = huella_relleno(huecos, duracion_ms)
    except Exception as exc:  # noqa: BLE001
        print(f"[motion-llm] no se pudo calcular la huella del relleno: {exc}")
        return {}

    sufijo = f"{stem}.relleno" if stem else ""
    if not forzar and sufijo:
        previo = _sidecar_reutilizable(sufijo, marca)
        if previo:
            print(f"[motion-llm] cache HIT relleno de {stem} | sin llamada al LLM")
            INCIDENCIAS.extend(incidencias_guardadas(sufijo))
            return _sanear_relleno(previo, huecos)

    try:
        import brain  # noqa: PLC0415

        # TEMPERATURA 0. Este texto va a un MP4 y a una cache: dos corridas del mismo
        # clip tienen que dar el mismo plan, no uno parecido.
        with brain.temperatura(TEMPERATURA_TEXTOS):
            crudo = brain.llm(
                [
                    {"role": "system", "content": _SYSTEM_RELLENO},
                    {"role": "user", "content": _prompt_relleno(huecos, duracion_ms)},
                ]
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[motion-llm] fallo el relleno, se usan las reglas: {type(exc).__name__}: {exc}")
        return {}

    bruto = crudo.get("textos") if isinstance(crudo, dict) else None
    textos = _sanear_relleno(bruto, huecos)
    # UNA sola correccion para los dos motivos por los que un texto no sirve: no cabe en la
    # plantilla, o repite lo que ya dice otra pieza del mismo clip. Juntarlos en una llamada
    # evita dos viajes por clip para dos peticiones que el modelo puede atender a la vez.
    motivos = {
        **_motivos_por_largo(bruto, huecos),
        **_motivos_por_repeticion(textos, huecos),
        **_motivos_por_cifra_repetida(textos, huecos),
    }
    if motivos:
        textos = _corregir(textos, huecos, duracion_ms, motivos)
    incidencias = _registrar_inventadas(textos, huecos, transcripcion)
    INCIDENCIAS.extend(incidencias)
    if incidencias:
        print(f"[motion-llm] guarda: {len(incidencias)} campo(s) con palabras no dichas")
    if textos and sufijo:
        _guardar_relleno(sufijo, marca, textos, incidencias)
    print(f"[motion-llm] relleno: {len(textos)}/{len(huecos)} letreros escritos")
    return textos


# Que pieza cede cuando dos dicen lo mismo. El hook es el unico que se lee sin contexto y el
# cierre es el que se recuerda; una seccion intermedia se puede reescribir sin perder nada.
PRIORIDAD = {"hook": 0, "cierre": 1, "dato_destacado": 2, "titulo_seccion": 3}


def _motivos_por_largo(bruto: object, huecos: list[dict]) -> dict[int, str]:
    """Ids cuyo texto vino pasado del limite. PURO.

    `_sanear_relleno` los tira, y tirarlos era exactamente la causa de que tres piezas de los 34
    clips acabaran con el texto de las reglas. Antes de renunciar, se pide una version corta.
    """
    limites = {h["id"]: h["limite"] for h in huecos}
    largos = _crudos_por_id(bruto)
    return {
        ident: f"tenia {len(texto)} caracteres y el maximo es {limites[ident]}"
        for ident, texto in largos.items()
        if ident in limites and len(texto) > limites[ident]
    }


def _crudos_por_id(bruto: object) -> dict[int, str]:
    """Lista cruda del modelo -> {id: texto}, sin aplicar limites. PURO."""
    if isinstance(bruto, dict):
        bruto = [{"id": k, "texto": v} for k, v in bruto.items()]
    if not isinstance(bruto, list):
        return {}
    salida: dict[int, str] = {}
    for item in bruto:
        if not isinstance(item, dict) or not isinstance(item.get("texto"), str):
            continue
        ident = item.get("id")
        if isinstance(ident, str) and ident.isdigit():
            ident = int(ident)
        if isinstance(ident, int) and not isinstance(ident, bool):
            salida[ident] = " ".join(item["texto"].split())
    return salida


def _motivos_por_cifra_repetida(textos: dict[int, str], huecos: list[dict]) -> dict[int, str]:
    """Ids que repiten la cifra que ya pinta el `dato_destacado`. PURO.

    Medido en la demo 18: el hook decia "La desercion escolar subio 10.5%" y la tarjeta, seis
    segundos despues, "10.5%" a pantalla completa. La cifra es lo que hace destacable a esa
    tarjeta, asi que se queda ahi y cede la otra pieza, sea cual sea su prioridad. Un numero
    repetido no lo caza `secuencia_compartida`, que pide tres palabras significativas seguidas,
    ni `arranque_compartido`, que solo mira la primera.
    """
    cifras = {
        _NUMERO_INICIAL.search(h["cifra"]).group(0)
        for h in huecos
        if h.get("cifra") and _NUMERO_INICIAL.search(h["cifra"])
    }
    if not cifras:
        return {}
    duenos = {h["id"] for h in huecos if h.get("cifra")}
    motivos: dict[int, str] = {}
    for ident, texto in sorted(textos.items()):
        if ident in duenos:
            continue
        # Sin los bordes, la cifra "26" se daria por repetida dentro de "2026".
        repetidas = sorted(c for c in cifras if re.search(rf"(?<!\d){re.escape(c)}(?!\d)", texto))
        if repetidas:
            motivos[ident] = (
                f'lleva la cifra "{", ".join(repetidas)}", que ya pinta en grande la tarjeta '
                f"del dato. Di lo mismo SIN el numero."
            )
    return motivos


def _motivos_por_repeticion(textos: dict[int, str], huecos: list[dict]) -> dict[int, str]:
    """Ids que repiten lo que ya dice otra pieza del clip. Cede el de MENOR prioridad. PURO.

    El sintoma medido en la demo 14: una seccion decia "Garcia con vision de futuro" y el cierre
    "Un Garcia con vision de futuro y bienestar". Dos letreros, un solo mensaje.
    """
    import motion_guarda  # noqa: PLC0415

    plantillas = {h["id"]: h["plantilla"] for h in huecos}
    orden = sorted(textos, key=lambda i: (PRIORIDAD.get(plantillas.get(i, ""), 9), i))
    motivos: dict[int, str] = {}
    for puesto, ident in enumerate(orden):
        for otro in orden[:puesto]:
            comun = motion_guarda.secuencia_compartida(textos[ident], textos[otro])
            if comun:
                motivos[ident] = (
                    f'repite "{" ".join(comun)}", que ya dice el letrero [{otro}]: "{textos[otro]}"'
                )
                break
            # Tres letreros seguidos empezando por "Garcia" se leen como el mismo aunque cada
            # uno diga algo distinto: lo que se repite es el SUJETO, no la frase. Repetir la
            # plantilla esta bien; arrancar igual, no.
            arranque = motion_guarda.arranque_compartido(textos[ident], textos[otro])
            if arranque:
                motivos[ident] = (
                    f'empieza por "{arranque}", igual que el letrero [{otro}]: '
                    f'"{textos[otro]}". Cambia el sujeto o la construccion.'
                )
                break
    return motivos


def _corregir(
    textos: dict[int, str], huecos: list[dict], duracion_ms: int, motivos: dict[int, str]
) -> dict[int, str]:
    """UNA llamada de correccion para los ids con motivo. Lo que no mejore se queda igual.

    Nunca empeora: un texto corregido solo sustituye al original si vuelve dentro del limite.
    """
    afectados = [h for h in huecos if h["id"] in motivos]
    if not afectados:
        return textos
    detalle = "\n".join(f"[{h['id']}] {motivos[h['id']]}" for h in afectados)
    try:
        import brain  # noqa: PLC0415

        # TEMPERATURA 0. Este texto va a un MP4 y a una cache: dos corridas del mismo
        # clip tienen que dar el mismo plan, no uno parecido.
        with brain.temperatura(TEMPERATURA_TEXTOS):
            crudo = brain.llm(
                [
                    {"role": "system", "content": _SYSTEM_RELLENO},
                    {
                        "role": "user",
                        "content": (
                            _prompt_relleno(afectados, duracion_ms)
                            + "\n\nCORRECCION OBLIGATORIA. Reescribe SOLO estos letreros:\n"
                            + detalle
                            + "\nCada uno tiene que decir algo DISTINTO de los demas letreros del "
                            "clip y caber en su limite de caracteres."
                        ),
                    },
                ]
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[motion-llm] la correccion fallo, se conserva lo que habia: {type(exc).__name__}")
        return textos
    nuevos = _sanear_relleno(crudo.get("textos") if isinstance(crudo, dict) else None, afectados)
    print(f"[motion-llm] correccion: {len(nuevos)}/{len(afectados)} letreros reescritos")
    return {**textos, **nuevos}


def _registrar_inventadas(
    textos: dict[int, str], huecos: list[dict], transcripcion: str
) -> list[dict]:
    """Palabras no dichas de cada letrero, SOLO para el registro. No toca ni un texto.

    El reintento general se quito: gastaba una llamada por clip y devolvia un texto peor,
    porque obligar al modelo a usar solo palabras del fragmento es pedirle que copie el
    fragmento, que es justo lo que no queremos. Un titular tiene derecho a abstraer, y para lo
    que se le escape esta el editor.

    Se contrasta contra la transcripcion del CLIP ENTERO, no contra el fragmento: un letrero
    puede usar legitimamente una palabra dicha treinta segundos antes.
    """
    import motion_guarda  # noqa: PLC0415

    fuente = transcripcion or " ".join(h.get("contexto", "") for h in huecos)
    plantillas = {h["id"]: h["plantilla"] for h in huecos}
    incidencias: list[dict] = []
    for ident, texto in sorted(textos.items()):
        veredicto = motion_guarda.revisar(texto, fuente)
        if veredicto.ok:
            continue
        incidencias.append(
            {
                "id": ident,
                "campo": plantillas.get(ident, ""),
                "tipo": "palabra",
                "palabras": list(veredicto.sospechosas),
                "resuelto": "registrada",
            }
        )
    return incidencias


def _renumerado(dato: list, huecos: list[dict]) -> list | None:
    """La misma lista con los ids REALES, si el modelo la devolvio renumerada. PURO.

    El modelo entrega los letreros en orden pero renumerados de 0 en adelante, ignorando los
    ids que se le dieron. Con huecos [0, 2, 3, 4, 5, 6] eso hacia que el ultimo letrero, el
    cierre, no encajara en ningun hueco y cayera al respaldo de reglas: dos de las tres piezas
    sin texto del modelo en los 34 clips venian de aqui, no de la longitud.

    Solo se acepta cuando hay tantos textos como huecos y los ids son exactamente 0..N-1: en
    ese caso el orden es la unica lectura posible. Con cualquier otra forma se devuelve None y
    manda el id declarado, porque adivinar seria peor que perder un letrero.
    """
    if len(dato) != len(huecos):
        return None
    ids = [x.get("id") for x in dato if isinstance(x, dict)]
    if len(ids) != len(huecos) or ids != list(range(len(huecos))):
        return None
    reales = [h["id"] for h in huecos]
    if ids == reales:
        return None  # no hay nada que renumerar
    return [{**x, "id": real} for x, real in zip(dato, reales, strict=True)]


def _sanear_relleno(dato: object, huecos: list[dict]) -> dict[int, str]:
    """Lista cruda -> {id: texto}, con el limite de cada hueco aplicado."""
    limites = {h["id"]: h["limite"] for h in huecos}
    cifras = {h["id"]: h.get("cifra", "") for h in huecos}
    salida: dict[int, str] = {}
    if isinstance(dato, dict):  # tolerancia: algunos modelos devuelven {"3": "..."}
        dato = [{"id": k, "texto": v} for k, v in dato.items()]
    if not isinstance(dato, list):
        return {}
    dato = _renumerado(dato, huecos) or dato
    for item in dato:
        if not isinstance(item, dict):
            continue
        ident = item.get("id")
        if isinstance(ident, str) and ident.isdigit():
            ident = int(ident)
        if not isinstance(ident, int) or isinstance(ident, bool) or ident not in limites:
            continue
        texto = _texto_valido(item.get("texto"), limites[ident])
        texto = _sin_la_cifra_delante(texto, cifras.get(ident, ""))
        if texto:
            salida[ident] = texto
    return salida


def _guardar_relleno(
    sufijo: str, marca: str, textos: dict[int, str], incidencias: list[dict]
) -> None:
    try:
        from atomic_io import atomic_write_json  # noqa: PLC0415

        atomic_write_json(
            ruta_sidecar(sufijo),
            {
                "schema": SCHEMA_CACHE,
                "huella": marca,
                "textos": [{"id": k, "texto": v} for k, v in sorted(textos.items())],
                # Lo que la guarda caza queda ESCRITO junto al resultado. Si solo se imprimiera,
                # una corrida con cache no podria decir cuantas palabras invento el modelo, y
                # esa cuenta es justamente lo que dice si la guarda sobra o hace falta.
                "incidencias": incidencias,
            },
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[motion-llm] no se pudo guardar el relleno: {exc}")


__all__ = [
    "INCIDENCIAS",
    "LIMITES",
    "MAX_SECCIONES",
    "SUFIJO_SIDECAR",
    "TextosLLM",
    "huella",
    "huella_relleno",
    "incidencias_guardadas",
    "reiniciar_incidencias",
    "pedir_textos",
    "pedir_textos_para",
    "ruta_sidecar",
    "sanear",
]
