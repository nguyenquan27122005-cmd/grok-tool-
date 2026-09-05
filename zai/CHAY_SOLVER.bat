@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Z.ai Solver :5073

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1

set PY=..\grok_tool\venv\Scripts\python.exe
if not exist "%PY%" set PY=venv\Scripts\python.exe
if not exist "%PY%" (
    echo [LOI] Khong thay Python venv.
    pause
    exit /b 1
)

echo.
echo   ==============================================
echo     Z.AI ALIYUN SOLVER  (Chrome offscreen)
echo     http://127.0.0.1:5073
echo   ==============================================
echo.
echo   Giu cua so nay MO khi reg. Reg tool tu goi /signup.
echo.
"%PY%" -u zaisolver.py --host 127.0.0.1 --port 5073
set ERR=%ERRORLEVEL%
echo.
if not "%ERR%"=="0" echo [LOI] Solver exit=%ERR%
pause
exit /b %ERR%
