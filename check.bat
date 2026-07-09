@echo off
REM check.bat — verificacion completa del proyecto en un comando.
REM Uso:  check.bat        (rapido: lint + formato + imports + tests)
REM       check.bat full   (agrega smoke render con GPU, mas lento)
setlocal
set PYTHONIOENCODING=utf-8
set PY=venv\Scripts\python.exe

if not exist %PY% (
  echo [X] No existe venv\Scripts\python.exe - crea el venv primero.
  exit /b 1
)

echo [1/4] ruff check...
%PY% -m ruff check .
if errorlevel 1 (echo [X] Lint fallo & exit /b 1)

echo [2/4] ruff format --check...
%PY% -m ruff format --check .
if errorlevel 1 (echo [X] Formato inconsistente. Corre: %PY% -m ruff format . & exit /b 1)

echo [3/4] imports base...
%PY% -c "import styles, caption" 
if errorlevel 1 (echo [X] Import roto en styles/caption & exit /b 1)
%PY% -c "import core" >nul 2>&1
if errorlevel 1 (echo [i] core.py aun no existe - OK hasta Fase 1)

echo [4/4] pytest...
%PY% -m pytest -q
set PC=%errorlevel%
if %PC%==0 goto tests_ok
if %PC%==5 (echo [i] Sin tests recolectados & goto tests_ok)
echo [X] Tests fallando
exit /b 1
:tests_ok

if /i "%1"=="full" (
  echo [full] Smoke render...
  %PY% caption.py input\tacosjuan.mp4 --style hormozi --lang es --out-stem _smoke
  if errorlevel 1 (echo [X] Smoke render fallo & exit /b 1)
  del /q output\_smoke* >nul 2>&1
  echo [full] Smoke OK
)

echo.
echo ===== TODO OK =====
exit /b 0
