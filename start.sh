#!/usr/bin/env bash
# Linux counterpart of start.bat: create .venv, install dependencies, run BonkScanner.
# Re-run any time; it only installs what is missing. Pass --no-run to just set up,
# --no-shortcut to skip the application-menu entry.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON=${PYTHON:-python3}
if [ ! -x .venv/bin/python3 ]; then
  # --copies gives the venv a real interpreter binary, so the ptrace capability
  # below can be attached to it without touching the system Python.
  "$PYTHON" -m venv --copies .venv
fi
.venv/bin/python3 -m pip install --quiet --upgrade pip
.venv/bin/python3 -m pip install --quiet -r src/requirements.txt || {
  echo "Dependency install failed. evdev is built from source: install a C compiler and the"
  echo "Python headers (python3-dev/python3-devel and gcc), then run ./start.sh again."
  exit 1
}

# Reading the game's memory needs ptrace permission. The default Yama scope (1)
# only allows reading descendants, so grant CAP_SYS_PTRACE to the venv Python.
# The capability survives reinstalls of packages but not a rebuilt .venv.
if command -v getcap >/dev/null && ! getcap .venv/bin/python3 2>/dev/null | grep -q cap_sys_ptrace; then
  scope=$(cat /proc/sys/kernel/yama/ptrace_scope 2>/dev/null || echo 0)
  if [ "$scope" != "0" ]; then
    echo "BonkScanner needs permission to read the game's memory (ptrace)."
    echo "Granting CAP_SYS_PTRACE to .venv/bin/python3 (asks for sudo; skip with Ctrl-C):"
    sudo setcap cap_sys_ptrace=ep "$(readlink -f .venv/bin/python3)" || echo "  skipped; memory reads will fail until this is done."
  fi
fi

# Global hotkeys read /dev/input/event* and key injection writes /dev/uinput.
if ! find /dev/input -maxdepth 1 -name 'event*' -readable 2>/dev/null | grep -q .; then
  echo "Your user cannot read /dev/input/event*. Hotkeys need that; see README.md (Linux)."
fi
if [ ! -w /dev/uinput ]; then
  echo "Your user cannot write /dev/uinput. The reset key needs that; see README.md (Linux)."
fi

# Application-menu shortcut (~/.local/share/applications), pointing at this
# checkout's run.sh. Re-created on every run so a moved checkout stays launchable.
# Skip with --no-shortcut.
if [ "${1:-}" != "--no-shortcut" ] && [ "${2:-}" != "--no-shortcut" ]; then
  HERE="$(pwd)"
  APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
  mkdir -p "$APPS"
  cat > "$APPS/bonkscanner.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=BonkScanner
Comment=Megabonk map reroll scanner, live stats and overlays (unofficial Linux port)
Exec=$HERE/run.sh
Path=$HERE
Icon=$HERE/src/media/bonkscanner_icon2.png
Terminal=false
Categories=Game;Utility;
StartupWMClass=BonkScanner
Keywords=Megabonk;reroll;overlay;
DESKTOP
  command -v update-desktop-database >/dev/null && update-desktop-database -q "$APPS" || true
  echo "Application-menu shortcut installed: $APPS/bonkscanner.desktop"
fi

if [ "${1:-}" = "--no-run" ] || [ "${2:-}" = "--no-run" ]; then
  exit 0
fi
exec ./run.sh
