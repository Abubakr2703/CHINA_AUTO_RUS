@echo off
rem Launch CHINA AUTO RUS without a console window (pythonw.exe).
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo [CHINA AUTO RUS] Virtual environment not found: .venv\Scripts\pythonw.exe
    echo Create it first: see README.md
    pause
    exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" -m china_auto_rus
