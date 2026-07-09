# Skill: Captions Pipeline — Prompt Models Studio

## Cuando usar esta skill
Cuando el usuario pida:
- Agregar captions animados a un video
- Cambiar el estilo de captions
- Diagnosticar por que el pipeline falla
- Agregar un nuevo estilo
- Ajustar posicion/tamano de los subtitulos

## Estado del proyecto (2026-07-08)
- Pipeline completamente funcional y probado en 9:16 y 16:9
- 4 estilos implementados: hormozi, karaoke, bounce, pms
- Rendimiento: ~4s para video de 15s (GPU RTX 5070 Ti + CUDA)
- Modelo: faster-whisper small en CUDA float16

## Estructura de archivos

```
caption.py    — CLI principal (punto de entrada)
styles.py     — Definicion de estilos (editar PMS_* vars al top)
requirements.txt
venv/         — entorno Python (ya instalado)
input/        — videos de entrada
output/       — videos procesados
```

## Comandos de operacion

```powershell
# Setup de entorno (obligatorio en Windows)
$env:PYTHONIOENCODING="utf-8"
$env:HF_HUB_DISABLE_SYMLINKS_WARNING="1"

# Uso basico
.\venv\Scripts\python caption.py input/video.mp4 --style hormozi --lang es

# Batch
.\venv\Scripts\python caption.py input/ --style karaoke --lang es
```

## Como agregar un estilo

En `styles.py`, agrega al dict `STYLES`:

```python
"nombre": StyleConfig(
    name="nombre",
    font_name="Arial Black",      # Fuente instalada en Windows
    font_size=88,
    primary_color="&H00FFFFFF",   # Blanco (formato &HAABBGGRR)
    highlight_color="&H000000FF", # Rojo
    outline_color="&H00000000",
    outline_size=5.0,
    shadow_color="&H88000000",
    shadow_depth=2.0,
    bold=True,
    uppercase=True,
    animation_type="highlight",   # "highlight" | "karaoke" | "bounce" | "scale"
    max_chars_per_line=18,
    margin_pct=0.10,
),
```

Luego agregar `"nombre"` a los `choices` del argparse en `caption.py`.

## Diagnostico de problemas comunes

### "No se encontraron palabras con timestamps"
- Causa: faster-whisper no genero word_timestamps (raro con vad_filter=True)
- Fix: verificar que el audio tiene voz clara. Probar con `--lang` correcto.

### Primera corrida muy lenta (~180s)
- Causa: descarga del modelo + warmup de CUDA
- Normal. Las corridas siguientes son ~4s.

### Error de symlinks con modelo medium
- Causa: Windows sin Developer Mode no permite symlinks
- Fix: Activar Developer Mode en Windows Settings, o usar `small` (ya funciona)

### Texto cortado en un lado
- Causa: `max_chars_per_line` muy alto para la fuente/resolucion
- Fix: reducir `max_chars_per_line` en el estilo correspondiente en `styles.py`

### Video de salida sin audio
- Causa: el video original tenia audio en formato que FFmpeg no copia directamente
- Fix: cambiar `-c:a copy` por `-c:a aac -b:a 128k` en `burn_subtitles()` en `caption.py`

## Tecnica ASS word-by-word
El efecto se logra creando UN evento ASS por cada palabra en el grupo. Cada evento dura desde el inicio de esa palabra hasta el inicio de la siguiente. El texto del evento muestra TODAS las palabras del grupo, pero solo la palabra activa lleva tags ASS de color/animacion. El tag `\r` resetea al final de cada palabra activa para que el resto del texto vuelva al color base.

## Colores ASS (referencia rapida)
Formato: `&HAABBGGRR` (alpha, blue, green, red — NOT RGB)
- Blanco:   `&H00FFFFFF`
- Amarillo: `&H0000FFFF`
- Cian:     `&H00FFFF00`
- Naranja:  `&H000080FF`
- Morado:   `&H00ED3A7C`  (#7C3AED en hex)
- Rojo:     `&H000000FF`
Conversor: RGB(R,G,B) → `&H00` + hex(B) + hex(G) + hex(R)
