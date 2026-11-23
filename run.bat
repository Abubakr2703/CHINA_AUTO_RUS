@echo off
rem Launch CHINA AUTO RUS GUI with the project virtual environment.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [CHINA AUTO RUS] Virtual environment not found: .venv\Scripts\python.exe
    echo Create it first:
    echo     python -m venv .venv
    echo     .venv\Scripts\python.exe -m pip install -e ".[dev]"
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m china_auto_rus %*
