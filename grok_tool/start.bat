@echo off
cd /d "%~dp0"
title Grok Register Tool

echo [*] Killing previous runs (save RAM)...
call kill_old.bat

if not exist venv (
    echo [*] Creating venv...
    python -m venv venv
)

call venv\Scripts\activate.bat
echo [*] Installing dependencies...
pip install -r requirements.txt -q

if not exist hotmails.txt (
    type nul > hotmails.txt
    echo [*] Created empty hotmails.txt
)

echo [*] Starting...
echo.
echo   Chon email:
echo     1 = Hotmail
echo     2 = Temp mail (azpopmail.com)
echo.
set /p CHOICE="Chon [1/2]: "
if "%CHOICE%"=="" set CHOICE=1
python main.py %CHOICE%
echo.
echo [*] Cleaning up after run...
call kill_old.bat
pause
