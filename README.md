# Centrito Studio

Herramienta local para generar captions animados palabra por palabra (estilo Hormozi/CapCut/karaoke). Incluye UI web con editor de transcripción sincronizado y CLI para batch processing.

Equivalente self-hosted de captions.ai. Sin suscripción, sin API externa, sin Docker.

## Centrito Studio — UI Web (recomendado)

### Arranque en 1 clic

Doble clic en **`arranque.bat`** — levanta el server y abre el navegador automáticamente.

### Flujo en 5 pasos

1. **Videos** → arrastra tu .mp4 o haz clic para seleccionar
2. **Transcribir** → haz clic en el botón "Transcribir" del video; espera la barra de progreso
3. **Editor** → abre el Editor, haz clic en cualquier grupo para saltar al timestamp; edita el texto si Whisper se equivocó
4. **Guardar** → "Guardar cambios" preserva tus ediciones; "Restaurar original" vuelve a la transcripción automática
5. **Render** → elige estilo y palabras por grupo → "Renderizar" → preview + Descargar

### Características del editor

- Click en grupo → el video salta a ese momento
- El grupo activo se resalta automáticamente mientras se reproduce
- "Unir con siguiente" fusiona grupos adyacentes
- Los cambios solo afectan al texto; los timestamps se redistribuyen proporcionalmente

## Requisitos

- Python 3.10+
- FFmpeg en PATH (instalado con Chocolatey o Gyan.dev)
- (Opcional) GPU NVIDIA con CUDA para mayor velocidad

## Instalación

```powershell
cd C:\CLAUDECODE\ediciondevideo
python -m venv venv
.\venv\Scripts\pip install -r requirements.txt
```

## Uso básico

```powershell
# Activar entorno (o prefijar comandos con .\venv\Scripts\python)
$env:PYTHONIOENCODING="utf-8"

# Un video
.\venv\Scripts\python caption.py input/mi_video.mp4 --style hormozi --lang es

# Modo batch: todos los .mp4 de una carpeta
.\venv\Scripts\python caption.py input/ --style karaoke --lang es
```

El archivo de salida se guarda en `output/` con el nombre `{original}_{estilo}.mp4`.

## Estilos disponibles

| Estilo | Descripcion | Animacion |
|--------|-------------|-----------|
| `hormozi` | Blanco bold + amarillo en palabra activa | Color change |
| `karaoke` | Relleno progresivo cian por palabra | `\kf` fill |
| `bounce` | Naranja con escala 122% al activarse | `\t()` scale |
| `pms` | Marca PMS: morado configurable | Color change |

## Parametros CLI

```
python caption.py <input> [--style ESTILO] [--lang IDIOMA] [--output-dir CARPETA]

  input          Video .mp4 o carpeta para batch
  --style        hormozi | karaoke | bounce | pms  (default: hormozi)
  --lang         Codigo de idioma (default: es)
  --output-dir   Carpeta de salida (default: output/)
```

## Personalizar el estilo PMS

Abre `styles.py` y edita el bloque marcado al inicio:

```python
PMS_FONT            = "Arial"          # Cambia la fuente
PMS_FONT_SIZE       = 85
PMS_PRIMARY_COLOR   = "&H00FFFFFF"     # Blanco
PMS_HIGHLIGHT_COLOR = "&H00ED3A7C"     # Morado #7C3AED (formato BGR invertido)
PMS_OUTLINE_SIZE    = 3.5
```

Los colores usan formato ASS `&HAABBGGRR` (alpha, blue, green, red — NO es RGB directo).
Conversor: RGB(R,G,B) -> `&H00{B:02X}{G:02X}{R:02X}`

## Como agregar un nuevo estilo

1. Abre `styles.py`
2. Agrega una entrada en el dict `STYLES`:

```python
"mi_estilo": StyleConfig(
    name="mi_estilo",
    font_name="Impact",
    font_size=88,
    primary_color="&H00FFFFFF",
    highlight_color="&H000000FF",  # Rojo
    outline_color="&H00000000",
    outline_size=5.0,
    shadow_color="&H88000000",
    shadow_depth=2.0,
    bold=True,
    uppercase=True,
    animation_type="highlight",    # o "karaoke", "bounce", "scale"
    max_chars_per_line=18,
    margin_pct=0.10,
),
```

3. Agrega `"mi_estilo"` a los `choices` en el argparse de `caption.py`

## Rendimiento (RTX 5070 Ti, video de 15s)

| Fase | Tiempo |
|------|--------|
| Carga del modelo (primera vez) | ~10s |
| Transcripcion (GPU, small) | ~1.1s |
| Generacion .ass | <0.1s |
| Quemado FFmpeg | ~2.5s |
| **Total (post-warmup)** | **~3.8s** |

Para videos de 1 minuto: estimado 12-18s de procesamiento total.

Para mejor precision de transcripcion, usa el modelo medium (requiere descargar ~1.5GB):
edita `_detect_device()` en `caption.py` para retornar `"medium"` en vez de `"small"`.
