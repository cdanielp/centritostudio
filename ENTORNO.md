# Auditoría de Entorno

**Fecha:** 2026-07-08

## Sistema
- OS: Windows 11 Pro 10.0.26200
- Shell: PowerShell

## Python
- Versión: 3.12.10
- Pip: 26.0.1
- Ruta: `C:\Program Files\Python312\`

## FFmpeg
- Versión: 8.0 (build Gyan.dev / Chocolatey essentials)
- Ruta: `C:\ProgramData\chocolatey\bin\ffmpeg.exe`
- En PATH: Sí

## GPU
- Modelo: NVIDIA GeForce RTX 5070 Ti
- VRAM: 16303 MiB (~16 GB)
- Driver: 610.47
- CUDA: disponible

## Disco (C:)
- Usado: ~1.74 TB
- Libre: ~303 GB

## Docker
- No instalado (no necesario — se usa pipeline nativo Python)

## Decisión de entorno
Pipeline nativo Python con:
- `faster-whisper` + CUDA para transcripción con word timestamps
- `pysubs2` para generación de archivos .ass
- `ffmpeg` (sistema) para quemado de subtítulos
- `edge-tts` para generación de audio de prueba
