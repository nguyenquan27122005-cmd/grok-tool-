@echo off
chcp 65001 >nul
cd /d "%~dp0"
title HeyGen Reg · Web :8788

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
set WEB_PORT=8788
set WEB_HOST=127.0.0.1

set PY=..\grok_tool\venv\Scripts\python.exe
if not exist "%PY%" set PY=venv\Scripts\python.exe
if not exist "%PY%" (
    echo [LOI] Khong thay Python venv. Dung venv cua grok_tool hoac tao venv tai day.
    pause
    exit /b 1
)

echo.
echo   ========================================
echo     HEYGEN REG
echo     http://127.0.0.1:%WEB_PORT%/
echo   ========================================
echo   Giu cua so nay MO. Dong = tat web.
echo.

"%PY%" -m web.app
set ERR=%ERRORLEVEL%
if not "%ERR%"=="0" echo [LOI] Server exit=%ERR%
pause
exit /b %ERR%
