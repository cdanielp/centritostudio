@echo off
cd /d "%~dp0"
call venv\Scripts\activate.bat
set PYTHONIOENCODING=utf-8
set HF_HUB_DISABLE_SYMLINKS_WARNING=1

echo Iniciando Centrito Studio en http://127.0.0.1:8787
start "" "http://127.0.0.1:8787"
REM H1 (P0-4): bind SOLO a loopback. Sin modo LAN en esta fase (sin token/auth).
python -m uvicorn app:app --host 127.0.0.1 --port 8787 --reload
