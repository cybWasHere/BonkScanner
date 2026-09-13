"""Non-capturing Windows input state for click-through map marker gestures."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os


_NAMED_VK = {
    "backspace": 0x08,
    "return": 0x0D,
    "enter": 0x0D,
    "pause": 0x13,
    "pageup": 0x21,
    "pagedown": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "print": 0x2C,
    "insert": 0x2D,
    "delete": 0x2E,
    "mouse_middle": 0x04,
    "mouse4": 0x05,
    "mouse5": 0x06,
}
_MODIFIER_VK = {
    "shift": (0x10,),
    "ctrl": (0x11,),
    "alt": (0x12,),
    "win": (0x5B, 0x5C),
}


def virtual_key_for_token(token: str) -> int | None:
    normalized = str(token).strip().lower()
    if normalized in _NAMED_VK:
        return _NAMED_VK[normalized]
    if len(normalized) == 1 and normalized.isalnum():
        return ord(normalized.upper())
    if normalized.startswith("f") and normalized[1:].isdigit():
        number = int(normalized[1:])
        if 1 <= number <= 24:
            return 0x70 + number - 1
    return None


class WindowsMapMarkerInput:
    def __init__(self, user32=None) -> None:
        self._user32 = user32
        if self._user32 is None and os.name == "nt":
            self._user32 = ctypes.windll.user32

    def is_pressed(self, binding: str) -> bool:
        if self._user32 is None:
            return False
        parts = [part for part in str(binding).lower().split("+") if part]
        if not parts:
            return False
        base_vk = virtual_key_for_token(parts[-1])
        if base_vk is None or not self._vk_pressed(base_vk):
            return False
        for modifier in parts[:-1]:
            variants = _MODIFIER_VK.get(modifier)
            if not variants or not any(self._vk_pressed(vk) for vk in variants):
                return False
        return True

    def cursor_position(self) -> tuple[int, int]:
        if self._user32 is None:
            return (0, 0)
        point = wintypes.POINT()
        if not self._user32.GetCursorPos(ctypes.byref(point)):
            return (0, 0)
        return (int(point.x), int(point.y))

    def _vk_pressed(self, virtual_key: int) -> bool:
        return bool(self._user32.GetAsyncKeyState(int(virtual_key)) & 0x8000)


class LinuxMapMarkerInput:
    """The same two questions answered from evdev state and the X11 pointer.

    ``keyboard`` is the evdev backend (``infra.linux_keyboard.LinuxKeyboard``),
    which tracks pressed keys and mouse buttons; ``cursor`` is any callable
    returning the pointer position on the root window, by default the X11
    shim's ``GetCursorPos``.
    """

    _MODIFIER_NAMES = {
        "shift": ("left shift", "right shift"),
        "ctrl": ("left ctrl", "right ctrl"),
        "alt": ("left alt", "right alt"),
        "win": ("left windows", "right windows"),
    }

    def __init__(self, keyboard=None, cursor=None) -> None:
        self._keyboard = keyboard
        self._cursor = cursor
        if self._keyboard is None and os.name != "nt":
            from infra.keyboard_backend import load_keyboard

            self._keyboard = load_keyboard()
        if self._cursor is None and os.name != "nt":
            from infra.winapi import win32gui

            self._cursor = getattr(win32gui, "GetCursorPos", None)

    def is_pressed(self, binding: str) -> bool:
        if self._keyboard is None:
            return False
        parts = [part for part in str(binding).lower().split("+") if part]
        if not parts:
            return False
        try:
            if not self._keyboard.is_pressed(parts[-1]):
                return False
            for modifier in parts[:-1]:
                names = self._MODIFIER_NAMES.get(modifier, (modifier,))
                if not any(self._keyboard.is_pressed(name) for name in names):
                    return False
        except (ValueError, KeyboardInterrupt):
            return False
        except Exception:
            return False
        return True

    def cursor_position(self) -> tuple[int, int]:
        if self._cursor is None:
            return (0, 0)
        try:
            x, y = self._cursor()
        except Exception:
            return (0, 0)
        return (int(x), int(y))


def default_map_marker_input():
    """The platform's non-capturing input reader for map-marker gestures."""

    if os.name == "nt":
        return WindowsMapMarkerInput()
    return LinuxMapMarkerInput()
