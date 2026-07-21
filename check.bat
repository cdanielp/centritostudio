@echo off
REM check.bat — verificacion completa del proyecto en un comando.
REM Uso:  check.bat        (entorno + lint + formato + imports + tests)
REM       check.bat full   (agrega smoke render con GPU sobre un fixture SINTETICO)
setlocal
set PYTHONIOENCODING=utf-8
set PY=venv\Scripts\python.exe

if not exist "%PY%" (
  echo [X] No existe venv\Scripts\python.exe - crea el venv: py -3.12 -m venv venv
  exit /b 1
)

echo [1/5] entorno (Python/venv/ffmpeg/ffprobe/modelos/imports)...
"%PY%" -m system_preflight --strict-local
if errorlevel 1 (echo [X] Entorno local incompleto - ver docs\ENTORNO.md & exit /b 1)

echo [2/5] ruff check...
"%PY%" -m ruff check .
if errorlevel 1 (echo [X] Lint fallo & exit /b 1)

echo [3/5] ruff format --check...
"%PY%" -m ruff format --check .
if errorlevel 1 (echo [X] Formato inconsistente. Corre: %PY% -m ruff format . & exit /b 1)

echo [4/5] imports base...
"%PY%" -c "import styles, caption, app, system_preflight, studio_launcher"
if errorlevel 1 (echo [X] Import roto & exit /b 1)

echo [5/5] pytest...
"%PY%" -m pytest -q
set PC=%errorlevel%
if %PC%==0 goto tests_ok
if %PC%==5 (echo [i] Sin tests recolectados & goto tests_ok)
echo [X] Tests fallando
exit /b 1
:tests_ok

if /i "%1"=="full" (
  echo [full] Generando fixture sintetico ^(sin datos privados^)...
  ffmpeg -y -f lavfi -i color=c=0x1a1a2e:size=1080x1920:rate=30:duration=3 -f lavfi -i sine=frequency=220:duration=3 -shortest -c:v libx264 -crf 23 -pix_fmt yuv420p -c:a aac input\_smoke_synth.mp4
  if errorlevel 1 (echo [X] No se pudo generar el fixture ^(ffmpeg^) & exit /b 1)
  echo [full] Smoke render...
  "%PY%" caption.py input\_smoke_synth.mp4 --style hormozi --lang es --out-stem _smoke
  set RC=%errorlevel%
  del /q input\_smoke_synth.mp4 >nul 2>&1
  del /q output\_smoke* >nul 2>&1
  del /q transcripts\_smoke_synth* >nul 2>&1
  del /q thumbs\_smoke_synth* >nul 2>&1
  if not "%RC%"=="0" (echo [X] Smoke render fallo & exit /b 1)
  echo [full] Smoke OK
)

echo.
echo ===== TODO OK =====
exit /b 0
