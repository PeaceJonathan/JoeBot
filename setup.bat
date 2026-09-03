@echo off
REM One-command setup for Windows: clone repo -> run this -> configure .env -> run.bat.
setlocal enabledelayedexpansion
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: python not found on PATH. Install Python 3.11+ from https://www.python.org/downloads/ first.
    exit /b 1
)

if not exist .venv (
    echo Creating virtual environment in .venv ...
    python -m venv .venv
)

echo Installing dependencies (this can take a minute the first time) ...
.venv\Scripts\pip install -q --upgrade pip
.venv\Scripts\pip install -q -e ".[dashboard,sentiment,dev]"

if not exist .env (
    echo Creating .env from .env.example ...
    copy .env.example .env >nul
    echo.
    echo IMPORTANT: edit .env now and set SEC_USER_AGENT to a real contact
    echo email (SEC requires this on every request^). Everything else in
    echo .env is optional -- see README.md's "Data sources" table for what
    echo you lose by skipping each one.
) else (
    echo .env already exists -- leaving it as-is.
)

echo.
echo Setup complete. Next steps:
echo   1. Edit .env -- at minimum, set SEC_USER_AGENT to a real email address.
echo   2. Run run.bat to launch the dashboard, or
echo      .venv\Scripts\python scripts\validate_live_data.py to confirm your
echo      API access actually works before trusting any output.
