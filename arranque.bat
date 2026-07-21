@echo off
REM arranque.bat — wrapper minimo (H3). La logica robusta vive en studio_launcher.py:
REM preflight, estado del puerto y apertura del navegador SOLO tras el health check.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
set PY=venv\Scripts\python.exe

if not exist "%PY%" (
  echo [X] No existe venv\Scripts\python.exe
  echo     Crea el entorno con:  py -3.12 -m venv venv
  echo     e instala dependencias: venv\Scripts\python.exe -m pip install -r requirements.txt
  exit /b 1
)

"%PY%" studio_launcher.py
exit /b %errorlevel%
