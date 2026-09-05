@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Canva Redeem · CLI

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

if "%~1"=="" (
    "%PY%" -u canva_tool.py redeem --accounts data/accounts.txt --codes data/codes.txt --threads 3 --output data/proof.json --success-only
) else (
    "%PY%" -u canva_tool.py redeem %*
)
echo.
pause
