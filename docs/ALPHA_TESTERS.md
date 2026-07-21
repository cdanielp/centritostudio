# Centrito Studio — Guía para testers (v0.1.1-alpha candidate)

> **v0.1.1-alpha candidate** es una etiqueta de documentación. **No** existe todavía un tag ni un
> release publicado; recibes un clon o ZIP del repositorio.

Gracias por probar el Alpha. Es software en construcción: lo más útil es que lo uses con TUS
videos reales y nos digas exactamente dónde se sintió mal. Esta guía sirve para arrancar desde un
clon/ZIP **limpio**.

Centrito Studio es una **suite local de producción y revisión de video**: transcribe, corta,
reencuadra a vertical y quema captions animados, con un **Modo Automático** que produce un paquete
de clips para que **tú** los revises y publiques. No es un editor multipista tipo Premiere/CapCut.

> **Local por defecto, con integraciones externas explícitas y opcionales.** Nada sale de tu PC a
> menos que actives una integración remota (ver §7). No afirmamos "nada se sube": si usas Submagic,
> el video puede subirse a su nube.

---

## 1. Requisitos previos

- **Windows 11** (validado). Otros sistemas: ver §8.
- **Python 3.12.x** (misma major.minor; el arranque rechaza otra versión con un mensaje accionable).
- **FFmpeg + ffprobe** en el PATH (`choco install ffmpeg`, o builds de gyan.dev / BtbN).
- GPU NVIDIA: **opcional** (acelera transcripción y codificación; hay fallback CPU).

Instalación reproducible:

```powershell
py -3.12 -m venv venv
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install -r requirements.txt
venv\Scripts\python.exe scripts\setup_models.py    # modelos de detección facial (SHA256)
copy .env.example .env                              # opcional: solo si usarás LLM/Pexels/Submagic
.\check.bat                                         # debe terminar "===== TODO OK ====="
```

Guía técnica detallada de instalación, diagnóstico y modo degradado: [`ENTORNO.md`](ENTORNO.md).

## 2. Qué NO viene en el repositorio

Nada de esto se versiona; lo generas tú localmente:

- Videos de entrada (`input/`) y salidas (`output/`).
- Transcripciones y análisis (`transcripts/`).
- Modelos de detección facial (`models/`, `referencia/yunet/` — instálalos con `setup_models.py`).
- `.env` con tus claves.
- Paquetes generados, miniaturas y renders.

## 3. Cómo arrancar la app

1. Doble click en `arranque.bat` (raíz del proyecto).
2. Se abre el navegador en `http://127.0.0.1:8787` (solo loopback) en **Inicio**.
3. Si no abre solo, abre esa dirección a mano en Edge/Chrome.

La barra superior tiene **7 secciones**:

> **Inicio · Automático · Editor · Creador · Submagic · Paquetes · Ajustes**

Regla mental: **Automático genera · Editor revisa · Creador controla.**

## 4. Modos que puedes probar

- **Automático → Clásico:** video entra → paquete de clips (reframe + captions + emojis, flujo
  histórico).
- **Automático → v2:** lo mismo + b-roll automático, FX y verificación A/V.
- **Creador (herramientas sueltas):** transcribir, clipper, reframe, stack, captions, Caption QA,
  depurador.
- **Captions desde transcript** (Whisper) o **desde SRT seleccionado** (ver §6).
- **Editor de Paquete:** abre un paquete ya generado y revisa clip por clip (estados, alertas,
  timeline) y su `REPORTE.md` (scores, avisos, telemetría). **Es revisión, no edición**: no
  recalcula ni toca el video.

> No prometemos edición persistente ni timeline multipista: el "Editor" es una **mesa de revisión**
> sobre lo ya producido.

## 5. GPU y codificación

En **Ajustes → Codificación de video** eliges el selector:

- **Automático** — NVIDIA si está disponible; si no, CPU (nunca falla por ausencia de NVENC).
- **GPU NVIDIA (NVENC)** — fuerza NVENC; si no hay, el job se rechaza (no cae silencioso a CPU).
- **CPU** — máxima compatibilidad (`libx264`).

Ten presente:

- **Transcripción (CUDA) y codificación (NVENC) son cosas distintas.** Tener una no implica la otra.
- **El reframe y los filtros NO son 100% GPU:** la lectura/resize (OpenCV), la detección facial,
  libass y el audio siguen en **CPU**. Por eso el reframe acelera menos que un encode puro.
- **CPU es una ruta válida y completa.** Si no tienes GPU NVIDIA, todo funciona.

Al reportar rendimiento, incluye: encoder mostrado (Ajustes o el resumen del job), CPU/GPU de tu
equipo, resolución y duración del video, y tiempos aproximados. Detalle técnico y benchmarks:
[`GPU_NVENC.md`](GPU_NVENC.md).

## 6. SRT (subtítulos como fuente oficial)

Puedes asociar un archivo `.srt` a un video (pestaña de SRT en Render/Auto):

- La asociación es **explícita** (tú eliges el video y el SRT); **no hay autodiscovery**.
- El **texto del SRT es la fuente oficial** de los captions; Whisper solo aporta timings.
- Funciones **incompatibles con la ruta SRT** (se deshabilitan con explicación): **Palabras por
  grupo**, **Énfasis IA** y **Caption QA**. Estilo/Preset/Intensidad/Emojis siguen disponibles.
- Para reportar un error con un SRT, **no compartas tu SRT privado** salvo que tú, como propietario,
  decidas expresamente hacerlo. Describe el problema con un SRT de ejemplo genérico.

## 7. Servicios externos (opt-in) — qué sale de tu PC

Antes de probar una función externa, ten claro qué envía. Todas son **opt-in** (requieren su API
key en `.env` o elegir la estación):

| Función | Local/remoto | Qué sale de la PC |
|---|---|---|
| DeepSeek / proveedor LLM | Remoto, opcional | **Texto/contexto** para análisis editorial |
| Pexels (b-roll) | Remoto, opcional | **Búsquedas** de stock (descarga assets) |
| Submagic (pestaña) | Remoto, opcional | Puede **subir el video** a la nube de Submagic |
| ComfyUI (emojis/popups) | **Local** (loopback `127.0.0.1:8188`) | Assets PNG locales; no sale de la PC |

**No pruebes las funciones remotas con material sensible sin autorización.** Sin claves, esas capas
quedan deshabilitadas y el pipeline local sigue.

## 8. Compatibilidad honesta

| Entorno | Estado |
|---|---|
| Windows 11 + NVIDIA | Validado |
| Windows 11 sin NVIDIA | CPU fallback soportado por diseño |
| Windows 10 | No validado |
| GPU AMD | No validado |
| Linux / macOS | No validados |
| FFmpeg sin NVENC | Usa CPU (`libx264`) |
| Sin modelos de detección facial | Reframe con seguimiento facial degradado (el resto sigue) |

No inventamos resultados de sistemas que no probamos: si usas uno "no validado", cuéntanos qué pasó.

## 9. Recuperación (qué hacer si algo se corta)

- **Cierras la app o se reinicia el servidor a mitad de un job:** al volver, la UI detecta el
  **job perdido** ("El servidor se reinició o el trabajo ya no existe") y ofrece **Reintentar /
  Cancelar / Seguir esperando** — no se queda un spinner infinito.
- **Un paquete quedó a medias:** usa **"Reanudar clips fallidos"**; reprocesa solo los clips
  fallidos/faltantes del mismo paquete, sin re-render de los que ya salieron bien.
- **Un output previo válido se preserva:** un intento fallido nunca borra un MP4 bueno anterior ni
  publica archivos de 0 bytes.

## 10. Formato de feedback (obligatorio)

Primero mándanos esto (NO el video real como primer paso):

- pasos que seguiste;
- captura de pantalla;
- mensaje de error (saneado, sin rutas personales);
- segundo aproximado donde ocurrió;
- tu configuración (modo, encoder, estilo/preset);
- un **fixture sintético** o una muestra autorizada.

Luego responde con tus palabras:

```
Video probado:
Modo usado:
Duración y resolución:
Encoder mostrado:
Qué funcionó:
Qué falló:
Captura o mensaje:
En qué segundo ocurrió:
Qué parte fue confusa:
Qué mejorarías:
¿Lo usarías en un trabajo real?:
¿Compartirías este resultado?:
```

Solo comparte el video original si es necesario y tú decides hacerlo.

## 11. Limpieza segura

Los resultados viven en carpetas locales que puedes borrar a mano cuando quieras:

- Paquetes del Modo Automático: `output/paquetes/`
- Renders sueltos: `output/`
- Clips cortados: `output/clips/`
- Transcripciones y análisis: `transcripts/`
- Miniaturas: `thumbs/`

Borra solo el contenido de esas carpetas (o la subcarpeta del paquete que ya no quieras).

> **Prohibido** usar `git clean -fdx` u otros comandos destructivos generales: borrarían tu `.env`,
> tus modelos y cualquier trabajo no versionado.

---

## Qué NO esperar todavía (Alpha)

- Publicación automática a TikTok/Reels/Shorts: publicas a mano.
- Editor de video / timeline multipista / cortes manuales: no es ese producto.
- Otros idiomas: por ahora español.
- Multi-persona perfecto: con 2+ caras el reframe sigue a una sola (aviso en el reporte); no hay
  selección manual de la persona a seguir.
- Grabaciones de pantalla sin cámara: el reencuadre centra fijo, sin seguimiento.
- Emojis/popups IA requieren ComfyUI local; si no está, salen sin emojis (normal).

## Checklist de prueba

- [ ] El video carga en Creador → Biblioteca (miniatura + duración)
- [ ] El Modo Automático (Clásico y/o v2) genera un paquete sin errores
- [ ] El botón "Abrir en el Editor" te llevó al paquete recién generado
- [ ] En el Editor: el preview del clip se reproduce
- [ ] Los captions se ven y están sincronizados con la voz
- [ ] El reencuadre vertical mantiene a la persona en cuadro
- [ ] (SRT) Asociar un `.srt` y renderizar con él funciona
- [ ] (GPU) El encoder mostrado coincide con tu selección en Ajustes
- [ ] (Recuperación) Cerrar y reabrir ofrece Reintentar/Reanudar, sin spinner infinito
