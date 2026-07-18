# Evidencia local S37-C — Modo Automático v2 en Studio

Esta evidencia es totalmente sintética: no usa videos, transcripts, SRT, nombres, rutas ni credenciales reales. Los MP4/JSON generados viven bajo `output/` y `transcripts/`, están ignorados por Git y se eliminan con `--clean`.

## Crear y abrir

```powershell
.\venv\Scripts\python.exe revision\s37-modo-automatico-studio\gen_fixture_studio.py --create
.\venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8787
```

Abrir `http://127.0.0.1:8787`, entrar a Editor y elegir `test_s37c_demo_v2_20260718-1200`. Para revisar la pestaña Automático no hace falta Pexels, GPU ni un render real.

El fixture contiene un clip vertical de 12 s, tres ventanas renderizadas (imagen, video y fallback a imagen), un FX eliminado por colisión, brain disponible y compuertas Audio/Sync en PASS. El resolved está confinado en `transcripts/` y la API solo publica su vista saneada.

## Limpiar

```powershell
.\venv\Scripts\python.exe revision\s37-modo-automatico-studio\gen_fixture_studio.py --clean
```

La limpieza solo elimina el paquete `test_s37c_demo_v2_20260718-1200` y `test_s37c_clip1_9x16_broll_resolved.json`; no toca otros paquetes ni sidecars.

Capturas locales, si el navegador headless las permite, se guardan en `output/revision-s37c/` y no se versionan. La lista de aceptación vinculante está en `CHECKLIST_VISUAL.md`.

En esta sesión Edge/Chrome headless produjo `auto_classic_desktop.png`, `editor_v2_desktop.png` y `editor_v2_mobile.png` (viewport 390 px). La automatización disponible no pudo ejecutar de forma fiable las interacciones de modo/toggles/resultado, por lo que `auto_v2_desktop.png`, `auto_v2_mobile.png` y `auto_v2_result.png` quedan deliberadamente para el recorrido manual de K; no se fabricaron capturas estáticas.
