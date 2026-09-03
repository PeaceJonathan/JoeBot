#!/usr/bin/env bash
# One-command setup: clone repo -> run this -> configure .env -> run.sh.
#
# Creates a Python virtualenv, installs dependencies, and copies .env.example
# to .env if it doesn't already exist. Safe to re-run (idempotent).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "ERROR: $PYTHON_BIN not found. Install Python 3.11+ first (https://www.python.org/downloads/)." >&2
    exit 1
fi

PY_VERSION="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "Using $PYTHON_BIN (Python $PY_VERSION)"

if [ ! -d .venv ]; then
    echo "Creating virtual environment in .venv ..."
    "$PYTHON_BIN" -m venv .venv
fi

echo "Installing dependencies (this can take a minute the first time) ..."
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -e ".[dashboard,sentiment,dev]"

if [ ! -f .env ]; then
    echo "Creating .env from .env.example ..."
    cp .env.example .env
    echo
    echo "IMPORTANT: edit .env now and set SEC_USER_AGENT to a real contact"
    echo "email (SEC requires this on every request). Everything else in"
    echo ".env is optional -- see README.md's 'Data sources' table for what"
    echo "you lose by skipping each one."
else
    echo ".env already exists -- leaving it as-is."
fi

echo
echo "Setup complete. Next steps:"
echo "  1. Edit .env -- at minimum, set SEC_USER_AGENT to a real email address."
echo "  2. Run ./run.sh to launch the dashboard, or"
echo "     .venv/bin/python scripts/validate_live_data.py to confirm your"
echo "     API access actually works before trusting any output."
