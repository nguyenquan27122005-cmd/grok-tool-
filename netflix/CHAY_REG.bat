@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Netflix Reg · CLI

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

"%PY%" -u main.py %*
echo.
pause
