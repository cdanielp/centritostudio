# Centrito Studio — Reporte de Pruebas E2E
**Fecha:** 2026-07-08  
**Versión:** v2.0 (web UI sobre pipeline refactorizado)

---

## Arquitectura implementada

```
core.py         Funciones puras: transcribe, group_words, build_ass, burn_video
caption.py      CLI (sin lógica duplicada, importa core.py)
app.py          FastAPI server en puerto 8787
static/index.html  UI completa vanilla JS, una sola página
arranque.bat    Doble clic → levanta server + abre navegador
vocabulario.txt 30 términos técnicos como initial_prompt para Whisper
```

**Mejoras de backend integradas:**
- `vocabulario.txt` → `initial_prompt` en Whisper: "confiwai" → **"ComfyUI"** ✅
- Agrupación por pausas naturales (threshold 0.4s) + puntuación final (`.!?…`) ✅
- `condition_on_previous_text=False`, `beam_size=5` anti-alucinación ✅
- Filtro prob < 0.05 (bajado de 0.30 para no perder palabras técnicas) ✅
- Fuente relativa a PlayResY: `font_size * (video_height / 1920)` siempre ✅

---

## E2E Test 1: Transcribir → Editar → Renderizar (reel02)

**Objetivo:** Verificar que la edición de texto vía API queda quemada en el video final.

| Paso | Resultado |
|------|-----------|
| POST /api/videos/reel02/transcribe | 200 OK, job completado |
| GET /api/videos/reel02/transcript | 4 grupos, "ComfyUI." en grupo [2] |
| PUT /api/videos/reel02/transcript (edición) | 200 OK, 4 grupos guardados |
| POST /api/videos/reel02/render (hormozi) | 200 OK, 1.0s de FFmpeg |
| Extracción de frame @4.5s | "COMFYUI." visible en amarillo ✅ |

**Evidencia visual:** `revision/e2e_reel02_comfyui.png`
- Frame muestra "COMFYUI." en estilo hormozi (blanco bold + amarillo en palabra activa)
- El vocabulario.txt corrigió automáticamente la transcripción sin intervención manual
- El PUT endpoint con `Body(...)` guarda correctamente la edición

---

## E2E Test 2: Seek on click y resaltado activo (mecanismo JS)

**Nota:** Playwright no disponible en este entorno. Mecanismo documentado y verificado por código:

**Click en grupo → seek:**
```javascript
// En cada g-header (onclick)
function seekTo(t) { editorVideo.currentTime = t; }
// → HTML5 video salta inmediatamente al timestamp del grupo
```

**Resaltado activo durante reproducción:**
```javascript
videoEl.addEventListener('timeupdate', () => {
    const t = videoEl.currentTime;
    editorGroups.forEach(g => {
        const el = document.getElementById('g-' + g.id);
        if (t >= g.start && t <= g.end + 0.15)
            el.classList.add('active-group');  // borde morado + bg oscuro
        else
            el.classList.remove('active-group');
    });
});
```
- El evento `timeupdate` dispara ~4-8x/segundo durante reproducción
- Margen +0.15s evita parpadeo al borde de los grupos
- El grupo activo hace scroll automático a la vista (`scrollIntoView`)

---

## E2E Test 3: Consistencia de fuente entre resoluciones

**Objetivo:** 1056×1920 y 1080×1920 deben verse idénticos en tamaño de texto.

**Matemática:**
```
ref_height = 1920 (ambos son verticales, height >= width)
dim_scale  = video_height / ref_height = 1920 / 1920 = 1.0
font_size  = 90 * 1.0 = 90px en ambos
marginv    = video_height * 0.10 = 192px en ambos
```

**Resultado:** Idéntico en ambas resoluciones porque PlayResY = 1920 para ambas.
La diferencia de 24px en ancho (1056 vs 1080) no afecta el tamaño de fuente (ASS escala por height).

**Evidencia visual:** `revision/font_consistency_test.png`
- Texto del mismo tamaño relativo en ambas resoluciones ✅
- Ambos textos en la misma posición vertical ✅
- Contenido idéntico (mismo audio) en distintos timestamps por diferencia de agrupación

---

## Tiempos de API (POST warmup, modelo medium en CUDA)

| Operación | Tiempo |
|-----------|--------|
| POST /transcribe (primera vez, model load) | ~8s |
| POST /transcribe (modelo ya cargado) | ~2-3s |
| POST /render (video 9.96s) | ~4s |
| GET /api/videos (4 videos con info cached) | <50ms |
| PUT /transcript (4 grupos) | <10ms |

---

## UI — Funcionalidades implementadas

| Feature | Estado |
|---------|--------|
| Lista de videos con miniatura, duración, estado | ✅ |
| Drag & drop / upload via FileInput | ✅ |
| Botón Transcribir con barra de progreso (polling) | ✅ |
| Advertencia si mean_volume < -40 dB | ✅ |
| Editor: video player HTML5 | ✅ |
| Editor: grupos editables con timestamp | ✅ |
| Editor: click en grupo → seek | ✅ |
| Editor: resaltado del grupo activo (timeupdate) | ✅ |
| Editor: "unir con siguiente" grupo | ✅ |
| Editor: guardar / restaurar original | ✅ |
| Render: dropdown estilo + palabras por grupo | ✅ |
| Render: progreso en background sin bloquear UI | ✅ |
| Render: preview + botón Descargar | ✅ |
| UTF-8 completo (á é í ó ú ñ ¿ ¡) | ✅ |

---

## Pendientes / Limitaciones conocidas

1. **No hay autenticación** — solo para uso local, no exponer a internet
2. **El server debe estar corriendo** — la UI no funciona sin él (es una API real, no estática pura)
3. **Playwright no testeado** — el mecanismo de seek/resaltado está en código pero no verificado con browser real automatizado
4. **Miniatura de video con path** — si el input no tiene audio a t=1s, la miniatura puede estar en negro
5. **No hay desfase de model** — el primer transcribe tarda más por carga del modelo; una próxima versión podría pre-cargar al arrancar

---

*Generado por Centrito Studio v2.0 — Prompt Models Studio*
