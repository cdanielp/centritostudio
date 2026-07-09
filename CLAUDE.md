# Contexto del Proyecto — Captions Pipeline PMS

## Que es esto
Pipeline CLI local para generar captions animados word-by-word sobre videos con voz en español. Equivalente self-hosted de captions.ai. Construido para Prompt Models Studio.

## Comandos frecuentes

```powershell
# Siempre setear encoding antes de correr
$env:PYTHONIOENCODING="utf-8"
$env:HF_HUB_DISABLE_SYMLINKS_WARNING="1"

# Un video (9:16 o 16:9, se detecta automatico)
.\venv\Scripts\python caption.py input/video.mp4 --style hormozi --lang es

# Batch
.\venv\Scripts\python caption.py input/ --style karaoke

# Generar audio de prueba con edge-tts
.\venv\Scripts\python -c "
import asyncio, edge_tts
async def main():
    c = edge_tts.Communicate('Tu texto aqui', 'es-MX-JorgeNeural')
    await c.save('input/audio.mp3')
asyncio.run(main())
"

# Crear video de prueba 9:16
ffmpeg -y -f lavfi -i 'color=c=0x1a1a2e:size=1080x1920:rate=30' -i input/audio.mp3 -shortest -c:v libx264 -crf 23 -c:a aac input/test_9_16.mp4

# Extraer frame para verificar
ffmpeg -y -i output/video_hormozi.mp4 -ss 5 -vframes 1 output/frame_check.png
```

## Arquitectura

```
caption.py     CLI principal + transcripcion + pipeline
styles.py      Definicion de los 4 estilos (editar PMS_ vars al inicio)
input/         Videos de entrada + audios de test
output/        Videos con captions quemados + .ass + frames de verificacion
referencias/   Repos clonados solo para estudio (no tocar)
venv/          Entorno Python
```

## Stack tecnico
- `faster-whisper` 1.2.1 con ctranslate2 4.8.1 (CUDA)
- `pysubs2` 1.8.1 para generacion de archivos .ass
- `edge-tts` 7.2.8 para audio de prueba
- FFmpeg 8.0 (Chocolatey) para quemado con filtro `ass=`
- GPU: RTX 5070 Ti, CUDA detectada via `ctranslate2.get_cuda_device_count()`
- Modelo actual: `small` + `float16` en CUDA

## Tecnica de animacion word-by-word (ASS)
Por cada grupo de palabras (max 2 lineas, ~18 chars/linea) se crean N eventos ASS donde N = numero de palabras. Cada evento muestra todas las palabras del grupo pero solo la palabra activa lleva tags de color/animacion:
- `highlight`: `{\c&H0000FFFF&}PALABRA{\r}` (cambia color)
- `karaoke`: `{\kf{dur_cs}\c&H00FFFF00&}PALABRA{\r}` (relleno progresivo)
- `bounce`: `{\t(0,80,\fscx122\fscy122)\t(80,160,\fscx100\fscy100)\c...}PALABRA{\r}`

## Problemas conocidos / workarounds
1. Primera corrida lenta (~180s) — modelo se descarga + CUDA warmup. Corridas siguientes: ~4s
2. `HF_HUB_DISABLE_SYMLINKS_WARNING=1` necesario en Windows sin Developer Mode
3. Modelo `medium` requiere Developer Mode o admin para descargarse (symlinks). Usar `small` es estable
4. Colores ASS: formato `&HAABBGGRR` (NO es RGB). Conversor: RGB(R,G,B) -> `&H00{B:02X}{G:02X}{R:02X}`

## Que falta / mejoras posibles
- Modo `--model medium` con flag explicito para usuarios con Developer Mode
- Soporte para fuentes custom (instalar TTF en Windows y referenciar por nombre)
- Posicion configurable por CLI (`--position bottom|center|top` en porcentaje)
- Preview de un frame sin quemar el video completo
- Exportar .srt tambien (para plataformas que lo requieran)
