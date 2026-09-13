"""Linux implementation of the subset of the ``keyboard`` package BonkScanner uses.

The Windows build talks to the third-party ``keyboard`` module: global hooks
through a low-level keyboard hook, and key injection through ``keybd_event``.
On Linux that module insists on running as root, so this module offers the
same surface on top of ``evdev`` (reading ``/dev/input/event*``) and
``uinput`` (a virtual keyboard for injection).  Both are kernel-level, so they
work under X11, Wayland, and for games running under Proton alike.

Surface implemented (see ``infra.hotkeys`` and ``infra.keyboard_run_control``):

* ``key_to_scan_codes(name)`` and ``parse_hotkey(hotkey)`` with the
  ``keyboard`` package's shapes: a hotkey is a tuple of steps, a step a tuple
  of keys, a key a tuple of alternative scan codes.
* ``hook(callback)`` / ``add_hotkey(hotkey, callback)`` returning removers.
* ``press`` / ``release`` / ``press_and_release`` / ``is_pressed``.

Scan codes are Linux evdev key codes (``KEY_F6`` is 64), which is also what the
``keyboard`` package reports on Linux.

Permissions: reading needs the input devices to be readable by the user (the
``input`` group, or a udev rule tagging ``event*`` with ``uaccess``) and
injection needs write access to ``/dev/uinput``.  Both failures raise with a
message that says which one is missing.
"""

from __future__ import annotations

import selectors
import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable

try:  # pragma: no cover - exercised on Linux only
    import evdev
    from evdev import ecodes
except ImportError:  # pragma: no cover
    evdev = None
    ecodes = None


VIRTUAL_DEVICE_NAME = "BonkScanner virtual keyboard"

# ``keyboard``-style names that do not map to ``KEY_<UPPER>`` directly.  Values
# are evdev key names without the ``KEY_`` prefix; a tuple lists alternatives
# (any of them satisfies the key).
_NAME_ALIASES: dict[str, str | tuple[str, ...]] = {
    "esc": "ESC",
    "escape": "ESC",
    "enter": "ENTER",
    "return": "ENTER",
    "space": "SPACE",
    " ": "SPACE",
    "tab": "TAB",
    "backspace": "BACKSPACE",
    "delete": "DELETE",
    "del": "DELETE",
    "insert": "INSERT",
    "ins": "INSERT",
    "home": "HOME",
    "end": "END",
    "page up": "PAGEUP",
    "pageup": "PAGEUP",
    "page down": "PAGEDOWN",
    "pagedown": "PAGEDOWN",
    "up": "UP",
    "down": "DOWN",
    "left": "LEFT",
    "right": "RIGHT",
    "shift": ("LEFTSHIFT", "RIGHTSHIFT"),
    "left shift": "LEFTSHIFT",
    "right shift": "RIGHTSHIFT",
    "ctrl": ("LEFTCTRL", "RIGHTCTRL"),
    "control": ("LEFTCTRL", "RIGHTCTRL"),
    "left ctrl": "LEFTCTRL",
    "right ctrl": "RIGHTCTRL",
    "alt": ("LEFTALT", "RIGHTALT"),
    "left alt": "LEFTALT",
    "right alt": "RIGHTALT",
    "alt gr": "RIGHTALT",
    "altgr": "RIGHTALT",
    "windows": ("LEFTMETA", "RIGHTMETA"),
    "win": ("LEFTMETA", "RIGHTMETA"),
    "super": ("LEFTMETA", "RIGHTMETA"),
    "left windows": "LEFTMETA",
    "right windows": "RIGHTMETA",
    "menu": "COMPOSE",
    "caps lock": "CAPSLOCK",
    "capslock": "CAPSLOCK",
    "num lock": "NUMLOCK",
    "scroll lock": "SCROLLLOCK",
    "print screen": "SYSRQ",
    "pause": "PAUSE",
    "-": "MINUS",
    "=": "EQUAL",
    "[": "LEFTBRACE",
    "]": "RIGHTBRACE",
    ";": "SEMICOLON",
    "'": "APOSTROPHE",
    "`": "GRAVE",
    "\\": "BACKSLASH",
    ",": "COMMA",
    ".": "DOT",
    "/": "SLASH",
    "plus": "KPPLUS",
    "minus": "MINUS",
    # Mouse buttons, named as the map-marker bindings spell them.
    "mouse_left": "BTN_LEFT",
    "mouse_right": "BTN_RIGHT",
    "mouse_middle": "BTN_MIDDLE",
    "mouse4": "BTN_SIDE",
    "mouse5": "BTN_EXTRA",
}


class KeyboardAccessError(PermissionError):
    """Raised when input devices or uinput cannot be opened."""


@dataclass(frozen=True)
class KeyboardEvent:
    """Mirror of ``keyboard.KeyboardEvent`` for the fields BonkScanner reads."""

    event_type: str  # "down" or "up"
    scan_code: int
    name: str
    time: float


def _normalize_name(name: str) -> str:
    return " ".join(str(name).strip().lower().split())


def key_to_scan_codes(name: str | int) -> tuple[int, ...]:
    """Return the evdev key codes a ``keyboard``-style key name may mean."""

    if ecodes is None:
        raise RuntimeError("python-evdev is not installed.")
    if isinstance(name, int):
        return (int(name),)
    normalized = _normalize_name(name)
    if not normalized:
        raise ValueError("Key name must not be empty.")

    alias = _NAME_ALIASES.get(normalized)
    candidates: tuple[str, ...]
    if alias is None:
        if len(normalized) == 1 and normalized.isalnum():
            candidates = (normalized.upper(),)
        elif normalized.startswith("f") and normalized[1:].isdigit() and 1 <= int(normalized[1:]) <= 24:
            candidates = ("F" + normalized[1:],)
        else:
            candidates = (normalized.upper().replace(" ", ""),)
    elif isinstance(alias, tuple):
        candidates = alias
    else:
        candidates = (alias,)

    scan_codes: list[int] = []
    for candidate in candidates:
        attribute = candidate if candidate.startswith("BTN_") else "KEY_" + candidate
        code = getattr(ecodes, attribute, None)
        if isinstance(code, int):
            scan_codes.append(code)
    if not scan_codes:
        raise ValueError(f"Key name is not recognized: {name!r}")
    return tuple(scan_codes)


def parse_hotkey(hotkey: str) -> tuple[tuple[tuple[int, ...], ...], ...]:
    """``"ctrl+f6, r"`` -> ``(((29, 97), (64,)), ((19,),))``."""

    steps: list[tuple[tuple[int, ...], ...]] = []
    for step in str(hotkey).split(","):
        keys = [part for part in (key.strip() for key in step.split("+")) if part]
        if not keys:
            raise ValueError(f"Hotkey step must contain at least one key: {hotkey!r}")
        steps.append(tuple(key_to_scan_codes(key) for key in keys))
    if not steps:
        raise ValueError("Hotkey must not be empty.")
    return tuple(steps)


def scan_code_name(scan_code: int) -> str:
    if ecodes is None:
        return str(scan_code)
    raw = ecodes.KEY.get(int(scan_code), "")
    if isinstance(raw, (list, tuple)):
        raw = raw[0] if raw else ""
    return str(raw).removeprefix("KEY_").lower()


def _looks_like_keyboard(device: "evdev.InputDevice") -> bool:
    try:
        capabilities = device.capabilities(verbose=False)
    except OSError:
        return False
    keys = set(capabilities.get(ecodes.EV_KEY, ()))
    return ecodes.KEY_ESC in keys or ecodes.KEY_ENTER in keys or ecodes.KEY_F6 in keys


def _looks_like_keyboard_or_mouse(device: "evdev.InputDevice") -> bool:
    """Keyboards plus pointing devices, so mouse-button bindings are seen too.

    Motion events are discarded unread by the listener; only EV_KEY matters.
    """

    if _looks_like_keyboard(device):
        return True
    try:
        capabilities = device.capabilities(verbose=False)
    except OSError:
        return False
    keys = set(capabilities.get(ecodes.EV_KEY, ()))
    return ecodes.BTN_LEFT in keys


class LinuxKeyboard:
    """``keyboard``-compatible facade over evdev and uinput.

    A single listener thread reads every keyboard-like input device and fans
    events out to hook callbacks and hotkey bindings, on that thread -- the
    same contract as the ``keyboard`` package.  Devices are rescanned every few
    seconds so a keyboard plugged in later is picked up.
    """

    RESCAN_SECONDS = 5.0

    def __init__(self, *, device_filter: Callable[[object], bool] | None = None) -> None:
        if evdev is None:
            raise RuntimeError("python-evdev is not installed; run start.sh again.")
        self._device_filter = device_filter or _looks_like_keyboard_or_mouse
        self._lock = threading.RLock()
        self._hooks: list[Callable[[KeyboardEvent], None]] = []
        self._hotkeys: list[tuple[tuple[tuple[tuple[int, ...], ...], ...], Callable[[], None]]] = []
        self._pressed: set[int] = set()
        self._devices: dict[str, evdev.InputDevice] = {}
        self._selector: selectors.DefaultSelector | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._uinput: evdev.UInput | None = None

    # -- ``keyboard`` API ----------------------------------------------------

    key_to_scan_codes = staticmethod(key_to_scan_codes)
    parse_hotkey = staticmethod(parse_hotkey)

    def hook(self, callback: Callable[[KeyboardEvent], None]) -> Callable[[], None]:
        with self._lock:
            self._hooks.append(callback)
        self._ensure_listener()

        def remove() -> None:
            with self._lock:
                try:
                    self._hooks.remove(callback)
                except ValueError:
                    pass

        return remove

    def unhook(self, remover: Callable[[], None]) -> None:
        remover()

    def add_hotkey(self, hotkey: str, callback: Callable[[], None]) -> Callable[[], None]:
        parsed = parse_hotkey(hotkey)
        entry = (parsed, callback)
        with self._lock:
            self._hotkeys.append(entry)
        self._ensure_listener()

        def remove() -> None:
            with self._lock:
                try:
                    self._hotkeys.remove(entry)
                except ValueError:
                    pass

        return remove

    def remove_hotkey(self, remover: Callable[[], None]) -> None:
        remover()

    def is_pressed(self, key: str | int) -> bool:
        codes = set(key_to_scan_codes(key))
        with self._lock:
            return bool(codes & self._pressed)

    def press(self, key: str | int) -> None:
        self._inject(key, 1)

    def release(self, key: str | int) -> None:
        self._inject(key, 0)

    def press_and_release(self, key: str | int, *, hold_seconds: float = 0.03) -> None:
        self.press(key)
        time.sleep(max(0.0, hold_seconds))
        self.release(key)

    send = press_and_release

    # -- lifecycle -----------------------------------------------------------

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        with self._lock:
            for device in self._devices.values():
                try:
                    device.close()
                except OSError:
                    pass
            self._devices.clear()
            if self._uinput is not None:
                try:
                    self._uinput.close()
                except OSError:
                    pass
                self._uinput = None
        self._thread = None

    # -- internals -----------------------------------------------------------

    def _inject(self, key: str | int, value: int) -> None:
        scan_code = key_to_scan_codes(key)[0]
        uinput = self._ensure_uinput()
        uinput.write(ecodes.EV_KEY, scan_code, value)
        uinput.syn()

    def _ensure_uinput(self) -> "evdev.UInput":
        with self._lock:
            if self._uinput is not None:
                return self._uinput
            try:
                self._uinput = evdev.UInput(
                    {ecodes.EV_KEY: list(range(1, 0x300))},
                    name=VIRTUAL_DEVICE_NAME,
                )
            except (OSError, evdev.UInputError) as exc:
                raise KeyboardAccessError(
                    "Cannot open /dev/uinput for key injection: "
                    f"{exc}. Grant your user write access (udev rule tagging uinput "
                    "with uaccess, or the input group)."
                ) from exc
            return self._uinput

    def _ensure_listener(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._selector = selectors.DefaultSelector()
            self._rescan_devices()
            if not self._devices:
                raise KeyboardAccessError(
                    "No readable keyboard device under /dev/input. Grant your user "
                    "read access (udev rule tagging input event devices with uaccess, "
                    "or membership of the input group) and restart."
                )
            self._thread = threading.Thread(
                target=self._run, name="bonkscanner-evdev", daemon=True
            )
            self._thread.start()

    def _rescan_devices(self) -> None:
        assert self._selector is not None
        seen: set[str] = set()
        for path in evdev.list_devices():
            seen.add(path)
            if path in self._devices:
                continue
            try:
                device = evdev.InputDevice(path)
            except OSError:
                continue
            if device.name == VIRTUAL_DEVICE_NAME or not self._device_filter(device):
                device.close()
                continue
            self._devices[path] = device
            self._selector.register(device.fd, selectors.EVENT_READ, device)
        for path in list(self._devices):
            if path not in seen:
                self._drop_device(path)

    def _drop_device(self, path: str) -> None:
        device = self._devices.pop(path, None)
        if device is None:
            return
        try:
            if self._selector is not None:
                self._selector.unregister(device.fd)
        except (KeyError, ValueError, OSError):
            pass
        try:
            device.close()
        except OSError:
            pass

    def _run(self) -> None:
        assert self._selector is not None
        next_rescan = time.monotonic() + self.RESCAN_SECONDS
        while not self._stop.is_set():
            try:
                ready = self._selector.select(timeout=0.5)
            except (OSError, ValueError):
                ready = []
            for key, _mask in ready:
                device = key.data
                try:
                    events = list(device.read())
                except OSError:
                    with self._lock:
                        self._drop_device(device.path)
                    continue
                for event in events:
                    if event.type == ecodes.EV_KEY and event.value in (0, 1):
                        self._dispatch(int(event.code), "down" if event.value == 1 else "up")
            if time.monotonic() >= next_rescan:
                with self._lock:
                    self._rescan_devices()
                next_rescan = time.monotonic() + self.RESCAN_SECONDS

    def _dispatch(self, scan_code: int, event_type: str) -> None:
        with self._lock:
            if event_type == "down":
                self._pressed.add(scan_code)
            else:
                self._pressed.discard(scan_code)
            pressed = frozenset(self._pressed)
            hooks = list(self._hooks)
            hotkeys = list(self._hotkeys)

        event = KeyboardEvent(event_type, scan_code, scan_code_name(scan_code), time.time())
        for callback in hooks:
            try:
                callback(event)
            except Exception:
                pass

        if event_type != "down":
            return
        for parsed, callback in hotkeys:
            step = parsed[0]  # multi-step sequences are not needed by BonkScanner
            if scan_code not in step[-1]:
                continue
            if all(any(code in pressed for code in key) for key in step):
                try:
                    callback()
                except Exception:
                    pass


__all__ = [
    "KeyboardAccessError",
    "KeyboardEvent",
    "LinuxKeyboard",
    "VIRTUAL_DEVICE_NAME",
    "key_to_scan_codes",
    "parse_hotkey",
    "scan_code_name",
]
