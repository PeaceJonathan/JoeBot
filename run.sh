#!/usr/bin/env bash
# One-command launch: starts the Streamlit dashboard. Run setup.sh first.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if [ ! -x .venv/bin/streamlit ]; then
    echo "ERROR: .venv not found or incomplete. Run ./setup.sh first." >&2
    exit 1
fi

if [ ! -f .env ]; then
    echo "WARNING: .env not found -- SEC_USER_AGENT and every optional API key will be unset."
    echo "Run ./setup.sh to create .env from .env.example, then edit it."
fi

exec .venv/bin/streamlit run dashboard/app.py "$@"
