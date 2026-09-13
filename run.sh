#!/usr/bin/env bash
# Launch BonkScanner from an existing .venv (Linux counterpart of run.bat).
# Run ./start.sh first if .venv does not exist yet.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
[ -x .venv/bin/python3 ] || { echo "BonkScanner: .venv missing, run ./start.sh first." >&2; exit 1; }
exec .venv/bin/python3 src/main.py "$@"
