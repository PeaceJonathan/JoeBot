@echo off
REM One-command launch for Windows: starts the Streamlit dashboard. Run setup.bat first.
cd /d "%~dp0"

if not exist .venv\Scripts\streamlit.exe (
    echo ERROR: .venv not found or incomplete. Run setup.bat first.
    exit /b 1
)

if not exist .env (
    echo WARNING: .env not found -- SEC_USER_AGENT and every optional API key will be unset.
    echo Run setup.bat to create .env from .env.example, then edit it.
)

.venv\Scripts\streamlit run dashboard\app.py %*
