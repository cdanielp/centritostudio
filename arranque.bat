@echo off
cd /d "%~dp0"
call venv\Scripts\activate.bat
set PYTHONIOENCODING=utf-8
set HF_HUB_DISABLE_SYMLINKS_WARNING=1

echo Iniciando Centrito Studio en http://localhost:8787
start "" "http://localhost:8787"
python -m uvicorn app:app --host 0.0.0.0 --port 8787 --reload
