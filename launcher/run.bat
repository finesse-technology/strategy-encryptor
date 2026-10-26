@echo off
REM Launch the Strategy Encryptor GUI using the project's .venv (Windows).
setlocal
set "ROOT=%~dp0.."
set "PYW=%ROOT%\.venv\Scripts\pythonw.exe"
set "PY=%ROOT%\.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo [ERROR] .venv not found at "%ROOT%\.venv"
    echo.
    echo Create it first:
    echo     python -m venv .venv
    echo     .venv\Scripts\python -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

REM pythonw = no console window; fall back to python.exe if missing.
if exist "%PYW%" (
    start "" "%PYW%" "%ROOT%\gui.py"
) else (
    start "" "%PY%" "%ROOT%\gui.py"
)
endlocal
