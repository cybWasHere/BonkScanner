"""The global-keyboard backend for the current platform.

Windows uses the third-party ``keyboard`` package.  Linux uses
``infra.linux_keyboard``, which offers the same functions on top of evdev and
uinput without needing root.  ``load_keyboard()`` returns a module-like object
with ``hook``, ``add_hotkey``, ``press``, ``release``, ``press_and_release``,
``parse_hotkey`` and ``key_to_scan_codes``, or ``None`` when the dependency is
missing; ``keyboard_dependency_hint()`` says what to install in that case.
"""

from __future__ import annotations

from typing import Any

from infra.platform import IS_WINDOWS

_UNLOADED = object()
_keyboard: Any = _UNLOADED


def load_keyboard() -> Any | None:
    global _keyboard
    if _keyboard is not _UNLOADED:
        return _keyboard
    loaded: Any | None
    if IS_WINDOWS:
        try:
            import keyboard as loaded  # type: ignore[no-redef]
        except ImportError:
            loaded = None
    else:
        try:
            from infra.linux_keyboard import LinuxKeyboard

            loaded = LinuxKeyboard()
        except ImportError:
            loaded = None
    _keyboard = loaded
    return loaded


def keyboard_dependency_hint() -> str:
    if IS_WINDOWS:
        return "Install it with: pip install keyboard"
    return "On Linux the backend is python-evdev: pip install evdev (start.sh does this)."


def reset_for_tests() -> None:
    global _keyboard
    _keyboard = _UNLOADED


__all__ = ["keyboard_dependency_hint", "load_keyboard", "reset_for_tests"]
