#!/usr/bin/env bash
# BonkScanner for Linux: install, update and uninstall with one command.
#
#   curl -fsSL https://raw.githubusercontent.com/cybWasHere/BonkScanner/linux-native/install.sh | bash
#
# Installs the few system packages it needs if any are missing (git, curl,
# setcap, Qt's X11 libraries), clones this fork to ~/.local/share/bonkscanner or
# updates the existing install, gives it a private Python and .venv, grants the
# two permissions BonkScanner needs behind a single sudo prompt, and adds an
# application-menu entry and a `bonkscanner` command. Running it again updates.
# Run from inside a checkout (./install.sh) it sets up that checkout and does
# not pull.
#
# Options (with curl, put them after `bash -s --`):
#   --dir DIR       install location (default ~/.local/share/bonkscanner)
#   --no-shortcut   skip the menu entry and the bonkscanner command
#   --uninstall     remove the menu entry, command and udev rule, then offer to
#                   delete the install folder (it holds config.json and recordings)
set -euo pipefail

REPO_URL=https://github.com/cybWasHere/BonkScanner.git
BRANCH=${BONKSCANNER_BRANCH:-linux-native}
# BonkScanner runs on its own Python (a uv standalone build in .python/), so it
# needs no Python from the distribution and a distribution upgrade cannot break
# the venv or the capability on it.
PY_VERSION=3.13
UV_URL=https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-unknown-linux-gnu.tar.gz
DATA_HOME=${XDG_DATA_HOME:-$HOME/.local/share}
DEFAULT_DIR=$DATA_HOME/bonkscanner
DESKTOP_FILE=$DATA_HOME/applications/bonkscanner.desktop
BIN_LINK=$HOME/.local/bin/bonkscanner
UDEV_RULE=/etc/udev/rules.d/71-bonkscanner-input.rules
# With systemd-logind (or elogind) the uaccess tag gives whoever sits at the
# machine access. Without it, fall back to the input group.
UDEV_RULE_UACCESS='SUBSYSTEM=="input", KERNEL=="event*", TAG+="uaccess"
KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess"'
UDEV_RULE_GROUP='SUBSYSTEM=="input", KERNEL=="event*", GROUP="input", MODE="0660"
KERNEL=="uinput", SUBSYSTEM=="misc", GROUP="input", MODE="0660"'
SUDO_HINT="If your account has no password yet (Steam Deck), set one with passwd first."

say()  { printf '==> %s\n' "$*"; }
note() { printf '    %s\n' "$*"; }
warn() { printf 'Warning: %s\n' "$*" >&2; }
die()  { printf 'Error: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'USAGE'
Usage: install.sh [--dir DIR] [--no-shortcut] [--uninstall]
  --dir DIR       install location (default ~/.local/share/bonkscanner)
  --no-shortcut   skip the menu entry and the bonkscanner command
  --uninstall     remove BonkScanner (asks before deleting the install folder)
Environment: PYTHON=/usr/bin/python3.12 builds .venv on that interpreter (3.11+)
instead of downloading a private Python.
USAGE
}

# stdin is /dev/null for everything that runs as root: under `curl | bash` it is
# the script itself.
root() {
  if ! command -v sudo >/dev/null; then
    warn "sudo is not installed, so this cannot run: $*"
    return 1
  fi
  sudo "$@" </dev/null
}

# setcap, getcap and ldconfig live in /sbin on distributions that keep it off a
# normal user's PATH.
find_tool() {
  command -v "$1" 2>/dev/null && return
  local d
  for d in /usr/sbin /sbin; do
    if [ -x "$d/$1" ]; then echo "$d/$1"; return; fi
  done
  return 1
}

fetch() {
  if command -v curl >/dev/null; then
    curl -fsSL --retry 3 -o "$2" "$1"
  else
    wget -q -O "$2" "$1"
  fi
}

# One line per missing prerequisite; nothing when all are present.
missing_prereqs() {
  local missing=() ldconfig cache lib
  command -v git >/dev/null || missing+=(git)
  command -v curl >/dev/null || command -v wget >/dev/null || missing+=(curl)
  find_tool setcap >/dev/null || missing+=(setcap)
  # PySide6 wheels bundle Qt but not these system libraries.
  if ldconfig=$(find_tool ldconfig); then
    cache=$("$ldconfig" -p 2>/dev/null || true)
    for lib in libxcb-cursor.so.0 libxkbcommon-x11.so.0 libEGL.so.1 libOpenGL.so.0 libGL.so.1 libfontconfig.so.1; do
      [[ $cache == *"$lib "* ]] || missing+=("$lib")
    done
  fi
  if [ ${#missing[@]} -gt 0 ]; then printf '%s\n' "${missing[@]}"; fi
}

ensure_prereqs() {
  local missing list
  missing=$(missing_prereqs)
  [ -n "$missing" ] || return 0
  list=${missing//$'\n'/, }
  say "Installing missing system packages (for: $list)"
  if command -v pacman >/dev/null; then
    root pacman -S --needed --noconfirm git curl libcap xcb-util-cursor libxkbcommon-x11 libglvnd fontconfig
  elif command -v apt-get >/dev/null; then
    root apt-get update -q &&
      root apt-get install -y -q git curl ca-certificates libcap2-bin libxcb-cursor0 libxkbcommon-x11-0 libegl1 libopengl0 libgl1 libfontconfig1
  elif command -v dnf >/dev/null; then
    root dnf install -y git curl libcap xcb-util-cursor libxkbcommon-x11 libglvnd-egl libglvnd-opengl libglvnd-glx fontconfig
  elif command -v zypper >/dev/null; then
    root zypper --non-interactive install git curl libcap-progs libxcb-cursor0 libxkbcommon-x11-0 libEGL1 libOpenGL0 libGL1 fontconfig
  else
    die "Missing: $list. Install them with your package manager, then run this again."
  fi || die "Installing packages failed (see above). On Arch-based systems update first (sudo pacman -Syu); on read-only systems (SteamOS, Bazzite) install $list another way. $SUDO_HINT Then run this again."

  command -v git >/dev/null || die "git is still missing."
  missing=$(missing_prereqs)
  if [ -n "$missing" ]; then warn "Still not found: ${missing//$'\n'/, }. Continuing; BonkScanner may not start."; fi
}

# The checkout the application-menu entry points at, if it is still there.
existing_install() {
  local p
  [ -f "$DESKTOP_FILE" ] || return 1
  p=$(sed -n 's/^Path=//p' "$DESKTOP_FILE")
  p=${p%%$'\n'*}
  [ -n "$p" ] && [ -f "$p/src/main.py" ] && [ -d "$p/.git" ] && echo "$p"
}

bootstrap() {
  ensure_prereqs
  if [ -d "$DIR/.git" ]; then
    say "Updating $DIR"
    git -C "$DIR" pull --ff-only </dev/null ||
      warn "git pull failed (local changes or a diverged branch?); setting up the checkout as it is."
  elif [ -e "$DIR" ] && [ -n "$(ls -A "$DIR" 2>/dev/null)" ]; then
    die "$DIR exists but is not a git checkout. Move it away or pass --dir."
  else
    say "Downloading BonkScanner to $DIR"
    mkdir -p "$(dirname "$DIR")"
    git clone --quiet --branch "$BRANCH" "$REPO_URL" "$DIR" </dev/null
  fi
  [ -f "$DIR/install.sh" ] || die "$DIR has no install.sh; update it (git pull) and run this again."
  # Continue with the checkout's own copy, so setup always matches the code.
  exec bash "$DIR/install.sh" "${PASS[@]}"
}

# Keep the private Python out of `git status` without touching .gitignore.
exclude_private_python() {
  local exclude
  exclude=$(git rev-parse --git-path info/exclude 2>/dev/null) || return 0
  mkdir -p "$(dirname "$exclude")"
  grep -qx '/.python/' "$exclude" 2>/dev/null || printf '/.python/\n' >> "$exclude"
}

private_python() {
  local p
  for p in ".python/cpython-$PY_VERSION-linux-x86_64-gnu/bin/python$PY_VERSION" \
           .python/cpython-"$PY_VERSION".*-linux-x86_64-gnu/bin/python"$PY_VERSION"; do
    if [ -x "$p" ] && "$p" -c '' 2>/dev/null; then echo "$PWD/$p"; return 0; fi
  done
  return 1
}

ensure_python() {
  if [ -n "$PYTHON" ]; then
    "$PYTHON" -c 'import sys, venv, ensurepip; sys.exit(sys.version_info < (3, 11))' 2>/dev/null ||
      die "PYTHON=$PYTHON is not Python 3.11 or newer with the venv module."
    return 0
  fi
  if PYTHON=$(private_python); then return 0; fi

  say "Downloading a private Python $PY_VERSION for BonkScanner (the system Python is not touched)"
  local tmp uv asset=${UV_URL##*/}
  tmp=$(mktemp -d)
  # shellcheck disable=SC2064  # expand $tmp now
  trap "rm -rf '$tmp'" EXIT
  { fetch "$UV_URL" "$tmp/$asset" && fetch "$UV_URL.sha256" "$tmp/$asset.sha256"; } ||
    die "Could not download uv from GitHub, which fetches Python. Check your connection and run this again."
  (cd "$tmp" && sha256sum --quiet -c "$asset.sha256") || die "The uv download is corrupt; run this again."
  tar -xzf "$tmp/$asset" -C "$tmp"
  uv=$(find "$tmp" -type f -name uv -print -quit)
  [ -n "$uv" ] || die "The uv download did not contain uv."
  UV_NO_CONFIG=1 UV_CACHE_DIR=$tmp/cache UV_PYTHON_INSTALL_DIR=$PWD/.python \
    "$uv" python install --quiet --no-bin --install-dir "$PWD/.python" "$PY_VERSION" </dev/null ||
    die "uv could not install Python $PY_VERSION (see above)."
  rm -rf "$tmp"
  trap - EXIT
  PYTHON=$(private_python) || die "Python $PY_VERSION was installed to $PWD/.python but does not run."
}

build_venv() {
  local marker=.venv/bonkscanner-python
  # Rebuild when the venv was made by another interpreter or can no longer start.
  if [ -e .venv ] && { [ "$(cat "$marker" 2>/dev/null)" != "$PYTHON" ] || ! .venv/bin/python3 -c '' 2>/dev/null; }; then
    note "Rebuilding .venv on $PYTHON"
    rm -rf .venv
  fi
  if [ ! -e .venv ]; then
    # --copies gives the venv a real interpreter binary, so the ptrace capability
    # can be attached to it alone.
    "$PYTHON" -m venv --copies .venv
    printf '%s\n' "$PYTHON" > "$marker"
  fi
  local pip=(.venv/bin/python3 -m pip --disable-pip-version-check)
  "${pip[@]}" install --quiet --upgrade pip </dev/null
  # evdev now comes as prebuilt wheels (evdev-binary), so no compiler is needed.
  # Both install the same module: drop a source-built evdev from older setups.
  if "${pip[@]}" show evdev >/dev/null 2>&1; then
    "${pip[@]}" uninstall --quiet -y evdev </dev/null
  fi
  say "Installing Python packages (Qt alone is about 300 MB the first time)"
  "${pip[@]}" install --quiet -r src/requirements.txt </dev/null ||
    die "pip could not install the requirements (see above)."
}

ptrace_scope() { cat /proc/sys/kernel/yama/ptrace_scope 2>/dev/null || echo 0; }

has_ptrace_cap() {
  local getcap
  getcap=$(find_tool getcap) || return 1
  [[ $("$getcap" "$(readlink -f .venv/bin/python3)" 2>/dev/null) == *cap_sys_ptrace* ]]
}

input_access_ok() {
  [ -w /dev/uinput ] && [ -n "$(find /dev/input -maxdepth 1 -name 'event*' -readable -print -quit 2>/dev/null)" ]
}

udev_rule_current() {
  [ -f "$UDEV_RULE" ] && [ "$(cat "$UDEV_RULE")" = "$UDEV_RULE_TEXT" ]
}

has_logind() { [ -d /run/systemd/seats ]; }

# Membership as recorded in the group database, not this process's groups,
# so it is true right after usermod even before a new login.
in_input_group() { [[ " $(id -nG "$(id -un)" 2>/dev/null) " == *" input "* ]]; }

# Everything keyboard access needs is in place, even if a new login is still due.
input_setup_done() { udev_rule_current && { has_logind || in_input_group; }; }

grant_permissions() {
  local need_cap=0 need_udev=0 need_group=0 setcap="" py
  py=$(readlink -f .venv/bin/python3)
  case $(ptrace_scope) in
    # Yama scope 1 only lets a process read its own descendants, 2 needs the capability.
    1|2)
      if ! has_ptrace_cap; then
        if setcap=$(find_tool setcap); then need_cap=1; else warn "setcap not found; skipping the memory-read permission."; fi
      fi ;;
    3) warn "kernel.yama.ptrace_scope is 3: no program may read another's memory, so the scanner cannot see the game. Set it to 1 and reboot." ;;
  esac
  if ! input_access_ok; then
    udev_rule_current || need_udev=1
    if ! has_logind && ! in_input_group; then need_group=1; fi
  fi
  [ "$need_cap" = 1 ] || [ "$need_udev" = 1 ] || [ "$need_group" = 1 ] || return 0

  say "BonkScanner needs system permissions (one sudo prompt):"
  if [ "$need_cap" = 1 ]; then note "- read the game's memory: CAP_SYS_PTRACE on $py"; fi
  if [ "$need_udev" = 1 ]; then note "- hotkeys and the reset key: $UDEV_RULE gives keyboard devices and /dev/uinput to $(if has_logind; then echo "your login session"; else echo "the input group"; fi)"; fi
  if [ "$need_group" = 1 ]; then note "- add $(id -un) to the input group (takes effect at your next login)"; fi
  # shellcheck disable=SC2016  # expanded by the root shell, from its arguments
  root sh -c '
    set -e
    if [ "$1" = 1 ]; then "$2" cap_sys_ptrace=ep "$3"; fi
    if [ "$4" = 1 ]; then
      printf "%s\n" "$5" > "$6"
      udevadm control --reload
      udevadm trigger --action=change --subsystem-match=input || true
      udevadm trigger --action=change --name-match=uinput || true
      udevadm settle || true
    fi
    if [ "$7" = 1 ]; then usermod -aG input "$8" || gpasswd -a "$8" input; fi' \
    sh "$need_cap" "$setcap" "$py" "$need_udev" "$UDEV_RULE_TEXT" "$UDEV_RULE" "$need_group" "$(id -un)" ||
    warn "Granting permissions failed or was refused; run this again to retry. $SUDO_HINT"
}

install_shortcut() {
  local apps
  apps=$(dirname "$DESKTOP_FILE")
  mkdir -p "$apps" "$(dirname "$BIN_LINK")"
  cat > "$DESKTOP_FILE" <<DESKTOP
[Desktop Entry]
Type=Application
Name=BonkScanner
Comment=Megabonk map reroll scanner, live stats and overlays (unofficial Linux port)
Exec="$DIR/run.sh"
Path=$DIR
Icon=$DIR/src/media/bonkscanner_icon2.png
Terminal=false
Categories=Game;
StartupWMClass=BonkScanner
Keywords=Megabonk;reroll;overlay;
DESKTOP
  if command -v update-desktop-database >/dev/null; then update-desktop-database -q "$apps" || true; fi
  if [ -L "$BIN_LINK" ] || [ ! -e "$BIN_LINK" ]; then ln -sfn "$DIR/run.sh" "$BIN_LINK"; fi
}

setup() {
  cd "$DIR"
  say "Setting up $DIR"
  ensure_prereqs
  exclude_private_python
  ensure_python
  build_venv
  grant_permissions
  if [ "$SHORTCUT" = 1 ]; then install_shortcut; fi

  local problems=0
  case $(ptrace_scope) in
    1|2) if ! has_ptrace_cap; then warn "No memory-read permission yet: the scanner cannot see the game. Run this again to grant it."; problems=1; fi ;;
    3) problems=1 ;;
  esac
  if ! input_access_ok; then
    problems=1
    if input_setup_done; then
      warn "Hotkeys and the reset key start working after you log out and back in."
    else
      warn "No keyboard-device access yet: hotkeys and the reset key will not work. Run this again to grant it."
    fi
  fi

  if [ "$problems" = 0 ]; then say "BonkScanner is ready."; else say "BonkScanner is installed, with the warnings above."; fi
  if [ "$SHORTCUT" = 1 ]; then
    if [ "$(command -v bonkscanner 2>/dev/null)" = "$BIN_LINK" ]; then
      note "Start Megabonk, then open BonkScanner from your application menu or run: bonkscanner"
    else
      note "Start Megabonk, then open BonkScanner from your application menu or run: $DIR/run.sh"
    fi
  else
    note "Start Megabonk, then run: $DIR/run.sh"
  fi
  note "To update, run the install command again. Settings and recordings live in $DIR"
}

uninstall() {
  say "Uninstalling BonkScanner"
  if [ -f "$DESKTOP_FILE" ]; then rm -f "$DESKTOP_FILE"; note "Removed the menu entry."; fi
  if [ -L "$BIN_LINK" ] && [ "$(readlink "$BIN_LINK")" = "$DIR/run.sh" ]; then rm -f "$BIN_LINK"; note "Removed $BIN_LINK."; fi
  if [ -f "$UDEV_RULE" ]; then
    note "Removing $UDEV_RULE (sudo)"
    # shellcheck disable=SC2016
    root sh -c 'rm -f "$1" && udevadm control --reload' sh "$UDEV_RULE" ||
      warn "Could not remove $UDEV_RULE."
  fi
  if [ -f "$DIR/src/main.py" ] && [ -d "$DIR/.git" ]; then
    local answer=n
    if (: </dev/tty) 2>/dev/null; then
      printf 'Also delete %s? It holds your config.json and stats recordings. [y/N] ' "$DIR" >/dev/tty
      read -r answer </dev/tty || answer=n
    fi
    case $answer in
      [yY]*) rm -rf "$DIR"; note "Deleted $DIR." ;;
      *) note "Kept $DIR (delete it yourself to remove everything)." ;;
    esac
  fi
}

# Everything runs from main, so bash has read the whole file before a git pull
# can rewrite it.
main() {
  PYTHON=${PYTHON:-}
  SHORTCUT=1
  PASS=()
  local dir="" action=install self here=""
  while [ $# -gt 0 ]; do
    case $1 in
      --dir) [ $# -ge 2 ] || die "--dir needs a path"; dir=$2; shift ;;
      --dir=*) dir=${1#--dir=} ;;
      --no-shortcut) SHORTCUT=0; PASS+=("$1") ;;
      --uninstall) action=uninstall ;;
      -h|--help) usage; exit 0 ;;
      *) usage >&2; die "Unknown option: $1" ;;
    esac
    shift
  done
  [ "$(id -u)" != 0 ] || die "Run this as your normal user, not root; it asks for sudo when it needs to."
  if has_logind; then UDEV_RULE_TEXT=$UDEV_RULE_UACCESS; else UDEV_RULE_TEXT=$UDEV_RULE_GROUP; fi
  if [ "$action" = install ] && [ "$(uname -m)" != x86_64 ]; then
    die "BonkScanner and Megabonk need an x86_64 PC; this machine is $(uname -m)."
  fi

  self=${BASH_SOURCE[0]:-}
  if [ -n "$self" ] && [ -f "$self" ]; then here=$(cd "$(dirname "$self")" && pwd); fi
  if [ -z "$dir" ] && [ -n "$here" ] && [ -f "$here/src/main.py" ]; then
    DIR=$here
    mode=setup
  else
    DIR=${dir:-${BONKSCANNER_DIR:-$(existing_install || echo "$DEFAULT_DIR")}}
    case $DIR in /*) ;; *) DIR=$PWD/$DIR ;; esac
    mode=bootstrap
  fi

  if [ "$action" = uninstall ]; then uninstall
  elif [ "$mode" = bootstrap ]; then bootstrap
  else setup
  fi
}

main "$@"
