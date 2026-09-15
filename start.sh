#!/usr/bin/env bash
# Linux counterpart of start.bat: set up this checkout with install.sh, then run
# BonkScanner. Re-run any time; setup only does what is missing. Pass --no-run to
# just set up, --no-shortcut to skip the application-menu entry.
set -euo pipefail
cd "$(dirname "$0")"

run=1
args=()
for arg in "$@"; do
  case $arg in
    --no-run) run=0 ;;
    *) args+=("$arg") ;;
  esac
done
./install.sh "${args[@]}"
if [ "$run" = 1 ]; then exec ./run.sh; fi
