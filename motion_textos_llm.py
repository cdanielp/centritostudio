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
from dataclasses import dataclass
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
        # Una etiqueta sin cifra no significa nada: se descarta con ella.
        dato_etiqueta=_texto_valido(dato.get("dato_etiqueta"), LIMITES["dato_etiqueta"])
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
                return textos

    try:
        import brain  # noqa: PLC0415

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
    _guardar(stem, marca, textos)
    print(
        f"[motion-llm] OK | hook={'si' if textos.hook_titulo else 'no'} "
        f"secciones={len(textos.secciones)} cifra={textos.dato_cifra or 'no'}"
    )
    return textos


def _guardar(stem: str, marca: str, textos: TextosLLM) -> None:
    """Persiste el sidecar. Un fallo de escritura no puede tumbar el render."""
    if not stem:
        return
    try:
        from atomic_io import atomic_write_json  # noqa: PLC0415

        atomic_write_json(
            ruta_sidecar(stem),
            {"schema": SCHEMA_CACHE, "huella": marca, "textos": textos.a_dict()},
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
- USA SOLO PALABRAS QUE APARECEN EN SU FRAGMENTO. No inventes terminos ni sinonimos.
- Devuelve un texto por CADA id de la lista. Ninguno vacio.

JSON: {{"textos":[{{"id":int,"texto":str}}]}}"""


def _prompt_relleno(huecos: list[dict], duracion_ms: int) -> str:
    lineas = "\n".join(
        f"[{h['id']}] {h['plantilla']} en el segundo {h['t0_ms'] / 1000:.1f}, "
        f'maximo {h["limite"]} caracteres. Se habla: "{h["contexto"]}"'
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
                [h["id"], h["plantilla"], h["t0_ms"], h["limite"], h["contexto"]] for h in huecos
            ],
            "system": _SYSTEM_RELLENO,
            "prompt": _PROMPT_RELLENO,
            "modelo": brain.MODEL,
            "proveedor": brain.PROVIDER,
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
    INCIDENCIAS.clear()
    if not forzar and sufijo:
        previo = _sidecar_reutilizable(sufijo, marca)
        if previo:
            print(f"[motion-llm] cache HIT relleno de {stem} | sin llamada al LLM")
            INCIDENCIAS.extend(incidencias_guardadas(sufijo))
            return _sanear_relleno(previo, huecos)

    try:
        import brain  # noqa: PLC0415

        crudo = brain.llm(
            [
                {"role": "system", "content": _SYSTEM_RELLENO},
                {"role": "user", "content": _prompt_relleno(huecos, duracion_ms)},
            ]
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[motion-llm] fallo el relleno, se usan las reglas: {type(exc).__name__}: {exc}")
        return {}

    textos = _sanear_relleno(crudo.get("textos") if isinstance(crudo, dict) else None, huecos)
    textos, incidencias = _filtrar_inventadas(textos, huecos, duracion_ms, transcripcion)
    INCIDENCIAS.extend(incidencias)
    if incidencias:
        print(f"[motion-llm] guarda: {len(incidencias)} campo(s) con palabras no dichas")
    if textos and sufijo:
        _guardar_relleno(sufijo, marca, textos, incidencias)
    print(f"[motion-llm] relleno: {len(textos)}/{len(huecos)} letreros escritos")
    return textos


def _filtrar_inventadas(
    textos: dict[int, str], huecos: list[dict], duracion_ms: int, transcripcion: str
) -> tuple[dict[int, str], list[dict]]:
    """Quita los textos con palabras que nadie dijo, tras UN reintento. Devuelve las incidencias.

    El reintento se pide en bloque y solo para los campos sospechosos, con la instruccion
    explicita de usar unicamente palabras del fragmento. Lo que vuelva a fallar se descarta y
    ese campo cae al respaldo de reglas, que nunca inventa nada.
    """
    import motion_guarda  # noqa: PLC0415

    # Se contrasta contra la transcripcion del CLIP ENTERO, no contra el fragmento: un letrero
    # puede usar legitimamente una palabra dicha treinta segundos antes.
    fuente = transcripcion or " ".join(h.get("contexto", "") for h in huecos)
    incidencias: list[dict] = []
    sospechosos = {}
    for ident, texto in textos.items():
        veredicto = motion_guarda.revisar(texto, fuente)
        if not veredicto.ok:
            sospechosos[ident] = veredicto.sospechosas
    if not sospechosos:
        return textos, incidencias

    reintentados = _reintentar(sospechosos, huecos, duracion_ms)
    limpios = dict(textos)
    for ident, palabras in sospechosos.items():
        nuevo = reintentados.get(ident, "")
        if nuevo and motion_guarda.revisar(nuevo, fuente).ok:
            limpios[ident] = nuevo
            incidencias.append({"id": ident, "palabras": list(palabras), "resuelto": "reintento"})
            continue
        # Segundo fallo: fuera. Ese campo se queda con el texto de las reglas.
        limpios.pop(ident, None)
        incidencias.append({"id": ident, "palabras": list(palabras), "resuelto": "respaldo"})
    return limpios, incidencias


def _reintentar(
    sospechosos: dict[int, tuple[str, ...]], huecos: list[dict], duracion_ms: int
) -> dict[int, str]:
    """UNA segunda llamada, solo para los campos sospechosos. Sin cache: es un caso raro."""
    afectados = [h for h in huecos if h["id"] in sospechosos]
    if not afectados:
        return {}
    detalle = "\n".join(
        f"[{h['id']}] escribiste palabras que NO se dicen: "
        f"{', '.join(sospechosos[h['id']])}. Se habla: {h['contexto']}"
        for h in afectados
    )
    try:
        import brain  # noqa: PLC0415

        crudo = brain.llm(
            [
                {"role": "system", "content": _SYSTEM_RELLENO},
                {
                    "role": "user",
                    "content": (
                        _prompt_relleno(afectados, duracion_ms)
                        + "\n\nCORRECCION OBLIGATORIA:\n"
                        + detalle
                        + "\nReescribelos usando UNICAMENTE palabras de su fragmento."
                    ),
                },
            ]
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[motion-llm] el reintento fallo: {type(exc).__name__}: {exc}")
        return {}
    return _sanear_relleno(crudo.get("textos") if isinstance(crudo, dict) else None, afectados)


def _sanear_relleno(dato: object, huecos: list[dict]) -> dict[int, str]:
    """Lista cruda -> {id: texto}, con el limite de cada hueco aplicado."""
    limites = {h["id"]: h["limite"] for h in huecos}
    salida: dict[int, str] = {}
    if isinstance(dato, dict):  # tolerancia: algunos modelos devuelven {"3": "..."}
        dato = [{"id": k, "texto": v} for k, v in dato.items()]
    if not isinstance(dato, list):
        return {}
    for item in dato:
        if not isinstance(item, dict):
            continue
        ident = item.get("id")
        if isinstance(ident, str) and ident.isdigit():
            ident = int(ident)
        if not isinstance(ident, int) or isinstance(ident, bool) or ident not in limites:
            continue
        texto = _texto_valido(item.get("texto"), limites[ident])
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
    "pedir_textos",
    "pedir_textos_para",
    "ruta_sidecar",
    "sanear",
]
