<div align="center">

# BonkScanner · Linux

**Megabonk map rerolling, live run stats, OBS and in-game overlays, a Twitch bot.**<br>
Native on Linux. Any distro. One command.

[![Linux](https://img.shields.io/badge/platform-linux-1793d1?logo=linux&logoColor=white)](#install)
[![Unofficial port](https://img.shields.io/badge/status-unofficial%20port-orange)](#the-fine-print)
[![Upstream](https://img.shields.io/badge/upstream-ALuiell%2FBonkScanner-181717?logo=github)](https://github.com/ALuiell/BonkScanner)
[![Sync and test](https://github.com/cybWasHere/BonkScanner/actions/workflows/upstream-sync.yml/badge.svg?branch=linux-native)](https://github.com/cybWasHere/BonkScanner/actions/workflows/upstream-sync.yml)
[![GPL-3.0](https://img.shields.io/badge/license-GPL--3.0-3da639)](LICENSE)

</div>

> Unofficial, vibecoded port of [ALuiell/BonkScanner](https://github.com/ALuiell/BonkScanner).
> Not endorsed by upstream, and nobody has reviewed the code line by line. [The fine print.](#the-fine-print)

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/cybWasHere/BonkScanner/linux-native/install.sh | bash
```

Start Megabonk, then open **BonkScanner** from your app menu or run `bonkscanner`.
The same command updates. It asks for your password up to twice: once for
missing packages, once for the permissions below.

| Flag (after `bash -s --`) | |
|---|---|
| `--dir DIR` | install somewhere other than `~/.local/share/bonkscanner` |
| `--no-shortcut` | no menu entry, no `bonkscanner` command |
| `--uninstall` | remove it; asks before deleting the folder with your config and recordings |

`PYTHON=/usr/bin/python3.12` builds on an interpreter of your own (3.11+) instead of the bundled one.

<details>
<summary><b>What the installer does</b> &nbsp;·&nbsp; <a href="install.sh">read it first if you like</a></summary>
<br>

- installs whatever is missing of `git`, `curl`, `setcap` and the libraries Qt needs (pacman, apt, dnf or zypper);
- clones this fork to `~/.local/share/bonkscanner`, or pulls if it is already there;
- ships a private Python 3.13 ([uv](https://github.com/astral-sh/uv) standalone build) and builds `.venv` on it, so your distro's Python never matters and no compiler is needed;
- grants that Python `CAP_SYS_PTRACE`, without which the kernel refuses to let it read the game's memory;
- installs `/etc/udev/rules.d/71-bonkscanner-input.rules` so your session can read keyboards and write `/dev/uinput` for global hotkeys and the reset key (falls back to the `input` group without logind/elogind);
- adds the application-menu entry and `~/.local/bin/bonkscanner`.

</details>

## How it works

Same app as upstream, with the operating-system layer swapped out underneath.

| | Windows | Linux |
|---|---|---|
| Game memory | pymem | `/proc` maps + `process_vm_readv` |
| Hotkeys, reset key | keyboard | evdev / uinput |
| Game window, overlay | win32gui | X11 / XWayland |
| Twitch token | Credential Manager | Secret Service keyring |

It drives the native `Megabonk.x86_64` and the Windows build under Proton alike;
memory offsets are picked per binary (`.so` or `.dll`), so `PROCESS_NAME` in
`config.json` can stay at `Megabonk.exe`.

## Good to know

- **X11 or XWayland.** The game must be an X11 window, which Unity's native build and Proton both are by default. Forced onto native Wayland (`SDL_VIDEODRIVER=wayland`, `PROTON_ENABLE_WAYLAND=1`) it becomes invisible to the window backend: memory reads still work, focus detection and the in-game overlay do not.
- **Verified on KDE Plasma 6.** The in-game overlay is made a transient of the game window so it stacks above fullscreen; other compositors cooperate only if they honour transients the same way.
- **Twitch needs a keyring** (KWallet 6, GNOME Keyring, KeePassXC), or the bot cannot remember its login.
- **Ignore the in-app updater.** It belongs to upstream's packaged Windows build and downloads an `.exe`. Update by rerunning the install command.
- **After a Megabonk update**, run `tools/verify_type_info.py` with the game open. It reports which classes in `src/infra/memory/offsets.py` no longer resolve and, given an Il2CppDumper `script.json` for the new `GameAssembly.so`, prints the replacement addresses.

## Everything else

Templates, scores, recordings, run comparison, the OBS and in-game overlays,
the Twitch commands, settings: all of it is upstream's work and documented in
[upstream's README](https://github.com/ALuiell/BonkScanner#readme) and the
in-app help. This fork leaves the Windows code untouched but does not ship or
test Windows builds.

<details>
<summary><b>Developing</b></summary>
<br>

```bash
git clone -b linux-native https://github.com/cybWasHere/BonkScanner.git
cd BonkScanner
./start.sh                            # set up this checkout in place and launch (./install.sh: set up only)
./run_tests.sh                        # whole suite
./run_tests.sh test_linux_backends    # one module
```

The Linux-specific code is `src/infra/memory/linux_process.py`,
`src/infra/linux_keyboard.py`, `src/infra/x11_windows.py`, the LINUX table in
`src/infra/memory/offsets.py` and `tools/verify_type_info.py`. A handful of
upstream tests fail on Linux by design (the Windows updater, `ctypes.windll`,
Windows font metrics, locale number formatting); the Linux backend tests must pass.

By hand: `python3 -m venv --copies .venv`, install `src/requirements.txt` into
it, then `sudo setcap cap_sys_ptrace=ep "$(readlink -f .venv/bin/python3)"`
(again whenever `.venv` is rebuilt). Qt starts on `xcb`; set `QT_QPA_PLATFORM`
to override.

</details>

## The fine print

**Unofficial and vibecoded.** This fork is not maintained, endorsed or published
by the BonkScanner project. The Linux backends, the offset table and these docs
were written by Claude, an AI coding agent, directed by the fork owner, who ran
and verified each step against the live game on KDE Plasma 6. No human has
reviewed the code line by line. Read it before you trust it, and expect rough
edges on setups other than the one it was built on.

**Thank you, [Aluiel](https://github.com/ALuiell).** Everything this tool does,
from the memory reading to the overlays and the Twitch bot, is his work; this
fork only swaps the operating-system layer. If BonkScanner saves you time,
support the person who built it: [Patreon](https://www.patreon.com/cw/ALuiel)
or a [crypto donation](https://aluiell.github.io/BonkScanner/).

**License.** GPL-3.0-only, © 2026 Aluiel and BonkScanner contributors; see
[LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). The
GPL grants no right to use the BonkScanner name or logo in a way that suggests
an unofficial build is official. This one is not.
