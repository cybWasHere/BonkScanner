#!/usr/bin/env bash
# Linux counterpart of run_tests.bat: run the unit test suite from the project venv.
set -euo pipefail
cd "$(dirname "$0")"
[ -x .venv/bin/python3 ] || { echo "Run ./start.sh --no-run first to create .venv."; exit 1; }
export PYTHONPATH="$PWD:$PWD/src:$PWD/src/tests"
if [ $# -eq 0 ]; then
  exec .venv/bin/python3 -m unittest discover -s src/tests -p 'test_*.py'
fi
exec .venv/bin/python3 -m unittest "$@"
