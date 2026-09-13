# BonkScanner

> **Unofficial Linux port.** This fork adds native Linux support on the
> `linux-native` branch. It is not maintained, endorsed, or published by the
> BonkScanner project; the official app and its releases are at
> [ALuiell/BonkScanner](https://github.com/ALuiell/BonkScanner).
>
> **How it was made:** the port is vibecoded. The Linux backends, the offset
> table and the docs were written by Claude, an AI coding agent, directed by
> the fork owner, who ran and verified each step against the live game on
> KDE Plasma 6 (memory reads, rerolls, the in-game overlay and map markers).
> No human has reviewed the code line by line. Read it before you trust it,
> and expect rough edges on setups other than the one it was built on.

**BonkScanner** is a desktop tool for Megabonk reroll automation, live run inspection, saved-run review, OBS overlays, and Twitch chat integration. This branch runs it natively on Linux.
It observes the running game locally, evaluates each reset in real time, and can keep rerolling until a selected template or score tier is found.

## Install on Linux

The Linux port drives the native Linux build of Megabonk (`Megabonk.x86_64`)
and, with the same code, the Windows build running under Proton. Only the OS
glue differs from the Windows app: process memory is read through `/proc`,
hotkeys and the reset key go through `evdev`/`uinput`, windows are found
through X11, and the Twitch token lives in the desktop keyring.

1. Install Python 3.12+, `git`, and a C compiler with the Python headers
   (`python3-dev` and `gcc` on Debian/Ubuntu, `python3-devel` and `gcc` on
   Fedora; Arch has them with `base-devel`), which the `evdev` package is
   built with. Then:

   ```bash
   git clone https://github.com/ALuiell/BonkScanner.git
   cd BonkScanner
   ./start.sh
   ```

   `start.sh` creates `.venv`, installs the Linux requirements, and asks for
   `sudo` once to grant the venv's Python `CAP_SYS_PTRACE` (reading another
   process's memory is otherwise refused by the kernel's default
   `ptrace_scope`). Re-run it any time; it only installs what is missing.

2. Let your user read input devices and write `/dev/uinput`, which global
   hotkeys and the reset key need. Either add yourself to the `input` group and
   log in again, or install a udev rule that grants the active seat access:

   ```bash
   sudo tee /etc/udev/rules.d/71-bonkscanner-input.rules <<'RULES'
   SUBSYSTEM=="input", KERNEL=="event*", TAG+="uaccess"
   KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess"
   RULES
   sudo udevadm control --reload && sudo udevadm trigger --subsystem-match=input
   ```

3. Start the game, then `./start.sh` (or `.venv/bin/python3 src/main.py`).
   Use `./run_tests.sh` for the unit tests.

Notes for Linux:

- Works in X11 sessions and in Wayland sessions through XWayland: the game
  must be an X11 window (the native Unity build and Proton both are by
  default). A game forced onto native Wayland (`SDL_VIDEODRIVER=wayland`,
  `PROTON_ENABLE_WAYLAND=1`) is invisible to the window backend: memory
  reads still work, but focus detection and the in-game overlay do not.
- Verified on KDE Plasma 6. Other compositors stack the overlay above a
  fullscreen game only if they honour transient windows the same way.
- The Twitch token needs a Secret Service keyring (KWallet 6, GNOME
  Keyring, KeePassXC); without one the bot cannot remember its login.

- `PROCESS_NAME` in `config.json` defaults to `Megabonk.x86_64` on Linux. Set
  it to `Megabonk.exe` when the game runs under Proton; the memory offsets are
  chosen per binary automatically.
- The app runs Qt on X11 (`QT_QPA_PLATFORM=xcb`, also under Wayland through
  XWayland) so the in-game overlay can be placed over the game window. On KDE
  Plasma the overlay is made a transient of the game window so it stacks above
  it even when the game is fullscreen.
- Updating: see *Updates* below.

## Windows

The Windows app is the original project. Packaged builds, Windows setup
(`start.bat`, `run.bat`, `build_exe.bat`) and the auto-updater all live at
[ALuiell/BonkScanner](https://github.com/ALuiell/BonkScanner); this fork leaves
the Windows code paths untouched but does not ship or test Windows builds.

If BonkScanner is useful to you, the person to support is its author: a
Supporter Pack or monthly support on [Patreon](https://www.patreon.com/cw/ALuiel),
or a [crypto donation](https://aluiell.github.io/BonkScanner/).

## Safety Notes
BonkScanner is a local desktop tool. It does not modify Megabonk files on disk,
install game mods, or send gameplay data anywhere by default.

Some parts of the project use technical names, so here is what they mean:

- `Memory reads`: BonkScanner reads live values from the running Megabonk process
  to detect map state, player stats, items, weapons, tomes, banishes, damage
  sources, and run time. This is used for display, recording, scoring, overlays,
  and Twitch commands.
- `Standard restart`: the default restart mode sends the configured reset hotkey,
  similar to pressing it yourself.
- `OBS Overlay`: runs only on `127.0.0.1`, which means it is available from the
  same PC for OBS/browser sources, not from the public internet.
- `Twitch Bot`: only connects after you authorize it manually. Disconnecting
  removes the stored token and attempts to revoke it with Twitch.

## What The App Does
- rerolls maps automatically until the current map matches selected filters;
- supports two evaluation modes: `Templates` and `Scores`;
- applies active template and score-tier changes while the scan loop is running;
- shows session reroll stats and persistent total reroll tracking;
- reads live player stats, passive items, weapons, tomes, banishes, damage sources, level, kills, and run time from the running game;
- records live stat snapshots into saved `.jsonl` recordings with timeline playback;
- tracks stage summaries for live runs and recordings, including time, kills, and item gains per stage;
- compares saved runs side by side with synced in-game time and configurable diff sections;
- serves a local OBS browser overlay with draggable/resizable widgets and widget-specific URLs;
- provides a transparent in-game overlay with status, KPS, powerups, Luck,
  stats, event-timer, timed-item cooldown, and build-progression widgets;
- runs an optional Twitch chat bot with live stat commands and stage announcements;
- uses the configured keyboard reset hotkey for run restarts;
- stores app settings, templates, score rules, overlay settings, Twitch bot settings, and update preferences in `config.json`.

## Main UI Areas

### Left Side
- `Templates`: strict rule-based filtering with selectable active templates.
- `Scores`: weighted score evaluation with selectable target tiers and a dedicated scores settings dialog.

### Right Side
- `Logs`: scanner activity, warnings, wait states, and result messages.
- `Session Stats`: session time, reroll count, RPM, best and worst maps, tracked item counters, and averages per target.
- `Live Stats`: current run stats, items, weapons, tomes, Chaos Tome data, banishes, damage sources, stage summary, powerups, and recording controls.
- `Recordings`: saved recording viewer with timeline, Chaos Tome data, rename, delete, cleanup, and in-run compare tools.
- `Compare Runs`: side-by-side comparison of two saved recordings with synced in-game time, Chaos Tome diffs, and a central difference panel.
- `OBS Overlay`: local browser-source overlay controls for streaming layouts.
- `Twitch Bot`: built-in Twitch IRC bot controls and command settings.
- `In-Game Overlay`: transparent desktop widgets and Full Map activity markers.

## How Scanning Works
1. BonkScanner connects to the running game locally.
2. It reads the map-ready state, interactable counters, seeds, and other runtime values needed for scanning.
3. Runtime values are evaluated by the active `Templates` or `Scores` mode.
4. If the map does not match, the app restarts the run.
5. Before accepting a snapshot, the scanner waits for a stable ready-state so transient map-load reads are less likely.

The scan hotkey also has a late-run safeguard. If a Forest or Desert run is
already past Tier 1, pressing the configured scan hotkey leaves auto-reroll off
and writes a visible warning instead of resetting the run. Tier 1 and Graveyard
are unaffected, and the safeguard does not change the game's normal manual `R`
input.

## Evaluation Modes

### Templates Mode
Use strict requirements such as:
- `S+M`
- `Microwaves`
- `Boss Curses`
- `Shady Guy`
- `Moais`

The built-in template manager lets you:
- create custom templates;
- edit template values inline;
- enable only the templates you want the scanner to stop on;
- delete custom templates.

### Scores Mode
Use weighted scoring instead of hard requirements.

Current score configuration supports:
- signed Shrine Points for Moais, Shady Guys, Boss Curses, Magnet Shrines, and
  Challenges (positive rewards, zero has no effect, negative penalizes);
- microwave multipliers;
- auto-calculated or manual score thresholds;
- active target tiers: `Light`, `Good`, `Perfect`, `Perfect+`.

Positive Magnet points count at most two Magnet Shrines; negative Magnet points
penalize every Magnet Shrine. Automatic thresholds scale from positive Shrine
Points only, so increasing a penalty never lowers the target score.

The active left-side tab decides which evaluation mode is currently used.

## Live Stats And Recordings

### Session Stats
The `Session Stats` tab shows:
- session time, reroll count, and rerolls per minute;
- best and worst map found during the current session;
- average rerolls per target;
- configurable `Tracked Items` counters for live item gains.

By default, `Tracked Items` tracks `Anvils Map 1`. Use the small settings button
on that card to search for an item, choose `Map 1 only` when needed, and add or
remove tracked rules. `Map 1 only` counts gains observed during stage 1 only.

### Live Stats
The `Live Stats` tab shows:
- grouped player stat cards;
- passive items with rarity highlighting, sorting, and total item count;
- average chests per minute;
- in-game timer;
- mob kill count with thousands separators;
- player level;
- `Stage Summary` with per-stage time, kills, and gained item counts;
- a live `Powerups` summary;
- `Banishes`;
- current weapons with level and upgraded stats;
- current tomes with level and active effects;
- Chaos Tome tracking when available;
- Charge Shrine and character-passive tracking when available, including Dice
  Gamba rolls;
- damage sources when available.

`Live Stats` does not require recording. Recording only saves snapshots for later
playback and comparison.

Passive item reads use the normal passive inventory path first and fall back to
the main `PlayerInventory.ItemInventory` path when needed. This helps with runs
where items were added by mods or external tools.

If some live sections temporarily show unavailable data, that is not always an
error. During loading screens, some game memory pointers may not be ready yet.

### Recording
The built-in recorder can:
- start and stop from the UI or a hotkey;
- auto-start when a live run is detected, if enabled;
- save snapshots at a configurable interval;
- include run seed metadata when available;
- automatically stop if the run seed disappears and stays unavailable;
- automatically continue into a new file when a truly new run is detected;
- keep one recording together across normal stage transitions even if the map seed changes.

`Snapshot Interval (s)` in `Settings` controls how often `Live Stats` recording
saves a snapshot. Shorter intervals make the recording timeline, segment compare,
and saved-run review more precise, but create more snapshots. Longer intervals
keep recordings lighter, but changes between snapshots are captured less exactly.

### Saved Recordings
Recordings are stored in `stats_recordings\` as `.jsonl` files and can be:
- reviewed with a timeline slider;
- inspected for stats, items, weapons, tomes, Chaos Tome data, stage summary, damage sources, and banishes;
- compared against an earlier snapshot from the same recording;
- renamed in-app, including the actual file name on disk;
- deleted individually;
- batch-cleaned by minimum snapshot count.

Legacy recordings from `vods\` are still read when present.
The current writer uses recording format version `10`; loaders keep compatibility
with older supported formats and treat newer fields as optional when replaying
legacy files.

## Compare Runs
`Compare Runs` loads two saved recordings side by side as `Run A` and `Run B`.
This is useful for checking how two runs diverged at the same in-game time.

It supports:
- guided first selection when no runs are selected yet;
- swapping selected runs;
- synced snapshot comparison by nearest in-game time;
- configurable stat selection;
- optional diff sections for stats, stage summary, items, weapons, tomes, and Chaos Tome data;
- item detail comparison for gained, broken, and lost items.

## OBS Overlay
`OBS Overlay` runs a local browser-source overlay server for stream layouts.

Default overlay URL:

```text
http://127.0.0.1:17845/overlay
```

The server binds to `127.0.0.1`, so it is intended for the same PC only.
Recording is not required; the overlay uses live stats reads.

Overlay features:
- transparent browser page for OBS;
- selectable widgets for `Stage Summary`, `Tracked Items`, `Stats`, `Banishes`, `KPS`, `Luck Rarity`, and `Build Progression`;
- tracked item rules, including map-1-only tracking;
- widget-specific URLs such as `/overlay/stats`, `/overlay/banishes`, `/overlay/tracked_items`, `/overlay/stage_summary`, `/overlay/kps`, `/overlay/luck_rarity`, and `/overlay/build_progression`;
- visual layout editor at `/overlay?edit=true`;
- draggable widget positions;
- per-widget scaling;
- widget resizing;
- configurable canvas width and height for matching OBS source dimensions;
- game preview background in edit mode only.

If OBS keeps showing an old layout after an update, refresh the browser source
cache from the OBS source properties.

## In-Game Overlay

`In-Game Overlay` is a transparent, click-through desktop overlay aligned to
the game window. It needs neither OBS nor recording. Enable it from its tab,
optionally enable auto-start, then use **Edit Layout** or the configured edit
hotkey (F9 by default) to position widgets.

Available widgets are Scanner status, Recording status, KPS, Active powerups,
Luck rarity %, Stats, Event timer, Item cooldowns, and Build Progression. The timed-item widget
currently supports Bob's Light, hides when no supported item is held, and
correctly freezes while the game is paused.

`Map Activity Markers` are a separate Full Map-anchored layer inside the
in-game overlay. They appear only while the game's Full Map is open, support
manual marker hotkeys, and can optionally add supported nearby activities after
the game selects them through its normal interaction system. Automatic
discovery is off by default.

## Twitch Bot
The `Twitch Bot` tab runs a built-in Twitch IRC chat bot for the configured channel.

Basic setup:
1. Open the `Twitch Bot` tab.
2. Click `Connect to Twitch`.
3. Authorize through the browser.
4. Configure target channel, access tier, cooldowns, enabled commands, and announcements.
5. Click `Start Bot`.

By default, `Target Channel` uses the authorized Twitch account. If you authorize
a separate bot account, set `Target Channel` to the streamer channel where the
bot should join and respond.

Available chat commands:
- `!stats` / `!bonkstats`: current selected live stats.
- `!session`: session stats summary (reroll count, match rate, best/worst maps, tracked item counters).
- `!bans` / `!banishes`: banished items.
- `!disabled`: lists highlighted items globally disabled in lobby.
- `!items` / `!tracked`: collected items, sorted by rarity and compressed when needed.
- `!weapons`: current weapons and upgraded stats.
- `!tomes`: current tomes and values.
- `!chaos` / `!chaostome`: tracked Chaos Tome level and stat roll totals.
- `!dice`: accumulated Dice Gamba bonuses and tracked rolls.
- `!shrines`: accumulated Charge Shrine stat bonuses.
- `!stages`: stage summary.
- `!powerups`: active powerup duration info.
- `!kps`: current and average kill rate metrics.
- `!build`: active build checklist progress and missing requirements.
- `!luck`: item rarity drop chances and expected counts based on current Luck.
- `!chests` / `!chest`: displays per-stage and total chest progress, paid openings, actual and expected Key procs, inherently free chests, and the current Key proc chance. The same data is arranged as six readable rows in the sixth Stats card and saved in recordings.
- `!scanner`: general info about the BonkScanner app and download link.
- `!presets` / `!preset`: active templates or score tiers and weights.
- `!bonkhelp` / `!bonkcmds` / `!bonkcommands` / `!bhelp`: list of all active Twitch bot commands.

Command settings support:
- access tiers: `Everyone`, `Mods & VIPs`, `Subs & Mods`;
- global and per-command cooldowns;
- per-command enable toggles;
- selected stats for `!stats`;
- customizable response templates;
- automatic stage transition announcements.
- an opt-in `Announce The One Ring` option with separate first-pickup and
  duplicate phrase pools; it is off by default and works on every map.

OAuth tokens are stored through the app's credential helper when available.
Disconnecting removes the stored token and attempts to revoke it with Twitch.

## Settings
The main `Settings` dialog currently includes:
- `Scan Hotkey`
- `Reset Hotkey`
- `Record Hotkey`
- `In-Game Overlay Edit Hotkey`
- `Auto-start recording`
- `Stop scanning when player moves`
- `Show OBS reminder on Start Scanner`
- `Reset Hold Duration (s)`
- `Safety Margin (s)` (advanced)
- derived Megabonk `quick_reset_time` preview
- `Snapshot Interval (s)`
- `Check for Updates`

Notes:
- `Reset Hotkey` and `Reset Hold Duration` control the community restart path;
- close Megabonk before changing Reset Speed; the game reads this value on its next start;
- `Safety Margin` is editable in Settings (`0.00` to `1.00`, default `0.05`). The effective scanner minimum is Megabonk's `0.01` minimum plus the selected margin; there is no separate `0.10` scanner floor;
- every Settings save verifies the scanner config and synchronizes and verifies the game's `quick_reset_time`, even when the reset field itself did not change, so hand-edited drift is repaired;
- if either config cannot be saved or verified, Settings stays open, keeps the last known-good runtime values, and shows the exact reason;
- global hotkeys and keyboard-driven restart need input-device access on Linux (see *Install on Linux*) and may require Administrator privileges on Windows.

## Updates

A source checkout updates with `git pull`. The in-app updater belongs to the
upstream packaged Windows build: it checks the `ALuiell/BonkScanner` releases and
downloads a `.exe`, so on Linux it does nothing useful and can be ignored.

After a Megabonk update the game's IL2CPP layout may change. Run
`tools/verify_type_info.py` with the game open; it reports which classes in
`src/infra/memory/offsets.py` no longer resolve and, given an Il2CppDumper
`script.json` for the new `GameAssembly.so`, prints the replacement addresses.

## Dependencies

Runtime dependencies are listed in `src/requirements.txt` with platform markers.

Everywhere:
- `PySide6>=6.8.0`
- `requests~=2.33.1`
- `colorama==0.4.6`

Linux:
- `evdev>=1.7.0` - global hotkeys and the reset key (needs a C compiler and Python headers to install)
- `python-xlib>=0.33` - game window lookup, focus and geometry through X11 / XWayland
- `keyring>=25.0` - Twitch token storage through the Secret Service (KWallet, GNOME Keyring, KeePassXC)

Windows only, unused here: `pymem`, `keyboard`, `pywin32`.

## Manual Developer Setup

`start.sh` does all of this; by hand it is:

```bash
python3 -m venv --copies .venv
.venv/bin/python3 -m pip install --upgrade pip
.venv/bin/python3 -m pip install -r src/requirements.txt
sudo setcap cap_sys_ptrace=ep "$(readlink -f .venv/bin/python3)"
.venv/bin/python3 src/main.py
```

The `setcap` step has to be repeated whenever `.venv` is rebuilt. Qt is started
on the `xcb` platform by default; set `QT_QPA_PLATFORM` yourself to override.

## Project Structure
- `src/main.py` - desktop app entry point.
- `src/gui_app.py` - PySide6 application class and top-level app wiring.
- `src/ui/layout.py` - main UI layout, tabs, and shared UI sections.
- `src/gui_scanner.py` - scanner loop, hotkeys, lifecycle, and shutdown flow.
- `src/gui_run_control.py` - run restart mode UI and provider coordination.
- `src/ui/tabs/player_stats/` - live stats, recordings, and snapshot UI.
- `src/gui_overlay.py` - OBS overlay controls and overlay state refresh.
- `src/ui/tabs/twitch/` - Twitch bot controls and announcement settings.
- `src/ui/dialogs/` - settings, help, score, template, update and Twitch dialogs.
- `src/ui/styles.py` - Qt stylesheet helpers. Item rarity colours now live in
  `src/core/item_metadata.py` and the item sort modes in `src/projections/item_sort.py`.
- `src/app/config.py` - app config, game config integration, templates, scores, overlay, Twitch, and compare settings.
- `src/core/logic.py` - template and score evaluation logic.
- `src/infra/memory/game_data_client.py` - map-ready state, counters, seed-related runtime reads, and scan data.
- `src/infra/memory/reader.py` - low-level memory helpers over `pymem` (Windows) or `linux_process.py`.
- `src/infra/memory/linux_process.py` - Linux process lookup, module bases and reads through `/proc` and `process_vm_readv`.
- `src/infra/memory/offsets.py` - IL2CPP type-info addresses per game binary (Windows `.dll`, Linux `.so`).
- `src/infra/linux_keyboard.py` and `src/infra/keyboard_backend.py` - evdev/uinput hotkeys and key injection, selected per platform.
- `src/infra/x11_windows.py` and `src/infra/winapi.py` - the `win32gui` call surface implemented over X11, selected per platform.
- `tools/verify_type_info.py` - checks the offsets table against the running game.
- `src/infra/memory/player_stats_client.py` - live player stats, passive items, weapons, tomes, banishes, damage sources, and chest-rate calculations.
- `src/infra/memory/map_marker_client.py` - Full Map projection, map/player/stage identity, and opt-in nearby activity discovery.
- `src/app/refresh_coordinator.py`, `src/app/read_sources.py`, and `src/app/refresh_tasks.py` - demand-driven memory-read scheduling and per-tick read sharing.
- `src/app/map_marker_tracker.py` - latest-wins Full Map marker worker and marker lifecycle.
- `src/core/tracker/live_run.py` - thread-safe live run tracking and runtime snapshots for overlays and Twitch.
- `src/projections/obs.py` - builds the OBS overlay payload from a tracker snapshot.
- `src/projections/in_game.py` and `src/projections/in_game_html.py` - project and render the in-game overlay.
- `src/infra/overlay_server.py` - local HTTP server for OBS/browser overlay pages.
- `src/twitch_auth.py` - local Twitch OAuth flow.
- `src/twitch_bot.py` - Twitch IRC bot worker and command handlers.
- `src/infra/twitch_credentials.py` - Twitch token storage helpers.
- `src/infra/vod_storage.py` - saved recording format, metadata cache, load, rename, and cleanup helpers.
- `src/core/run_summary.py` - recording and compare summary helpers.
- `src/core/run_control.py` and `src/infra/keyboard_run_control.py` - restart port and keyboard adapter.
- `src/app/update_flow.py` and `src/infra/updater.py` - packaged-build update checks and application flow.
- `src/tests` - unit tests.
- `src/media/overlay` - browser overlay HTML, CSS, JS, and preview asset.
- `src/media/help` - in-app help text in English, Ukrainian, and Russian.

## Developer Validation

```bash
./run_tests.sh              # whole suite
./run_tests.sh test_linux_backends   # one module
```

On Linux a handful of upstream tests fail by design: the Windows-only updater
and `ctypes.windll` tests, tests that assert Windows font metrics in Qt layouts,
and two that format numbers with the system locale. Everything else, including
the Linux backend tests, must pass.

## Basic Usage
1. Start Megabonk and wait until the target scene is loaded.
2. Run `./start.sh` (first run installs everything and asks for `sudo` once).
3. Choose `Templates` or `Scores`.
4. Configure your filters, score tiers, and optional recording/overlay/Twitch settings.
5. Press `Start`.
6. Press the scan hotkey in-game to arm or pause the scanning loop.
7. When a matching map is found, the app stops and logs the result.

BonkScanner is meant to reduce repetition, speed up rerolling, and make target hunting less frustrating while also giving streamers and run reviewers better live data.

## License

Copyright (C) 2026 Aluiel and BonkScanner contributors.

BonkScanner's original source code and documentation in this repository are
licensed under the **GNU General Public License, version 3 only**
(`GPL-3.0-only`). You may use, study, modify, and redistribute the covered
work under the terms of the [LICENSE](LICENSE) file. Distributed modified
versions must preserve the same license and make their corresponding source
available as required by GPLv3.

The GPL does not grant permission to use the BonkScanner name or original
project logo in a way that suggests an unofficial build is maintained,
endorsed, or published by the BonkScanner project. Official hosted services,
supporter keys, and accounts are separate from the licensed client source.

Bundled dependencies and third-party names, logos, and other assets remain
subject to their respective licenses and owners' rights. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
